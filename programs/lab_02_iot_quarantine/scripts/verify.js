const { network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const file = path.resolve(__dirname, `../deployments/${network.name}.json`);
  if (!fs.existsSync(file)) throw new Error(`Deployment file not found: ${file}.`);
  const { contracts, constructorArguments } = JSON.parse(fs.readFileSync(file, "utf8"));
  const { run } = require("hardhat");
  for (const [name, address, args] of [
    ["DeviceRegistry", contracts.registry, constructorArguments.registry],
    ["contracts/AccessControl.sol:AccessControl", contracts.accessControl, constructorArguments.accessControl],
    ["DeviceQuarantine", contracts.quarantineImplementation, []],
  ]) {
    try {
      await run("verify:verify", { address, constructorArguments: args });
    } catch (error) {
      if (!String(error.message).toLowerCase().includes("already verified")) throw error;
    }
  }
  process.stdout.write(`Implementation verification requested. Proxy: ${contracts.quarantineProxy}; implementation: ${contracts.quarantineImplementation}.\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
