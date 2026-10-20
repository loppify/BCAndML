// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {AccessControlUpgradeable} from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {ReentrancyGuardUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {IAuthorRegistry} from "./interfaces/IAuthorRegistry.sol";
import {IContributionToken} from "./interfaces/IContributionToken.sol";

/// @title CrowdfundingHub
/// @notice ETH crowdfunding with ERC-20 rewards and pull-based settlement.
contract CrowdfundingHub is Initializable, AccessControlUpgradeable, PausableUpgradeable, ReentrancyGuardUpgradeable, UUPSUpgradeable {
    enum Status { Active, Successful, Failed }

    struct Campaign {
        address payable creator;
        uint128 goal;
        uint64 deadline;
        uint128 totalRaised;
        Status status;
        bool proceedsWithdrawn;
        string metadataURI;
    }

    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");
    uint256 public constant MAX_PAGE_SIZE = 100;
    IAuthorRegistry public authorRegistry;
    IContributionToken public rewardToken;
    uint256 public campaignCount;
    mapping(uint256 campaignId => Campaign campaign) private _campaigns;
    mapping(uint256 campaignId => mapping(address contributor => uint256 amount)) public contributions;

    error ZeroAddress();
    error ZeroGoal();
    error DeadlineNotFuture();
    error CampaignNotFound(uint256 campaignId);
    error NotAuthor(address account);
    error CampaignNotActive(uint256 campaignId);
    error CampaignEnded(uint256 campaignId);
    error DeadlineNotReached(uint256 campaignId);
    error ContributionIsZero();
    error ContributionTooLarge();
    error GoalNotReached(uint256 campaignId);
    error GoalReached(uint256 campaignId);
    error NotCreator(address caller);
    error AlreadyWithdrawn(uint256 campaignId);
    error NothingToRefund(uint256 campaignId);
    error TransferFailed();
    error InvalidPageSize();

    event CampaignCreated(uint256 indexed campaignId, address indexed creator, uint256 goal, uint256 deadline, string metadataURI);
    event ContributionReceived(uint256 indexed campaignId, address indexed contributor, uint256 amount, uint256 totalRaised);
    event CampaignSucceeded(uint256 indexed campaignId, uint256 totalRaised);
    event CampaignFailed(uint256 indexed campaignId, uint256 totalRaised);
    event ProceedsWithdrawn(uint256 indexed campaignId, address indexed creator, uint256 amount);
    event ContributionRefunded(uint256 indexed campaignId, address indexed contributor, uint256 amount);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() { _disableInitializers(); }

    /// @notice Initializes component addresses and administrative roles.
    function initialize(address admin, address registry, address token) external initializer {
        if (admin == address(0) || registry == address(0) || token == address(0)) revert ZeroAddress();
        __AccessControl_init();
        __Pausable_init();
        __ReentrancyGuard_init();
        __UUPSUpgradeable_init();
        authorRegistry = IAuthorRegistry(registry);
        rewardToken = IContributionToken(token);
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
    }

    /// @notice Creates a campaign for an approved author.
    /// @param goalWei Minimum amount of wei required for success.
    /// @param deadlineUnix Timestamp after which contributions stop.
    /// @param metadataURI Off-chain description identifier or URI.
    function createCampaign(uint128 goalWei, uint64 deadlineUnix, string calldata metadataURI)
        external whenNotPaused returns (uint256 campaignId)
    {
        if (!authorRegistry.isAuthor(msg.sender)) revert NotAuthor(msg.sender);
        if (goalWei == 0) revert ZeroGoal();
        if (deadlineUnix <= block.timestamp) revert DeadlineNotFuture();
        campaignId = ++campaignCount;
        _campaigns[campaignId] = Campaign(payable(msg.sender), goalWei, deadlineUnix, 0, Status.Active, false, metadataURI);
        emit CampaignCreated(campaignId, msg.sender, goalWei, deadlineUnix, metadataURI);
    }

    /// @notice Contributes ETH before the deadline and receives ERC-20 rewards.
    function contribute(uint256 campaignId) external payable nonReentrant whenNotPaused {
        Campaign storage campaign = _getCampaign(campaignId);
        if (campaign.status != Status.Active) revert CampaignNotActive(campaignId);
        if (block.timestamp >= campaign.deadline) revert CampaignEnded(campaignId);
        if (msg.value == 0) revert ContributionIsZero();
        if (msg.value > type(uint128).max - campaign.totalRaised) revert ContributionTooLarge();
        campaign.totalRaised += uint128(msg.value);
        contributions[campaignId][msg.sender] += msg.value;
        authorRegistry.registerContributor(msg.sender);
        rewardToken.mint(msg.sender, msg.value);
        emit ContributionReceived(campaignId, msg.sender, msg.value, campaign.totalRaised);
        if (campaign.totalRaised >= campaign.goal) {
            campaign.status = Status.Successful;
            emit CampaignSucceeded(campaignId, campaign.totalRaised);
        }
    }

    /// @notice Finalizes an expired campaign that has not reached its goal.
    function finalize(uint256 campaignId) external {
        Campaign storage campaign = _getCampaign(campaignId);
        if (campaign.status != Status.Active) revert CampaignNotActive(campaignId);
        if (block.timestamp < campaign.deadline) revert DeadlineNotReached(campaignId);
        campaign.status = Status.Failed;
        emit CampaignFailed(campaignId, campaign.totalRaised);
    }

    /// @notice Lets the creator pull proceeds from a successful campaign once.
    function withdrawProceeds(uint256 campaignId) external nonReentrant {
        Campaign storage campaign = _getCampaign(campaignId);
        if (campaign.creator != msg.sender) revert NotCreator(msg.sender);
        if (campaign.status != Status.Successful) revert GoalNotReached(campaignId);
        if (campaign.proceedsWithdrawn) revert AlreadyWithdrawn(campaignId);
        uint256 amount = campaign.totalRaised;
        campaign.proceedsWithdrawn = true;
        (bool ok,) = campaign.creator.call{value: amount}("");
        if (!ok) revert TransferFailed();
        emit ProceedsWithdrawn(campaignId, msg.sender, amount);
    }

    /// @notice Lets a contributor pull their funds after a failed campaign.
    function refund(uint256 campaignId) external nonReentrant {
        Campaign storage campaign = _getCampaign(campaignId);
        if (campaign.status == Status.Active && block.timestamp >= campaign.deadline) {
            campaign.status = Status.Failed;
            emit CampaignFailed(campaignId, campaign.totalRaised);
        }
        if (campaign.status != Status.Failed) revert GoalReached(campaignId);
        uint256 amount = contributions[campaignId][msg.sender];
        if (amount == 0) revert NothingToRefund(campaignId);
        contributions[campaignId][msg.sender] = 0;
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        if (!ok) revert TransferFailed();
        emit ContributionRefunded(campaignId, msg.sender, amount);
    }

    /// @notice Returns one campaign record.
    function getCampaign(uint256 campaignId) external view returns (Campaign memory) { return _getCampaign(campaignId); }

    /// @notice Returns a bounded page of campaign records.
    function getCampaigns(uint256 offset, uint256 limit) external view returns (Campaign[] memory page) {
        if (limit == 0 || limit > MAX_PAGE_SIZE) revert InvalidPageSize();
        if (offset >= campaignCount) return new Campaign[](0);
        uint256 size = campaignCount - offset;
        if (size > limit) size = limit;
        page = new Campaign[](size);
        for (uint256 i; i < size; ++i) page[i] = _campaigns[offset + i + 1];
    }

    /// @notice Pauses campaign creation and contributions during an emergency.
    function pause() external onlyRole(PAUSER_ROLE) { _pause(); }

    /// @notice Resumes campaign creation and contributions.
    function unpause() external onlyRole(PAUSER_ROLE) { _unpause(); }

    function _getCampaign(uint256 campaignId) internal view returns (Campaign storage campaign) {
        if (campaignId == 0 || campaignId > campaignCount) revert CampaignNotFound(campaignId);
        campaign = _campaigns[campaignId];
    }

    function _authorizeUpgrade(address) internal override onlyRole(DEFAULT_ADMIN_ROLE) {}
}
