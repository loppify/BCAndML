const { ethers, upgrades } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { classifyFlow, model } = require("../oracle/stub");

function sha256(bytes) {
  return `0x${crypto.createHash("sha256").update(bytes).digest("hex")}`;
}

async function main() {
  const [admin, owner, gateway, oracle, actor] = await ethers.getSigners();
  const Registry = await ethers.getContractFactory("DeviceRegistry");
  const registry = await Registry.deploy(admin.address);
  await registry.waitForDeployment();

  const Access = await ethers.getContractFactory("contracts/AccessControl.sol:AccessControl");
  const access = await Access.deploy(admin.address, await registry.getAddress());
  await access.waitForDeployment();
  await access.grantRole(await access.GATEWAY_ROLE(), gateway.address);

  const Quarantine = await ethers.getContractFactory("DeviceQuarantine");
  const quarantine = await upgrades.deployProxy(
    Quarantine,
    [admin.address, oracle.address, await registry.getAddress()],
    { kind: "uups" },
  );
  await quarantine.waitForDeployment();
  const dataDir = path.resolve(__dirname, "../artifacts/demo-data");
  fs.mkdirSync(dataDir, { recursive: true });
  const normalPath = path.join(dataDir, "normal-flow.json");
  const attackPath = path.join(dataDir, "attack-flow.json");
  const tamperedPath = path.join(dataDir, "attack-flow-tampered.json");
  const normalBytes = Buffer.from(JSON.stringify({ device: "virtual-01", packets: 24, failedLogins: 0, label: "normal" }, null, 2) + "\n");
  const attackBytes = Buffer.from(JSON.stringify({ device: "virtual-02", packets: 840, failedLogins: 17, label: "attack" }, null, 2) + "\n");
  fs.writeFileSync(normalPath, normalBytes);
  fs.writeFileSync(attackPath, attackBytes);
  const modelPath = path.resolve(__dirname, "../oracle/stub-model.json");
  await quarantine.registerModel(model.version, sha256(fs.readFileSync(modelPath)));

  const salt = ethers.keccak256(ethers.toUtf8Bytes("lab2:virtual-01"));
  const deviceId = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt]));
  await registry.connect(owner).registerDevice(salt, ethers.keccak256(ethers.toUtf8Bytes("virtual-01 metadata")));
  const salt2 = ethers.keccak256(ethers.toUtf8Bytes("lab2:virtual-02"));
  const deviceId2 = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt2]));
  await registry.connect(owner).registerDevice(salt2, ethers.keccak256(ethers.toUtf8Bytes("virtual-02 metadata")));

  const expiry = BigInt((await ethers.provider.getBlock("latest")).timestamp + 3600);
  await access.connect(owner).grantAccess(deviceId, actor.address, expiry);
  const normalDecision = classifyFlow(JSON.parse(normalBytes.toString("utf8")));
  const attackDecision = classifyFlow(JSON.parse(attackBytes.toString("utf8")));
  await quarantine.connect(oracle).recordDecision(deviceId, normalDecision.attack, normalDecision.confidence, normalDecision.modelVersion, sha256(normalBytes));
  await quarantine.connect(oracle).recordDecision(deviceId2, attackDecision.attack, attackDecision.confidence, attackDecision.modelVersion, sha256(attackBytes));

  const tamperedBytes = Buffer.from(attackBytes.toString("utf8").replace('"packets": 840', '"packets": 841'));
  fs.writeFileSync(tamperedPath, tamperedBytes);
  const result = {
    chainId: (await ethers.provider.getNetwork()).chainId.toString(),
    contracts: {
      registry: await registry.getAddress(),
      accessControl: await access.getAddress(),
      quarantineProxy: await quarantine.getAddress(),
      quarantineImplementation: await upgrades.erc1967.getImplementationAddress(await quarantine.getAddress()),
    },
    demo: {
      normal: { deviceId, confidenceBps: normalDecision.confidence, expectedFileHash: sha256(normalBytes), onChainStatus: Number(await quarantine.deviceStatus(deviceId)) },
      attack: {
        deviceId: deviceId2,
        confidenceBps: attackDecision.confidence,
        expectedFileHash: sha256(attackBytes),
        tamperedFileHash: sha256(tamperedBytes),
        hashesMatchTamperedCheck: sha256(attackBytes) === sha256(tamperedBytes),
        onChainStatus: Number(await quarantine.deviceStatus(deviceId2)),
      },
      accessGranted: await access.connect(gateway).canInteract(deviceId, actor.address),
    },
  };
  const out = path.join(dataDir, "local-demo-result.json");
  fs.writeFileSync(out, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
