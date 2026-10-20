const { expect } = require("chai");
const { ethers, upgrades } = require("hardhat");

async function deploySystem() {
  const [admin, author, donor, other, arbiter] = await ethers.getSigners();
  const Registry = await ethers.getContractFactory("AuthorRegistry");
  const registry = await upgrades.deployProxy(Registry, [admin.address], { kind: "uups" });
  const Token = await ethers.getContractFactory("ContributionToken");
  const token = await upgrades.deployProxy(Token, [admin.address], { kind: "uups" });
  const Hub = await ethers.getContractFactory("CrowdfundingHub");
  const hub = await upgrades.deployProxy(Hub, [admin.address, await registry.getAddress(), await token.getAddress()], { kind: "uups" });
  await registry.grantRole(await registry.CAMPAIGN_ROLE(), await hub.getAddress());
  await token.grantRole(await token.MINTER_ROLE(), await hub.getAddress());
  await registry.registerAuthor(author.address);
  return { admin, author, donor, other, arbiter, registry, token, hub };
}

async function futureDeadline(seconds = 3600) {
  const block = await ethers.provider.getBlock("latest");
  return BigInt(block.timestamp + seconds);
}

async function setTime(timestamp) {
  await ethers.provider.send("evm_setNextBlockTimestamp", [Number(timestamp)]);
  await ethers.provider.send("evm_mine", []);
}

async function makeCampaign(ctx, goal = ethers.parseEther("2"), deadline = undefined) {
  const end = deadline ?? await futureDeadline();
  await ctx.hub.connect(ctx.author).createCampaign(goal, end, "ipfs://bafy-campaign");
  return { id: await ctx.hub.campaignCount(), deadline: end };
}

describe("CrowdfundingHub and role/token contracts", function () {
  beforeEach(async function () { Object.assign(this, await deploySystem()); });

  it("initializes token metadata and administrator roles", async function () {
    expect(await this.token.name()).to.equal("Crowd Reward");
    expect(await this.token.symbol()).to.equal("CRWD");
    expect(await this.token.hasRole(await this.token.DEFAULT_ADMIN_ROLE(), this.admin.address)).to.equal(true);
  });

  it("rejects a zero reward-token administrator", async function () {
    const Token = await ethers.getContractFactory("ContributionToken");
    await expect(upgrades.deployProxy(Token, [ethers.ZeroAddress], { kind: "uups" }))
      .to.be.revertedWithCustomError(Token, "ZeroAddress");
  });

  it("disables implementation initializers", async function () {
    const Factory = await ethers.getContractFactory("AuthorRegistry");
    const implementation = await Factory.deploy();
    await expect(implementation.initialize(this.admin.address)).to.be.revertedWithCustomError(implementation, "InvalidInitialization");
  });

  it("rejects a zero administrator during initialization", async function () {
    const Factory = await ethers.getContractFactory("AuthorRegistry");
    await expect(upgrades.deployProxy(Factory, [ethers.ZeroAddress], { kind: "uups" }))
      .to.be.revertedWithCustomError(Factory, "ZeroAddress");
  });

  it("rejects missing hub component addresses", async function () {
    const Hub = await ethers.getContractFactory("CrowdfundingHub");
    await expect(upgrades.deployProxy(Hub, [this.admin.address, ethers.ZeroAddress, await this.token.getAddress()], { kind: "uups" }))
      .to.be.revertedWithCustomError(Hub, "ZeroAddress");
    await expect(upgrades.deployProxy(Hub, [this.admin.address, await this.registry.getAddress(), ethers.ZeroAddress], { kind: "uups" }))
      .to.be.revertedWithCustomError(Hub, "ZeroAddress");
  });

  it("registers and removes approved authors", async function () {
    await expect(this.registry.registerAuthor(this.other.address))
      .to.emit(this.registry, "AuthorRegistered").withArgs(this.other.address, this.admin.address);
    expect(await this.registry.isAuthor(this.other.address)).to.equal(true);
    await expect(this.registry.removeAuthor(this.other.address)).to.emit(this.registry, "AuthorRemoved");
    expect(await this.registry.isAuthor(this.other.address)).to.equal(false);
  });

  it("rejects author registration by a non-admin", async function () {
    await expect(this.registry.connect(this.author).registerAuthor(this.other.address))
      .to.be.revertedWithCustomError(this.registry, "AccessControlUnauthorizedAccount");
  });

  it("rejects zero and duplicate author registrations", async function () {
    await expect(this.registry.registerAuthor(ethers.ZeroAddress)).to.be.revertedWithCustomError(this.registry, "ZeroAddress");
    await expect(this.registry.registerAuthor(this.author.address)).to.be.revertedWithCustomError(this.registry, "AlreadyAuthor");
  });

  it("rejects revocation of an unregistered author", async function () {
    await expect(this.registry.removeAuthor(this.other.address)).to.be.revertedWithCustomError(this.registry, "NotAuthor");
  });

  it("restricts author revocation to the administrator", async function () {
    await expect(this.registry.connect(this.author).removeAuthor(this.author.address))
      .to.be.revertedWithCustomError(this.registry, "AccessControlUnauthorizedAccount");
  });

  it("returns bounded author pages and rejects invalid limits", async function () {
    await this.registry.registerAuthor(this.other.address);
    expect((await this.registry.authors(0, 1)).length).to.equal(1);
    expect((await this.registry.authors(0, 10)).length).to.equal(2);
    expect((await this.registry.authors(100, 10)).length).to.equal(0);
    await expect(this.registry.authors(0, 0)).to.be.revertedWithCustomError(this.registry, "InvalidPageSize");
    await expect(this.registry.authors(0, 101)).to.be.revertedWithCustomError(this.registry, "InvalidPageSize");
  });

  it("only campaign operators can register contributors", async function () {
    await expect(this.registry.connect(this.donor).registerContributor(this.donor.address))
      .to.be.revertedWithCustomError(this.registry, "AccessControlUnauthorizedAccount");
    await expect(this.registry.connect(this.hub.runner).registerContributor(ethers.ZeroAddress))
      .to.be.reverted;
  });

  it("rejects campaign creation by an unapproved account", async function () {
    await expect(this.hub.connect(this.donor).createCampaign(1, await futureDeadline(), ""))
      .to.be.revertedWithCustomError(this.hub, "NotAuthor");
  });

  it("rejects zero goals and expired deadlines", async function () {
    await expect(this.hub.connect(this.author).createCampaign(0, await futureDeadline(), ""))
      .to.be.revertedWithCustomError(this.hub, "ZeroGoal");
    const block = await ethers.provider.getBlock("latest");
    await expect(this.hub.connect(this.author).createCampaign(1, block.timestamp, ""))
      .to.be.revertedWithCustomError(this.hub, "DeadlineNotFuture");
  });

  it("creates a campaign and emits its complete initial state", async function () {
    const deadline = await futureDeadline();
    await expect(this.hub.connect(this.author).createCampaign(1000, deadline, "ipfs://metadata"))
      .to.emit(this.hub, "CampaignCreated").withArgs(1, this.author.address, 1000, deadline, "ipfs://metadata");
    const campaign = await this.hub.getCampaign(1);
    expect(campaign.creator).to.equal(this.author.address);
    expect(campaign.goal).to.equal(1000);
    expect(campaign.status).to.equal(0);
  });

  it("rejects reads and writes using unknown campaign identifiers", async function () {
    await expect(this.hub.getCampaign(1)).to.be.revertedWithCustomError(this.hub, "CampaignNotFound");
    await expect(this.hub.connect(this.donor).contribute(1, { value: 1 })).to.be.revertedWithCustomError(this.hub, "CampaignNotFound");
  });

  it("rejects a zero-value contribution", async function () {
    await makeCampaign(this);
    await expect(this.hub.connect(this.donor).contribute(1)).to.be.revertedWithCustomError(this.hub, "ContributionIsZero");
  });

  it("rejects a value that exceeds the packed accounting width", async function () {
    await makeCampaign(this);
    await ethers.provider.send("hardhat_setBalance", [this.donor.address, ethers.toBeHex(1n << 130n)]);
    await expect(this.hub.connect(this.donor).contribute(1, { value: 1n << 128n }))
      .to.be.revertedWithCustomError(this.hub, "ContributionTooLarge");
  });

  it("accepts contributions, grants contributor role, and mints rewards", async function () {
    const { id } = await makeCampaign(this);
    const amount = ethers.parseEther("0.5");
    await expect(this.hub.connect(this.donor).contribute(id, { value: amount }))
      .to.emit(this.hub, "ContributionReceived").withArgs(id, this.donor.address, amount, amount);
    expect(await this.registry.hasRole(await this.registry.CONTRIBUTOR_ROLE(), this.donor.address)).to.equal(true);
    expect(await this.token.balanceOf(this.donor.address)).to.equal(amount);
    expect(await this.hub.contributions(id, this.donor.address)).to.equal(amount);
    await this.hub.connect(this.donor).contribute(id, { value: 1 });
  });

  it("rejects a contribution at the exact deadline", async function () {
    const { id, deadline } = await makeCampaign(this);
    await setTime(deadline);
    await expect(this.hub.connect(this.donor).contribute(id, { value: 1 })).to.be.revertedWithCustomError(this.hub, "CampaignEnded");
  });

  it("marks a campaign successful when the goal is met and blocks further contributions", async function () {
    const goal = ethers.parseEther("1");
    await makeCampaign(this, goal);
    await expect(this.hub.connect(this.donor).contribute(1, { value: goal }))
      .to.emit(this.hub, "CampaignSucceeded").withArgs(1, goal);
    expect((await this.hub.getCampaign(1)).status).to.equal(1);
    await expect(this.hub.connect(this.other).contribute(1, { value: 1 })).to.be.revertedWithCustomError(this.hub, "CampaignNotActive");
  });

  it("rejects finalize before the deadline", async function () {
    await makeCampaign(this);
    await expect(this.hub.finalize(1)).to.be.revertedWithCustomError(this.hub, "DeadlineNotReached");
  });

  it("finalizes an underfunded campaign as failed at the deadline", async function () {
    const { id, deadline } = await makeCampaign(this);
    await this.hub.connect(this.donor).contribute(id, { value: 10 });
    await setTime(deadline);
    await expect(this.hub.connect(this.other).finalize(id)).to.emit(this.hub, "CampaignFailed").withArgs(id, 10);
    expect((await this.hub.getCampaign(id)).status).to.equal(2);
  });

  it("finalizes a funded campaign successfully after expiry", async function () {
    const goal = ethers.parseEther("1");
    const { id, deadline } = await makeCampaign(this, goal);
    await this.hub.connect(this.donor).contribute(id, { value: goal });
    await setTime(deadline);
    await expect(this.hub.finalize(id)).to.be.revertedWithCustomError(this.hub, "CampaignNotActive");
    expect((await this.hub.getCampaign(id)).status).to.equal(1);
  });

  it("rejects refunds while a campaign is still active", async function () {
    await makeCampaign(this);
    await this.hub.connect(this.donor).contribute(1, { value: 1 });
    await expect(this.hub.connect(this.donor).refund(1)).to.be.revertedWithCustomError(this.hub, "GoalReached");
  });

  it("rejects a refund when the caller made no contribution", async function () {
    const { id, deadline } = await makeCampaign(this);
    await setTime(deadline);
    await this.hub.finalize(id);
    await expect(this.hub.connect(this.donor).refund(id)).to.be.revertedWithCustomError(this.hub, "NothingToRefund");
  });

  it("returns a failed contribution through pull payment exactly once", async function () {
    const { id, deadline } = await makeCampaign(this);
    await this.hub.connect(this.donor).contribute(id, { value: 12345 });
    await setTime(deadline);
    await expect(this.hub.connect(this.donor).refund(id)).to.emit(this.hub, "ContributionRefunded").withArgs(id, this.donor.address, 12345);
    expect(await this.hub.contributions(id, this.donor.address)).to.equal(0);
    await expect(this.hub.connect(this.donor).refund(id)).to.be.revertedWithCustomError(this.hub, "NothingToRefund");
  });

  it("lets a creator withdraw successful proceeds once", async function () {
    const goal = ethers.parseEther("1");
    await makeCampaign(this, goal);
    await this.hub.connect(this.donor).contribute(1, { value: goal });
    await expect(this.hub.connect(this.author).withdrawProceeds(1))
      .to.emit(this.hub, "ProceedsWithdrawn").withArgs(1, this.author.address, goal);
    expect((await this.hub.getCampaign(1)).proceedsWithdrawn).to.equal(true);
    await expect(this.hub.connect(this.author).withdrawProceeds(1)).to.be.revertedWithCustomError(this.hub, "AlreadyWithdrawn");
  });

  it("prevents non-creators withdrawing and creators withdrawing failed proceeds", async function () {
    await makeCampaign(this);
    await expect(this.hub.connect(this.other).withdrawProceeds(1)).to.be.revertedWithCustomError(this.hub, "NotCreator");
    await expect(this.hub.connect(this.author).withdrawProceeds(1)).to.be.revertedWithCustomError(this.hub, "GoalNotReached");
  });

  it("preserves funds when the creator rejects a pull payment", async function () {
    const Receiver = await ethers.getContractFactory("RejectingReceiver");
    const receiver = await Receiver.deploy(await this.hub.getAddress());
    await this.registry.registerAuthor(await receiver.getAddress());
    await receiver.create(1000, await futureDeadline());
    await this.hub.connect(this.donor).contribute(1, { value: 1000 });
    await expect(receiver.withdraw(1)).to.be.revertedWithCustomError(this.hub, "TransferFailed");
    expect((await this.hub.getCampaign(1)).proceedsWithdrawn).to.equal(false);
  });

  it("preserves a refund claim if the contributor rejects the payment", async function () {
    const { deadline } = await makeCampaign(this);
    const Receiver = await ethers.getContractFactory("RejectingReceiver");
    const receiver = await Receiver.deploy(await this.hub.getAddress());
    await receiver.contribute(1, { value: 1000 });
    await setTime(deadline);
    await this.hub.finalize(1);
    await expect(receiver.claimRefund(1)).to.be.revertedWithCustomError(this.hub, "TransferFailed");
    expect(await this.hub.contributions(1, await receiver.getAddress())).to.equal(1000);
  });

  it("exposes campaigns in bounded pages", async function () {
    await makeCampaign(this, 1);
    await makeCampaign(this, 2);
    expect((await this.hub.getCampaigns(0, 1)).length).to.equal(1);
    expect((await this.hub.getCampaigns(0, 10)).length).to.equal(2);
    expect((await this.hub.getCampaigns(2, 1)).length).to.equal(0);
    await expect(this.hub.getCampaigns(0, 0)).to.be.revertedWithCustomError(this.hub, "InvalidPageSize");
    await expect(this.hub.getCampaigns(0, 101)).to.be.revertedWithCustomError(this.hub, "InvalidPageSize");
  });

  it("pauses creation and contributions but leaves refunds available", async function () {
    const { id, deadline } = await makeCampaign(this);
    await this.hub.pause();
    await expect(this.hub.connect(this.author).createCampaign(1, await futureDeadline(), ""))
      .to.be.revertedWithCustomError(this.hub, "EnforcedPause");
    await expect(this.hub.connect(this.donor).contribute(id, { value: 1 })).to.be.revertedWithCustomError(this.hub, "EnforcedPause");
    await this.hub.unpause();
    await this.hub.connect(this.donor).contribute(id, { value: 1 });
    await setTime(deadline);
    await this.hub.finalize(id);
    await this.hub.pause();
    await expect(this.hub.connect(this.donor).refund(id)).to.emit(this.hub, "ContributionRefunded");
  });

  it("restricts pause control to the pauser role", async function () {
    await expect(this.hub.connect(this.donor).pause()).to.be.revertedWithCustomError(this.hub, "AccessControlUnauthorizedAccount");
    await this.hub.pause();
    await expect(this.hub.connect(this.donor).unpause()).to.be.revertedWithCustomError(this.hub, "AccessControlUnauthorizedAccount");
  });

  it("restricts token minting and supports emergency pause", async function () {
    await expect(this.token.connect(this.donor).mint(this.donor.address, 1)).to.be.revertedWithCustomError(this.token, "AccessControlUnauthorizedAccount");
    await expect(this.token.connect(this.donor).pause()).to.be.revertedWithCustomError(this.token, "AccessControlUnauthorizedAccount");
    await this.token.grantRole(await this.token.MINTER_ROLE(), this.admin.address);
    await this.token.mint(this.donor.address, 1);
    await this.token.pause();
    await expect(this.token.mint(this.donor.address, 1)).to.be.revertedWithCustomError(this.token, "EnforcedPause");
    await expect(this.token.connect(this.donor).transfer(this.other.address, 1)).to.be.revertedWithCustomError(this.token, "EnforcedPause");
    await expect(this.token.connect(this.donor).unpause()).to.be.revertedWithCustomError(this.token, "AccessControlUnauthorizedAccount");
    await this.token.unpause();
    await expect(this.token.mint(ethers.ZeroAddress, 1)).to.be.revertedWithCustomError(this.token, "ZeroAddress");
  });

  it("rejects zero addresses in registry contributor registration", async function () {
    await this.registry.grantRole(await this.registry.CAMPAIGN_ROLE(), this.donor.address);
    await expect(this.registry.connect(this.donor).registerContributor(ethers.ZeroAddress)).to.be.revertedWithCustomError(this.registry, "ZeroAddress");
  });

  it("upgrades registry and token UUPS proxies while retaining state", async function () {
    await this.token.grantRole(await this.token.MINTER_ROLE(), this.admin.address);
    await this.token.mint(this.donor.address, 42);
    const RegistryV2 = await ethers.getContractFactory("AuthorRegistryV2");
    const registryV2 = await upgrades.upgradeProxy(await this.registry.getAddress(), RegistryV2, { call: "initializeV2" });
    const TokenV2 = await ethers.getContractFactory("ContributionTokenV2");
    const tokenV2 = await upgrades.upgradeProxy(await this.token.getAddress(), TokenV2, { call: "initializeV2" });
    expect(await registryV2.isAuthor(this.author.address)).to.equal(true);
    expect(await registryV2.implementationVersion()).to.equal(2);
    await expect(registryV2.initializeV2()).to.be.revertedWithCustomError(registryV2, "InvalidInitialization");
    expect(await tokenV2.balanceOf(this.donor.address)).to.equal(42);
    expect(await tokenV2.implementationVersion()).to.equal(2);
    await expect(tokenV2.initializeV2()).to.be.revertedWithCustomError(tokenV2, "InvalidInitialization");
  });

  it("rejects unauthorized registry and token UUPS upgrades", async function () {
    const RegistryV2 = await ethers.getContractFactory("AuthorRegistryV2");
    await expect(upgrades.upgradeProxy(await this.registry.getAddress(), RegistryV2.connect(this.donor), { call: "initializeV2" }))
      .to.be.revertedWithCustomError(this.registry, "AccessControlUnauthorizedAccount");
    const TokenV2 = await ethers.getContractFactory("ContributionTokenV2");
    await expect(upgrades.upgradeProxy(await this.token.getAddress(), TokenV2.connect(this.donor), { call: "initializeV2" }))
      .to.be.revertedWithCustomError(this.token, "AccessControlUnauthorizedAccount");
  });

  it("blocks re-entrant refund callbacks in the production campaign", async function () {
    const { deadline } = await makeCampaign(this);
    const Factory = await ethers.getContractFactory("SafeRefundAttacker");
    const attacker = await Factory.deploy(await this.hub.getAddress(), 1);
    await attacker.contribute({ value: 1000 });
    await setTime(deadline);
    await attacker.attackRefund();
    expect(await attacker.reentryBlocked()).to.equal(true);
    expect(await ethers.provider.getBalance(await this.hub.getAddress())).to.equal(0);
    console.log("SAFE_REFUND: re-entry blocked; legitimate credit cleared before callback; hub balance=0");
  });

  it("demonstrates that the intentionally vulnerable copy can be drained", async function () {
    const [victim] = await ethers.getSigners();
    const Vault = await ethers.getContractFactory("VulnerableRefundVault");
    const vault = await Vault.deploy();
    await vault.connect(victim).deposit({ value: ethers.parseEther("5") });
    const Attacker = await ethers.getContractFactory("RefundAttacker");
    const attacker = await Attacker.deploy(await vault.getAddress());
    await attacker.attack({ value: ethers.parseEther("1") });
    expect(await ethers.provider.getBalance(await vault.getAddress())).to.equal(0);
    expect(await attacker.received()).to.equal(ethers.parseEther("6"));
    console.log("VULNERABLE_REFUND: attacker deposited 1 ETH, withdrew 6 ETH; vault balance=0");
  });

  it("demonstrates failed payout to a receiver that rejects ETH", async function () {
    const Vault = await ethers.getContractFactory("VulnerableRefundVault");
    const vault = await Vault.deploy();
    const Claimant = await ethers.getContractFactory("RejectingVaultClaimant");
    const claimant = await Claimant.deploy(await vault.getAddress());
    await claimant.deposit({ value: 1000 });
    await expect(claimant.claim()).to.be.reverted;
    expect(await vault.credit(await claimant.getAddress())).to.equal(1000);
  });

  it("upgrades the hub implementation without losing campaign state", async function () {
    const { id } = await makeCampaign(this, 9876);
    const before = await this.hub.getCampaign(id);
    const V2 = await ethers.getContractFactory("CrowdfundingHubV2");
    const upgraded = await upgrades.upgradeProxy(await this.hub.getAddress(), V2, { call: "initializeV2" });
    expect(await upgraded.implementationVersion()).to.equal(2);
    const after = await upgraded.getCampaign(id);
    expect(after.creator).to.equal(before.creator);
    expect(after.goal).to.equal(before.goal);
    expect(after.metadataURI).to.equal(before.metadataURI);
    await expect(upgraded.initializeV2()).to.be.revertedWithCustomError(upgraded, "InvalidInitialization");
  });

  it("rejects an upgrade from a non-admin account", async function () {
    const V2 = await ethers.getContractFactory("CrowdfundingHubV2");
    await expect(upgrades.upgradeProxy(await this.hub.getAddress(), V2.connect(this.donor), { call: "initializeV2" }))
      .to.be.revertedWithCustomError(this.hub, "AccessControlUnauthorizedAccount");
  });
});
