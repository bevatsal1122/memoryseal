// Creates a private Railway import file without printing the wallet key.
import {readFile,writeFile,chmod} from 'node:fs/promises';
import {resolve} from 'node:path';
const root=resolve(import.meta.dirname,'../..');
const wallet=JSON.parse(await readFile(resolve(root,'.local-demo/wallet.json'),'utf8'));
if(!wallet.recipient)throw new Error('Configure the receiving address first.');
const operator=wallet.operator || wallet.recipient;
const origin=process.argv[2] || 'https://memoryseal.work';
if(new URL(origin).origin!==origin || !origin.startsWith('https://'))throw new Error('Pass the exact HTTPS frontend origin.');
const entries={MEMORYSEAL_DEMO_ENABLED:'true',MEMORYSEAL_DEMO_PRIVATE_KEY:wallet.privateKey,MEMORYSEAL_DEMO_RECIPIENT:wallet.recipient,MEMORYSEAL_DEMO_OPERATORS:operator,MEMORYSEAL_DEMO_RPC_URL:wallet.rpcUrl,MEMORYSEAL_DEMO_DATA_DIR:'/data/demo',MEMORYSEAL_DEMO_FRONTEND_ORIGIN:origin};
const file=resolve(root,'.env.railway-demo');
await writeFile(file,Object.entries(entries).map(([key,value])=>`${key}=${value}`).join('\n')+'\n',{mode:0o600});await chmod(file,0o600);
console.log(`Private Railway import file written: ${file}\nApproved operator: ${operator}\nFrontend origin: ${origin}\nNo secrets printed.`);
