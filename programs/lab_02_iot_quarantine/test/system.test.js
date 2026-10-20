const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");
const { deploySystem, digest } = require("./helpers");
const { classifyFlow } = require("../oracle/stub");

describe("IoT IDS smart-contract system", function () {
  describe("oracle stub", function () {
    it("classifies the demonstration flows using the committed rule artifact", function () {
      expect(classifyFlow({ failedLogins: 0 })).to.deep.equal({ attack: false, confidence: 1200, modelVersion: 1 });
      expect(classifyFlow({ failedLogins: 17 })).to.deep.equal({ attack: true, confidence: 9200, modelVersion: 1 });
      expect(() => classifyFlow({ failedLogins: -1 })).to.throw("failedLogins must be a non-negative integer");
    });
  });

  describe("DeviceRegistry", function () {
    it("registers a pseudonymous device and prevents duplicate IDs", async function () {
      const { registry, owner, deviceId } = await deploySystem();
      expect(await registry.exists(deviceId)).to.equal(true);
      expect(await registry.ownerOfDevice(deviceId)).to.equal(owner.address);
      await expect(registry.connect(owner).registerDevice(digest("device-1-salt"), digest("other")))
        .to.be.revertedWithCustomError(registry, "DeviceAlreadyRegistered");
    });

    it("allows the device owner to transfer ownership", async function () {
      const { registry, admin, owner, actor, other, deviceId } = await deploySystem();
      expect(await registry.metadataHashOf(deviceId)).to.equal(digest("device-metadata"));
      await registry.connect(owner).updateOwner(deviceId, actor.address);
      expect(await registry.ownerOfDevice(deviceId)).to.equal(actor.address);
      await expect(registry.connect(owner).updateOwner(deviceId, owner.address))
        .to.be.revertedWithCustomError(registry, "NotDeviceOwner");
      await expect(registry.connect(actor).updateOwner(deviceId, ethers.ZeroAddress))
        .to.be.revertedWithCustomError(registry, "ZeroOwner");
      await registry.connect(admin).grantRole(await registry.ADMIN_ROLE(), other.address);
      await registry.connect(other).updateOwner(deviceId, owner.address);
      expect(await registry.ownerOfDevice(deviceId)).to.equal(owner.address);
    });

    it("rejects zero salts, zero metadata hashes and unregistered devices", async function () {
      const { registry, owner } = await deploySystem();
      await expect(registry.connect(owner).registerDevice(ethers.ZeroHash, digest("metadata")))
        .to.be.revertedWithCustomError(registry, "ZeroDeviceSalt");
      await expect(registry.connect(owner).registerDevice(digest("valid-salt"), ethers.ZeroHash))
        .to.be.revertedWithCustomError(registry, "ZeroMetadataHash");
      await expect(registry.ownerOfDevice(digest("missing-device")))
        .to.be.revertedWithCustomError(registry, "DeviceNotRegistered");
    });
  });

  describe("AccessControl", function () {
    it("grants expiring access and reports it only to a gateway", async function () {
      const { access, owner, actor, gateway, deviceId } = await deploySystem();
      const expiry = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
      await access.connect(owner).grantAccess(deviceId, actor.address, expiry);
      const [grantExpiry, active] = await access.accessGrant(deviceId, actor.address);
      expect(grantExpiry).to.equal(expiry);
      expect(active).to.equal(true);
      expect(await access.connect(gateway).canInteract(deviceId, actor.address)).to.equal(true);
      await expect(access.connect(actor).canInteract(deviceId, actor.address))
        .to.be.revertedWithCustomError(access, "AccessControlUnauthorizedAccount");
      await access.connect(owner).revokeAccess(deviceId, actor.address);
      expect((await access.accessGrant(deviceId, actor.address)).enabled).to.equal(false);
      expect(await access.connect(gateway).canInteract(deviceId, actor.address)).to.equal(false);
    });

    it("treats an elapsed grant as inactive", async function () {
      const { access, owner, actor, gateway, deviceId } = await deploySystem();
      const now = (await ethers.provider.getBlock("latest")).timestamp;
      await access.connect(owner).grantAccess(deviceId, actor.address, now + 30);
      await ethers.provider.send("evm_increaseTime", [31]);
      await ethers.provider.send("evm_mine", []);
      expect(await access.connect(gateway).canInteract(deviceId, actor.address)).to.equal(false);
      expect((await access.accessGrant(deviceId, actor.address)).enabled).to.equal(false);
    });

    it("rejects non-owner grants, expired leases and revocation without a grant", async function () {
      const { access, other, owner, actor, deviceId } = await deploySystem();
      const now = (await ethers.provider.getBlock("latest")).timestamp;
      await expect(access.connect(other).grantAccess(deviceId, actor.address, now + 300))
        .to.be.revertedWithCustomError(access, "NotDeviceOwner");
      await expect(access.connect(owner).grantAccess(deviceId, actor.address, now))
        .to.be.revertedWithCustomError(access, "InvalidExpiry");
      await expect(access.connect(owner).revokeAccess(deviceId, actor.address))
        .to.be.revertedWithCustomError(access, "NoActiveGrant");
      await expect(access.connect(owner).grantAccess(deviceId, ethers.ZeroAddress, now + 300))
        .to.be.revertedWithCustomError(access, "ZeroAddress");
    });
  });

  describe("DeviceQuarantine", function () {
    it("moves Active -> Quarantined for an attack at or above the threshold", async function () {
      const { quarantine, oracle, deviceId } = await deploySystem();
      await expect(quarantine.connect(oracle).recordDecision(deviceId, true, 5000, 1, digest("flow-a")))
        .to.emit(quarantine, "DeviceQuarantined").withArgs(deviceId, 1);
      expect(await quarantine.deviceStatus(deviceId)).to.equal(2);
      expect(await quarantine.incidentCount(deviceId)).to.equal(1);
      const decision = await quarantine.getDecision(deviceId, 1);
      expect(decision.attack).to.equal(true);
      expect(decision.confidence).to.equal(5000);
      expect(decision.inputHash).to.equal(digest("flow-a"));
    });

    it("does not quarantine normal or sub-threshold results", async function () {
      const { quarantine, oracle, deviceId } = await deploySystem();
      await quarantine.connect(oracle).recordDecision(deviceId, false, 9900, 1, digest("normal-flow"));
      await quarantine.connect(oracle).recordDecision(deviceId, true, 4999, 1, digest("weak-attack"));
      expect(await quarantine.deviceStatus(deviceId)).to.equal(1);
    });

    it("validates model, hash, confidence and incident identifiers", async function () {
      const { quarantine, admin, oracle, deviceId } = await deploySystem();
      await expect(quarantine.connect(admin).registerModel(2, ethers.ZeroHash))
        .to.be.revertedWithCustomError(quarantine, "ZeroHash");
      await quarantine.connect(admin).registerModel(2, digest("model-v2"));
      await expect(quarantine.connect(admin).registerModel(2, digest("duplicate-model")))
        .to.be.revertedWithCustomError(quarantine, "ModelVersionAlreadyRegistered");
      await expect(quarantine.connect(oracle).recordDecision(deviceId, false, 0, 0, digest("unknown-version")))
        .to.be.revertedWithCustomError(quarantine, "ModelVersionUnknown");
      await expect(quarantine.connect(oracle).recordDecision(deviceId, false, 0, 1, ethers.ZeroHash))
        .to.be.revertedWithCustomError(quarantine, "ZeroHash");
      await expect(quarantine.connect(oracle).recordDecision(deviceId, false, 10001, 1, digest("bad-confidence")))
        .to.be.revertedWithCustomError(quarantine, "InvalidConfidence");
      await expect(quarantine.getDecision(deviceId, 0))
        .to.be.revertedWithCustomError(quarantine, "IncidentNotFound");
    });

    it("supports administrator pause recovery and rejects unauthorized administration", async function () {
      const { quarantine, admin, other, oracle, deviceId } = await deploySystem();
      await expect(quarantine.connect(other).pause())
        .to.be.revertedWithCustomError(quarantine, "AccessControlUnauthorizedAccount");
      await quarantine.connect(admin).pause();
      await expect(quarantine.connect(other).unpause())
        .to.be.revertedWithCustomError(quarantine, "AccessControlUnauthorizedAccount");
      await quarantine.connect(admin).unpause();
      await quarantine.connect(oracle).recordDecision(deviceId, false, 100, 1, digest("resumed"));
      expect(await quarantine.deviceStatus(deviceId)).to.equal(1);
    });

    it("rejects duplicate input hashes and unauthorized oracle calls", async function () {
      const { quarantine, oracle, other, deviceId } = await deploySystem();
      const inputHash = digest("one-flow");
      await quarantine.connect(oracle).recordDecision(deviceId, false, 0, 1, inputHash);
      await expect(quarantine.connect(oracle).recordDecision(deviceId, false, 0, 1, inputHash))
        .to.be.revertedWithCustomError(quarantine, "DecisionAlreadyProcessed");
      await expect(quarantine.connect(other).recordDecision(deviceId, false, 0, 1, digest("other-flow")))
        .to.be.revertedWithCustomError(quarantine, "AccessControlUnauthorizedAccount");
    });

    it("allows owner release, oracle replacement and emergency pause", async function () {
      const { quarantine, admin, owner, oracle, other, deviceId } = await deploySystem();
      await quarantine.connect(oracle).recordDecision(deviceId, true, 7000, 1, digest("attack-flow"));
      await expect(quarantine.connect(other).releaseQuarantine(deviceId))
        .to.be.revertedWithCustomError(quarantine, "NotDeviceOwner");
      await quarantine.connect(owner).releaseQuarantine(deviceId);
      expect(await quarantine.deviceStatus(deviceId)).to.equal(1);

      await quarantine.connect(admin).replaceOracle(other.address);
      await expect(quarantine.connect(oracle).recordDecision(deviceId, false, 0, 1, digest("old-oracle")))
        .to.be.revertedWithCustomError(quarantine, "AccessControlUnauthorizedAccount");
      await quarantine.connect(admin).pause();
      await expect(quarantine.connect(other).recordDecision(deviceId, false, 0, 1, digest("paused")))
        .to.be.revertedWithCustomError(quarantine, "EnforcedPause");
    });

    it("preserves records and roles through a UUPS implementation upgrade", async function () {
      const { quarantine, oracle, admin, deviceId } = await deploySystem();
      await quarantine.connect(oracle).recordDecision(deviceId, true, 6000, 1, digest("upgrade-flow"));
      const V2 = await ethers.getContractFactory("DeviceQuarantineV2");
      const upgraded = await upgrades.upgradeProxy(await quarantine.getAddress(), V2, {
        kind: "uups",
        unsafeAllow: ["missing-initializer"],
      });
      await upgraded.initializeV2();
      expect(await upgraded.implementationVersion()).to.equal(2);
      expect(await upgraded.incidentCount(deviceId)).to.equal(1);
      expect(await upgraded.hasRole(await upgraded.DEFAULT_ADMIN_ROLE(), admin.address)).to.equal(true);
      expect((await upgraded.getDecision(deviceId, 1)).inputHash).to.equal(digest("upgrade-flow"));
    });
  });
});
