import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeFunctionData } from "viem";
import { verifyAgentConfig, writeAgentConfig } from "../agent-config.mjs";

test("agent signs its public config reference and verification binds the exact write", async () => {
  const agent = `0x${"1".repeat(40)}`, resolver = `0x${"2".repeat(40)}`, txHash = `0x${"a".repeat(64)}`, blockHash = `0x${"b".repeat(64)}`;
  let call, observed = "ipfs://config";
  const publicClient = { getChainId: async () => 11155111, getEnsResolver: async () => resolver,
    simulateContract: async (request) => { call = request; return { request }; },
    getTransaction: async () => ({ from: agent, to: resolver, input: encodeFunctionData(call) }),
    getTransactionReceipt: async () => ({ status: "success", transactionHash: txHash, blockNumber: 5n, blockHash }),
    getBlock: async () => ({ hash: blockHash }),
    getEnsText: async ({ blockNumber }) => { assert.equal(blockNumber, 5n); return observed; },
  };
  const walletClient = { account: { address: agent }, getChainId: async () => 11155111, writeContract: async () => txHash };
  const write = await writeAgentConfig({ publicClient, walletClient, name: "Browser.example.eth", resolver, value: observed });
  assert.equal(write.name, "browser.example.eth");
  assert.equal((await verifyAgentConfig({ publicClient, ...write })).matches, true);
  observed = "another reference";
  assert.equal((await verifyAgentConfig({ publicClient, ...write })).matches, false);
  await assert.rejects(verifyAgentConfig({ publicClient, ...write, value: "forged" }), /transaction mismatch/);
  await assert.rejects(writeAgentConfig({ publicClient, walletClient, name: write.name, resolver, value: "x".repeat(2049) }), /2048/);
  publicClient.getEnsResolver = async () => agent;
  await assert.rejects(writeAgentConfig({ publicClient, walletClient, name: write.name, resolver, value: "" }), /does not match/);
});
