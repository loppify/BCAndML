const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const hardhat = path.join(root, "node_modules/.bin/hardhat");
const lines = [];
function run(args, env = {}) {
  const result = spawnSync(hardhat, args, { cwd: root, encoding: "utf8", env: { ...process.env, ...env } });
  lines.push(`$ hardhat ${args.join(" ")}\n${result.stdout || ""}${result.stderr || ""}`);
  if (result.status !== 0) throw new Error(`Command failed: hardhat ${args.join(" ")}`);
}
async function ready() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch("http://127.0.0.1:8545", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }) }); if (r.ok) return; } catch (_) {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Local Hardhat node did not start.");
}

async function main() {
  const node = spawn(hardhat, ["node", "--hostname", "127.0.0.1"], { cwd: root, stdio: "ignore" });
  try {
    await ready();
    run(["run", "scripts/deploy.js", "--network", "localhost"]);
    run(["run", "scripts/demo-local.js", "--network", "localhost"]);
    const idx = spawnSync(process.execPath, ["scripts/index-events.js"], { cwd: root, encoding: "utf8", env: { ...process.env, DEPLOYMENT_NETWORK: "localhost", INDEXER_RPC_URL: "http://127.0.0.1:8545" } });
    lines.push(`$ node scripts/index-events.js\n${idx.stdout || ""}${idx.stderr || ""}`);
    if (idx.status !== 0) throw new Error("Event indexer failed.");
    fs.mkdirSync(path.join(root, "artifacts"), { recursive: true });
    const deployment = path.join(root, "deployments/localhost.json");
    fs.copyFileSync(deployment, path.join(root, "artifacts/deployment-local.json"));
    const log = path.join(root, "artifacts/local-run.txt");
    fs.mkdirSync(path.dirname(log), { recursive: true });
    fs.writeFileSync(log, lines.join("\n"), "utf8");
    process.stdout.write(lines.join("\n"));
  } finally { node.kill("SIGTERM"); }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
