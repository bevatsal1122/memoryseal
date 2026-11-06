import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeFunctionData, keccak256, parseAbi, stringToHex } from "viem";
import { verifyIdentityDelegation } from "../delegation.mjs";

const owner = `0x${"1".repeat(40)}`, agent = `0x${"2".repeat(40)}`, resolver = `0x${"3".repeat(40)}`;
const transactionHash = `0x${"a".repeat(64)}`, hash = `0x${"b".repeat(64)}`;
const abi = parseAbi(["function revokeRoles(uint256 resource, uint256 roleBitmap, address account) returns (bool)"]);

test("checks the exact revocation and separately reports surviving root access", async () => {
  const client = { getChainId: async () => 11155111,
    getTransaction: async () => ({ from: owner, to: resolver, input: encodeFunctionData({ abi, functionName: "revokeRoles", args: [BigInt(keccak256(stringToHex("memoryseal.config"))), 16n, agent] }) }),
    getTransactionReceipt: async () => ({ status: "success", transactionHash, blockNumber: 10n, blockHash: hash }),
    getBlock: async () => ({ hash }),
    readContract: async ({ functionName, blockNumber }) => { assert.equal(blockNumber, 10n); return functionName === "roles" ? 0n : true; },
  };
  const context = { publicClient: client, owner, agent, resolver, grant: false, transactionHash };
  const result = await verifyIdentityDelegation(context);
  assert.equal(result.matches, true);
  assert.equal(result.keyRole, false);
  assert.equal(result.rootRole, true);
  await assert.rejects(verifyIdentityDelegation({ ...context, agent: owner }), /transaction mismatch/);
});
