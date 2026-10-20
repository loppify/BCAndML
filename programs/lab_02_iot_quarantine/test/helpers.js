const { ethers } = require("hardhat");

async function deploySystem() {
  const [admin, owner, gateway, oracle, other, actor] = await ethers.getSigners();
  const Registry = await ethers.getContractFactory("DeviceRegistry");
  const registry = await Registry.deploy(admin.address);

  const Access = await ethers.getContractFactory("contracts/AccessControl.sol:AccessControl");
  const access = await Access.deploy(admin.address, await registry.getAddress());
  await access.grantRole(await access.GATEWAY_ROLE(), gateway.address);

  const Quarantine = await ethers.getContractFactory("DeviceQuarantine");
  const quarantine = await upgrades.deployProxy(
    Quarantine,
    [admin.address, oracle.address, await registry.getAddress()],
    { kind: "uups" },
  );
  await quarantine.registerModel(1, ethers.keccak256(ethers.toUtf8Bytes("model-v1")));

  const salt = ethers.keccak256(ethers.toUtf8Bytes("device-1-salt"));
  const metadataHash = ethers.keccak256(ethers.toUtf8Bytes("device-metadata"));
  const deviceId = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt]));
  await registry.connect(owner).registerDevice(salt, metadataHash);

  return { admin, owner, gateway, oracle, other, actor, registry, access, quarantine, deviceId };
}

function digest(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

module.exports = { deploySystem, digest };
