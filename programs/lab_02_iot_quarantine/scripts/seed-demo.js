const { ethers, network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const file = path.resolve(__dirname, `../deployments/${network.name}.json`);
  if (!fs.existsSync(file)) throw new Error(`Deployment file not found: ${file}. Run npm run deploy:${network.name} first.`);
  const deployment = JSON.parse(fs.readFileSync(file, "utf8"));
  const [owner] = await ethers.getSigners();
  const actor = ethers.getAddress(`0x${ethers.keccak256(ethers.toUtf8Bytes(`${owner.address}:gateway`)).slice(-40)}`);
  const registry = await ethers.getContractAt("DeviceRegistry", deployment.contracts.registry);
  const access = await ethers.getContractAt("contracts/AccessControl.sol:AccessControl", deployment.contracts.accessControl);
  const quarantine = await ethers.getContractAt("DeviceQuarantine", deployment.contracts.quarantineProxy);
  const gatewayRole = await access.GATEWAY_ROLE();
  if (!(await access.hasRole(gatewayRole, actor))) {
    await (await access.grantRole(gatewayRole, actor)).wait();
  }

  const devices = [];
  for (const label of ["virtual-normal", "virtual-attack"]) {
    const salt = ethers.keccak256(ethers.toUtf8Bytes(`${network.name}:${label}:${owner.address}`));
    const metadataHash = ethers.keccak256(ethers.toUtf8Bytes(`${label}:metadata-v1`));
    const deviceId = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt]));
    if (!(await registry.exists(deviceId))) await (await registry.connect(owner).registerDevice(salt, metadataHash)).wait();
    devices.push({ label, deviceId, owner: owner.address, metadataHash });
  }
  const expiry = BigInt((await ethers.provider.getBlock("latest")).timestamp + 86_400);
  const accessGrant = await access.connect(owner).grantAccess(devices[0].deviceId, actor, expiry);
  await accessGrant.wait();
  deployment.demo = { devices, actor, accessExpiresAt: expiry.toString() };
  fs.writeFileSync(file, `${JSON.stringify(deployment, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ devices, actor, accessGrantTx: accessGrant.hash }, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
