import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Wallet} from '../../../contracts/node_modules/ethers/lib.esm/index.js';
import {MemorySealClient,generateIdentity,wrapKey,newKey,keyFingerprint,sha256,unb64,sealRecord,openRecord} from '../dist/index.js';

test('signed HTTP: team isolation, ciphertext sharing, rotation, stale writes and revocation',{skip:!process.env.MEMORYSEAL_TEST_GATEWAY},async()=>{
 const wallets=Array.from({length:4},()=>Wallet.createRandom());
 const [owner,admin,agent,auditor]=wallets.map(w=>new MemorySealClient({address:w.address,signMessage:m=>w.signMessage(m)},process.env.MEMORYSEAL_TEST_GATEWAY));
 const org=await owner.createOrganization('Research team');
 await owner.setMember(org.id,admin.signer.address,'admin',1);
 await owner.setMember(org.id,auditor.signer.address,'auditor',2);
 await assert.rejects(auditor.registerOrganizationAgent(org.id,agent.signer.address));
 await assert.rejects(admin.setMember(org.id,auditor.signer.address,'admin',3));
 const a=await admin.registerOrganizationAgent(org.id,agent.signer.address);
 const write=await admin.grantOrganization(org.id,{agent_id:a.id,operation:'write',resource:'secret'});
 const read=await admin.grantOrganization(org.id,{agent_id:a.id,operation:'read',resource:'secret'});
 assert.equal((await agent.agentAccess()).agents[0].id,a.id);
 const ids=[await generateIdentity(),await generateIdentity()];
 await owner.registerEncryptionIdentity(ids[0].publicKey);await agent.registerEncryptionIdentity(ids[1].publicKey);
 const scope={id:crypto.randomUUID(),owner_address:owner.signer.address.toLowerCase(),namespace:'secret',active_version:1};
 async function epoch(s){const key=newKey();const envelopes={};for(const [c,i] of [[owner,ids[0]],[agent,ids[1]]]){const address=c.signer.address.toLowerCase();envelopes[address]=await wrapKey(key,i.publicKey,await sha256(unb64(i.publicKey)),s.id,s.active_version,address);}return {key,envelopes,fingerprint:await keyFingerprint(key)}}
 const first=await epoch(scope);await owner.createVault(scope,first.fingerprint,first.envelopes);
 await assert.rejects(agent.writeMemory({agent_id:a.id,namespace:'secret',content:'must never go to inference',source_type:'agent'}),e=>e.status===409);
 const key=await agent.vaultKey(scope,ids[1]);
 const payload={...await sealRecord(scope,key,'CLIENT_ONLY_SECRET_789'),agent_id:a.id};
 await agent.submitVault(scope,payload);await agent.submitVault(scope,payload);
 const events=await owner.vaultEvents(scope,payload.id);assert.equal(events.events.length,1);
 assert.equal(events.events[0].event_type,'vault_written');
 assert.equal((await owner.vaultEventAction(scope,payload.id,events.events[0].id,'publish')).state,'not_configured');
 await assert.rejects(agent.vaultEvents(scope,payload.id));
 assert.equal((await agent.vaultRecords(scope)).records.length,0);
 const row=(await owner.vaultRecords(scope)).records[0];
 assert.equal((await openRecord(scope,await owner.vaultKey(scope,ids[0]),row)).content,'CLIENT_ONLY_SECRET_789');
 await assert.rejects(agent.reviewVault(scope,row,true));
 await owner.reviewVault(scope,row,true);
 assert.equal((await agent.vaultRecords(scope)).records.length,1);
 // An untrusted gateway cannot substitute a key version or envelope unnoticed.
 const altered=new MemorySealClient(owner.signer,process.env.MEMORYSEAL_TEST_GATEWAY,'memoryseal-local',async(url,options)=>{
  const response=await fetch(url,options);const body=await response.json();
  if(String(url).includes('/epochs/')) body.manifest[5]='0'.repeat(64);
  return new Response(JSON.stringify(body),{status:response.status,headers:{'Content-Type':'application/json'}});
 });
 await assert.rejects(altered.vaultKey(scope,ids[0]),/Invalid owner-signed/);

 await assert.rejects(owner.reviewVault(scope,row,false),e=>e.status===409);
 const current=(await owner.vaultRecords(scope)).records[0];
 await assert.rejects(owner.request('POST',`/vault/namespaces/${scope.id}/records/${current.id}/rewrap`,{
  expected_revision:row.revision,key_version:1,envelope:current.envelope}),e=>e.status===409);

 // Batch changes are atomic and remain owner-only; a missing second row rolls back the first.
 const batchPath=`/vault/namespaces/${scope.id}/rewrap-batch`;
 const batchRow={id:current.id,expected_revision:current.revision,key_version:1,envelope:current.envelope};
 await assert.rejects(agent.request('POST',batchPath,{records:[batchRow]}));
 await assert.rejects(owner.request('POST',batchPath,{records:[batchRow,{...batchRow,id:crypto.randomUUID()}]}),e=>e.status===404);
 assert.equal((await owner.vaultRecords(scope)).records[0].revision,current.revision);
 assert.equal((await owner.request('POST',batchPath,{records:[batchRow]})).migrated,1);
 assert.equal((await owner.request('POST',batchPath,{records:[batchRow]})).migrated,0);
 const nextScope={...scope,active_version:2},second=await epoch(nextScope);
 await owner.rotateVault(scope,second.fingerprint,second.envelopes);
 await assert.rejects(owner.rotateVault(scope,second.fingerprint,second.envelopes),e=>e.status===409);
 const stale={...await sealRecord(scope,key,'stale write'),agent_id:a.id};
 await assert.rejects(agent.submitVault(scope,stale),e=>e.status===409);
 const newPayload={...await sealRecord(nextScope,await agent.vaultKey(nextScope,ids[1]),'concurrent new write'),agent_id:a.id};
 await agent.submitVault(nextScope,newPayload);
 const progress=await owner.migrateVaultBatch(nextScope,ids[0]);assert.equal(progress.status.remaining,0);
 const migrated=(await owner.vaultRecords(nextScope)).records.find(r=>r.id===payload.id);
 assert.equal(migrated.commitment,payload.commitment);assert.equal(migrated.status,'released');
 assert.equal((await openRecord(nextScope,second.key,migrated)).content,'CLIENT_ONLY_SECRET_789');
 await agent.submitVault(scope,payload); // original retry still identifies the migrated record
 await owner.setMember(org.id,admin.signer.address,'remove',3);
 await assert.rejects(admin.revokeOrganization(org.id,'capability',read.id));
 await owner.revokeOrganization(org.id,'capability',read.id);
 await assert.rejects(agent.vaultRecords(nextScope));
 await owner.revokeOrganization(org.id,'capability',write.id);
 await assert.rejects(agent.vaultKey(scope,ids[1],1));
 await assert.rejects(auditor.organization(crypto.randomUUID()));
});
