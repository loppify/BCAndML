const { JsonRpcProvider, Contract } = require("ethers");
const fs = require("node:fs");
const path = require("node:path");

const selectedNetwork = process.env.DEPLOYMENT_NETWORK || "sepolia";
const configPath = path.join(__dirname, `../deployments/${selectedNetwork}.json`);
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const rpc = process.env.INDEXER_RPC_URL || process.env.SEPOLIA_RPC_URL || "http://127.0.0.1:8545";
const provider = new JsonRpcProvider(rpc);
const abi = JSON.parse(fs.readFileSync(path.join(__dirname, "../frontend/public/CrowdfundingHub.json"), "utf8"));
const hub = new Contract(config.hub, abi, provider);
const output = path.join(__dirname, "../frontend/public/history.json");
const events = ["CampaignCreated", "ContributionReceived", "CampaignSucceeded", "CampaignFailed", "ProceedsWithdrawn", "ContributionRefunded"];

async function index() {
  const history = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output, "utf8")) : [];
  const fromBlock = history.length ? Math.max(0, history[history.length - 1].blockNumber - 1) : config.deployedAtBlock;
  const latest = await provider.getBlockNumber();
  for (const eventName of events) {
    const filter = hub.filters[eventName]();
    for (const log of await hub.queryFilter(filter, fromBlock, latest)) {
      if (!history.some((entry) => entry.transactionHash === log.transactionHash && entry.index === log.index)) {
        history.push({ event: eventName, blockNumber: log.blockNumber, index: log.index, transactionHash: log.transactionHash, args: log.args.toObject ? log.args.toObject() : Array.from(log.args, String) });
      }
    }
  }
  history.sort((a, b) => a.blockNumber - b.blockNumber || a.index - b.index);
  fs.writeFileSync(output, JSON.stringify(history, (_, value) => typeof value === "bigint" ? value.toString() : value, 2));
  console.log(`Indexed ${history.length} contract events through block ${latest}.`);
}

index().catch((error) => { console.error(error); process.exitCode = 1; });
