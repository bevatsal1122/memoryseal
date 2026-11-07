// Two-phase transaction adapter: prepare signs but NEVER broadcasts. Python
// durably stores the exact signed bytes before calling broadcast/reconcile.
import {createPublicClient,createWalletClient,http,custom,keccak256,parseAbi,stringToHex,zeroAddress} from 'viem';
import {privateKeyToAccount} from 'viem/accounts';
import {sepolia} from 'viem/chains';
import {normalize} from 'viem/ens';
import {observeSubnameRegistry,verifyOwnedSubname,attachAgentResolver,verifyResolverAttachment,setAgentSubnameRecord,verifyAgentRecordWrite,observeAgentAddress} from './identity.mjs';
import {deployAgentResolver,verifyAgentResolver} from './resolver.mjs';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {action,job,raw,hash}=JSON.parse(input);
const publicClient=createPublicClient({chain:sepolia,transport:http(process.env.MEMORYSEAL_ENS_RPC_URL,{timeout:15000,retryCount:0})});
const account=privateKeyToAccount(process.env.MEMORYSEAL_ENS_REGISTRAR_PRIVATE_KEY);
const feeCap=BigInt(process.env.MEMORYSEAL_ENS_REGISTRATION_MAX_FEE_GWEI||20)*1000000000n;
const same=(a,b)=>a?.toLowerCase()===b?.toLowerCase();
const output=x=>process.stdout.write(JSON.stringify(x,(_,v)=>typeof v==='bigint'?v.toString():v));
try {
 if(await publicClient.getChainId()!==11155111)throw Error('wrong network');
 if(action==='status') {output({address:account.address,chainId:11155111});}
 else if(action==='broadcast') {
  if(keccak256(raw)!==hash)throw Error('transaction hash mismatch');
  let receipt;
  try {receipt=await publicClient.getTransactionReceipt({hash});}catch(e){if(e.name!=='TransactionReceiptNotFoundError')throw e;}
  if(!receipt){await publicClient.sendRawTransaction({serializedTransaction:raw}).catch(()=>{});output({state:'pending'});}
  else {
   const block=await publicClient.getBlock({blockNumber:receipt.blockNumber});
   if(!same(block.hash,receipt.blockHash))throw Error('reorganized');
   output({state:receipt.status==='success'?'confirmed':'reverted'});
  }
 } else if(action==='verify') {
  const common={publicClient,expectedChainId:11155111,parentName:job.parentName,label:job.label,owner:account.address};
  let result;
  if(job.stage===0)result=await verifyOwnedSubname({...common,...job.registration});
  if(job.stage===1)result=await verifyAgentResolver({...common,...job.resolver});
  if(job.stage===2)result=await verifyResolverAttachment({...common,...job.attachment});
  if(job.stage===3){
   result=await verifyAgentRecordWrite({...common,name:job.name,agentAddress:job.agentAddress,writer:account.address,...job.address});
   if(result.matches)result=await observeAgentAddress(publicClient,{name:job.name,expectedAddress:job.agentAddress,expectedChainId:11155111});
  }
  if(result?.matches===false)throw Error('record mismatch');output({verified:true});
 } else if(action==='prepare') {
  if(normalize(job.parentName)!==normalize(process.env.MEMORYSEAL_ENS_PARENT||'memoryseal.eth'))throw Error('wrong parent');
  let serialized;
  // Viem signs locally; intercept only the send call so preparation cannot broadcast.
  const transport=custom({request:async args=>{
   if(args.method==='eth_sendRawTransaction'){serialized=args.params[0];return keccak256(serialized);}
   return publicClient.request(args);
  }});
  const estimate=await publicClient.estimateFeesPerGas();
  if(estimate.maxFeePerGas>feeCap)throw Error('fee cap exceeded');
  const baseWallet=createWalletClient({chain:sepolia,account,transport});
  const walletClient={...baseWallet,writeContract:args=>baseWallet.writeContract({...args,maxFeePerGas:feeCap,maxPriorityFeePerGas:estimate.maxPriorityFeePerGas,nonce:undefined})};
  const args={publicClient,walletClient,parentName:job.parentName,label:job.label,expectedChainId:11155111};
  let result;
  if(job.stage===0){
   const state=await observeSubnameRegistry(publicClient,{...args,account:account.address});
   if(same(state.registry,zeroAddress)||!state.canRegister||same(state.parentOwner,zeroAddress))throw Error('registrar not authorized');
   const abi=parseAbi(['function getStatus(uint256) view returns (uint8)','function getExpiry(uint256) view returns (uint64)','function register(string,address,address,address,uint256,uint64) returns (uint256)']);
   const id=BigInt(keccak256(stringToHex(job.label)));
   const status=await publicClient.readContract({address:state.registry,abi,functionName:'getStatus',args:[id]});
   const expiry=await publicClient.readContract({address:state.registry,abi,functionName:'getExpiry',args:[id]});
   if(Number(status)!==0||expiry!==0n)throw Error('name unavailable');
   const roles=(1n<<16n)|(1n<<20n)|(1n<<24n)|(1n<<156n);
   const {request}=await publicClient.simulateContract({address:state.registry,abi,functionName:'register',args:[job.label,account.address,zeroAddress,zeroAddress,roles,BigInt(job.expiry)],account});
   const transactionHash=await walletClient.writeContract(request);
   result={registry:state.registry,expiry:job.expiry,owner:account.address,transactionHash};
  }
  if(job.stage===1)result=await deployAgentResolver({...args,salt:job.salt});
  if(job.stage===2)result=await attachAgentResolver({...args,deployment:job.resolver});
  if(job.stage===3)result=await setAgentSubnameRecord({...args,agentAddress:job.agentAddress});
  if(!serialized||keccak256(serialized)!==result.transactionHash)throw Error('missing signed transaction');
  output({result,raw:serialized,hash:result.transactionHash});
 } else throw Error('unknown action');
} catch {process.stderr.write('ENS sponsor operation failed');process.exitCode=1;}
