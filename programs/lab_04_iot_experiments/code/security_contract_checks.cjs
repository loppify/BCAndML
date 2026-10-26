const path = require("node:path");
const fs = require("node:fs");
const LAB3_PROJECT = path.resolve(__dirname, "../../lab_03_iot_ml_integration");
const CODE_ROOT = fs.existsSync(path.join(LAB3_PROJECT, "code")) ? path.join(LAB3_PROJECT, "code") : LAB3_PROJECT;
const { ethers, upgrades } = require(path.join(CODE_ROOT, "node_modules", "hardhat"));
const crypto = require("node:crypto");

async function rejected(label, action) {
  try {
    const tx = await action();
    await tx.wait();
    return { attack: label, blocked: false, evidence: "transaction unexpectedly succeeded" };
  } catch (error) {
    return { attack: label, blocked: true, evidence: String(error.shortMessage || error.message).split("\n")[0] };
  }
}

async function main() {
  const [admin, owner, gateway, oracle, attacker] = await ethers.getSigners();
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
  await (await access.connect(admin).grantRole(await access.GATEWAY_ROLE(), gateway.address)).wait();
  await (await quarantine.connect(admin).registerModel(2, modelHash)).wait();
  const salt = ethers.id("lab4-security-device");
  const deviceId = ethers.keccak256(ethers.AbiCoder.defaultAbiCoder().encode(["address", "bytes32"], [owner.address, salt]));
  await (await registry.connect(owner).registerDevice(salt, ethers.id("lab4-security-metadata"))).wait();
  const validHash = ethers.id("lab4-security-valid-decision");
  const checks = [];
  checks.push(await rejected("Прямий виклик recordDecision без ORACLE_ROLE", () =>
    quarantine.connect(attacker).recordDecision(deviceId, true, 9000, 2, ethers.id("unauthorized"))));
  checks.push(await rejected("Надання operator-доступу сторонньою адресою", () =>
    access.connect(attacker).grantAccess(deviceId, attacker.address, BigInt(Math.floor(Date.now() / 1000) + 3600))));
  checks.push(await rejected("Реєстрація нової версії моделі без ADMIN_ROLE", () =>
    quarantine.connect(attacker).registerModel(3, ethers.id("attacker-model"))));
  checks.push(await rejected("Confidence поза діапазоном 0..10000", () =>
    quarantine.connect(oracle).recordDecision(deviceId, true, 10001, 2, ethers.id("invalid-confidence"))));
  await (await quarantine.connect(oracle).recordDecision(deviceId, false, 0, 2, validHash)).wait();
  checks.push(await rejected("Повторне подання того самого inputHash", () =>
    quarantine.connect(oracle).recordDecision(deviceId, false, 0, 2, validHash)));
  await (await quarantine.connect(admin).pause()).wait();
  checks.push(await rejected("Oracle-запис під час аварійної паузи", () =>
    quarantine.connect(oracle).recordDecision(deviceId, false, 0, 2, ethers.id("paused-decision"))));
  await (await quarantine.connect(admin).unpause()).wait();

  const output = {
    network: "Hardhat local EVM, chain ID 31337",
    target_contracts: { registry: await registry.getAddress(), access_control: await access.getAddress(), quarantine: await quarantine.getAddress() },
    attempted_attacks: checks.length,
    blocked_attacks: checks.filter((row) => row.blocked).length,
    checks,
    assertions_passed: checks.every((row) => row.blocked),
  };
  const outputPath = path.resolve(__dirname, "../artifacts/security_contract_checks.json");
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify({ output: outputPath, blocked: output.blocked_attacks, total: output.attempted_attacks }, null, 2)}\n`);
  if (!output.assertions_passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
