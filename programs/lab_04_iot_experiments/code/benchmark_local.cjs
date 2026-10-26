const path = require("node:path");
const fs = require("node:fs");
const LAB3_PROJECT = path.resolve(__dirname, "../../lab_03_iot_ml_integration");
const CODE_ROOT = fs.existsSync(path.join(LAB3_PROJECT, "code")) ? path.join(LAB3_PROJECT, "code") : LAB3_PROJECT;
const { ethers, upgrades } = require(path.join(CODE_ROOT, "node_modules", "hardhat"));
const crypto = require("node:crypto");
const { performance } = require("node:perf_hooks");

async function main() {
  const [admin, owner, gateway, oracle] = await ethers.getSigners();
  const modelPath = path.join(CODE_ROOT, "models", "random_forest_v2.joblib");
  const modelHash = `0x${crypto.createHash("sha256").update(fs.readFileSync(modelPath)).digest("hex")}`;

  const Registry = await ethers.getContractFactory("DeviceRegistry");
  const registry = await Registry.deploy(admin.address);
  await registry.waitForDeployment();
  const Access = await ethers.getContractFactory("contracts/AccessControl.sol:AccessControl");
  const access = await Access.deploy(admin.address, await registry.getAddress());
  await access.waitForDeployment();
  const Quarantine = await ethers.getContractFactory("DeviceQuarantine");
  const quarantine = await upgrades.deployProxy(Quarantine, [admin.address, oracle.address, await registry.getAddress()], { kind: "uups" });
  await quarantine.waitForDeployment();
  await (await quarantine.connect(admin).registerModel(2, modelHash)).wait();

  let serial = 0;
  async function createDevice(label) {
    serial += 1;
    const salt = ethers.id(`lab4-${label}-${serial}`);
    const metadataHash = ethers.id(`metadata-${label}-${serial}`);
    const tx = await registry.connect(owner).registerDevice(salt, metadataHash);
    await tx.wait();
    return ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt]));
  }
  async function decision(deviceId, label) {
    const inputHash = ethers.id(`lab4-input-${label}-${crypto.randomUUID()}`);
    const t0 = performance.now();
    const tx = await quarantine.connect(oracle).recordDecision(deviceId, false, 0, 2, inputHash);
    const receipt = await tx.wait();
    return {
      prior_records_label: label,
      gas_used: Number(receipt.gasUsed),
      calldata_bytes: (tx.data.length - 2) / 2,
      submit_to_receipt_ms: performance.now() - t0,
      block_number: Number(receipt.blockNumber),
      transaction_hash: receipt.hash,
    };
  }

  const rows = [];
  for (const priorCount of [0, 1, 10, 100]) {
    const deviceId = await createDevice(`prior-${priorCount}`);
    for (let i = 0; i < priorCount; i += 1) {
      await decision(deviceId, `seed-${priorCount}-${i}`);
    }
    for (let repeat = 1; repeat <= 5; repeat += 1) {
      const result = await decision(deviceId, priorCount);
      rows.push({ prior_records: priorCount, repeat, ...result });
    }
  }

  const latencyDevice = await createDevice("latency-100");
  const confirmationRows = [];
  for (let repeat = 1; repeat <= 100; repeat += 1) {
    confirmationRows.push({ repeat, ...await decision(latencyDevice, "latency-100") });
  }

  const lookupCount = 1000;
  const registeredIds = [];
  const registrationStarted = performance.now();
  for (let i = 0; i < lookupCount; i += 1) {
    registeredIds.push(await createDevice(`lookup-${i}`));
  }
  const registrationMs = performance.now() - registrationStarted;
  const lookupStarted = performance.now();
  let found = 0;
  for (const deviceId of registeredIds) {
    if (await registry.exists(deviceId)) found += 1;
  }
  const lookupMs = performance.now() - lookupStarted;
  const eventRows = await quarantine.queryFilter(quarantine.filters.DecisionRecorded());
  const auditCheck = {
    decisions: eventRows.length,
    all_have_model_version_2: eventRows.every((event) => Number(event.args.modelVersion) === 2),
    all_have_32_byte_input_hash: eventRows.every((event) => event.args.inputHash.length === 66),
  };

  const output = {
    network: "Hardhat in-process local EVM",
    chain_id: Number((await ethers.provider.getNetwork()).chainId),
    operation: "DeviceQuarantine.recordDecision, normal decision, model version 2",
    data_size_note: "Only a fixed bytes32 input digest is sent on-chain; raw-flow byte length is not an ABI input.",
    repetitions_per_prior_record_count: 5,
    prior_record_counts: [0, 1, 10, 100],
    gas_and_latency: rows,
    local_confirmation_latency: confirmationRows.map((row) => row.submit_to_receipt_ms),
    local_confirmation_trials: confirmationRows,
    nfr_device_scale: { registered_devices: lookupCount, registrations_succeeded: lookupCount,
      registration_time_ms: registrationMs, lookup_count: lookupCount, found_count: found, lookup_time_ms: lookupMs },
    audit_coverage: auditCheck,
    contracts: {
      registry: await registry.getAddress(),
      access_control: await access.getAddress(),
      quarantine: await quarantine.getAddress(),
    },
  };
  const outputPath = path.resolve(__dirname, "../artifacts/local_chain_experiments.json");
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ output: outputPath, groups: rows.length, repetitions: 5 }, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
