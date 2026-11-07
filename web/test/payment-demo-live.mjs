// Opt-in protected-only smoke test. Writes isolated gateway records and publishes proof.
// The fixed 0.05 ETH request exceeds the server's protected limit; no transfer is submitted.
const origin=process.env.MEMORYSEAL_DEMO_FRONTEND || 'http://localhost:3000';
const response=await fetch(new URL('/api/demo/run',origin),{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify({mode:'protected',runId:crypto.randomUUID()}),signal:AbortSignal.timeout(240000)});
if(!response.ok)throw new Error(await response.text());
const reader=response.body.getReader(),decoder=new TextDecoder();
let buffer='',result;
function receive(line) {
 const message=JSON.parse(line);
 if(message.type==='event')console.log(`${message.value.actor}: ${message.value.title}`);
 if(message.type==='error')throw new Error(message.value);
 if(message.type==='result')result=message.value;
}
while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});let end;while((end=buffer.indexOf('\n'))!==-1){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(line)receive(line);}if(done)break;}
if(buffer.trim())receive(buffer);
if(!result || result.paid || result.memoryVisible || result.transaction?.state!=='blocked' || result.transaction?.hash)throw new Error('Protected demo invariant failed');
console.log(JSON.stringify(result,null,2));
