import {generatePrivateKey, privateKeyToAccount} from 'viem/accounts';
import {MemorySealClient} from '../../sdk/typescript/dist/index.js';
import {runPaymentDemo,demoAgentNames} from './payment-demo.mjs';
import {prepareDemoEns} from './demo-ens.mjs';
import {cachedRun,finishRun,sendDemoPayment,load,save} from './sepolia-demo-server.mjs';

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
    let identity=await load('agent-identities.json');
    if(identity && (identity.gateway!==gateway || identity.finance!==wallet.account.address || identity.audience!==audience))throw new Error('Demo identity configuration changed. Restore the original gateway and finance wallet before resuming.');
    if(!identity) {
      identity={gateway,audience,finance:wallet.account.address,ownerKey:generatePrivateKey(),browserKey:generatePrivateKey(),names:demoAgentNames()};
      await save('agent-identities.json',identity);
    }
    const clients={owner:make(privateKeyToAccount(identity.ownerKey)),browser:make(privateKeyToAccount(identity.browserKey)),finance:make(wallet.account)};
    const result=await runPaymentDemo({mode:run.mode,invoice,clients,names:identity.names,
     prepareAgents: callbacks=>prepareDemoEns({...clients,names:identity.names,...callbacks}),
     emit:event=>emit('event',event),onMemory:memory=>emit('memory',memory),
     onStage:async stage=>{signal?.throwIfAborted();emit('stage',stage);const delay=run.mode==='baseline' ? (stage==='scan' ? 5000 : 1000) : 350;await new Promise(resolve=>setTimeout(resolve,delay));signal?.throwIfAborted();},
     payment:{send:async args=>{
      signal?.throwIfAborted();
      // Once broadcast begins it must be journaled even if the browser disconnects.
      return sendDemoPayment({...args,runId:run.runId,onSubmitted:transaction=>emit('memory',{transaction})});
     }},
    });
    await finishRun(run.runId,result); emit('result',result);

}
