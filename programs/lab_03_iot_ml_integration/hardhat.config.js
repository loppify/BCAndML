require("@nomicfoundation/hardhat-toolbox");
require("@openzeppelin/hardhat-upgrades");
require("solidity-coverage");
require("hardhat-gas-reporter");
const path = require("node:path");
require("dotenv").config({ path: process.env.DOTENV_CONFIG_PATH || path.resolve(__dirname, ".env") });

const args = process.argv.slice(2);
const networkFlag = args.findIndex((arg) => arg === "--network");
const selectedNetwork = networkFlag >= 0
  ? args[networkFlag + 1]
  : args.find((arg) => arg.startsWith("--network="))?.split("=", 2)[1];

if (selectedNetwork === "sepolia") {
  const missing = ["SEPOLIA_RPC_URL", "DEPLOYER_PRIVATE_KEY"]
    .filter((name) => !process.env[name]?.trim());
  if (missing.length) {
    throw new Error(`Sepolia configuration is incomplete. Set ${missing.join(", ")} in a local .env file.`);
  }
}

module.exports = {
  solidity: {
    version: "0.8.28",
    settings: { optimizer: { enabled: true, runs: 200 } },
  },
  gasReporter: {
    enabled: process.env.REPORT_GAS === "true",
    currency: "USD",
    noColors: true,
  },
  networks: {
    hardhat: { chainId: 31337 },
    localhost: {
      url: process.env.WEB3_PROVIDER_URL || "http://127.0.0.1:8545",
      chainId: Number(process.env.CHAIN_ID || 31337),
    },
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL || "",
      chainId: 11155111,
      accounts: process.env.DEPLOYER_PRIVATE_KEY ? [process.env.DEPLOYER_PRIVATE_KEY] : [],
    },
  },
  etherscan: { apiKey: process.env.ETHERSCAN_API_KEY || "" },
  paths: { artifacts: "./build/hardhat-artifacts", cache: "./cache" },
  mocha: { timeout: 120000 },
};
