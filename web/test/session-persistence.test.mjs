import assert from 'node:assert/strict';
import {test} from 'node:test';

// Reload the module to simulate losing all in-memory state on a page refresh.
let reload = 0;
const fresh = () => import(`../lib/browser-session.mjs?reload=${++reload}`);
test('tab session survives refresh, stays scoped, expires and clears on logout', async () => {
  const originals = {fetch: globalThis.fetch, location: globalThis.location, storage: globalThis.sessionStorage};
  const values = new Map();
  globalThis.sessionStorage = {getItem:k=>values.get(k) || null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  globalThis.location = {origin:'https://memoryseal.test'};
  const args = {account:'0xabc',api:'https://gateway.test',audience:'test',path:'/agents'};
  let prompts = 0, rejected = false;
  const wallet = {request: async()=>{prompts++;return 'signature';}};
  globalThis.fetch = async (url, options={}) => {
    if (url.endsWith('/auth/challenge')) return Response.json({challenge:'nonce',issued_at:'now',sign_before:'later',
      message:'Sign in to MemorySeal\n\nWebsite: https://memoryseal.test\nWallet: 0xabc\nGateway audience: test\n\nAllow this browser to read your workspace for 30 minutes.\nThis does not authorize transfers or permission changes.\n\nIssued at: now\nSign before: later\nNonce: nonce'});
    if(url.endsWith('/auth/session')) return Response.json({token:'read-only-token',expires_at:Date.now()/1000+1800});
    if(url.endsWith('/auth/logout')) return Response.json({ok:true});
    assert.equal(options.headers.Authorization,'Bearer read-only-token');
    return Response.json(rejected ? {detail:'revoked'} : {agents:[]},{status:rejected?401:200});
  };
  try {
    const first = await fresh();
    await first.browserRead({...args,wallet});
    assert.equal(prompts,1);
    const refreshed = await fresh();
    assert.equal(refreshed.hasBrowserSession(args),true);
    for(const override of [{account:'0xdef'},{api:'https://other.test'},{audience:'other'}]) {
      assert.equal(refreshed.hasBrowserSession({...args,...override}),false);
      await assert.rejects(refreshed.browserRead({...args,...override,wallet,allowLogin:false}),/Session expired/);
    }
    assert.deepEqual(await refreshed.browserRead({...args,wallet,allowLogin:false}),{agents:[]});
    assert.equal(prompts,1);
    rejected=true;
    await assert.rejects(refreshed.browserRead({...args,wallet,allowLogin:false}),/revoked/);
    assert.equal((await fresh()).hasBrowserSession(args),false);
    assert.equal(prompts,1);
    rejected=false;
    await refreshed.browserRead({...args,wallet});
    const stored=JSON.parse(values.get('memoryseal.browser-sessions.v1'));
    Object.values(stored).forEach(v=>v.expires_at=Date.now()/1000-1);
    values.set('memoryseal.browser-sessions.v1',JSON.stringify(stored));
    const expired=await fresh();
    assert.equal(expired.hasBrowserSession(args),false);
    await assert.rejects(expired.browserRead({...args,wallet,allowLogin:false}),/Session expired/);
    await expired.browserRead({...args,wallet});
    expired.clearBrowserSessions();
    assert.equal((await fresh()).hasBrowserSession(args),false);
    assert.equal(values.has('memoryseal.browser-sessions.v1'),false);
    // Browsers that block storage still support in-memory sessions.
    globalThis.sessionStorage = {getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
    const blocked=await fresh();
    await blocked.browserRead({...args,wallet});
    assert.equal(blocked.hasBrowserSession(args),true);
    blocked.clearBrowserSessions();
  } finally {
    globalThis.fetch=originals.fetch;globalThis.location=originals.location;
    if(originals.storage === undefined) delete globalThis.sessionStorage;else globalThis.sessionStorage=originals.storage;
  }
});
