require("dotenv").config();
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
const historyFile = selectedNetwork === "localhost" ? "history.json" : `history-${selectedNetwork}.json`;
const output = path.join(__dirname, "../frontend/public", historyFile);
const events = ["CampaignCreated", "ContributionReceived", "CampaignSucceeded", "CampaignFailed", "ProceedsWithdrawn", "ContributionRefunded"];
const LOG_RANGE_LIMIT = 5000;
const eventTopics = events.map((name) => hub.interface.getEvent(name).topicHash);

async function getLogsWithRetry(fromBlock, toBlock) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await provider.getLogs({ address: config.hub, fromBlock, toBlock, topics: [eventTopics] });
    } catch (error) {
      if (!/too many requests|rate limit|-32005/i.test(error.message) || attempt >= 5) throw error;
      const waitMs = Math.min(30000, 1000 * 2 ** attempt);
      console.log(`RPC rate limit reached; retrying log query in ${waitMs / 1000}s.`);
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
  }
}

async function index() {
  const history = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output, "utf8")) : [];
  const fromBlock = history.length ? Math.max(config.deployedAtBlock, history[history.length - 1].blockNumber - 1) : config.deployedAtBlock;
  const latest = await provider.getBlockNumber();
  for (let start = fromBlock; start <= latest; start += LOG_RANGE_LIMIT) {
    const end = Math.min(latest, start + LOG_RANGE_LIMIT - 1);
    for (const log of await getLogsWithRetry(start, end)) {
      const parsed = hub.interface.parseLog(log);
      if (!parsed) continue;
      if (!history.some((entry) => entry.transactionHash === log.transactionHash && entry.index === log.index)) {
        history.push({ event: parsed.name, blockNumber: log.blockNumber, index: log.index, transactionHash: log.transactionHash, args: parsed.args.toObject ? parsed.args.toObject() : Array.from(parsed.args, String) });
      }
    }
  }
  history.sort((a, b) => a.blockNumber - b.blockNumber || a.index - b.index);
  fs.writeFileSync(output, JSON.stringify(history, (_, value) => typeof value === "bigint" ? value.toString() : value, 2));
  console.log(`Indexed ${history.length} contract events through block ${latest}.`);
}

index().catch((error) => { console.error(error); process.exitCode = 1; });
