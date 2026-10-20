const { ethers, network } = require("hardhat");
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [admin, author, donor] = await ethers.getSigners();
  const deployment = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../deployments/localhost.json"), "utf8"));
  const hub = await ethers.getContractAt("CrowdfundingHub", deployment.hub, author);

  let block = await ethers.provider.getBlock("latest");
  let deadline = BigInt(block.timestamp + 3600);
  await (await hub.createCampaign(ethers.parseEther("1"), deadline, "ipfs://success-demo")).wait();
  await (await hub.connect(donor).contribute(1, { value: ethers.parseEther("1") })).wait();
  await (await hub.withdrawProceeds(1)).wait();

  block = await ethers.provider.getBlock("latest");
  deadline = BigInt(block.timestamp + 3600);
  await (await hub.createCampaign(ethers.parseEther("2"), deadline, "ipfs://failed-demo")).wait();
  await (await hub.connect(donor).contribute(2, { value: ethers.parseEther("0.25") })).wait();
  await network.provider.send("evm_setNextBlockTimestamp", [Number(deadline)]);
  await network.provider.send("evm_mine");
  await (await hub.connect(admin).finalize(2)).wait();
  await (await hub.connect(donor).refund(2)).wait();

  const first = await hub.getCampaign(1);
  const second = await hub.getCampaign(2);
  const results = {
    chainId: Number((await ethers.provider.getNetwork()).chainId),
    admin: admin.address,
    author: author.address,
    contributor: donor.address,
    successfulCampaign: { id: "1", status: Number(first.status), raisedWei: first.totalRaised.toString(), proceedsWithdrawn: first.proceedsWithdrawn },
    failedCampaign: { id: "2", status: Number(second.status), raisedWei: second.totalRaised.toString(), contributorRefundWei: (await hub.contributions(2, donor.address)).toString() },
    contributorRewardWei: String(await (await ethers.getContractAt("ContributionToken", deployment.token)).balanceOf(donor.address)),
    indexedEventsExpected: ["CampaignCreated", "ContributionReceived", "CampaignSucceeded", "ProceedsWithdrawn", "CampaignCreated", "ContributionReceived", "CampaignFailed", "ContributionRefunded"]
  };
  const output = path.resolve(__dirname, "../artifacts/local-demo.json");
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
