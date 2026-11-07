import assert from "node:assert/strict";
import { test } from "node:test";
import { gatewayOrigin, signedRequest } from "../lib/gateway.mjs";

test("gateway URL and dashboard origin enforce secure remote transport", () => {
  const local = { protocol: "http:", hostname: "localhost" };
  const remote = { protocol: "https:", hostname: "dashboard.example" };
  assert.equal(gatewayOrigin("http://localhost:8000", local), "http://localhost:8000");
  assert.equal(gatewayOrigin("https://gateway.example/", remote), "https://gateway.example");
  for (const url of [
    "http://gateway.example", "http://localhost.evil.example", "https://user:pass@gateway.example",
    "https://gateway.example/?token=secret", "https://gateway.example/#fragment", "https://gateway.example/prefix",
  ]) assert.throws(() => gatewayOrigin(url, local));
  assert.throws(() => gatewayOrigin("http://localhost:8000", remote));
  assert.throws(() => gatewayOrigin("https://gateway.example", { protocol: "http:", hostname: "dashboard.example" }));
});

test("invalid gateway is rejected before asking the wallet to sign", async () => {
  let prompted = false;
  const wallet = { request: () => { prompted = true; } };
  await assert.rejects(signedRequest({ account: "0x1", method: "GET", path: "/agents", api: "http://example.com", audience: "test", wallet }));
  assert.equal(prompted, false);
});

test("signed requests do not follow gateway redirects", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, "https://gateway.example/agents");
      assert.equal(options.redirect, "error");
      return { ok: true, json: async () => ({ agents: [] }) };
    };
    const response = await signedRequest({ account: "0x1", method: "GET", path: "/agents",
      api: "https://gateway.example/", audience: "test", wallet: { request: async () => "0xsigned" } });
    assert.deepEqual(response, { agents: [] });
  } finally { globalThis.fetch = originalFetch; }
});

test("signed streaming requests return the authenticated raw response", async () => {
  const originalFetch = globalThis.fetch;
  const streamed = new Response('{"type":"stage","value":"setup"}\n', {headers: {'Content-Type':'application/x-ndjson'}});
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(options.method, 'POST');
      assert.equal(options.body, JSON.stringify({mode:'protected'}));
      assert.equal(options.headers['X-Memoryseal-Signature'], '0xsigned');
      return streamed;
    };
    const result=await signedRequest({account:'0x1',method:'POST',path:'/demo/run',payload:{mode:'protected'},api:'https://gateway.example',audience:'test',wallet:{request:async()=> '0xsigned'},rawResponse:true});
    assert.equal(result,streamed);
    assert.match(await result.text(),/setup/);
  } finally {globalThis.fetch=originalFetch;}
});
