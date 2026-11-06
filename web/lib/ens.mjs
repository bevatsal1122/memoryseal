import { createPublicClient, createWalletClient, custom } from "viem";
import { mainnet, sepolia } from "viem/chains";
import { changeIdentityDelegation, verifyIdentityDelegation } from "../../integrations/ens/delegation.mjs";
import { deployAgentResolver, verifyAgentResolver } from "../../integrations/ens/resolver.mjs";
import { attachAgentResolver, verifyResolverAttachment, observeSubnameRegistry, registerOwnedSubname, setAgentSubnameRecord, verifyAgentRecordWrite, verifyOwnedSubname } from "../../integrations/ens/identity.mjs";

function clients(wallet, owner, chainId) {
  const chain = { "1": mainnet, "11155111": sepolia }[String(chainId)];
  if (!chain) throw new Error("ENS supports Ethereum mainnet or Sepolia here.");
  const transport = custom(wallet);
  return { publicClient: createPublicClient({ chain, transport }),
    walletClient: createWalletClient({ chain, transport, account: owner }), expectedChainId: chain.id };
}

export async function writeAgentName(wallet, { owner, chainId, parentName, label, agentAddress }) {
  return setAgentSubnameRecord({ ...clients(wallet, owner, chainId), parentName, label, agentAddress });
}

export async function verifyAgentName(wallet, { owner, chainId, name, agentAddress, transactionHash }) {
  const { publicClient, expectedChainId } = clients(wallet, owner, chainId);
  return verifyAgentRecordWrite({ publicClient, name, agentAddress, writer: owner, transactionHash, expectedChainId });
}

export async function inspectSubnameRegistry(wallet, { owner, chainId, parentName, label }) {
  const { publicClient, expectedChainId } = clients(wallet, owner, chainId);
  return observeSubnameRegistry(publicClient, { parentName, label, account: owner, expectedChainId });
}

export async function registerAgentSubname(wallet, { owner, chainId, parentName, label, expiry }) {
  return registerOwnedSubname({ ...clients(wallet, owner, chainId), parentName, label, expiry });
}

export async function verifyAgentSubname(wallet, { owner, chainId, parentName, label, registry, expiry, transactionHash }) {
  const { publicClient, expectedChainId } = clients(wallet, owner, chainId);
  return verifyOwnedSubname({ publicClient, expectedChainId, owner, parentName, label, registry, expiry, transactionHash });
}

export async function deployDedicatedResolver(wallet, { owner, chainId, salt }) {
  return deployAgentResolver({ ...clients(wallet, owner, chainId), salt });
}

export async function verifyDedicatedResolver(wallet, { owner, chainId, ...deployment }) {
  const { publicClient } = clients(wallet, owner, chainId);
  return verifyAgentResolver({ publicClient, owner, ...deployment });
}

export async function attachDedicatedResolver(wallet, { owner, chainId, parentName, label, deployment }) {
  return attachAgentResolver({ ...clients(wallet, owner, chainId), parentName, label, deployment });
}

export async function verifyDedicatedAttachment(wallet, { chainId, ...attachment }) {
  const { publicClient } = clients(wallet, attachment.owner, chainId);
  return verifyResolverAttachment({ publicClient, ...attachment });
}

export async function changeDedicatedDelegation(wallet, { owner, chainId, deployment, attachment, agent, grant }) {
  return changeIdentityDelegation({ ...clients(wallet, owner, chainId), deployment, attachment, agent, grant });
}

export async function verifyDedicatedDelegation(wallet, { chainId, ...context }) {
  const { publicClient } = clients(wallet, context.owner, chainId);
  return verifyIdentityDelegation({ publicClient, ...context });
}
