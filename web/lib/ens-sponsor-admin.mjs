import {checkEnsWallet} from "./ens-wallet-check.mjs";
import {createPublicClient,createWalletClient,custom,parseAbi,encodeFunctionData,toHex,keccak256,stringToHex,zeroAddress} from 'viem';
import {packetToBytes,normalize} from 'viem/ens';
import {sepolia} from 'viem/chains';
const helper='0xd453e5bdb62cc3bea84341b1e306319c8ffd7dfe';
const factory='0xda70306c98e97ece36f997a21368e53298572991';
const implementation='0x9bd8a88719068d09ecee662f36c0e3856708366a';
const helperAbi=parseAbi(['function findExactOwner(bytes) view returns (address)','function findExactRegistry(bytes) view returns (address)','function findParentRegistry(bytes) view returns (address)','function findCanonicalRegistry(bytes) view returns (address)']);
const factoryAbi=parseAbi(['function deployProxy(address,uint256,bytes) returns (address)','function verifyContract(address) view returns (address)']);
const registryAbi=parseAbi(['function initialize((address account,uint256 roleBitmap)[] grants)','function setParent(address,string)','function setSubregistry(uint256,address)','function hasRootRoles(uint256,address) view returns (bool)']);
const eq=(a,b)=>a?.toLowerCase()===b?.toLowerCase();
export async function configureSponsor(wallet,owner,config,job,save,progress) {
 const transport=custom(wallet),client=createPublicClient({chain:sepolia,transport});
 const signer=createWalletClient({chain:sepolia,transport,account:owner});
 const check=()=>checkEnsWallet(wallet,owner);
 await check();
 const parent=normalize(config.parent),encoded=toHex(packetToBytes(parent));
 const read=fn=>client.readContract({address:helper,abi:helperAbi,functionName:fn,args:[encoded]});
 if(!eq(await read('findExactOwner'),owner))throw Error('Only the memoryseal.eth owner can perform this one-time setup.');
 const containing=await read('findParentRegistry');
 const current=await read('findExactRegistry');
 if(!eq(current,zeroAddress)&&!eq(current,job.registry))throw Error('Parent already has a subregistry. Grant its registrar role to the configured signer instead; this flow will not replace it.');
 const salt=BigInt(job.salt);
 const init=encodeFunctionData({abi:registryAbi,functionName:'initialize',args:[[{account:owner,roleBitmap:BigInt('0x'+'11'.repeat(32))},{account:config.registrar,roleBitmap:1n}]]});
 for(const stage of ['deploy','parent','attach']){
  progress(stage);await check();
  if(job[stage]==='uncertain')throw Error('A submission returned no hash. Check wallet activity before continuing.');
  const call=stage==='deploy'?{address:factory,abi:factoryAbi,functionName:'deployProxy',args:[implementation,salt,init]}:
    stage==='parent'?{address:job.registry,abi:registryAbi,functionName:'setParent',args:[containing,parent.split('.')[0]]}:
    {address:containing,abi:registryAbi,functionName:'setSubregistry',args:[BigInt(keccak256(stringToHex(parent.split('.')[0]))),job.registry]};
  if(!job[stage]){
   const {request,result}=await client.simulateContract({...call,account:owner});
   if(stage==='deploy')job.registry=result;
   job[stage]='uncertain';save({...job});
   try{job[stage]=await signer.writeContract(request);save({...job});}
   catch(error){let e=error;while(e&&e.code!==4001&&e.name!=='UserRejectedRequestError')e=e.cause;if(e){delete job[stage];save({...job});}throw error;}
  }
  const receipt=await client.waitForTransactionReceipt({hash:job[stage],timeout:60000});
  const tx=await client.getTransaction({hash:job[stage]});
  const block=await client.getBlock({blockNumber:receipt.blockNumber});
  if(receipt.status!=='success'||!eq(block.hash,receipt.blockHash)||!eq(tx.from,owner)||!eq(tx.to,call.address)||!eq(tx.input,encodeFunctionData(call)))throw Error('Setup transaction failed verification.');
  if(stage==='deploy'){
   const actual=await client.readContract({address:factory,abi:factoryAbi,functionName:'verifyContract',args:[job.registry]});
   if(!eq(actual,implementation))throw Error('Unexpected registry implementation.');
  }
 }
 const canonical=await read('findCanonicalRegistry');
 if(!eq(canonical,job.registry))throw Error('Parent registry is not canonical yet. Resume to check again.');
 const allowed=await client.readContract({address:canonical,abi:registryAbi,functionName:'hasRootRoles',args:[1n,config.registrar]});
 if(!allowed)throw Error('Registrar role missing.');
 return canonical;
}
