const { ethers, upgrades, network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

async function main() {
  if (network.name !== "localhost" && network.name !== "hardhat") {
    throw new Error(`This script deploys the Lab 3 demo locally; selected network is ${network.name}.`);
  }

  const modelVersion = Number(process.env.MODEL_VERSION || 2);
  const modelPath = path.resolve(__dirname, "../models/random_forest_v2.joblib");
  if (!fs.existsSync(modelPath)) throw new Error(`Model artifact is missing: ${modelPath}. Run python -m app.train first.`);
  const modelHash = `0x${crypto.createHash("sha256").update(fs.readFileSync(modelPath)).digest("hex")}`;
  const [admin, owner, gateway, oracle, auditor, actor] = await ethers.getSigners();

  const Registry = await ethers.getContractFactory("DeviceRegistry");
  const registry = await Registry.deploy(admin.address);
  await registry.waitForDeployment();

  const Access = await ethers.getContractFactory("contracts/AccessControl.sol:AccessControl");
  const access = await Access.deploy(admin.address, await registry.getAddress());
  await access.waitForDeployment();
  await (await access.connect(admin).grantRole(await access.GATEWAY_ROLE(), gateway.address)).wait();

  const Quarantine = await ethers.getContractFactory("DeviceQuarantine");
  const quarantine = await upgrades.deployProxy(
    Quarantine,
    [admin.address, oracle.address, await registry.getAddress()],
    { kind: "uups" },
  );
  await quarantine.waitForDeployment();
  const modelReceipt = await (await quarantine.connect(admin).registerModel(modelVersion, modelHash)).wait();

  const provider = ethers.provider;
  const deployment = {
    network: network.name,
    chain_id: Number((await provider.getNetwork()).chainId),
    deployment_block: await provider.getBlockNumber(),
    deployed_at: new Date().toISOString(),
    contracts: {
      registry: await registry.getAddress(),
      access_control: await access.getAddress(),
      quarantine: await quarantine.getAddress(),
    },
    roles: {
      admin: admin.address,
      owner: owner.address,
      gateway: gateway.address,
      oracle: oracle.address,
      auditor: auditor.address,
      actor: actor.address,
    },
    model: { version: modelVersion, artifact_hash: modelHash },
    transactions: { model_registration: modelReceipt.hash },
  };
  const directory = path.resolve(__dirname, "../deployments");
  fs.mkdirSync(directory, { recursive: true });
  const output = path.join(directory, "localhost.json");
  fs.writeFileSync(output, `${JSON.stringify(deployment, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(deployment, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
