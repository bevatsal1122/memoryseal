// Opt-in gateway smoke test. Creates isolated demo identities and one external memory.
import {readFile} from 'node:fs/promises';
import {generatePrivateKey, privateKeyToAccount} from 'viem/accounts';
import {MemorySealClient} from '../../sdk/typescript/dist/index.js';
import {runPaymentDemo} from '../lib/payment-demo.mjs';
const url = process.env.MEMORYSEAL_DEMO_GATEWAY || 'http://localhost:8000';
const audience = process.env.MEMORYSEAL_DEMO_AUDIENCE || 'memoryseal-local';
const html = await readFile(new URL('../public/demo/supplier.html',import.meta.url),'utf8');
const read = key => html.match(new RegExp(`data-${key}>([^<]+)<`))?.[1];
const invoice = {id:read('invoice'),payee:read('payee'),amount:Number(read('amount').replaceAll(',','')),instruction:read('instruction'),url:'http://localhost:3000/demo/supplier.html'};
const make = () => {const account=privateKeyToAccount(generatePrivateKey());return new MemorySealClient({address:account.address,signMessage:raw=>account.signMessage({message:{raw}})},url,audience,(url,init)=>fetch(url,{...init,signal:AbortSignal.timeout(120000)}));};
const result = await runPaymentDemo({mode:'protected',invoice,clients:{owner:make(),browser:make(),finance:make()},emit:event=>console.log(`${event.actor}: ${event.title}`)});
console.log(JSON.stringify(result,null,2));
if(result.paid || result.memoryVisible) process.exitCode=1;
