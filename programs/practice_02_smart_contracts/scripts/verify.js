const { run } = require("hardhat");
const fs = require("node:fs");

async function main() {
  const deployment = JSON.parse(fs.readFileSync("deployments/sepolia.json", "utf8"));
  for (const address of [deployment.registryImplementation, deployment.tokenImplementation, deployment.hubImplementation]) {
    let verified = false;
    for (let attempt = 1; attempt <= 6 && !verified; attempt++) {
      try {
        await run("verify:verify", { address });
        verified = true;
      } catch (error) {
        if (/already verified/i.test(error.message)) {
          verified = true;
          continue;
        }
        if (!/does not have bytecode|Unable to locate ContractCode/i.test(error.message) || attempt === 6) throw error;
        console.log(`Explorer has not indexed ${address} yet; retry ${attempt}/5 in 15 seconds.`);
        await new Promise((resolve) => setTimeout(resolve, 15000));
      }
    }
  }
  console.log("Verified implementation contracts:", deployment.registryImplementation, deployment.tokenImplementation, deployment.hubImplementation);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
