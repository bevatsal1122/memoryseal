import {test} from 'node:test';
import assert from 'node:assert/strict';
import {generateIdentity,wrapKey,unwrapKey,newKey,keyFingerprint,sha256,unb64,sealRecord,openRecord,rewrapRecord,exportIdentity,importIdentity} from '../dist/index.js';

test('client keys wrap only for the pinned identity; payloads bind scope, ID, epoch and commitment',async()=>{
 const alice=await generateIdentity(),bob=await generateIdentity(),key=newKey();
 const address='0x'+'1'.repeat(40),scope={id:crypto.randomUUID(),owner_address:address,namespace:'research café',active_version:1};
 const fp=await sha256(unb64(alice.publicKey));
 const wrapped=await wrapKey(key,alice.publicKey,fp,scope.id,1,address);
 assert.deepEqual(await unwrapKey(alice,wrapped,scope.id,1,address,await keyFingerprint(key)),key);
 await assert.rejects(unwrapKey(bob,wrapped,scope.id,1,address,await keyFingerprint(key)));
 await assert.rejects(wrapKey(key,bob.publicKey,fp,scope.id,1,address));
 await assert.rejects(unwrapKey(alice,wrapped,scope.id,2,address,await keyFingerprint(key)));
 const record=await sealRecord(scope,key,'Private observation 🔐');
 assert.equal((await openRecord(scope,key,record)).content,'Private observation 🔐');
 for(const mutated of [{...record,id:crypto.randomUUID()},{...record,key_version:2},{...record,commitment:'0'.repeat(64)}])await assert.rejects(openRecord(scope,key,mutated));
 await assert.rejects(openRecord({...scope,owner_address:'0x'+'2'.repeat(40)},key,record));
 const key2=newKey(),migrated=await rewrapRecord({...scope,active_version:2},key,key2,record);
 assert.equal(migrated.commitment,record.commitment);
 assert.equal((await openRecord(scope,key2,migrated)).content,'Private observation 🔐');
 await assert.rejects(openRecord(scope,key,migrated));
 const backup=await exportIdentity(alice,'a sufficiently long passphrase');
 assert.equal((await importIdentity(backup,'a sufficiently long passphrase')).publicKey,alice.publicKey);
 await assert.rejects(importIdentity(backup,'wrong long passphrase'));
});
