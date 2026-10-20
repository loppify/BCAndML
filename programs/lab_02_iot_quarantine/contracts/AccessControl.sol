// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {AccessControl as OpenZeppelinAccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IDeviceRegistry} from "./interfaces/IDeviceRegistry.sol";

/**
 * @title AccessControl
 * @notice Manages expiring operator permissions for registered IoT devices.
 * @dev A gateway role is required to query interaction permissions. Access
 *      leases use uint64 timestamps so their fields fit in one storage slot.
 */
contract AccessControl is OpenZeppelinAccessControl {
    bytes32 public constant ADMIN_ROLE = DEFAULT_ADMIN_ROLE;
    bytes32 public constant GATEWAY_ROLE = keccak256("GATEWAY_ROLE");

    IDeviceRegistry public immutable registry;

    struct AccessGrant {
        uint64 validUntil;
        bool enabled;
    }

    mapping(bytes32 deviceId => mapping(address actor => AccessGrant grant)) private _grants;

    error ZeroAddress();
    error DeviceNotRegistered(bytes32 deviceId);
    error NotDeviceOwner(bytes32 deviceId, address caller);
    error InvalidExpiry(uint64 validUntil);
    error NoActiveGrant(bytes32 deviceId, address actor);

    event AccessGranted(bytes32 indexed deviceId, address indexed actor, uint64 validUntil);
    event AccessRevoked(bytes32 indexed deviceId, address indexed actor);

    /** @notice Initializes role management and stores the device registry. */
    constructor(address admin, IDeviceRegistry deviceRegistry) {
        if (admin == address(0) || address(deviceRegistry) == address(0)) revert ZeroAddress();
        registry = deviceRegistry;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /**
     * @notice Grants an actor permission until an explicit expiry timestamp.
     * @dev The owner or ADMIN may grant access; expired leases are inactive.
     */
    function grantAccess(bytes32 deviceId, address actor, uint64 validUntil) external {
        _requireDevice(deviceId);
        if (actor == address(0)) revert ZeroAddress();
        _requireOwnerOrAdmin(deviceId);
        if (validUntil <= block.timestamp) revert InvalidExpiry(validUntil);

        _grants[deviceId][actor] = AccessGrant({validUntil: validUntil, enabled: true});
        emit AccessGranted(deviceId, actor, validUntil);
    }

    /** @notice Revokes an existing access lease. */
    function revokeAccess(bytes32 deviceId, address actor) external {
        _requireDevice(deviceId);
        _requireOwnerOrAdmin(deviceId);
        AccessGrant storage grant = _grants[deviceId][actor];
        if (!grant.enabled) revert NoActiveGrant(deviceId, actor);

        grant.enabled = false;
        emit AccessRevoked(deviceId, actor);
    }

    /** @notice Checks whether an actor has a live permission for a device. */
    function canInteract(bytes32 deviceId, address actor) external view onlyRole(GATEWAY_ROLE) returns (bool) {
        if (!registry.exists(deviceId)) return false;
        AccessGrant memory grant = _grants[deviceId][actor];
        return grant.enabled && block.timestamp < grant.validUntil;
    }

    /** @notice Returns the permission's expiry and enabled flag. */
    function accessGrant(bytes32 deviceId, address actor) external view returns (uint64 validUntil, bool enabled) {
        AccessGrant memory grant = _grants[deviceId][actor];
        return (grant.validUntil, grant.enabled && block.timestamp < grant.validUntil);
    }

    function _requireDevice(bytes32 deviceId) private view {
        if (!registry.exists(deviceId)) revert DeviceNotRegistered(deviceId);
    }

    function _requireOwnerOrAdmin(bytes32 deviceId) private view {
        if (msg.sender != registry.ownerOfDevice(deviceId) && !hasRole(DEFAULT_ADMIN_ROLE, msg.sender)) {
            revert NotDeviceOwner(deviceId, msg.sender);
        }
    }
}
