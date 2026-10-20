const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

function sha256(filePath) {
  return `0x${crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex")}`;
}

const dir = path.resolve(__dirname, "../artifacts/demo-data");
const original = path.join(dir, "attack-flow.json");
const altered = path.join(dir, "attack-flow-tampered.json");
if (!fs.existsSync(original) || !fs.existsSync(altered)) {
  throw new Error("Run the local demo first to create the original and tampered flow artifacts.");
}
const originalHash = sha256(original);
const alteredHash = sha256(altered);
const result = { originalHash, alteredHash, unchanged: originalHash === alteredHash };
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (result.unchanged) process.exitCode = 1;
