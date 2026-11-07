import {test} from 'node:test';
import assert from 'node:assert/strict';
import {checkEnsWallet,switchEnsNetwork} from '../lib/ens-wallet-check.mjs';
const owner='0x'+'a'.repeat(40);
const wallet=(chain,accounts)=>({request:async({method})=>method==='eth_chainId'?chain:accounts});
test('checks the site RPC network, regardless of the wallet portfolio view',async()=>{
 await assert.rejects(checkEnsWallet(wallet('0x40d9',[owner]),owner),e=>e.code==='ENS_WRONG_NETWORK'&&e.message.includes('16601'));
 await checkEnsWallet(wallet('0xaa36a7',[owner]),owner);
});
test('requires the signed-in wallet account to remain authorized',async()=>{
 await assert.rejects(checkEnsWallet(wallet('0xaa36a7',[]),owner),/not connected/);
 await checkEnsWallet(wallet('0xaa36a7',['0x'+'b'.repeat(40),owner.toUpperCase()]),owner);
});
test('network switch requests Sepolia explicitly and preserves rejection',async()=>{
 let request;await switchEnsNetwork({request:async arg=>{request=arg;}});
 assert.deepEqual(request,{method:'wallet_switchEthereumChain',params:[{chainId:'0xaa36a7'}]});
 await assert.rejects(switchEnsNetwork({request:async()=>{throw Error('rejected');}}),/rejected/);
});
