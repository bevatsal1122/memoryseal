// Server-only: never import this module from a client component.
import {readFile, writeFile, mkdir, rename, unlink, open} from 'node:fs/promises';
import {resolve, basename} from 'node:path';
import {createPublicClient, http, isAddress, parseEther, formatEther, keccak256} from 'viem';
import {privateKeyToAccount} from 'viem/accounts';
import {sepolia} from 'viem/chains';
export const CHAIN_ID = 11155111;
export const VALUE = parseEther('0.05');
export const LIMIT = parseEther('0.005');
export const directory = process.env.MEMORYSEAL_DEMO_DATA_DIR || resolve(basename(process.cwd()) === 'web' ? '..' : '.', '.local-demo');

export function assertLocalRequest(request) {
 const url = new URL(request.url);
 if (!['localhost','127.0.0.1','[::1]'].includes(url.hostname)) throw new Error('The signing demo is available on localhost only.');
 const origin = request.headers.get('origin');
 if (request.method !== 'GET' && origin !== url.origin) throw new Error('Same-origin request required.');
 if (origin && origin !== url.origin) throw new Error('Cross-origin request rejected.');
 if (request.headers.get('sec-fetch-site') === 'cross-site') throw new Error('Cross-site request rejected.');
}
export async function config() {
 let value;
 if(process.env.MEMORYSEAL_DEMO_PRIVATE_KEY) {
  if(!process.env.MEMORYSEAL_DEMO_DATA_DIR)throw new Error('Set a persistent MEMORYSEAL_DEMO_DATA_DIR for hosted signing.');
  await mkdir(directory,{recursive:true,mode:0o700});
  value={privateKey:process.env.MEMORYSEAL_DEMO_PRIVATE_KEY,recipient:process.env.MEMORYSEAL_DEMO_RECIPIENT,rpcUrl:process.env.MEMORYSEAL_DEMO_RPC_URL || 'https://ethereum-sepolia-rpc.publicnode.com'};
 } else {
  try {value=JSON.parse(await readFile(resolve(directory,'wallet.json'),'utf8'));} catch {throw new Error('Run node web/scripts/init-sepolia-demo.mjs first.');}
 }
 const account=privateKeyToAccount(value.privateKey);
 const rpc=new URL(value.rpcUrl);
 if(rpc.protocol!=='https:' && !(['localhost','127.0.0.1'].includes(rpc.hostname) && rpc.protocol==='http:')) throw new Error('Invalid demo RPC configuration.');
 const recipient=value.recipient;
 if(recipient && (!isAddress(recipient) || /^0x0{40}$/i.test(recipient) || recipient.toLowerCase()===account.address.toLowerCase())) throw new Error('Configure a different, valid receiving address.');
 const client=createPublicClient({chain:sepolia,transport:http(value.rpcUrl,{timeout:15000,retryCount:1})});
 return {account,recipient,client};
}
export async function checkedChain(client) {
 if(await client.getChainId() !== CHAIN_ID) throw new Error('RPC is not Ethereum Sepolia. Sending is disabled.');
}
async function load(name) {try{return JSON.parse(await readFile(resolve(directory,name),'utf8'));}catch(e){if(e.code==='ENOENT')return null;throw e;}}
async function save(name,data) {
 const file=resolve(directory,name), temp=`${file}.${crypto.randomUUID()}.tmp`;
 await writeFile(temp,JSON.stringify(data,null,2),{mode:0o600}); await rename(temp,file);
}
export async function transactionStatus(client,record) {
 if(!record)return null;
 if(record.state==='confirmed'||record.state==='reverted')return record;
 try {
  const receipt=await client.getTransactionReceipt({hash:record.hash});
  return {...record,state:receipt.status==='success'?'confirmed':'reverted',blockNumber:receipt.blockNumber.toString()};
 } catch(error) {
  if(error.name==='TransactionReceiptNotFoundError')return record;
  throw error;
 }
}
export async function walletStatus() {
 const {account,recipient,client}=await config();
 await checkedChain(client);
 const balance=await client.getBalance({address:account.address});
 let last=await load('last-transaction.json');
 if(last) {last=await transactionStatus(client,last); await save('last-transaction.json',last);}
 let locked=false;
 try {await readFile(resolve(directory,'run.lock'));locked=true;} catch(e){if(e.code!=='ENOENT')throw e;}
 return {address:account.address,recipient,chainId:CHAIN_ID,balance:formatEther(balance),funded:balance>VALUE,configured:!!recipient,locked,last:last?{hash:last.hash,state:last.state,recipient:last.recipient,amount:'0.05',runId:last.runId}:null};
}
export async function acquireRun() {
 await mkdir(directory,{recursive:true,mode:0o700});
 let file;
 try{file=await open(resolve(directory,'run.lock'),'wx',0o600);}catch(e){if(e.code==='EEXIST')throw new Error('A run is already active or was interrupted. Check its transaction before clearing the local run lock.');throw e;}
 await file.writeFile(JSON.stringify({pid:process.pid,started:new Date().toISOString()})); await file.close();
 return async()=>{await unlink(resolve(directory,'run.lock'));};
}
export function validateRun(value) {
 if(!value || !['baseline','protected'].includes(value.mode) || !/^[a-f0-9-]{36}$/i.test(value.runId || '')) throw new Error('Invalid demo run.');
 return {mode:value.mode,runId:value.runId};
}
export async function cachedRun(runId) {return load(`run-${runId}.json`);}
export async function finishRun(runId,result) {await save(`run-${runId}.json`,result);}

export async function sendDemoPayment({runId,mode,amount,allowed,visible,onSubmitted}, services = {config, load, save}) {
 const {config: getConfig, load: readRecord, save: writeRecord} = services;
 // No arbitrary destination, calldata, chain, or value can come from the browser/page.
 if(amount!==0.05)throw new Error('Demo payments must be exactly 0.05 Sepolia ETH.');
 if(mode==='protected' && (!allowed || !visible || VALUE>LIMIT))return {state:'blocked',paid:false};
 if(mode!=='baseline' && mode!=='protected')throw new Error('Invalid payment mode.');
 const {account,recipient,client}=await getConfig();
 if(!recipient)throw new Error('Receiving address is not configured.');
 await checkedChain(client);
 const previous=await readRecord('last-transaction.json');
 if(previous) {
  const checked=await transactionStatus(client,previous);
  await writeRecord('last-transaction.json',checked);
  if(previous.runId===runId) return {state:checked.state,hash:checked.hash,paid:checked.state==='confirmed'};
  if(!['confirmed','reverted'].includes(checked.state))throw new Error('An earlier payment is still pending or uncertain. Check it before starting another payment.');
 }
 const gas=await client.estimateGas({account,to:recipient,value:VALUE});
 const fees=await client.estimateFeesPerGas();
 const balance=await client.getBalance({address:account.address});
 if(balance<VALUE+gas*fees.maxFeePerGas)throw new Error('Fund the demo wallet with 0.05 Sepolia ETH plus gas.');
 const nonce=await client.getTransactionCount({address:account.address,blockTag:'pending'});
 const serializedTransaction=await account.signTransaction({chainId:CHAIN_ID,type:'eip1559',to:recipient,value:VALUE,gas,nonce,maxFeePerGas:fees.maxFeePerGas,maxPriorityFeePerGas:fees.maxPriorityFeePerGas});
 const hash=keccak256(serializedTransaction);
 const record={runId,hash,recipient,nonce,state:'prepared',createdAt:new Date().toISOString()};
 // Journal the hash BEFORE broadcast: interrupted/repeated requests cannot silently pay twice.
 await writeRecord('last-transaction.json',record);
 await onSubmitted?.({state:'submitting',hash});
 try {
  await client.sendRawTransaction({serializedTransaction});
  await writeRecord('last-transaction.json',{...record,state:'submitted'});
  await onSubmitted?.({state:'submitted',hash});
  const receipt=await client.waitForTransactionReceipt({hash,confirmations:1,timeout:60000});
  const state=receipt.status==='success'?'confirmed':'reverted';
  await writeRecord('last-transaction.json',{...record,state,blockNumber:receipt.blockNumber.toString()});
  return {state,hash,paid:state==='confirmed'};
 } catch {
  await writeRecord('last-transaction.json',{...record,state:'uncertain'});
  return {state:'uncertain',hash,paid:false};
 }
}
