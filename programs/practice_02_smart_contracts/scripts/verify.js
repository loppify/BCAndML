const { run } = require("hardhat");
const fs = require("node:fs");

async function main() {
  const deployment = JSON.parse(fs.readFileSync("deployments/sepolia.json", "utf8"));
  for (const address of [deployment.registryImplementation, deployment.tokenImplementation, deployment.hubImplementation]) {
    await run("verify:verify", { address });
  }
  console.log("Verified implementation contracts:", deployment.registryImplementation, deployment.tokenImplementation, deployment.hubImplementation);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
