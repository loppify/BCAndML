// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @dev Test-only deliberately vulnerable copy of pull refunds.
contract VulnerableRefundVault {
    mapping(address => uint256) public credit;
    function deposit() external payable { credit[msg.sender] += msg.value; }
    function refund() external {
        uint256 amount = credit[msg.sender];
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
        credit[msg.sender] = 0; // vulnerability: the state changes after the callback
    }
}
