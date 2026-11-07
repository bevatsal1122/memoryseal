import { createPublicClient, custom } from 'viem';
import { sepolia } from 'viem/chains';
import { inspectSubnameRegistry, registerAgentSubname, verifyAgentSubname, deployDedicatedResolver, verifyDedicatedResolver,
 attachDedicatedResolver, verifyDedicatedAttachment, writeAgentName, verifyAgentName } from './ens.mjs';
import { observeAgentAddress } from '../../integrations/ens/identity.mjs';
export function agentEnsWallet(wallet, owner) {
 let onSending;
 const signingWallet={request:async args=>{
  if(args.method==='eth_sendTransaction')onSending?.();
  return wallet.request(args);
 }};
 const client=createPublicClient({chain:sepolia,transport:custom(wallet)});
 const context=job=>({owner,chainId:11155111,parentName:job.parentName,label:job.label,agentAddress:job.agentAddress});
 return {
  async assertWallet(expected) {
   const [chain,accounts]=await Promise.all([wallet.request({method:'eth_chainId'}),wallet.request({method:'eth_accounts'})]);
   if(Number(chain)!==11155111)throw new Error('Select Sepolia in your wallet and reconnect to continue agent setup.');
   if(accounts[0]?.toLowerCase()!==expected.toLowerCase())throw new Error('Wallet changed. Reconnect the setup owner wallet.');
  },
  inspect:job=>inspectSubnameRegistry(wallet,context(job)),
  async submit(stage,job,beforeSend) {
   onSending=beforeSend;
   const ctx=context(job);
   if(stage==='registration')return registerAgentSubname(signingWallet,{...ctx,expiry:job.expiry});
   if(stage==='resolver')return deployDedicatedResolver(signingWallet,{...ctx,salt:job.salt});
   if(stage==='attachment')return attachDedicatedResolver(signingWallet,{...ctx,deployment:job.resolver});
   return writeAgentName(signingWallet,ctx);
  },
  async wait(hash) {
   const receipt=await client.waitForTransactionReceipt({hash,timeout:60000});
   if(receipt.status!=='success')throw new Error('ENS transaction reverted. The setup is saved for inspection; it will not be resubmitted automatically.');
  },
  verify(stage,job) {
   const ctx=context(job);
   if(stage==='registration')return verifyAgentSubname(wallet,{...ctx,...job.registration});
   if(stage==='resolver')return verifyDedicatedResolver(wallet,{...ctx,...job.resolver});
   if(stage==='attachment')return verifyDedicatedAttachment(wallet,{...ctx,...job.attachment});
   return verifyAgentName(wallet,{...ctx,...job.address});
  },
  resolve:job=>observeAgentAddress(client,{name:`${job.label}.${job.parentName}`,expectedAddress:job.agentAddress,expectedChainId:11155111}),
 };
}
