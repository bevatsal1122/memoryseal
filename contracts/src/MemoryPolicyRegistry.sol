// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Owner-controlled policies. Memory records are never policy inputs.
contract MemoryPolicyRegistry {
    struct MemoryCapability { bool canRead; bool canWrite; bool canDelegate; uint64 expiresAt; bool revoked; }
    struct TransferCapability { uint256 maxAmount; uint64 expiresAt; bool revoked; }

    mapping(address => uint256) public policyVersion;
    mapping(address => mapping(address => bool)) public agentRevoked;
    mapping(address => mapping(address => mapping(bytes32 => MemoryCapability))) public memoryCapabilities;
    mapping(address => mapping(address => mapping(address => TransferCapability))) public transferCapabilities;

    event MemoryCapabilityChanged(address indexed owner, address indexed agent, bytes32 indexed namespace,
                                  bool canRead, bool canWrite, bool canDelegate, uint64 expiresAt,
                                  bool revoked, uint256 version);
    event TransferCapabilityChanged(address indexed owner, address indexed agent, address indexed token,
                                    uint256 maxAmount, uint64 expiresAt, bool revoked, uint256 version);
    event AgentRevoked(address indexed owner, address indexed agent, uint256 version);

    /// @notice Permanently revoke this signing address for the caller's policies.
    /// Register a new agent address to delegate again.
    function revokeAgent(address agent) external {
        require(agent != address(0) && !agentRevoked[msg.sender][agent], "invalid agent");
        agentRevoked[msg.sender][agent] = true;
        emit AgentRevoked(msg.sender, agent, ++policyVersion[msg.sender]);
    }

    function setMemoryCapability(address agent, bytes32 namespace, bool canRead, bool canWrite,
                                 bool canDelegate, uint64 expiresAt) external {
        require(agent != address(0) && namespace != bytes32(0), "invalid scope");
        require(!agentRevoked[msg.sender][agent], "agent revoked");
        require(expiresAt == 0 || expiresAt > block.timestamp, "expired");
        memoryCapabilities[msg.sender][agent][namespace] = MemoryCapability(canRead, canWrite, canDelegate, expiresAt, false);
        emit MemoryCapabilityChanged(msg.sender, agent, namespace, canRead, canWrite, canDelegate,
                                     expiresAt, false, ++policyVersion[msg.sender]);
    }

    function revokeMemoryCapability(address agent, bytes32 namespace) external {
        MemoryCapability storage cap = memoryCapabilities[msg.sender][agent][namespace];
        cap.revoked = true;
        emit MemoryCapabilityChanged(msg.sender, agent, namespace, cap.canRead, cap.canWrite,
                                     cap.canDelegate, cap.expiresAt, true, ++policyVersion[msg.sender]);
    }

    function setTransferCapability(address agent, address token, uint256 maxAmount, uint64 expiresAt) external {
        require(agent != address(0) && token != address(0) && maxAmount > 0, "invalid scope");
        require(!agentRevoked[msg.sender][agent], "agent revoked");
        require(expiresAt == 0 || expiresAt > block.timestamp, "expired");
        transferCapabilities[msg.sender][agent][token] = TransferCapability(maxAmount, expiresAt, false);
        emit TransferCapabilityChanged(msg.sender, agent, token, maxAmount, expiresAt, false, ++policyVersion[msg.sender]);
    }

    function revokeTransferCapability(address agent, address token) external {
        TransferCapability storage cap = transferCapabilities[msg.sender][agent][token];
        cap.revoked = true;
        emit TransferCapabilityChanged(msg.sender, agent, token, cap.maxAmount, cap.expiresAt,
                                       true, ++policyVersion[msg.sender]);
    }

    function canTransfer(address owner, address agent, address token, uint256 amount,
                         uint256 expectedVersion) external view returns (bool) {
        TransferCapability memory cap = transferCapabilities[owner][agent][token];
        return expectedVersion == policyVersion[owner] && amount > 0 && !agentRevoked[owner][agent] && !cap.revoked &&
               cap.maxAmount >= amount && (cap.expiresAt == 0 || cap.expiresAt > block.timestamp);
    }

    function canAccessMemory(address owner, address agent, bytes32 namespace, bool writeAccess)
        external view returns (bool) {
        MemoryCapability memory cap = memoryCapabilities[owner][agent][namespace];
        return !agentRevoked[owner][agent] && !cap.revoked &&
            (cap.expiresAt == 0 || cap.expiresAt > block.timestamp) &&
            (writeAccess ? cap.canWrite : cap.canRead);
    }
}
