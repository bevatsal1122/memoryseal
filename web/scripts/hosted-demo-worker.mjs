// Invoked only by the authenticated gateway; stdout contains public NDJSON, never keys.
import {config,checkedChain,acquireRun,validateRun,walletStatus} from '../lib/sepolia-demo-server.mjs';
import {executeDemoRun} from '../lib/sepolia-demo-workflow.mjs';
let connected=true;
process.stdout.on('error',()=>{connected=false;});
const emit=(type,value)=>{if(connected)process.stdout.write(JSON.stringify({type,value})+'\n');};
let release;
try {
 if(process.argv[2]==='status') {emit('wallet',await walletStatus());}
 else {
  let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>4096)throw new Error('Invalid run request.');}
  const run=validateRun(JSON.parse(input));
  const wallet=await config();await checkedChain(wallet.client);
  if(run.mode==='baseline'&&!wallet.recipient)throw new Error('Demo receiving address is not configured.');
  release=await acquireRun();
  await executeDemoRun({run,wallet,frontendOrigin:process.env.MEMORYSEAL_DEMO_FRONTEND_ORIGIN,emit});
 }
} catch(error) {emit('error',error.message || 'Hosted demo failed.');process.exitCode=1;}
finally {if(release)await release();}
