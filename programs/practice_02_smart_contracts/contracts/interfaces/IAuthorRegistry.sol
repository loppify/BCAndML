// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

interface IAuthorRegistry {
    function isAuthor(address account) external view returns (bool);
    function registerContributor(address account) external;
}
