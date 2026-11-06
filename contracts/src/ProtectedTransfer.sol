// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {MemoryPolicyRegistry} from "./MemoryPolicyRegistry.sol";

/// @notice Transfers owner-approved tokens only when the agent's current policy permits it.
/// @dev Limits are per transfer, not cumulative budgets. Owners approve this contract on the token.
contract ProtectedTransfer is ReentrancyGuard {
    using SafeERC20 for IERC20;
    MemoryPolicyRegistry public immutable registry;
    event TransferExecuted(address indexed owner, address indexed agent, address indexed token,
                           address recipient, uint256 amount, uint256 policyVersion);

    constructor(MemoryPolicyRegistry registry_) { require(address(registry_) != address(0), "invalid registry"); registry = registry_; }

    function execute(address owner, IERC20 token, address recipient, uint256 amount,
                     uint256 expectedVersion) external nonReentrant {
        require(recipient != address(0), "invalid recipient");
        require(registry.canTransfer(owner, msg.sender, address(token), amount, expectedVersion), "not authorized");
        token.safeTransferFrom(owner, recipient, amount);
        emit TransferExecuted(owner, msg.sender, address(token), recipient, amount, expectedVersion);
    }
}
