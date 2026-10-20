// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
import {AuthorRegistry} from "./AuthorRegistry.sol";

/// @custom:oz-upgrades-unsafe-allow missing-initializer
contract AuthorRegistryV2 is AuthorRegistry {
    function initializeV2() external reinitializer(2) {}
    function implementationVersion() external pure returns (uint256) { return 2; }
}
