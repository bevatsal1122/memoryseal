import { keccak256, stringToHex } from "viem";

const addressWord = value => {
  if (!/^0x[0-9a-fA-F]{40}$/.test(value) || /^0x0{40}$/i.test(value)) throw new Error("Enter a valid nonzero address.");
  return value.slice(2).toLowerCase().padStart(64, "0");
};
const uintWord = (value, bits = 256) => {
  if (!/^\d+$/.test(String(value))) throw new Error("Enter a whole nonnegative number.");
  const number = BigInt(value);
  if (number >= 2n ** BigInt(bits)) throw new Error("Number exceeds contract limit.");
  return number.toString(16).padStart(64, "0");
};
async function check(wallet, registry, chainId) {
  addressWord(registry);
  if (!/^\d+$/.test(String(chainId)) || BigInt(chainId) <= 0n) throw new Error("Enter the expected chain ID.");
  const actual = await wallet.request({ method: "eth_chainId" });
  if (BigInt(actual) !== BigInt(chainId)) throw new Error("Wallet network does not match the expected chain ID.");
  const code = await wallet.request({ method: "eth_getCode", params: [registry, "latest"] });
  if (!code || code === "0x" || code === "0x0") throw new Error("No contract found at registry address.");
}
async function sendEstimated(wallet, transaction) {
  const estimate = await wallet.request({ method: "eth_estimateGas", params: [transaction] });
  if (!/^0x[0-9a-fA-F]+$/.test(estimate)) throw new Error("Invalid gas estimate.");
  const gas = "0x" + ((BigInt(estimate) * 12n + 9n) / 10n).toString(16);
  return wallet.request({ method: "eth_sendTransaction", params: [{ ...transaction, gas }] });
}
export async function onchainVersion(wallet, registry, chainId, owner) {
  await check(wallet, registry, chainId);
  const result = await wallet.request({ method: "eth_call", params: [{ to: registry, data: "0xd3afe2b9" + addressWord(owner) }, "latest"] });
  if (!/^0x[0-9a-fA-F]{64}$/.test(result)) throw new Error("Invalid policy response.");
  return BigInt(result).toString();
}
export async function onchainCapability(wallet, { registry, chainId, owner, agent, token }) {
  await check(wallet, registry, chainId);
  const block = await wallet.request({ method: "eth_blockNumber" });
  if (!/^0x[0-9a-fA-F]+$/.test(block)) throw new Error("Invalid block number.");
  const version = await wallet.request({ method: "eth_call", params: [{ to: registry,
    data: "0xd3afe2b9" + addressWord(owner) }, block] });
  const capability = await wallet.request({ method: "eth_call", params: [{ to: registry,
    data: "0xef0c2135" + addressWord(owner) + addressWord(agent) + addressWord(token) }, block] });
  const agentStatus = await wallet.request({ method: "eth_call", params: [{ to: registry,
    data: "0xd1744682" + addressWord(owner) + addressWord(agent) }, block] });
  if (!/^0x[0-9a-fA-F]{64}$/.test(version) || !/^0x[0-9a-fA-F]{192}$/.test(capability) || !/^0x[0-9a-fA-F]{64}$/.test(agentStatus)) throw new Error("Invalid registry response.");
  const amount = BigInt("0x" + capability.slice(2, 66));
  const expiry = BigInt("0x" + capability.slice(66, 130));
  const revoked = BigInt("0x" + capability.slice(130, 194));
  const agentRevoked = BigInt(agentStatus);
  if (expiry >= 2n ** 64n || revoked > 1n || agentRevoked > 1n) throw new Error("Invalid capability response.");
  return { maxAmount: amount.toString(), expiresAt: expiry.toString(), revoked: revoked === 1n, agentRevoked: agentRevoked === 1n,
    version: BigInt(version).toString(), block: BigInt(block).toString() };
}
export async function revokeOnchainAgent(wallet, { registry, chainId, owner, agent }) {
  await check(wallet, registry, chainId);
  const data = "0x7da6ac0d" + addressWord(agent);
  return wallet.request({ method: "eth_sendTransaction", params: [{ from: owner, to: registry, data }] });
}
export async function setOnchainMemory(wallet, { registry, chainId, owner, agent, namespace, canRead, canWrite, expiry = "0" }) {
  await check(wallet, registry, chainId);
  if (!namespace || (!canRead && !canWrite)) throw new Error("Enter a namespace and select read or write.");
  const namespaceHash = keccak256(stringToHex(namespace)).slice(2);
  const data = "0x75281f72" + addressWord(agent) + namespaceHash + uintWord(canRead ? 1 : 0) +
    uintWord(canWrite ? 1 : 0) + uintWord(0) + uintWord(expiry, 64);
  return sendEstimated(wallet, { from: owner, to: registry, data });
}
export async function revokeOnchainMemory(wallet, { registry, chainId, owner, agent, namespace }) {
  await check(wallet, registry, chainId);
  if (!namespace) throw new Error("Enter a namespace.");
  const data = "0xe3f2a83d" + addressWord(agent) + keccak256(stringToHex(namespace)).slice(2);
  return wallet.request({ method: "eth_sendTransaction", params: [{ from: owner, to: registry, data }] });
}
export async function setOnchainLimit(wallet, { registry, chainId, owner, agent, token, amount, expiry = "0" }) {
  await check(wallet, registry, chainId);
  if (BigInt(amount) <= 0n) throw new Error("Limit must be positive.");
  const data = "0x11f61e6f" + addressWord(agent) + addressWord(token) + uintWord(amount) + uintWord(expiry, 64);
  return sendEstimated(wallet, { from: owner, to: registry, data });
}
export async function revokeOnchainLimit(wallet, { registry, chainId, owner, agent, token }) {
  await check(wallet, registry, chainId);
  const data = "0xad9a45fe" + addressWord(agent) + addressWord(token);
  return wallet.request({ method: "eth_sendTransaction", params: [{ from: owner, to: registry, data }] });
}
export async function onchainReceipt(wallet, registry, chainId, txHash, owner) {
  await check(wallet, registry, chainId);
  if (!/^0x[0-9a-fA-F]{64}$/.test(txHash)) throw new Error("Invalid transaction hash.");
  const receipt = await wallet.request({ method: "eth_getTransactionReceipt", params: [txHash] });
  if (!receipt) return "pending";
  if (receipt.transactionHash.toLowerCase() !== txHash.toLowerCase() || receipt.to?.toLowerCase() !== registry.toLowerCase() || receipt.from?.toLowerCase() !== owner.toLowerCase()) throw new Error("Receipt does not match registry transaction.");
  if (receipt.status === "0x1") return "included";
  if (receipt.status === "0x0") return "reverted";
  throw new Error("Invalid transaction receipt.");
}


/** Read the owner's ERC-20 allowance to the executor at one wallet-observed block. */
export async function tokenAllowance(wallet, { token, executor, chainId, owner }) {
  await check(wallet, token, chainId);
  addressWord(executor);
  const blockNumber = await wallet.request({ method: "eth_blockNumber" });
  if (!/^0x[0-9a-fA-F]+$/.test(blockNumber)) throw new Error("Invalid block number.");
  const block = await wallet.request({ method: "eth_getBlockByNumber", params: [blockNumber, false] });
  if (!block?.hash) throw new Error("Missing block identity.");
  const result = await wallet.request({ method: "eth_call", params: [{ to: token,
    data: "0xdd62ed3e" + addressWord(owner) + addressWord(executor) }, blockNumber] });
  if (!/^0x[0-9a-fA-F]{64}$/.test(result)) throw new Error("Invalid token allowance response.");
  const after = await wallet.request({ method: "eth_getBlockByNumber", params: [blockNumber, false] });
  if (after?.hash?.toLowerCase() !== block.hash.toLowerCase()) throw new Error("Allowance block reorganized.");
  return { amount: BigInt(result).toString(), block: BigInt(blockNumber).toString(), blockHash: block.hash };
}

/** Set a specific allowance; zero revokes it. The wallet must sign the transaction. */
export async function approveTokenAllowance(wallet, { token, executor, registry, chainId, owner, amount, observeDeployment }) {
  await check(wallet, token, chainId);
  addressWord(owner); addressWord(executor);
  const encodedAmount = uintWord(amount);
  if (BigInt(amount) > 0n) {
    addressWord(registry);
    if (typeof observeDeployment !== "function") throw new Error("A fresh gateway deployment observation is required.");
    const observed = await observeDeployment();
    if (!observed || observed.chain_id?.toString() !== BigInt(chainId).toString() ||
        observed.executor?.toLowerCase() !== executor.toLowerCase() ||
        observed.registry?.toLowerCase() !== registry.toLowerCase() || observed.matches !== true ||
        observed.registry_code_matches_local !== true || observed.executor_code_matches_local !== true) {
      throw new Error("Executor or registry does not match the configured local build.");
    }
    const code = await wallet.request({ method: "eth_getCode", params: [executor, "latest"] });
    if (!code || code === "0x" || code === "0x0") throw new Error("No contract found at executor address.");
  }
  const data = "0x095ea7b3" + addressWord(executor) + encodedAmount;
  const transaction = { from: owner, to: token, data };
  const result = await wallet.request({ method: "eth_call", params: [transaction, "latest"] });
  if (result !== "0x" && result !== "0x" + "0".repeat(63) + "1") throw new Error("Token approval simulation did not return success.");
  return sendEstimated(wallet, transaction);
}
