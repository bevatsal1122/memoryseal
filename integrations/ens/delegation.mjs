import { encodeFunctionData, isAddress, keccak256, parseAbi, stringToHex } from "viem";
import { observeSubnameRegistry, verifyResolverAttachment } from "./identity.mjs";
import { SEPOLIA_RESOLVER_FACTORY, SEPOLIA_RESOLVER_IMPLEMENTATION, verifyAgentResolver } from "./resolver.mjs";

// Only a public identity configuration reference, never a MemorySeal capability.
export const IDENTITY_CONFIG_KEY = "memoryseal.config";
const role = 1n << 4n;
const resource = BigInt(keccak256(stringToHex(IDENTITY_CONFIG_KEY)));
const abi = parseAbi([
  "function setText(bytes name, string key, string value)",
  "function grantSetterRoles(bytes setter, address account) returns (bool)",
  "function revokeRoles(uint256 resource, uint256 roleBitmap, address account) returns (bool)",
  "function roles(uint256 resource, address account) view returns (uint256)",
  "function hasRootRoles(uint256 roleBitmap, address account) view returns (bool)",
]);
const registryAbi = parseAbi(["function getResolver(string label) view returns (address)"]);
const factoryAbi = parseAbi(["function verifyContract(address proxy) view returns (address)"]);
const setter = encodeFunctionData({ abi, functionName: "setText", args: ["0x", IDENTITY_CONFIG_KEY, ""] });

/** Submit a key-scoped grant or revocation. Resolver sharing remains an owner responsibility. */
export async function changeIdentityDelegation({ publicClient, walletClient, deployment, attachment, agent, grant }) {
  const owner = walletClient.account?.address;
  if (!isAddress(owner ?? "") || !isAddress(agent) || /^0x0{40}$/i.test(agent) || typeof grant !== "boolean") throw new Error("Valid owner, agent and delegation action required.");
  if (owner.toLowerCase() !== deployment.owner?.toLowerCase() || owner.toLowerCase() !== attachment.owner?.toLowerCase() ||
      deployment.resolver?.toLowerCase() !== attachment.resolver?.toLowerCase()) throw new Error("Resolver context does not match the connected owner.");
  if (await walletClient.getChainId() !== 11155111) throw new Error("ENS delegation requires Sepolia.");
  await verifyAgentResolver({ publicClient, ...deployment });
  const verified = await verifyResolverAttachment({ publicClient, ...attachment });
  if (!verified.matches) throw new Error("Resolver attachment did not match.");
  const current = await observeSubnameRegistry(publicClient, { parentName: attachment.parentName, label: attachment.label, account: owner, expectedChainId: 11155111 });
  if (current.childOwner.toLowerCase() !== owner.toLowerCase() || current.registry.toLowerCase() !== attachment.registry.toLowerCase()) throw new Error("Subname ownership or registry changed.");
  const blockNumber = BigInt(current.blockNumber);
  const [resolver, implementation] = await Promise.all([
    publicClient.readContract({ address: current.registry, abi: registryAbi, functionName: "getResolver", args: [attachment.label], blockNumber }),
    publicClient.readContract({ address: SEPOLIA_RESOLVER_FACTORY, abi: factoryAbi, functionName: "verifyContract", args: [deployment.resolver], blockNumber }),
  ]);
  const block = await publicClient.getBlock({ blockNumber });
  if (block.hash?.toLowerCase() !== current.blockHash.toLowerCase()) throw new Error("block reorganized");
  if (resolver.toLowerCase() !== deployment.resolver.toLowerCase() || implementation.toLowerCase() !== SEPOLIA_RESOLVER_IMPLEMENTATION.toLowerCase()) throw new Error("Resolver or implementation changed.");
  const functionName = grant ? "grantSetterRoles" : "revokeRoles";
  const args = grant ? [setter, agent] : [resource, role, agent];
  const { request } = await publicClient.simulateContract({ address: resolver, abi, functionName, args, account: walletClient.account });
  const transactionHash = await walletClient.writeContract(request);
  return { owner, agent, resolver, grant, transactionHash };
}

/** Verify the intended role transaction and report key- and root-scoped roles at inclusion. */
export async function verifyIdentityDelegation({ publicClient, owner, agent, resolver, grant, transactionHash }) {
  if (![owner, agent, resolver].every(isAddress) || typeof grant !== "boolean" || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) throw new Error("Invalid delegation context.");
  if (await publicClient.getChainId() !== 11155111) throw new Error("ENS delegation requires Sepolia.");
  const [tx, receipt] = await Promise.all([publicClient.getTransaction({ hash: transactionHash }), publicClient.getTransactionReceipt({ hash: transactionHash })]);
  const block = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  const functionName = grant ? "grantSetterRoles" : "revokeRoles";
  const input = encodeFunctionData({ abi, functionName, args: grant ? [setter, agent] : [resource, role, agent] });
  if (receipt.status !== "success" || receipt.transactionHash.toLowerCase() !== transactionHash.toLowerCase() ||
      block.hash?.toLowerCase() !== receipt.blockHash.toLowerCase() || tx.from.toLowerCase() !== owner.toLowerCase() ||
      tx.to?.toLowerCase() !== resolver.toLowerCase() || tx.input.toLowerCase() !== input.toLowerCase()) throw new Error("Delegation transaction mismatch or reorganization.");
  const [keyRoles, rootRole] = await Promise.all([
    publicClient.readContract({ address: resolver, abi, functionName: "roles", args: [resource, agent], blockNumber: receipt.blockNumber }),
    publicClient.readContract({ address: resolver, abi, functionName: "hasRootRoles", args: [role, agent], blockNumber: receipt.blockNumber }),
  ]);
  const after = await publicClient.getBlock({ blockNumber: receipt.blockNumber });
  if (after.hash?.toLowerCase() !== receipt.blockHash.toLowerCase()) throw new Error("block reorganized");
  const keyRole = (keyRoles & role) !== 0n;
  return { keyRole, rootRole, matches: keyRole === grant, blockNumber: receipt.blockNumber.toString(), blockHash: receipt.blockHash };
}
