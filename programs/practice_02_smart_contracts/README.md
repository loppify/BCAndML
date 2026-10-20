# Practical Work 2: crowdfunding smart contracts and dApp

Requirements: Node.js 20+ and npm. From this directory:

```sh
npm ci
npm test
npm run coverage
npm run demo:local
```

`demo:local` starts a local Hardhat chain, deploys the UUPS contracts, executes a successful and a failed campaign with two local accounts, performs a refund, and indexes the emitted events. For a persistent local dApp session, start `npx hardhat node`, deploy with `npm run deploy:local`, then serve `frontend/` over HTTP and connect MetaMask to Hardhat Local (chain ID 31337).

For Sepolia, copy `.env.example` to `.env` and configure `SEPOLIA_RPC_URL`, `DEPLOYER_PRIVATE_KEY`, and `ETHERSCAN_API_KEY` locally. Never commit `.env` or share a private key. Deploy with `npm run deploy:sepolia`; run verification with `npx hardhat run scripts/verify.js --network sepolia`.
