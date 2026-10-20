const { ethers } = require("hardhat");
const { deploySystem, digest } = require("./helpers");

describe("Gas measurements for core state transitions", function () {
  it("records gas for registration, access grant, normal decision and quarantine", async function () {
    const system = await deploySystem();
    const { registry, access, quarantine, owner, actor, oracle } = system;
    const expiry = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);

    await (await access.connect(owner).grantAccess(system.deviceId, actor.address, expiry)).wait();
    const normal = await quarantine.connect(oracle).recordDecision(system.deviceId, false, 100, 1, digest("gas-normal"));
    await normal.wait();
    const attack = await quarantine.connect(oracle).recordDecision(system.deviceId, true, 8000, 1, digest("gas-attack"));
    await attack.wait();

    const salt = digest("second-device-salt");
    const registration = await registry.connect(actor).registerDevice(salt, digest("second-metadata"));
    await registration.wait();
  });
});
