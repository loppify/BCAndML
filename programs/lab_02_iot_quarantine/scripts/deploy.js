const { ethers, upgrades, network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { model } = require("../oracle/stub");

async function main() {
  const [admin] = await ethers.getSigners();
  const Registry = await ethers.getContractFactory("DeviceRegistry");
  const registry = await Registry.deploy(admin.address);
  await registry.waitForDeployment();
  const registryReceipt = await registry.deploymentTransaction().wait();

  const Access = await ethers.getContractFactory("contracts/AccessControl.sol:AccessControl");
  const access = await Access.deploy(admin.address, await registry.getAddress());
  await access.waitForDeployment();
  const accessReceipt = await access.deploymentTransaction().wait();

  const Quarantine = await ethers.getContractFactory("DeviceQuarantine");
  const quarantine = await upgrades.deployProxy(
    Quarantine,
    [admin.address, admin.address, await registry.getAddress()],
    { kind: "uups" },
  );
  await quarantine.waitForDeployment();
  const proxyAddress = await quarantine.getAddress();
  const implementationAddress = await upgrades.erc1967.getImplementationAddress(proxyAddress);
  const modelPath = path.resolve(__dirname, "../oracle/stub-model.json");
  const modelHash = `0x${crypto.createHash("sha256").update(fs.readFileSync(modelPath)).digest("hex")}`;
  const modelTx = await quarantine.registerModel(model.version, modelHash);
  const modelReceipt = await modelTx.wait();

  const record = {
    network: network.name,
    chainId: (await ethers.provider.getNetwork()).chainId.toString(),
    deployer: admin.address,
    deployedAt: new Date().toISOString(),
    contracts: {
      registry: await registry.getAddress(),
      accessControl: await access.getAddress(),
      quarantineProxy: proxyAddress,
      quarantineImplementation: implementationAddress,
    },
    constructorArguments: {
      registry: [admin.address],
      accessControl: [admin.address, await registry.getAddress()],
    },
    transactions: {
      registry: registryReceipt.hash,
      accessControl: accessReceipt.hash,
      modelRegistration: modelReceipt.hash,
    },
    model: { version: model.version, artifactHash: modelHash },
  };
  const dir = path.resolve(__dirname, "../deployments");
  fs.mkdirSync(dir, { recursive: true });
  const out = path.join(dir, `${network.name}.json`);
  fs.writeFileSync(out, `${JSON.stringify(record, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
