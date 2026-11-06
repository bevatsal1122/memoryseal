import { encodeFunctionData, isAddress, parseAbi, toHex } from "viem";
import { normalize, packetToBytes } from "viem/ens";
import { IDENTITY_CONFIG_KEY } from "./delegation.mjs";

const resolverAbi = parseAbi(["function setText(bytes name, string key, string value)"]);
const sepolia = 11155111;

function context(name, resolver, value) {
  if (!isAddress(resolver) || /^0x0{40}$/i.test(resolver)) throw new Error("A nonzero expected resolver is required.");
  if (typeof value !== "string" || new TextEncoder().encode(value).length > 2048) throw new Error("Configuration reference must be at most 2048 UTF-8 bytes.");
  const normalized = normalize(name);
  if (!normalized || !normalized.includes(".")) throw new Error("A full agent ENS name is required.");
  return { name: normalized, args: [toHex(packetToBytes(normalized)), IDENTITY_CONFIG_KEY, value] };
}

/** Write a public configuration reference using the agent's own wallet. */
export async function writeAgentConfig({ publicClient, walletClient, name, resolver, value }) {
  const account = walletClient.account;
  if (!account || !isAddress(account.address) || /^0x0{40}$/i.test(account.address)) throw new Error("Agent wallet required.");
  const normalized = context(name, resolver, value);
  const [readChain, writeChain] = await Promise.all([publicClient.getChainId(), walletClient.getChainId()]);
  if (readChain !== sepolia || writeChain !== sepolia) throw new Error("Agent configuration requires Sepolia.");
  const current = await publicClient.getEnsResolver({ name: normalized.name });
  if (!current || current.toLowerCase() !== resolver.toLowerCase()) throw new Error("Agent name resolver does not match.");
  const { request } = await publicClient.simulateContract({ address: resolver, abi: resolverAbi, functionName: "setText", args: normalized.args, account });
  const transactionHash = await walletClient.writeContract(request);
  return { name: normalized.name, resolver, value, agent: account.address, transactionHash };
}

/** Observe exact calldata and the resolved text at the transaction's canonical inclusion block. */
export async function verifyAgentConfig({ publicClient, name, resolver, value, agent, transactionHash }) {
  const normalized = context(name, resolver, value);
  if (!isAddress(agent) || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) throw new Error("Invalid agent configuration transaction context.");
  if (await publicClient.getChainId() !== sepolia) throw new Error("Agent configuration requires Sepolia.");
  const [tx, receipt] = await Promise.all([publicClient.getTransaction({ hash: transactionHash }), publicClient.getTransactionReceipt({ hash: transactionHash })]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  const input = encodeFunctionData({ abi: resolverAbi, functionName: "setText", args: normalized.args });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      block.hash?.toLowerCase() !== receipt.blockHash.toLowerCase() || tx.from.toLowerCase() !== agent.toLowerCase() ||
      tx.to?.toLowerCase() !== resolver.toLowerCase() || tx.input.toLowerCase() !== input.toLowerCase()) throw new Error("Configuration transaction mismatch or reorganization.");
  const [observedResolver, observedValue] = await Promise.all([
    publicClient.getEnsResolver({ name: normalized.name, blockNumber: receipt.blockNumber }),
    publicClient.getEnsText({ name: normalized.name, key: IDENTITY_CONFIG_KEY, blockNumber: receipt.blockNumber }),
  ]);
  const after = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (after.hash?.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("block reorganized");
  return { name: normalized.name, blockNumber: receipt.blockNumber.toString(), blockHash: receipt.blockHash,
    observedValue, matches: observedResolver?.toLowerCase() === resolver.toLowerCase() && observedValue === value };
}
