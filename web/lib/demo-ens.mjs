// Shared by local and hosted server workers. Reuses identities instead of buying names on replay.
export async function prepareDemoEns({owner,browser,finance,names,onMemory,onStage,signal,timeoutMs=480000,pollMs=2000}) {
 const config=await owner.request('GET','/ens-registration/config');
 if(!config.enabled || !config.registrar)throw new Error('Enable and fund the gateway’s sponsored ENS registrar before running this demo.');
 const roles=[['browser',browser,'write'],['finance',finance,'read']];
 const agents={};
 for(const [role,client,operation] of roles) {
  signal?.throwIfAborted();
  const list=await owner.request('GET','/agents');
  let agent=list.agents.find(a=>a.signing_address.toLowerCase()===client.signer.address.toLowerCase()&&!a.revoked);
  if(!agent) {
   const policy=await owner.listCapabilities();
   const created=await owner.request('POST','/agents/setup',{
    request_id:crypto.randomUUID(),policy_version:policy.policy_version,
    signing_address:client.signer.address,label:names[role],namespace:'demo-invoices',
    operations:[operation],acceptance:'strict',ens_name:null,sponsored_ens:true,
   });
   agent={...created,signing_address:client.signer.address,label:names[role]};
  }
  agents[`${role}Agent`]={...agent,address:client.signer.address};
  onMemory({[`${role}Agent`]:agents[`${role}Agent`]});
 }
 await onStage('ens');
 const deadline=Date.now()+timeoutMs;
 while(true) {
  signal?.throwIfAborted();
  const list=await owner.request('GET','/agents');
  for(const [role,client] of roles) {
   const agent=list.agents.find(a=>a.id===agents[`${role}Agent`].id);
   if(!agent || agent.revoked)throw new Error(`${role} demo agent is unavailable.`);
   agents[`${role}Agent`]={...agent,address:client.signer.address};
   onMemory({[`${role}Agent`]:agents[`${role}Agent`]});
   if(['failed','cancelled'].includes(agent.ens_registration?.state))throw new Error(`${role} ENS registration ${agent.ens_registration.state}: ${agent.ens_registration.message || 'Check registrar configuration.'}`);
  }
  if(roles.every(([role])=>agents[`${role}Agent`].ens_registration?.state==='registered' && agents[`${role}Agent`].ens_name))break;
  if(Date.now()>=deadline)throw new Error('ENS registration is still pending. Retry to resume the same names; no new identities will be created.');
  await new Promise(resolve=>setTimeout(resolve,pollMs));
 }
 const policy=await owner.listCapabilities();
 const financeId=agents.financeAgent.id;
 const grants=policy.capabilities.filter(c=>c.agent_id===financeId && c.operation==='transfer' && c.resource==='eip155:11155111/slip44:60' && !c.revoked);
 if(grants.some(c=>String(c.max_amount)!=='5000000000000000'))throw new Error('The demo finance permission changed. Restore the 0.005 ETH limit before running.');
 if(!grants.length)await owner.grant({agent_id:financeId,operation:'transfer',resource:'eip155:11155111/slip44:60',max_amount:'5000000000000000'});
 return agents;
}
