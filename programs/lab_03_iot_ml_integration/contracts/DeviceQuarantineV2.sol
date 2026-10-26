// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {DeviceQuarantine} from "./DeviceQuarantine.sol";

/** @title DeviceQuarantineV2 @notice Minimal upgrade used to verify proxy storage preservation. */
contract DeviceQuarantineV2 is DeviceQuarantine {
    uint32 public implementationVersion;

    /** @notice Initializes the added V2 field without changing existing state. */
    function initializeV2() external reinitializer(2) onlyRole(DEFAULT_ADMIN_ROLE) {
        implementationVersion = 2;
    }
}
