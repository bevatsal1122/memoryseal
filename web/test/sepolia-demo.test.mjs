import test from 'node:test';
import assert from 'node:assert/strict';
import {assertLocalRequest,sendDemoPayment,VALUE,CHAIN_ID} from '../lib/sepolia-demo-server.mjs';
const args={runId:'11111111-1111-4111-8111-111111111111',mode:'baseline',amount:0.05,allowed:true,visible:true};
function fixture({chain=CHAIN_ID,record=null,sendError=false}={}) {
 const calls=[];
 const client={getChainId:async()=>chain,getTransactionReceipt:async()=>{const e=new Error();e.name='TransactionReceiptNotFoundError';throw e;},estimateGas:async()=>21000n,estimateFeesPerGas:async()=>({maxFeePerGas:100n,maxPriorityFeePerGas:1n}),getBalance:async()=>VALUE*2n,getTransactionCount:async()=>3,sendRawTransaction:async()=>{calls.push('broadcast');if(sendError)throw new Error('lost connection');},waitForTransactionReceipt:async()=>({status:'success',blockNumber:123n})};
 const services={config:async()=>({recipient:'0x1111111111111111111111111111111111111111',client,account:{address:'0x2222222222222222222222222222222222222222',signTransaction:async tx=>{calls.push(tx);return '0x01';}}}),load:async()=>record,save:async(name,value)=>{record=value;calls.push(value.state);}};
 return {services,calls};
}
test('only local same-origin requests can access signer routes',()=>{
 assert.doesNotThrow(()=>assertLocalRequest(new Request('http://localhost:3000/api/demo/run',{method:'POST',headers:{origin:'http://localhost:3000'}})));
 assert.throws(()=>assertLocalRequest(new Request('http://localhost:3000/api/demo/run',{method:'POST',headers:{origin:'https://attacker.example'}})));
 assert.throws(()=>assertLocalRequest(new Request('https://memoryseal.work/api/demo/wallet')));
});
test('fixed Sepolia payment is journaled before broadcast and confirmed only by receipt',async()=>{
 const {services,calls}=fixture();const result=await sendDemoPayment(args,services);
 assert.equal(calls[0].chainId,11155111);assert.equal(calls[0].value,VALUE);
 assert.ok(calls.indexOf('prepared')<calls.indexOf('broadcast'));assert.equal(result.paid,true);assert.equal(result.state,'confirmed');
});
test('protected oversized payment never touches wallet or RPC even if gateway allows it',async()=>{
 const {services,calls}=fixture();assert.equal((await sendDemoPayment({...args,mode:'protected'},services)).state,'blocked');assert.equal(calls.length,0);
});
test('wrong chain cannot sign or broadcast',async()=>{
 const {services,calls}=fixture({chain:1});await assert.rejects(sendDemoPayment(args,services),/not Ethereum Sepolia/);assert.equal(calls.length,0);
});
test('pending journal prevents another transaction',async()=>{
 const {services,calls}=fixture({record:{runId:'other',state:'submitted',hash:'0x'+'a'.repeat(64)}});
 await assert.rejects(sendDemoPayment(args,services),/pending or uncertain/);assert.equal(calls.includes('broadcast'),false);
});
test('same run ID returns previous result without sending again',async()=>{
 const {services,calls}=fixture({record:{runId:args.runId,state:'confirmed',hash:'0x'+'a'.repeat(64)}});
 assert.equal((await sendDemoPayment(args,services)).paid,true);assert.equal(calls.includes('broadcast'),false);
});
test('network uncertainty is not shown as confirmed or retried',async()=>{
 const {services,calls}=fixture({sendError:true});const result=await sendDemoPayment(args,services);assert.equal(result.state,'uncertain');assert.equal(result.paid,false);assert.equal(calls.filter(c=>c==='broadcast').length,1);
});
