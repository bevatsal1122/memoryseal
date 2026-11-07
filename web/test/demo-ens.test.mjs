import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareDemoEns} from '../lib/demo-ens.mjs';
function fixture({disabled=false,pending=false}={}) {
 const agents=[],setups=[],grants=[];
 const owner={request:async(method,path,payload)=>{
  if(path==='/ens-registration/config')return {enabled:!disabled,registrar:'registrar'};
  if(path==='/agents')return {agents};
  assert.equal(path,'/agents/setup');setups.push(payload);
  const agent={id:String(agents.length),signing_address:payload.signing_address,label:payload.label,ens_name:pending?null:`${payload.label}.memoryseal.eth`,ens_registration:{state:pending?'queued':'registered',name:`${payload.label}.memoryseal.eth`}};
  agents.push(agent);return agent;
 },listCapabilities:async()=>({policy_version:agents.length,capabilities:grants}),grant:async g=>grants.push(g)};
 return {owner,browser:{signer:{address:'browser'}},finance:{signer:{address:'finance'}},names:{browser:'orbit',finance:'nova'},onMemory:()=>{},onStage:async()=>{},agents,setups,grants};
}
test('demo requests real sponsored ENS setup for both agents and grants wei-denominated limit',async()=>{
 const f=fixture();const result=await prepareDemoEns(f);
 assert.equal(f.setups.length,2);assert.ok(f.setups.every(s=>s.sponsored_ens===true));
 assert.equal(f.setups[0].operations[0],'write');assert.equal(f.setups[1].operations[0],'read');
 assert.equal(result.financeAgent.ens_name,'nova.memoryseal.eth');
 assert.equal(f.grants[0].max_amount,'5000000000000000');
 await prepareDemoEns(f);assert.equal(f.setups.length,2);assert.equal(f.grants.length,1);
});
test('disabled registrar stops instead of pretending names were registered',async()=>{
 const f=fixture({disabled:true});await assert.rejects(prepareDemoEns(f),/registrar/);assert.equal(f.setups.length,0);
});
test('pending registration exposes progress and stops before finance setup completes',async()=>{
 const f=fixture({pending:true}),updates=[];f.onMemory=value=>updates.push(value);
 await assert.rejects(prepareDemoEns({...f,timeoutMs:0}),/still pending/);
 assert.ok(updates.some(s=>s.browserAgent?.ens_registration.state==='queued'));assert.equal(f.grants.length,0);
});
