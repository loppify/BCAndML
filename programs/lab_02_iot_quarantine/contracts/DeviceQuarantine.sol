// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {AccessControlUpgradeable} from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {IDeviceRegistry} from "./interfaces/IDeviceRegistry.sol";

/**
 * @title DeviceQuarantine
 * @notice Records oracle decisions and enforces the device quarantine state machine.
 * @dev The UUPS proxy is used as one optional extension. Raw flow data is never
 *      stored on-chain; only SHA-256 hashes and compact decision fields are kept.
 */
contract DeviceQuarantine is Initializable, AccessControlUpgradeable, PausableUpgradeable, UUPSUpgradeable {
    bytes32 public constant ADMIN_ROLE = DEFAULT_ADMIN_ROLE;
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");
    uint16 public constant CONFIDENCE_THRESHOLD = 5_000;

    enum DeviceState {
        Unregistered,
        Active,
        Quarantined
    }

    struct Decision {
        bool attack;
        uint16 confidence;
        uint32 modelVersion;
        uint64 timestamp;
        bytes32 inputHash;
    }

    IDeviceRegistry public registry;
    address public oracle;
    mapping(uint32 version => bytes32 modelHash) public modelHash;
    mapping(bytes32 deviceId => bool quarantined) private _quarantined;
    mapping(bytes32 deviceId => uint256 count) public incidentCount;
    mapping(bytes32 deviceId => mapping(uint256 incidentId => Decision decision)) private _decisions;
    mapping(bytes32 deviceId => mapping(bytes32 inputHash => bool processed)) public processedInputHash;
    uint256[48] private __gap;

    error ZeroAddress();
    error ZeroHash();
    error DeviceNotRegistered(bytes32 deviceId);
    error ModelVersionUnknown(uint32 version);
    error ModelVersionAlreadyRegistered(uint32 version);
    error InvalidConfidence(uint16 confidence);
    error DecisionAlreadyProcessed(bytes32 deviceId, bytes32 inputHash);
    error DeviceNotQuarantined(bytes32 deviceId);
    error NotDeviceOwner(bytes32 deviceId, address caller);
    error IncidentNotFound(bytes32 deviceId, uint256 incidentId);
    error InvalidOracle(address oracleAddress);

    event ModelRegistered(uint32 indexed version, bytes32 modelHash);
    event DecisionRecorded(
        bytes32 indexed deviceId,
        uint256 indexed incidentId,
        bool attack,
        uint16 confidence,
        uint32 modelVersion,
        bytes32 inputHash
    );
    event DeviceQuarantined(bytes32 indexed deviceId, uint256 indexed incidentId);
    event QuarantineReleased(bytes32 indexed deviceId, address indexed owner);
    event OracleChanged(address indexed oldOracle, address indexed newOracle);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /** @notice Initializes the upgradeable proxy, administrator, oracle and registry. */
    function initialize(address admin, address initialOracle, IDeviceRegistry deviceRegistry) external initializer {
        if (admin == address(0) || address(deviceRegistry) == address(0)) revert ZeroAddress();
        if (initialOracle == address(0)) revert InvalidOracle(initialOracle);
        __AccessControl_init();
        __Pausable_init();
        __UUPSUpgradeable_init();
        registry = deviceRegistry;
        oracle = initialOracle;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ORACLE_ROLE, initialOracle);
    }

    /** @notice Registers a content hash for a numbered model version. */
    function registerModel(uint32 version, bytes32 modelArtifactHash) external onlyRole(DEFAULT_ADMIN_ROLE) whenNotPaused {
        if (version == 0) revert ModelVersionUnknown(version);
        if (modelArtifactHash == bytes32(0)) revert ZeroHash();
        if (modelHash[version] != bytes32(0)) revert ModelVersionAlreadyRegistered(version);
        modelHash[version] = modelArtifactHash;
        emit ModelRegistered(version, modelArtifactHash);
    }

    /**
     * @notice Records one oracle result and quarantines an active device over threshold.
     * @dev The inputHash is SHA-256 over the canonical off-chain feature payload.
     */
    function recordDecision(
        bytes32 deviceId,
        bool attack,
        uint16 confidence,
        uint32 version,
        bytes32 inputHash
    ) external onlyRole(ORACLE_ROLE) whenNotPaused {
        if (!registry.exists(deviceId)) revert DeviceNotRegistered(deviceId);
        if (modelHash[version] == bytes32(0)) revert ModelVersionUnknown(version);
        if (inputHash == bytes32(0)) revert ZeroHash();
        if (confidence > 10_000) revert InvalidConfidence(confidence);
        if (processedInputHash[deviceId][inputHash]) revert DecisionAlreadyProcessed(deviceId, inputHash);

        processedInputHash[deviceId][inputHash] = true;
        uint256 incidentId = ++incidentCount[deviceId];
        _decisions[deviceId][incidentId] = Decision({
            attack: attack,
            confidence: confidence,
            modelVersion: version,
            timestamp: uint64(block.timestamp),
            inputHash: inputHash
        });
        emit DecisionRecorded(deviceId, incidentId, attack, confidence, version, inputHash);

        bool meetsQuarantineThreshold = attack && confidence >= CONFIDENCE_THRESHOLD;
        if (meetsQuarantineThreshold && !_quarantined[deviceId]) {
            _quarantined[deviceId] = true;
            emit DeviceQuarantined(deviceId, incidentId);
        }
    }

    /** @notice Releases a quarantined device after its owner reviews the incident. */
    function releaseQuarantine(bytes32 deviceId) external {
        if (!registry.exists(deviceId)) revert DeviceNotRegistered(deviceId);
        address owner = registry.ownerOfDevice(deviceId);
        if (msg.sender != owner && !hasRole(DEFAULT_ADMIN_ROLE, msg.sender)) {
            revert NotDeviceOwner(deviceId, msg.sender);
        }
        if (!_quarantined[deviceId]) revert DeviceNotQuarantined(deviceId);
        _quarantined[deviceId] = false;
        emit QuarantineReleased(deviceId, owner);
    }

    /** @notice Replaces the active oracle signer. */
    function replaceOracle(address newOracle) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (newOracle == address(0) || newOracle == oracle) revert InvalidOracle(newOracle);
        address oldOracle = oracle;
        _revokeRole(ORACLE_ROLE, oldOracle);
        _grantRole(ORACLE_ROLE, newOracle);
        oracle = newOracle;
        emit OracleChanged(oldOracle, newOracle);
    }

    /** @notice Stops new model decisions; gateway command enforcement is fail-closed while paused. */
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) whenNotPaused {
        _pause();
    }

    /** @notice Resumes new model decisions. */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) whenPaused {
        _unpause();
    }

    /** @notice Returns Unregistered, Active or Quarantined for a device. */
    function deviceStatus(bytes32 deviceId) external view returns (DeviceState) {
        if (!registry.exists(deviceId)) return DeviceState.Unregistered;
        return _quarantined[deviceId] ? DeviceState.Quarantined : DeviceState.Active;
    }

    /** @notice Returns a previously recorded decision. */
    function getDecision(bytes32 deviceId, uint256 incidentId) external view returns (Decision memory) {
        if (incidentId == 0 || incidentId > incidentCount[deviceId]) {
            revert IncidentNotFound(deviceId, incidentId);
        }
        return _decisions[deviceId][incidentId];
    }

    /** @notice Restricts implementation upgrades to the administrator. */
    function _authorizeUpgrade(address) internal override onlyRole(DEFAULT_ADMIN_ROLE) {}
}
