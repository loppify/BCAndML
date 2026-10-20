// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @dev Compares compact custom errors with revert strings on the same condition.
contract ErrorStyleBenchmark {
    error Paused();
    function customError(bool paused) external pure { if (paused) revert Paused(); }
    function revertString(bool paused) external pure { require(!paused, "campaign paused"); }
}
