import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeAbiParameters, encodeEventTopics, encodeFunctionData, parseAbi } from "viem";
import { deployAgentResolver, verifyAgentResolver, SEPOLIA_RESOLVER_FACTORY, SEPOLIA_RESOLVER_IMPLEMENTATION } from "../resolver.mjs";

const owner = `0x${"1".repeat(40)}`, resolver = `0x${"2".repeat(40)}`;
const hash = `0x${"a".repeat(64)}`, txHash = `0x${"b".repeat(64)}`;

test("deploys and verifies the exact owner-initialized resolver transaction", async () => {
  let request;
  const eventAbi = parseAbi(["event ProxyDeployed(address indexed sender, address indexed proxyAddress, uint256 salt, address implementation)"]);
  const log = { address: SEPOLIA_RESOLVER_FACTORY, topics: encodeEventTopics({ abi: eventAbi, eventName: "ProxyDeployed", args: { sender: owner, proxyAddress: resolver } }),
    data: encodeAbiParameters([{ type: "uint256" }, { type: "address" }], [42n, SEPOLIA_RESOLVER_IMPLEMENTATION]) };
  const publicClient = {
    getChainId: async () => 11155111,
    simulateContract: async (call) => { request = call; return { request: call, result: resolver }; },
    getTransaction: async () => ({ from: owner, to: SEPOLIA_RESOLVER_FACTORY, input: encodeFunctionData(request) }),
    getTransactionReceipt: async () => ({ status: "success", transactionHash: txHash, blockNumber: 12n, blockHash: hash, logs: [log] }),
    getBlock: async () => ({ hash }),
    readContract: async ({ blockNumber }) => { assert.equal(blockNumber, 12n); return SEPOLIA_RESOLVER_IMPLEMENTATION; },
  };
  const walletClient = { account: { address: owner }, getChainId: async () => 11155111, writeContract: async () => txHash };
  const deployment = await deployAgentResolver({ publicClient, walletClient, salt: "42" });
  assert.equal(deployment.resolver, resolver);
  assert.equal((await verifyAgentResolver({ publicClient, ...deployment })).blockNumber, "12");
  await assert.rejects(verifyAgentResolver({ publicClient, ...deployment, salt: "43" }), /mismatch/);
  await assert.rejects(verifyAgentResolver({ publicClient, ...deployment, resolver: owner }), /event mismatch/);
  publicClient.readContract = async () => owner;
  await assert.rejects(verifyAgentResolver({ publicClient, ...deployment }), /implementation mismatch/);
  await assert.rejects(deployAgentResolver({ publicClient, walletClient, salt: "-1" }), /Salt/);
  walletClient.getChainId = async () => 1;
  await assert.rejects(deployAgentResolver({ publicClient, walletClient, salt: "42" }), /Sepolia/);
});

test("attaches a verified resolver only to an owner-held subname without an explicit resolver", async () => {
  const { attachAgentResolver, verifyResolverAttachment } = await import("../identity.mjs");
  const { changeIdentityDelegation } = await import("../delegation.mjs");
  const registry = `0x${"3".repeat(40)}`, zero = `0x${"0".repeat(40)}`;
  const eventAbi = parseAbi(["event ProxyDeployed(address indexed sender, address indexed proxyAddress, uint256 salt, address implementation)"]);
  const log = { address: SEPOLIA_RESOLVER_FACTORY, topics: encodeEventTopics({ abi: eventAbi, eventName: "ProxyDeployed", args: { sender: owner, proxyAddress: resolver } }),
    data: encodeAbiParameters([{ type: "uint256" }, { type: "address" }], [42n, SEPOLIA_RESOLVER_IMPLEMENTATION]) };
  let deployRequest, attachmentRequest, delegationRequest, explicitResolver = zero, hasRole = true;
  const publicClient = {
    getChainId: async () => 11155111,
    simulateContract: async (call) => {
      if (call.functionName === "deployProxy") { deployRequest = call; return { request: call, result: resolver }; }
      if (call.functionName === "setResolver") attachmentRequest = call;
      else delegationRequest = call;
      return { request: call };
    },
    getTransaction: async ({ hash: requested }) => requested === txHash
      ? { from: owner, to: SEPOLIA_RESOLVER_FACTORY, input: encodeFunctionData(deployRequest) }
      : { from: owner, to: registry, input: encodeFunctionData(attachmentRequest) },
    getTransactionReceipt: async ({ hash: requested }) => ({ status: "success", transactionHash: requested, blockNumber: 12n, blockHash: hash, logs: [log] }),
    getBlock: async () => ({ number: 12n, hash }),
    readContract: async ({ functionName, args }) => {
      if (functionName === "verifyContract") return SEPOLIA_RESOLVER_IMPLEMENTATION;
      if (functionName === "findCanonicalRegistry") return registry;
      if (functionName === "findExactOwner") return owner;
      if (functionName === "hasRootRoles") return true;
      if (functionName === "hasRoles") return hasRole;
      if (functionName === "getResolver") return explicitResolver;
      throw new Error(`Unexpected read ${functionName}`);
    },
  };
  const attachmentHash = `0x${"c".repeat(64)}`;
  const walletClient = { account: { address: owner }, getChainId: async () => 11155111,
    writeContract: async ({ functionName }) => functionName === "deployProxy" ? txHash : attachmentHash };
  const deployment = await deployAgentResolver({ publicClient, walletClient, salt: "42" });
  const args = { publicClient, walletClient, parentName: "example.eth", label: "browser", deployment };
  const result = await attachAgentResolver(args);
  assert.equal(result.transactionHash, attachmentHash);
  explicitResolver = resolver;
  assert.equal((await verifyResolverAttachment({ publicClient, ...result })).matches, true);
  const delegation = await changeIdentityDelegation({ publicClient, walletClient, deployment, attachment: result, agent: registry, grant: true });
  assert.equal(delegation.grant, true);
  assert.equal(delegationRequest.functionName, "grantSetterRoles");
  await assert.rejects(changeIdentityDelegation({ publicClient, walletClient, deployment, attachment: result, agent: zero, grant: true }), /Valid owner/);
  await assert.rejects(attachAgentResolver(args), /already has an explicit resolver/);
  explicitResolver = zero; hasRole = false;
  await assert.rejects(attachAgentResolver(args), /lacks the subname resolver role/);
  await assert.rejects(verifyResolverAttachment({ publicClient, ...result, resolver: owner }), /transaction mismatch/);
});
