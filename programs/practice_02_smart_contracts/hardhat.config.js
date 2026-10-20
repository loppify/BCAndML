require("@nomicfoundation/hardhat-toolbox");
require("@openzeppelin/hardhat-upgrades");
require("solidity-coverage");
require("hardhat-gas-reporter");
require("dotenv").config();

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
