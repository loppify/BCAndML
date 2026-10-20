// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {CrowdfundingHub} from "./CrowdfundingHub.sol";

/// @title CrowdfundingHubV2
/// @notice Upgrade demonstration that preserves existing campaign storage.
/// @custom:oz-upgrades-unsafe-allow missing-initializer
contract CrowdfundingHubV2 is CrowdfundingHub {
    function initializeV2() external reinitializer(2) onlyRole(DEFAULT_ADMIN_ROLE) {}
    function implementationVersion() external pure returns (uint256) { return 2; }
}
