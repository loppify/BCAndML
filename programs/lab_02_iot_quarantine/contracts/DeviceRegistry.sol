// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title DeviceRegistry
 * @notice Registers pseudonymous virtual device identifiers and their owners.
 * @dev Device IDs are derived from msg.sender and a caller-chosen salt to
 *      prevent another address from front-running a predictable device ID.
 */
contract DeviceRegistry is AccessControl {
    bytes32 public constant ADMIN_ROLE = DEFAULT_ADMIN_ROLE;

    struct Device {
        address owner;
        bytes32 metadataHash;
        bool registered;
    }

    mapping(bytes32 deviceId => Device device) private _devices;

    error ZeroDeviceSalt();
    error ZeroMetadataHash();
    error DeviceAlreadyRegistered(bytes32 deviceId);
    error DeviceNotRegistered(bytes32 deviceId);
    error ZeroOwner();
    error NotDeviceOwner(bytes32 deviceId, address caller);

    event DeviceRegistered(bytes32 indexed deviceId, address indexed owner, bytes32 metadataHash);
    event OwnerChanged(bytes32 indexed deviceId, address indexed oldOwner, address indexed newOwner);

    /** @notice Assigns the initial administrator. */
    constructor(address admin) {
        if (admin == address(0)) revert ZeroOwner();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /**
     * @notice Registers a device owned by the caller.
     * @param salt Unique secret or random value selected by the owner.
     * @param metadataHash Hash of off-chain metadata, never the raw metadata.
     * @return deviceId Stable ID derived from caller and salt.
     */
    function registerDevice(bytes32 salt, bytes32 metadataHash) external returns (bytes32 deviceId) {
        if (salt == bytes32(0)) revert ZeroDeviceSalt();
        if (metadataHash == bytes32(0)) revert ZeroMetadataHash();

        deviceId = keccak256(abi.encode(msg.sender, salt));
        if (_devices[deviceId].registered) revert DeviceAlreadyRegistered(deviceId);

        _devices[deviceId] = Device({owner: msg.sender, metadataHash: metadataHash, registered: true});
        emit DeviceRegistered(deviceId, msg.sender, metadataHash);
    }

    /**
     * @notice Transfers device ownership to a new address.
     * @dev The current owner or an administrator may transfer ownership.
     */
    function updateOwner(bytes32 deviceId, address newOwner) external {
        Device storage device = _requireDevice(deviceId);
        if (newOwner == address(0)) revert ZeroOwner();
        if (msg.sender != device.owner && !hasRole(DEFAULT_ADMIN_ROLE, msg.sender)) {
            revert NotDeviceOwner(deviceId, msg.sender);
        }

        address oldOwner = device.owner;
        device.owner = newOwner;
        emit OwnerChanged(deviceId, oldOwner, newOwner);
    }

    /** @notice Returns the registered owner of a device. */
    function ownerOfDevice(bytes32 deviceId) external view returns (address) {
        return _requireDeviceView(deviceId).owner;
    }

    /** @notice Returns whether a device ID has been registered. */
    function exists(bytes32 deviceId) external view returns (bool) {
        return _devices[deviceId].registered;
    }

    /** @notice Returns the hash of the device's off-chain metadata. */
    function metadataHashOf(bytes32 deviceId) external view returns (bytes32) {
        return _requireDeviceView(deviceId).metadataHash;
    }

    function _requireDevice(bytes32 deviceId) private view returns (Device storage device) {
        device = _devices[deviceId];
        if (!device.registered) revert DeviceNotRegistered(deviceId);
    }

    function _requireDeviceView(bytes32 deviceId) private view returns (Device storage device) {
        device = _devices[deviceId];
        if (!device.registered) revert DeviceNotRegistered(deviceId);
    }
}
