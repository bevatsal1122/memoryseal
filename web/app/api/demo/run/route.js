import {executeDemoRun} from '../../../../lib/sepolia-demo-workflow.mjs';
import {assertLocalRequest,config,checkedChain,acquireRun,validateRun,cachedRun,finishRun,sendDemoPayment} from '../../../../lib/sepolia-demo-server.mjs';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export const maxDuration=300;
export async function POST(request) {
 let release, run, wallet;
 try {
  assertLocalRequest(request);
  run=validateRun(await request.json());
  wallet=await config(); await checkedChain(wallet.client);
  if(run.mode==='baseline'&&!wallet.recipient)throw new Error('Configure your receiving address before sending.');
  release=await acquireRun();
 } catch(error) {return Response.json({error:error.message},{status:400});}
 const encoder=new TextEncoder();
 const stream=new ReadableStream({
  async start(controller) {
   let attached=true;
   const emit=(type,value)=>{if(attached)try{controller.enqueue(encoder.encode(JSON.stringify({type,value})+'\n'));}catch{attached=false;}};
   try {
    await executeDemoRun({run,wallet,frontendOrigin:new URL(request.url).origin,signal:request.signal,emit});
   } catch(error) {emit('error',error.message || 'Demo run failed.');}
   finally {await release();try{controller.close();}catch{}}
  }
 });
 return new Response(stream,{headers:{'Content-Type':'application/x-ndjson','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
}
