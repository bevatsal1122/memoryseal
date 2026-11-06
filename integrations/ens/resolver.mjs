import { encodeFunctionData, isAddress, parseAbi, parseEventLogs } from "viem";

// ENSv2 Sepolia deployment, pinned to the deployment artifacts documented in BUILD_RECORD.md.
export const SEPOLIA_RESOLVER_FACTORY = "0xda70306c98e97ece36f997a21368e53298572991";
export const SEPOLIA_RESOLVER_IMPLEMENTATION = "0x115eb53f0c60696633855f90b138178fb40b2b2c";
const chainId = 11155111;
const allRootRoles = BigInt(`0x${"11".repeat(32)}`);
const factoryAbi = parseAbi([
  "function deployProxy(address implementation, uint256 salt, bytes data) returns (address)",
  "function verifyContract(address proxy) view returns (address)",
  "event ProxyDeployed(address indexed sender, address indexed proxyAddress, uint256 salt, address implementation)",
]);
const resolverAbi = parseAbi(["function initialize((address account, uint256 roleBitmap)[] grants, bytes[] calls)"]);

function deploymentArgs(owner, salt) {
  if (!isAddress(owner) || /^0x0{40}$/i.test(owner)) throw new Error("A nonzero owner address is required.");
  if (!/^(0|[1-9][0-9]*)$/.test(String(salt))) throw new Error("Salt must be an unsigned decimal integer.");
  const value = BigInt(salt);
  if (value >= 2n ** 256n) throw new Error("Salt exceeds uint256.");
  const init = encodeFunctionData({ abi: resolverAbi, functionName: "initialize", args: [[{ account: owner, roleBitmap: allRootRoles }], []] });
  return [SEPOLIA_RESOLVER_IMPLEMENTATION, value, init];
}

/** Deploy an owner-controlled resolver proxy. This does not attach it to a name. */
export async function deployAgentResolver({ publicClient, walletClient, salt }) {
  const owner = walletClient.account?.address;
  const args = deploymentArgs(owner, salt);
  const [readChain, writeChain] = await Promise.all([publicClient.getChainId(), walletClient.getChainId()]);
  if (readChain !== chainId || writeChain !== chainId) throw new Error("ENS resolver deployment requires Sepolia.");
  const { request, result: resolver } = await publicClient.simulateContract({ address: SEPOLIA_RESOLVER_FACTORY,
    abi: factoryAbi, functionName: "deployProxy", args, account: walletClient.account });
  if (!isAddress(resolver) || /^0x0{40}$/i.test(resolver)) throw new Error("Factory returned an invalid resolver.");
  const transactionHash = await walletClient.writeContract(request);
  return { owner, salt: args[1].toString(), resolver, transactionHash };
}

/** Verify the exact factory transaction and implementation at the inclusion block. */
export async function verifyAgentResolver({ publicClient, owner, salt, resolver, transactionHash }) {
  const args = deploymentArgs(owner, salt);
  if (!isAddress(resolver) || /^0x0{40}$/i.test(resolver) || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) throw new Error("Invalid deployment context.");
  if (await publicClient.getChainId() !== chainId) throw new Error("ENS resolver verification requires Sepolia.");
  const [tx, receipt] = await Promise.all([publicClient.getTransaction({ hash: transactionHash }), publicClient.getTransactionReceipt({ hash: transactionHash })]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  const input = encodeFunctionData({ abi: factoryAbi, functionName: "deployProxy", args });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      !block.hash || block.hash.toLowerCase() !== receipt.blockHash.toLowerCase() ||
      tx.from.toLowerCase() !== owner.toLowerCase() || tx.to?.toLowerCase() !== SEPOLIA_RESOLVER_FACTORY.toLowerCase() ||
      tx.input.toLowerCase() !== input.toLowerCase()) throw new Error("Deployment transaction mismatch or reorganization.");
  const events = parseEventLogs({ abi: factoryAbi, eventName: "ProxyDeployed", logs: receipt.logs ?? [], strict: true });
  const matchingEvent = events.some((event) => event.address.toLowerCase() === SEPOLIA_RESOLVER_FACTORY.toLowerCase() &&
    event.args.sender.toLowerCase() === owner.toLowerCase() && event.args.proxyAddress.toLowerCase() === resolver.toLowerCase() &&
    event.args.salt === args[1] && event.args.implementation.toLowerCase() === SEPOLIA_RESOLVER_IMPLEMENTATION.toLowerCase());
  if (!matchingEvent) throw new Error("Resolver deployment event mismatch.");
  const implementation = await publicClient.readContract({ address: SEPOLIA_RESOLVER_FACTORY, abi: factoryAbi,
    functionName: "verifyContract", args: [resolver], blockNumber: receipt.blockNumber });
  const after = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (after.hash?.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("block reorganized");
  if (implementation.toLowerCase() !== SEPOLIA_RESOLVER_IMPLEMENTATION.toLowerCase()) throw new Error("Resolver implementation mismatch.");
  return { owner, resolver, transactionHash, blockNumber: receipt.blockNumber.toString(), blockHash: receipt.blockHash };
}
