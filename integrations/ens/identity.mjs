import { createPublicClient, encodeFunctionData, http, isAddress, keccak256, parseAbi, stringToHex, toHex } from "viem";
import { namehash, normalize, packetToBytes } from "viem/ens";
import { mainnet, sepolia } from "viem/chains";

export function createEnsClient({ network, rpcUrl, ccipRead = true }) {
  const chain = { mainnet, sepolia }[network];
  if (!chain || !rpcUrl) throw new Error("ENS network and RPC URL required");
  return createPublicClient({ chain, transport: http(rpcUrl), ...(ccipRead ? {} : { ccipRead: false }) });
}

export async function observeAgentAddress(client, { name, expectedAddress, expectedChainId }) {
  if (!isAddress(expectedAddress)) throw new Error("invalid agent address");
  if (await client.getChainId() !== expectedChainId) throw new Error("chain ID mismatch");
  const normalized = normalize(name);
  const block = await client.getBlock({ blockTag: "latest" });
  if (block.number === null || !block.hash) throw new Error("missing block identity");
  const resolved = await client.getEnsAddress({ name: normalized, blockNumber: block.number, strict: true });
  const canonical = await client.getBlock({ blockNumber: block.number });
  if (canonical.hash?.toLowerCase() !== block.hash.toLowerCase()) throw new Error("block reorganized");
  return { name: normalized, resolvedAddress: resolved,
    matches: resolved !== null && resolved.toLowerCase() === expectedAddress.toLowerCase(),
    chainId: expectedChainId, blockNumber: block.number.toString(), blockHash: block.hash };
}

// Resolution proves only the address record at the time of the read. It does
// not prove control of the parent name or grant gateway permissions.
export async function verifyAgentAddress(client, name, expectedAddress) {
  if (!isAddress(expectedAddress)) throw new Error("invalid agent address");
  const canonicalName = normalize(name);
  const resolved = await client.getEnsAddress({ name: canonicalName });
  return { name: canonicalName, resolvedAddress: resolved,
    matches: resolved !== null && resolved.toLowerCase() === expectedAddress.toLowerCase() };
}

const resolverAbi = parseAbi(["function setAddress(bytes name, uint256 coinType, bytes addressBytes)",
  "function getRecordId(bytes32 node) view returns (uint256)"]);
const helperAbi = parseAbi(["function findCanonicalRegistry(bytes name) view returns (address)",
  "function findExactOwner(bytes name) view returns (address)"]);
const registryAbi = parseAbi(["function hasRootRoles(uint256 roleBitmap, address account) view returns (bool)",
  "function getStatus(uint256 anyId) view returns (uint8)", "function getExpiry(uint256 anyId) view returns (uint64)",
  "function register(string label, address owner, address registry, address resolver, uint256 roleBitmap, uint64 expiry) returns (uint256)"]);
const sepoliaHelper = "0xd453e5bdb62cc3bea84341b1e306319c8ffd7dfe";
const zeroAddress = "0x0000000000000000000000000000000000000000";
// Owner may renew, change resolver/subregistry, and transfer. The registrar's
// own root roles are separate and may still control names in this registry.
const ownerRoles = (1n << 16n) | (1n << 20n) | (1n << 24n) | (1n << 156n);

/** Observe ownership and canonical registry before a possible owned-subname registration. */
export async function observeSubnameRegistry(client, { parentName, label, account, expectedChainId }) {
  if (expectedChainId !== 11155111 || !isAddress(account)) throw new Error("ENSv2 registry inspection requires a Sepolia account.");
  const parent = normalize(parentName), normalizedLabel = normalize(label);
  if (!normalizedLabel || normalizedLabel.includes(".")) throw new Error("agent label must be one ENS label");
  const name = normalize(`${normalizedLabel}.${parent}`);
  if (await client.getChainId() !== expectedChainId) throw new Error("chain ID mismatch");
  const block = await client.getBlock({ blockTag: "latest" });
  if (block.number === null || !block.hash) throw new Error("missing block identity");
  const read = (functionName, target) => client.readContract({ address: sepoliaHelper, abi: helperAbi,
    functionName, args: [toHex(packetToBytes(target))], blockNumber: block.number });
  const [parentOwner, childOwner, registry] = await Promise.all([
    read("findExactOwner", parent), read("findExactOwner", name), read("findCanonicalRegistry", parent),
  ]);
  let canRegister = false;
  if (registry.toLowerCase() !== zeroAddress) canRegister = await client.readContract({ address: registry,
    abi: registryAbi, functionName: "hasRootRoles", args: [1n, account], blockNumber: block.number });
  const canonical = await client.getBlock({ blockNumber: block.number });
  if (canonical.hash?.toLowerCase() !== block.hash.toLowerCase()) throw new Error("block reorganized");
  return { parent, name, parentOwner, childOwner, registry, canRegister, blockNumber: block.number.toString(), blockHash: block.hash };
}

/** Register a new, owner-held Sepolia name in its canonical parent registry. */
export async function registerOwnedSubname({ publicClient, walletClient, parentName, label, expiry, expectedChainId }) {
  const account = walletClient.account;
  if (!account || !isAddress(account.address) || account.address.toLowerCase() === zeroAddress) throw new Error("Wallet account required.");
  if (await walletClient.getChainId() !== expectedChainId) throw new Error("chain ID mismatch");
  const observed = await observeSubnameRegistry(publicClient, { parentName, label, account: account.address, expectedChainId });
  if (observed.parentOwner.toLowerCase() !== account.address.toLowerCase()) throw new Error("Connected wallet is not the parent owner.");
  if (observed.registry.toLowerCase() === zeroAddress || !observed.canRegister) throw new Error("Canonical parent subregistry or registrar role is missing.");
  if (!/^\d+$/.test(String(expiry))) throw new Error("A future expiry in seconds is required.");
  const expires = BigInt(expiry);
  const block = await publicClient.getBlock({ blockNumber: BigInt(observed.blockNumber) });
  if (block.hash?.toLowerCase() !== observed.blockHash.toLowerCase() || expires <= block.timestamp || expires >= 2n ** 64n) throw new Error("Invalid expiry or reorganized block.");
  const normalizedLabel = normalize(label);
  const labelId = BigInt(keccak256(stringToHex(normalizedLabel)));
  const [status, priorExpiry] = await Promise.all([
    publicClient.readContract({ address: observed.registry, abi: registryAbi, functionName: "getStatus", args: [labelId] }),
    publicClient.readContract({ address: observed.registry, abi: registryAbi, functionName: "getExpiry", args: [labelId] }),
  ]);
  if (status !== 0 || priorExpiry !== 0n) throw new Error("Label is reserved, registered, or previously used.");
  const args = [normalizedLabel, account.address, zeroAddress, zeroAddress, ownerRoles, expires];
  const { request } = await publicClient.simulateContract({ address: observed.registry, abi: registryAbi,
    functionName: "register", args, account });
  const transactionHash = await walletClient.writeContract(request);
  return { name: observed.name, registry: observed.registry, owner: account.address,
    expiry: expires.toString(), transactionHash, roles: ownerRoles.toString() };
}

/** Check the intended transaction and owned name at its inclusion block. */
export async function verifyOwnedSubname({ publicClient, parentName, label, owner, registry, expiry, transactionHash, expectedChainId }) {
  if (expectedChainId !== 11155111 || !isAddress(owner) || !isAddress(registry) ||
      !/^\d+$/.test(String(expiry)) || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) throw new Error("Invalid registration context.");
  if (await publicClient.getChainId() !== expectedChainId) throw new Error("chain ID mismatch");
  const parent = normalize(parentName), normalizedLabel = normalize(label);
  if (!normalizedLabel || normalizedLabel.includes(".")) throw new Error("agent label must be one ENS label");
  const name = normalize(`${normalizedLabel}.${parent}`);
  const [tx, receipt] = await Promise.all([publicClient.getTransaction({ hash: transactionHash }), publicClient.getTransactionReceipt({ hash: transactionHash })]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  const input = encodeFunctionData({ abi: registryAbi, functionName: "register", args: [normalizedLabel, owner, zeroAddress, zeroAddress, ownerRoles, BigInt(expiry)] });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      block.hash?.toLowerCase() !== receipt.blockHash.toLowerCase() || tx.from.toLowerCase() !== owner.toLowerCase() ||
      tx.to?.toLowerCase() !== registry.toLowerCase() || tx.input.toLowerCase() !== input.toLowerCase()) throw new Error("Registration transaction mismatch or reorganization.");
  const [canonicalRegistry, observedOwner] = await Promise.all([
    publicClient.readContract({ address: sepoliaHelper, abi: helperAbi, functionName: "findCanonicalRegistry", args: [toHex(packetToBytes(parent))], blockNumber: receipt.blockNumber }),
    publicClient.readContract({ address: sepoliaHelper, abi: helperAbi, functionName: "findExactOwner", args: [toHex(packetToBytes(name))], blockNumber: receipt.blockNumber }),
  ]);
  const after = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (after.hash?.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("block reorganized");
  return { name, blockNumber: receipt.blockNumber.toString(), blockHash: receipt.blockHash,
    matches: canonicalRegistry.toLowerCase() === registry.toLowerCase() && observedOwner.toLowerCase() === owner.toLowerCase() };
}

/** Set an owner-managed agent subname record on the name's current ENSv2 resolver.
 * This creates a resolver record, not an owned subname token. The caller must
 * hold the appropriate resolver role and must verify the transaction and record.
 */
export async function setAgentSubnameRecord({ publicClient, walletClient, parentName, label,
                                              agentAddress, expectedChainId }) {
  if (!walletClient.account || !isAddress(agentAddress) || /^0x0{40}$/i.test(agentAddress)) {
    throw new Error("wallet account and nonzero agent address required");
  }
  if (!Number.isSafeInteger(expectedChainId) || expectedChainId <= 0) throw new Error("invalid chain ID");
  const parent = normalize(parentName);
  const normalizedLabel = normalize(label);
  if (!normalizedLabel || normalizedLabel.includes(".")) throw new Error("agent label must be one ENS label");
  const name = normalize(`${normalizedLabel}.${parent}`);
  const [readChain, writeChain] = await Promise.all([publicClient.getChainId(), walletClient.getChainId()]);
  if (readChain !== expectedChainId || writeChain !== expectedChainId) throw new Error("chain ID mismatch");
  const resolver = await publicClient.getEnsResolver({ name });
  if (!resolver) throw new Error("no resolver found for agent name");
  const recordId = await publicClient.readContract({ address: resolver, abi: resolverAbi,
    functionName: "getRecordId", args: [namehash(name)] });
  if (recordId !== 0n) throw new Error("Agent name already has a resolver record that may be shared; this flow only creates new records.");
  const { request } = await publicClient.simulateContract({ address: resolver, abi: resolverAbi,
    functionName: "setAddress", args: [toHex(packetToBytes(name)), 60n, agentAddress],
    account: walletClient.account });
  const transactionHash = await walletClient.writeContract(request);
  return { name, resolver, transactionHash, registration: "resolver-record" };
}

/** Check the submitted transaction, canonical block and the current forward record.
 * A later reorg or resolver change can invalidate this observation.
 */
export async function verifyAgentRecordWrite({ publicClient, name, agentAddress, writer,
                                                transactionHash, expectedChainId }) {
  if (!isAddress(agentAddress) || !isAddress(writer) || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) {
    throw new Error("invalid transaction context");
  }
  if (await publicClient.getChainId() !== expectedChainId) throw new Error("chain ID mismatch");
  const normalized = normalize(name);
  const [tx, receipt] = await Promise.all([
    publicClient.getTransaction({ hash: transactionHash }),
    publicClient.getTransactionReceipt({ hash: transactionHash }),
  ]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      block.hash.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("transaction not canonical and successful");
  const resolver = await publicClient.getEnsResolver({ name: normalized });
  const expectedInput = encodeFunctionData({ abi: resolverAbi, functionName: "setAddress",
    args: [toHex(packetToBytes(normalized)), 60n, agentAddress] });
  if (!resolver || tx.from.toLowerCase() !== writer.toLowerCase() || tx.to?.toLowerCase() !== resolver.toLowerCase() ||
      tx.input.toLowerCase() !== expectedInput.toLowerCase()) throw new Error("transaction does not match agent record");
  const resolved = await publicClient.getEnsAddress({ name: normalized });
  return { name: normalized, resolver, resolvedAddress: resolved, blockNumber: receipt.blockNumber,
    blockHash: receipt.blockHash, matches: resolved !== null && resolved.toLowerCase() === agentAddress.toLowerCase() };
}

const resolverAttachmentAbi = parseAbi([
  "function setResolver(uint256 anyId, address resolver)",
  "function getResolver(string label) view returns (address)",
  "function hasRoles(uint256 anyId, uint256 roleBitmap, address account) view returns (bool)",
]);
const setResolverRole = 1n << 20n;

/** Attach a verified factory deployment to an owner-held name with no explicit resolver. */
export async function attachAgentResolver({ publicClient, walletClient, parentName, label, deployment }) {
  const { verifyAgentResolver, SEPOLIA_RESOLVER_FACTORY, SEPOLIA_RESOLVER_IMPLEMENTATION } = await import("./resolver.mjs");
  const account = walletClient.account;
  if (!account || account.address.toLowerCase() !== deployment.owner?.toLowerCase()) throw new Error("Resolver deployment owner must be the connected wallet.");
  if (await walletClient.getChainId() !== 11155111) throw new Error("ENS resolver attachment requires Sepolia.");
  await verifyAgentResolver({ publicClient, ...deployment });
  const observed = await observeSubnameRegistry(publicClient, { parentName, label, account: account.address, expectedChainId: 11155111 });
  if (observed.childOwner.toLowerCase() !== account.address.toLowerCase() || observed.registry.toLowerCase() === zeroAddress) throw new Error("Connected wallet must own the registered subname.");
  const normalizedLabel = normalize(label), labelId = BigInt(keccak256(stringToHex(normalizedLabel)));
  const blockNumber = BigInt(observed.blockNumber);
  const factoryAbi = parseAbi(["function verifyContract(address proxy) view returns (address)"]);
  const [currentResolver, hasRole, implementation] = await Promise.all([
    publicClient.readContract({ address: observed.registry, abi: resolverAttachmentAbi, functionName: "getResolver", args: [normalizedLabel], blockNumber }),
    publicClient.readContract({ address: observed.registry, abi: resolverAttachmentAbi, functionName: "hasRoles", args: [labelId, setResolverRole, account.address], blockNumber }),
    publicClient.readContract({ address: SEPOLIA_RESOLVER_FACTORY, abi: factoryAbi, functionName: "verifyContract", args: [deployment.resolver], blockNumber }),
  ]);
  const block = await publicClient.getBlock({ blockNumber });
  if (block.hash?.toLowerCase() !== observed.blockHash.toLowerCase()) throw new Error("block reorganized");
  if (currentResolver.toLowerCase() !== zeroAddress) throw new Error("Subname already has an explicit resolver; attachment would change its records.");
  if (!hasRole) throw new Error("Wallet lacks the subname resolver role.");
  if (implementation.toLowerCase() !== SEPOLIA_RESOLVER_IMPLEMENTATION.toLowerCase()) throw new Error("Resolver implementation changed.");
  const args = [labelId, deployment.resolver];
  const { request } = await publicClient.simulateContract({ address: observed.registry, abi: resolverAttachmentAbi, functionName: "setResolver", args, account });
  const transactionHash = await walletClient.writeContract(request);
  return { name: observed.name, parentName: observed.parent, label: normalizedLabel, registry: observed.registry,
    resolver: deployment.resolver, owner: account.address, transactionHash };
}

/** Check the attachment transaction and registry state at its inclusion block. */
export async function verifyResolverAttachment({ publicClient, parentName, label, registry, resolver, owner, transactionHash }) {
  if (![registry, resolver, owner].every(isAddress) || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) throw new Error("Invalid resolver attachment context.");
  if (await publicClient.getChainId() !== 11155111) throw new Error("ENS resolver verification requires Sepolia.");
  const parent = normalize(parentName), normalizedLabel = normalize(label);
  if (!normalizedLabel || normalizedLabel.includes(".")) throw new Error("agent label must be one ENS label");
  const name = normalize(`${normalizedLabel}.${parent}`), labelId = BigInt(keccak256(stringToHex(normalizedLabel)));
  const [tx, receipt] = await Promise.all([publicClient.getTransaction({ hash: transactionHash }), publicClient.getTransactionReceipt({ hash: transactionHash })]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  const input = encodeFunctionData({ abi: resolverAttachmentAbi, functionName: "setResolver", args: [labelId, resolver] });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      block.hash?.toLowerCase() !== receipt.blockHash.toLowerCase() || tx.from.toLowerCase() !== owner.toLowerCase() ||
      tx.to?.toLowerCase() !== registry.toLowerCase() || tx.input.toLowerCase() !== input.toLowerCase()) throw new Error("Attachment transaction mismatch or reorganization.");
  const [canonicalRegistry, observedOwner, attached] = await Promise.all([
    publicClient.readContract({ address: sepoliaHelper, abi: helperAbi, functionName: "findCanonicalRegistry", args: [toHex(packetToBytes(parent))], blockNumber: receipt.blockNumber }),
    publicClient.readContract({ address: sepoliaHelper, abi: helperAbi, functionName: "findExactOwner", args: [toHex(packetToBytes(name))], blockNumber: receipt.blockNumber }),
    publicClient.readContract({ address: registry, abi: resolverAttachmentAbi, functionName: "getResolver", args: [normalizedLabel], blockNumber: receipt.blockNumber }),
  ]);
  const after = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (after.hash?.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("block reorganized");
  return { name, blockNumber: receipt.blockNumber.toString(), blockHash: receipt.blockHash,
    matches: canonicalRegistry.toLowerCase() === registry.toLowerCase() && observedOwner.toLowerCase() === owner.toLowerCase() && attached.toLowerCase() === resolver.toLowerCase() };
}
