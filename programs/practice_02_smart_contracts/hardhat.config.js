require("@nomicfoundation/hardhat-toolbox");
require("@openzeppelin/hardhat-upgrades");
require("solidity-coverage");
require("hardhat-gas-reporter");
require("dotenv").config();

const args = process.argv.slice(2);
const networkFlag = args.findIndex((arg) => arg === "--network");
const selectedNetwork = networkFlag >= 0 ? args[networkFlag + 1] : args.find((arg) => arg.startsWith("--network="))?.split("=", 2)[1];
if (selectedNetwork === "sepolia") {
  const missing = ["SEPOLIA_RPC_URL", "DEPLOYER_PRIVATE_KEY", "ETHERSCAN_API_KEY"]
    .filter((name) => !process.env[name]?.trim());
  if (missing.length) {
    throw new Error(`Sepolia configuration is incomplete. Set ${missing.join(", ")} in report/practice_02_smart_contracts/code/.env (copy .env.example first).`);
  }
}

module.exports = {
  solidity: {
    version: "0.8.28",
    settings: { optimizer: { enabled: true, runs: 200 }, viaIR: true }
  },
  gasReporter: { enabled: process.env.REPORT_GAS === "true", currency: "USD", noColors: true },
  networks: {
    hardhat: { chainId: 31337 },
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL || "",
      chainId: 11155111,
      accounts: process.env.DEPLOYER_PRIVATE_KEY ? [process.env.DEPLOYER_PRIVATE_KEY] : []
    }
  },
  etherscan: { apiKey: process.env.ETHERSCAN_API_KEY || "" },
  paths: {
    artifacts: "./build/hardhat-artifacts",
    cache: "./cache"
  },
  mocha: { timeout: 120000 }
};
