import {mkdir, writeFile, readFile, chmod} from 'node:fs/promises';
import {resolve} from 'node:path';
import {generatePrivateKey, privateKeyToAccount} from 'viem/accounts';
const root = resolve(import.meta.dirname, '../..', '.local-demo');
await mkdir(root, {recursive:true, mode:0o700});
await chmod(root,0o700);
const file=resolve(root,'wallet.json');
try {
 await writeFile(file, JSON.stringify({privateKey:generatePrivateKey(),recipient:null,rpcUrl:'https://ethereum-sepolia-rpc.publicnode.com'},null,2)+'\n',{flag:'wx',mode:0o600});
} catch(error) {if(error.code!=='EEXIST')throw error;}
await chmod(file,0o600);
const wallet=JSON.parse(await readFile(file,'utf8'));
console.log(JSON.stringify({address:privateKeyToAccount(wallet.privateKey).address,chain:'Sepolia',chainId:11155111,recipient:wallet.recipient,configFile:file},null,2));
