// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @dev Gas-only reference: equivalent logical fields occupy separate full slots.
contract WideCampaignRecord {
    struct Record { address creator; uint256 goal; uint256 deadline; uint256 raised; uint256 status; bool withdrawn; }
    uint256 public count;
    mapping(uint256 => Record) public records;
    function create(uint256 goal, uint256 deadline) external returns (uint256 id) {
        id = ++count;
        records[id] = Record(msg.sender, goal, deadline, 0, 0, false);
    }
    function contribute(uint256 id, uint256 amount) external { records[id].raised += amount; }
}

/// @dev Same logical fields packed into smaller integer widths.
contract PackedCampaignRecord {
    struct Record { address creator; uint128 goal; uint64 deadline; uint128 raised; uint8 status; bool withdrawn; }
    uint256 public count;
    mapping(uint256 => Record) public records;
    function create(uint128 goal, uint64 deadline) external returns (uint256 id) {
        id = ++count;
        records[id] = Record(msg.sender, goal, deadline, 0, 0, false);
    }
    function contribute(uint256 id, uint128 amount) external { records[id].raised += amount; }
}
