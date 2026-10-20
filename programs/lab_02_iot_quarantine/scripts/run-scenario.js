const { ethers, network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { classifyFlow } = require("../oracle/stub");

function hashFile(file) {
  return `0x${crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex")}`;
}

async function main() {
  const file = path.resolve(__dirname, `../deployments/${network.name}.json`);
  if (!fs.existsSync(file)) throw new Error(`Deployment file not found: ${file}.`);
  const deployment = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!deployment.demo?.devices || deployment.demo.devices.length < 2) throw new Error("Run the seed command before the scenario.");
  const [oracle] = await ethers.getSigners();
  const quarantine = await ethers.getContractAt("DeviceQuarantine", deployment.contracts.quarantineProxy);
  if (!(await quarantine.hasRole(await quarantine.ORACLE_ROLE(), oracle.address))) {
    await (await quarantine.replaceOracle(oracle.address)).wait();
  }
  const dataDir = path.resolve(__dirname, "../artifacts/demo-data");
  fs.mkdirSync(dataDir, { recursive: true });
  const normalPath = path.join(dataDir, "normal-flow.json");
  const attackPath = path.join(dataDir, "attack-flow.json");
  fs.writeFileSync(normalPath, `${JSON.stringify({ packets: 24, failedLogins: 0, label: "normal" }, null, 2)}\n`);
  fs.writeFileSync(attackPath, `${JSON.stringify({ packets: 840, failedLogins: 17, label: "attack" }, null, 2)}\n`);
  const normalFlow = JSON.parse(fs.readFileSync(normalPath, "utf8"));
  const attackFlow = JSON.parse(fs.readFileSync(attackPath, "utf8"));
  const normalDecision = classifyFlow(normalFlow);
  const attackDecision = classifyFlow(attackFlow);
  const normalHash = hashFile(normalPath);
  const attackHash = hashFile(attackPath);
  let normalTxHash = null;
  let attackTxHash = null;
  if (!(await quarantine.processedInputHash(deployment.demo.devices[0].deviceId, normalHash))) {
    const normalTx = await quarantine.connect(oracle).recordDecision(
      deployment.demo.devices[0].deviceId,
      normalDecision.attack,
      normalDecision.confidence,
      normalDecision.modelVersion,
      normalHash,
    );
    normalTxHash = normalTx.hash;
    await normalTx.wait();
  }
  if (!(await quarantine.processedInputHash(deployment.demo.devices[1].deviceId, attackHash))) {
    const attackTx = await quarantine.connect(oracle).recordDecision(
      deployment.demo.devices[1].deviceId,
      attackDecision.attack,
      attackDecision.confidence,
      attackDecision.modelVersion,
      attackHash,
    );
    attackTxHash = attackTx.hash;
    await attackTx.wait();
  }
  const registryReceipt = await ethers.provider.getTransactionReceipt(deployment.transactions.registry);
  const eventFromBlock = registryReceipt.blockNumber;
  const normalEvents = await quarantine.queryFilter(
    quarantine.filters.DecisionRecorded(deployment.demo.devices[0].deviceId),
    eventFromBlock,
    "latest",
  );
  const attackEvents = await quarantine.queryFilter(
    quarantine.filters.DecisionRecorded(deployment.demo.devices[1].deviceId),
    eventFromBlock,
    "latest",
  );
  const result = {
    network: network.name,
    normal: { deviceId: deployment.demo.devices[0].deviceId, tx: normalTxHash || normalEvents.at(-1)?.transactionHash || null, status: Number(await quarantine.deviceStatus(deployment.demo.devices[0].deviceId)) },
    attack: { deviceId: deployment.demo.devices[1].deviceId, tx: attackTxHash || attackEvents.at(-1)?.transactionHash || null, status: Number(await quarantine.deviceStatus(deployment.demo.devices[1].deviceId)) },
    normalFlowHash: normalHash,
    attackFlowHash: attackHash,
  };
  fs.writeFileSync(path.join(dataDir, `${network.name}-scenario-result.json`), `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
