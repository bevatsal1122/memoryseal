import {generatePrivateKey, privateKeyToAccount} from 'viem/accounts';
import {MemorySealClient} from '../../sdk/typescript/dist/index.js';
import {runPaymentDemo} from './payment-demo.mjs';
import {cachedRun,finishRun,sendDemoPayment} from './sepolia-demo-server.mjs';

export async function executeDemoRun({run,wallet,frontendOrigin,signal,emit}) {
    const cached=await cachedRun(run.runId);
    if(cached) {emit('result',cached);return;}
    // Fetch only our fixed local invoice. The client cannot select arbitrary URLs or recipients.
    const source=new URL('/demo/supplier.html',frontendOrigin);
    emit('stage','load');
    const response=await fetch(source,{cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error('Supplier page unavailable.');
    const html=await response.text();
    const read=key=>html.match(new RegExp(`data-${key}>([^<]+)<`))?.[1];
    const invoice={id:read('invoice'),payee:read('payee'),amount:Number(read('amount')),instruction:read('instruction'),url:source.href};
    if(!invoice.instruction || invoice.amount!==0.05)throw new Error('Expected the 0.05 ETH demo invoice.');
    const gateway=process.env.MEMORYSEAL_DEMO_GATEWAY_URL || process.env.NEXT_PUBLIC_GATEWAY_URL || 'http://localhost:8000';
    const audience=process.env.MEMORYSEAL_REQUEST_AUDIENCE || process.env.NEXT_PUBLIC_GATEWAY_AUDIENCE || 'memoryseal-local';
    const make=(account=privateKeyToAccount(generatePrivateKey()))=>new MemorySealClient({address:account.address,signMessage:raw=>account.signMessage({message:{raw}})},gateway,audience,(url,options)=>fetch(url,{...options,signal:AbortSignal.timeout(120000)}));
    const result=await runPaymentDemo({mode:run.mode,invoice,clients:{owner:make(),browser:make(),finance:make(wallet.account)},
     emit:event=>emit('event',event),onMemory:memory=>emit('memory',memory),
     onStage:async stage=>{signal?.throwIfAborted();emit('stage',stage);await new Promise(resolve=>setTimeout(resolve,350));},
     payment:{send:async args=>{
      signal?.throwIfAborted();
      // Once broadcast begins it must be journaled even if the browser disconnects.
      return sendDemoPayment({...args,runId:run.runId,onSubmitted:transaction=>emit('memory',{transaction})});
     }},
    });
    await finishRun(run.runId,result); emit('result',result);

}
