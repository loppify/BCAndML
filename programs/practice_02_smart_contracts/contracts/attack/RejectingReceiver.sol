// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

interface ICrowdfundingActions {
    function createCampaign(uint128 goal, uint64 deadline, string calldata uri) external returns (uint256);
    function contribute(uint256 id) external payable;
    function withdrawProceeds(uint256 id) external;
    function refund(uint256 id) external;
}
interface IVulnerableRefund { function deposit() external payable; function refund() external; }

contract RejectingReceiver {
    ICrowdfundingActions public immutable hub;
    constructor(address hub_) { hub = ICrowdfundingActions(hub_); }
    function create(uint128 goal, uint64 deadline) external { hub.createCampaign(goal, deadline, ""); }
    function contribute(uint256 id) external payable { hub.contribute{value: msg.value}(id); }
    function withdraw(uint256 id) external { hub.withdrawProceeds(id); }
    function claimRefund(uint256 id) external { hub.refund(id); }
    receive() external payable { revert("recipient rejects ETH"); }
}

contract RejectingVaultClaimant {
    IVulnerableRefund public immutable vault;
    constructor(address vault_) { vault = IVulnerableRefund(vault_); }
    function deposit() external payable { vault.deposit{value: msg.value}(); }
    function claim() external { vault.refund(); }
    receive() external payable { revert("reject payment"); }
}
