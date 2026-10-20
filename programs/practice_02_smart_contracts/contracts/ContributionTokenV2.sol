// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import {ContributionToken} from "./ContributionToken.sol";

/// @custom:oz-upgrades-unsafe-allow missing-initializer
contract ContributionTokenV2 is ContributionToken {
    function initializeV2() external reinitializer(2) {}
    function implementationVersion() external pure returns (uint256) { return 2; }
}
