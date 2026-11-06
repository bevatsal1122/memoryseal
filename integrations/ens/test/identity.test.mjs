import assert from "node:assert/strict";
import { test } from "node:test";
import { observeAgentAddress, observeSubnameRegistry, registerOwnedSubname, setAgentSubnameRecord, verifyAgentAddress, verifyAgentRecordWrite, verifyOwnedSubname } from "../identity.mjs";
import { namehash, packetToBytes } from "viem/ens";
import { encodeFunctionData, parseAbi, toHex } from "viem";

test("checks resolved address and refuses an invalid expected address", async () => {
  const address = "0x" + "1".repeat(40);
  const client = { async getEnsAddress({ name }) { assert.equal(name, "agent.example.eth"); return address; } };
  assert.equal((await verifyAgentAddress(client, "agent.example.eth", address)).matches, true);
  assert.equal((await verifyAgentAddress(client, "agent.example.eth", "0x" + "2".repeat(40))).matches, false);
  await assert.rejects(verifyAgentAddress(client, "agent.example.eth", "invalid"));
});

test("checks canonical parent registry and ownership at one block", async () => {
  const owner = "0x" + "1".repeat(40), registry = "0x" + "2".repeat(40);
  const hash = "0x" + "a".repeat(64), zero = "0x" + "0".repeat(40);
  const client = { getChainId: async () => 11155111, getBlock: async () => ({ number: 12n, hash }),
    readContract: async ({ functionName, args, blockNumber }) => {
      assert.equal(blockNumber, 12n);
      if (functionName === "findCanonicalRegistry") return registry;
      if (functionName === "findExactOwner") return args[0] === toHex(packetToBytes("example.eth")) ? owner : zero;
      if (functionName === "hasRootRoles") { assert.deepEqual(args, [1n, owner]); return true; }
      throw new Error("unexpected call");
    } };
  const args = { parentName: "example.eth", label: "browser", account: owner, expectedChainId: 11155111 };
  const result = await observeSubnameRegistry(client, args);
  assert.equal(result.registry, registry);
  assert.equal(result.parentOwner, owner);
  assert.equal(result.childOwner, zero);
  assert.equal(result.canRegister, true);
  let calls = 0;
  client.getBlock = async () => ({ number: 12n, hash: ++calls === 1 ? hash : "0x" + "b".repeat(64) });
  await assert.rejects(observeSubnameRegistry(client, args), /reorganized/);
  await assert.rejects(observeSubnameRegistry(client, { ...args, expectedChainId: 1 }), /Sepolia/);
});

test("registers only a new name in a canonical owner-controlled Sepolia registry", async () => {
  const owner = "0x" + "1".repeat(40), registry = "0x" + "2".repeat(40), zero = "0x" + "0".repeat(40);
  const hash = "0x" + "a".repeat(64), txHash = "0x" + "c".repeat(64);
  let status = 0, priorExpiry = 0n, sent;
  const client = { getChainId: async () => 11155111, getBlock: async () => ({ number: 12n, hash, timestamp: 100n }),
    readContract: async ({ functionName, args }) => {
      if (functionName === "findCanonicalRegistry") return registry;
      if (functionName === "findExactOwner") return args[0] === toHex(packetToBytes("example.eth")) ? owner : zero;
      if (functionName === "hasRootRoles") return true;
      if (functionName === "getStatus") return status;
      if (functionName === "getExpiry") return priorExpiry;
      throw new Error("unexpected call");
    }, simulateContract: async request => ({ request }) };
  const wallet = { account: { address: owner }, getChainId: async () => 11155111,
    writeContract: async request => { sent = request; return txHash; } };
  const args = { publicClient: client, walletClient: wallet, parentName: "example.eth", label: "browser", expiry: "1000", expectedChainId: 11155111 };
  const result = await registerOwnedSubname(args);
  assert.equal(result.registry, registry);
  assert.equal(sent.functionName, "register");
  assert.deepEqual(sent.args.slice(0, 4), ["browser", owner, zero, zero]);
  assert.equal(sent.args[5], 1000n);
  sent = null; status = 1;
  await assert.rejects(registerOwnedSubname(args), /reserved/);
  assert.equal(sent, null);
  status = 0; priorExpiry = 200n;
  await assert.rejects(registerOwnedSubname(args), /previously used/);
  priorExpiry = 0n;
  await assert.rejects(registerOwnedSubname({ ...args, expiry: "100" }), /expiry/);
  const abi = parseAbi(["function register(string label, address owner, address registry, address resolver, uint256 roleBitmap, uint64 expiry) returns (uint256)"]);
  const input = encodeFunctionData({ abi, functionName: "register", args: ["browser", owner, zero, zero, BigInt(result.roles), 1000n] });
  client.getTransaction = async () => ({ from: owner, to: registry, input });
  client.getTransactionReceipt = async () => ({ status: "success", transactionHash: txHash, blockNumber: 12n, blockHash: hash });
  const originalRead = client.readContract;
  client.readContract = async request => request.functionName === "findExactOwner" ? owner : originalRead(request);
  const verified = await verifyOwnedSubname({ publicClient: client, parentName: "example.eth", label: "browser", owner, registry, expiry: "1000", transactionHash: txHash, expectedChainId: 11155111 });
  assert.equal(verified.matches, true);
  client.getTransaction = async () => ({ from: owner, to: registry, input: "0x00" });
  await assert.rejects(verifyOwnedSubname({ publicClient: client, parentName: "example.eth", label: "browser", owner, registry, expiry: "1000", transactionHash: txHash, expectedChainId: 11155111 }), /mismatch/);
});

test("observes a fixed block and rejects a reorganization", async () => {
  const address = "0x" + "1".repeat(40), hash = "0x" + "a".repeat(64);
  const client = { getChainId: async () => 11155111,
    getBlock: async () => ({ number: 42n, hash }),
    getEnsAddress: async ({ blockNumber, strict }) => { assert.equal(blockNumber, 42n); assert.equal(strict, true); return address; } };
  const result = await observeAgentAddress(client, { name: "agent.example.eth", expectedAddress: address, expectedChainId: 11155111 });
  assert.equal(result.matches, true);
  assert.equal(result.blockNumber, "42");
  let calls = 0;
  client.getBlock = async () => ({ number: 42n, hash: ++calls === 1 ? hash : "0x" + "b".repeat(64) });
  await assert.rejects(observeAgentAddress(client, { name: "agent.example.eth", expectedAddress: address, expectedChainId: 11155111 }), /reorganized/);
});

test("checks canonical transaction and current resolved agent address", async () => {
  const resolver = "0x" + "1".repeat(40), agent = "0x" + "2".repeat(40), owner = "0x" + "3".repeat(40);
  const hash = "0x" + "a".repeat(64), blockHash = "0x" + "b".repeat(64);
  const abi = parseAbi(["function setAddress(bytes name, uint256 coinType, bytes addressBytes)"]);
  const input = encodeFunctionData({ abi, functionName: "setAddress", args: [toHex(packetToBytes("browser.example.eth")), 60n, agent] });
  const client = { getChainId: async () => 11155111,
    getTransaction: async () => ({ from: owner, to: resolver, input }),
    getTransactionReceipt: async () => ({ status: "success", transactionHash: hash, blockNumber: 10n, blockHash }),
    getBlock: async () => ({ hash: blockHash }), getEnsResolver: async () => resolver,
    getEnsAddress: async () => agent };
  const fields = { publicClient: client, name: "browser.example.eth", agentAddress: agent,
    writer: owner, transactionHash: hash, expectedChainId: 11155111 };
  assert.equal((await verifyAgentRecordWrite(fields)).matches, true);
  client.getBlock = async () => ({ hash: "0x" + "c".repeat(64) });
  await assert.rejects(verifyAgentRecordWrite(fields), /canonical/);
});

test("writes the normalized agent record through the current resolver after simulation", async () => {
  const resolver = "0x" + "1".repeat(40), agent = "0x" + "2".repeat(40), owner = "0x" + "3".repeat(40);
  let sent;
  const reader = { getChainId: async () => 11155111, getEnsResolver: async ({ name }) => {
    assert.equal(name, "browser.example.eth"); return resolver;
  }, readContract: async request => {
    assert.equal(request.address, resolver);
    assert.equal(request.functionName, "getRecordId");
    assert.deepEqual(request.args, [namehash("browser.example.eth")]);
    return 0n;
  }, simulateContract: async request => {
    assert.equal(request.address, resolver);
    assert.deepEqual(request.args, [toHex(packetToBytes("browser.example.eth")), 60n, agent]);
    assert.equal(request.account.address, owner);
    return { request };
  }};
  const wallet = { account: { address: owner }, getChainId: async () => 11155111,
    writeContract: async request => { sent = request; return "0x" + "a".repeat(64); } };
  const result = await setAgentSubnameRecord({ publicClient: reader, walletClient: wallet,
    parentName: "example.eth", label: "browser", agentAddress: agent, expectedChainId: 11155111 });
  assert.equal(result.registration, "resolver-record");
  assert.equal(sent.functionName, "setAddress");
  sent = null;
  reader.readContract = async () => 3n;
  await assert.rejects(setAgentSubnameRecord({ publicClient: reader, walletClient: wallet,
    parentName: "example.eth", label: "browser", agentAddress: agent, expectedChainId: 11155111 }), /may be shared/);
  assert.equal(sent, null);
  await assert.rejects(setAgentSubnameRecord({ publicClient: reader, walletClient: wallet,
    parentName: "example.eth", label: "browser.bad", agentAddress: agent, expectedChainId: 11155111 }));
  await assert.rejects(setAgentSubnameRecord({ publicClient: reader, walletClient: wallet,
    parentName: "example.eth", label: "browser", agentAddress: agent, expectedChainId: 1 }), /chain ID/);
});
