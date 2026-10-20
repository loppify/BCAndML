const { ethers, upgrades, network, artifacts } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [admin, authorCandidate] = await ethers.getSigners();
  if (network.name === "sepolia" && !process.env.DEPLOYER_PRIVATE_KEY) {
    throw new Error("Set DEPLOYER_PRIVATE_KEY in the local .env file; do not commit it.");
  }
  const author = authorCandidate || admin;
  const Registry = await ethers.getContractFactory("AuthorRegistry");
  const registry = await upgrades.deployProxy(Registry, [admin.address], { kind: "uups" });
  await registry.waitForDeployment();
  const Token = await ethers.getContractFactory("ContributionToken");
  const token = await upgrades.deployProxy(Token, [admin.address], { kind: "uups" });
  await token.waitForDeployment();
  const Hub = await ethers.getContractFactory("CrowdfundingHub");
  const hub = await upgrades.deployProxy(Hub, [admin.address, await registry.getAddress(), await token.getAddress()], { kind: "uups" });
  await hub.waitForDeployment();

  await (await registry.grantRole(await registry.CAMPAIGN_ROLE(), await hub.getAddress())).wait();
  await (await token.grantRole(await token.MINTER_ROLE(), await hub.getAddress())).wait();
  if (!(await registry.isAuthor(author.address))) await (await registry.registerAuthor(author.address)).wait();

  const chain = await ethers.provider.getNetwork();
  const addresses = {
    network: network.name,
    chainId: Number(chain.chainId),
    admin: admin.address,
    demoAuthor: author.address,
    registry: await registry.getAddress(),
    registryImplementation: await upgrades.erc1967.getImplementationAddress(await registry.getAddress()),
    token: await token.getAddress(),
    tokenImplementation: await upgrades.erc1967.getImplementationAddress(await token.getAddress()),
    hub: await hub.getAddress(),
    hubImplementation: await upgrades.erc1967.getImplementationAddress(await hub.getAddress()),
    deployedAtBlock: await ethers.provider.getBlockNumber()
  };
  const output = path.resolve(__dirname, `../deployments/${network.name}.json`);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(addresses, null, 2));
  const hubArtifact = await artifacts.readArtifact("CrowdfundingHub");
  fs.mkdirSync(path.resolve(__dirname, "../frontend/public"), { recursive: true });
  fs.writeFileSync(path.resolve(__dirname, "../frontend/public/CrowdfundingHub.json"), JSON.stringify(hubArtifact.abi, null, 2));
  fs.writeFileSync(path.resolve(__dirname, "../frontend/public/config.js"), `window.CROWD_CONFIG = ${JSON.stringify(addresses)};\n`);
  console.log(JSON.stringify(addresses, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
