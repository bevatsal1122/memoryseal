import {test} from 'node:test';
import assert from 'node:assert/strict';
import {agentEnsName,provisionAgentEns} from '../lib/agent-ens-setup.mjs';
const owner='0x'+'1'.repeat(40),agentAddress='0x'+'2'.repeat(40),registry='0x'+'3'.repeat(40);
function fixture(){
 const sent=[],verified=[],saved=[];
 const job={owner,agentAddress,parentName:'memoryseal.eth',label:'research',expiry:'9999999999',salt:'123'};
 const deps={assertWallet:async()=>{},inspect:async()=>({parentOwner:owner,registry,canRegister:true}),
  submit:async(stage,job,before)=>{before();sent.push(stage);return {transactionHash:'0x'+stage};},
  wait:async()=>{},verify:async(stage)=>{verified.push(stage);return {matches:true};},resolve:async()=>({matches:true})};
 return {job,deps,sent,verified,save:job=>saved.push(structuredClone(job)),saved};
}
test('one flow registers, deploys, attaches and resolves before completing',async()=>{
 const f=fixture();await provisionAgentEns(f.job,f.deps,f.save);
 assert.deepEqual(f.sent,['registration','resolver','attachment','address']);assert.deepEqual(f.verified,f.sent);
 assert.equal(agentEnsName('Research'),'research.memoryseal.eth');
 assert.throws(()=>agentEnsName('research.other'),/one ENS label/);
});
test('receipt timeout resumes the same hash without sending registration twice',async()=>{
 const f=fixture();f.deps.wait=async()=>{throw Error('timeout');};
 await assert.rejects(provisionAgentEns(f.job,f.deps,f.save),/timeout/);
 f.deps.wait=async()=>{};await provisionAgentEns(f.job,f.deps,f.save);
 assert.deepEqual(f.sent,['registration','resolver','attachment','address']);
});
test('ambiguous wallet submission never retries blindly',async()=>{
 const f=fixture();f.deps.submit=async(stage,job,before)=>{before();throw Error('disconnected');};
 await assert.rejects(provisionAgentEns(f.job,f.deps,f.save),/disconnected/);
 await assert.rejects(provisionAgentEns(f.job,f.deps,f.save),/did not return/);
});
test('explicit wallet rejection and failed simulation can be retried',async()=>{
 for(const sending of [true,false]){
 const f=fixture();const original=f.deps.submit;
 f.deps.submit=async(stage,job,before)=>{if(sending)before();throw Object.assign(Error('rejected'),sending?{code:4001}:{});};
 await assert.rejects(provisionAgentEns(f.job,f.deps,f.save),/rejected/);assert.equal(f.job.registration,undefined);
 f.deps.submit=original;await provisionAgentEns(f.job,f.deps,f.save);assert.equal(f.sent.length,4);
 }
});
test('wrong parent owner, missing registry or registrar role prevents transactions',async()=>{
 for(const state of [{parentOwner:agentAddress,registry,canRegister:true},{parentOwner:owner,registry:'0x'+'0'.repeat(40),canRegister:true},{parentOwner:owner,registry,canRegister:false}]){
 const f=fixture();f.deps.inspect=async()=>state;await assert.rejects(provisionAgentEns(f.job,f.deps,f.save));assert.equal(f.sent.length,0);
 }
});
test('verification failure stops later transactions and resolution mismatch prevents success',async()=>{
 const f=fixture();f.deps.verify=async()=>({matches:false});await assert.rejects(provisionAgentEns(f.job,f.deps,f.save),/verification failed/);assert.deepEqual(f.sent,['registration']);
 const g=fixture();g.deps.resolve=async()=>({matches:false});await assert.rejects(provisionAgentEns(g.job,g.deps,g.save),/does not resolve/);
});
