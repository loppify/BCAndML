// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/** @title Minimal registry interface used by the other system contracts. */
interface IDeviceRegistry {
    function exists(bytes32 deviceId) external view returns (bool);
    function ownerOfDevice(bytes32 deviceId) external view returns (address);
}
