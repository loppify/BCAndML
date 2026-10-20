// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {ERC20Upgradeable} from "@openzeppelin/contracts-upgradeable/token/ERC20/ERC20Upgradeable.sol";
import {AccessControlUpgradeable} from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/// @title ContributionToken
/// @notice ERC-20 reward token minted for accepted campaign contributions.
contract ContributionToken is Initializable, ERC20Upgradeable, AccessControlUpgradeable, PausableUpgradeable, UUPSUpgradeable {
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    error ZeroAddress();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() { _disableInitializers(); }

    /// @notice Initializes token name, symbol, and administrator.
    function initialize(address admin) external initializer {
        if (admin == address(0)) revert ZeroAddress();
        __ERC20_init("Crowd Reward", "CRWD");
        __AccessControl_init();
        __Pausable_init();
        __UUPSUpgradeable_init();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Mints one reward token unit for each wei contributed.
    /// @dev Only the campaign contract can mint rewards.
    function mint(address to, uint256 amount) external onlyRole(MINTER_ROLE) whenNotPaused {
        if (to == address(0)) revert ZeroAddress();
        _mint(to, amount);
    }

    /// @notice Pauses reward token transfers and minting.
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) { _pause(); }

    /// @notice Resumes reward token transfers and minting.
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) { _unpause(); }

    function _update(address from, address to, uint256 value) internal override whenNotPaused {
        super._update(from, to, value);
    }

    function _authorizeUpgrade(address) internal override onlyRole(DEFAULT_ADMIN_ROLE) {}
}
