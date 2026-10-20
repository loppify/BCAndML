// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {AccessControlEnumerableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/extensions/AccessControlEnumerableUpgradeable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";

/// @title AuthorRegistry
/// @notice Maintains campaign author and contributor roles.
contract AuthorRegistry is Initializable, AccessControlEnumerableUpgradeable, UUPSUpgradeable {
    bytes32 public constant AUTHOR_ROLE = keccak256("AUTHOR_ROLE");
    bytes32 public constant CONTRIBUTOR_ROLE = keccak256("CONTRIBUTOR_ROLE");
    bytes32 public constant CAMPAIGN_ROLE = keccak256("CAMPAIGN_ROLE");

    error ZeroAddress();
    error AlreadyAuthor();
    error NotAuthor();
    error InvalidPageSize();

    event AuthorRegistered(address indexed author, address indexed by);
    event AuthorRemoved(address indexed author, address indexed by);
    event ContributorRegistered(address indexed contributor);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() { _disableInitializers(); }

    /// @notice Initializes the role administrator.
    /// @param admin Account allowed to manage roles and authorize upgrades.
    function initialize(address admin) external initializer {
        if (admin == address(0)) revert ZeroAddress();
        __AccessControl_init();
        __AccessControlEnumerable_init();
        __UUPSUpgradeable_init();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Adds an eligible campaign author.
    function registerAuthor(address author) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (author == address(0)) revert ZeroAddress();
        if (hasRole(AUTHOR_ROLE, author)) revert AlreadyAuthor();
        _grantRole(AUTHOR_ROLE, author);
        emit AuthorRegistered(author, msg.sender);
    }

    /// @notice Revokes an author's permission to create campaigns.
    function removeAuthor(address author) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (!hasRole(AUTHOR_ROLE, author)) revert NotAuthor();
        _revokeRole(AUTHOR_ROLE, author);
        emit AuthorRemoved(author, msg.sender);
    }

    /// @notice Registers a contributor after their first valid contribution.
    function registerContributor(address account) external onlyRole(CAMPAIGN_ROLE) {
        if (account == address(0)) revert ZeroAddress();
        if (!hasRole(CONTRIBUTOR_ROLE, account)) {
            _grantRole(CONTRIBUTOR_ROLE, account);
            emit ContributorRegistered(account);
        }
    }

    /// @notice Returns whether an account may create campaigns.
    function isAuthor(address account) external view returns (bool) { return hasRole(AUTHOR_ROLE, account); }

    /// @notice Reads a bounded page of author addresses.
    function authors(uint256 offset, uint256 limit) external view returns (address[] memory page) {
        if (limit == 0 || limit > 100) revert InvalidPageSize();
        uint256 count = getRoleMemberCount(AUTHOR_ROLE);
        if (offset >= count) return new address[](0);
        uint256 size = count - offset;
        if (size > limit) size = limit;
        page = new address[](size);
        for (uint256 i; i < size; ++i) page[i] = getRoleMember(AUTHOR_ROLE, offset + i);
    }

    function _authorizeUpgrade(address) internal override onlyRole(DEFAULT_ADMIN_ROLE) {}
}
