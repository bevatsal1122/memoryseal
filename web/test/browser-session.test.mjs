import assert from "node:assert/strict";
import { test } from "node:test";
import { Wallet, getBytes } from "../../contracts/node_modules/ethers/lib.esm/index.js";
import { signedRequest } from "../lib/gateway.mjs";
import { clearBrowserSessions } from "../lib/browser-session.mjs";

test("one login signs concurrent reads; writes still sign; logout and wallet changes require login", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.location = { origin: "http://localhost:3000", protocol: "http:", hostname: "localhost" };
  globalThis.fetch = (url, options = {}) => originalFetch(url, { ...options,
    headers: { ...options.headers, Origin: "http://localhost:3000" },
  });
  try {
    const api = process.env.MEMORYSEAL_TEST_GATEWAY;
    const owner = Wallet.createRandom();
    let prompts = 0;
    const wallet = { request: async ({ params }) => { prompts++; return owner.signMessage(getBytes(params[0])); } };
    const call = (method, path, payload) => signedRequest({ account: owner.address, api,
      audience: "memoryseal-local", wallet, useSession: true, method, path, payload });
    const results = await Promise.all(["/agents", "/capabilities", "/memories", "/events"].map(p => call("GET", p)));
    assert.equal(results.length, 4);
    assert.equal(prompts, 1);
    const agent = await call("POST", "/agents/register", { signing_address: Wallet.createRandom().address });
    assert.equal(prompts, 2);
    assert.equal((await call("GET", "/agents")).agents[0].id, agent.id);
    assert.equal(prompts, 2);
    clearBrowserSessions();
    await call("GET", "/agents");
    assert.equal(prompts, 3);
    const other = Wallet.createRandom();
    const result = await signedRequest({ account: other.address, api, audience: "memoryseal-local",
      wallet: { request: async ({ params }) => { prompts++; return other.signMessage(getBytes(params[0])); } },
      useSession: true, method: "GET", path: "/agents" });
    assert.deepEqual(result.agents, []);
    assert.equal(prompts, 4);
  } finally {
    clearBrowserSessions();
    globalThis.fetch = originalFetch;
    delete globalThis.location;
  }
});

test("cancelled login can retry; switching wallets during a prompt cannot create a session", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.location = { origin: "http://localhost:3000", protocol: "http:", hostname: "localhost" };
  let exchanges = 0;
  globalThis.fetch = (url, options = {}) => {
    if (url.endsWith("/auth/session")) exchanges++;
    return originalFetch(url, { ...options, headers: { ...options.headers, Origin: "http://localhost:3000" } });
  };
  try {
    const owner = Wallet.createRandom();
    const args = { account: owner.address, api: process.env.MEMORYSEAL_TEST_GATEWAY,
      audience: "memoryseal-local", useSession: true, method: "GET", path: "/identity" };
    await assert.rejects(signedRequest({ ...args, wallet: { request: async () => { throw new Error("User rejected"); } } }), /User rejected/);
    let finish, started;
    const ready = new Promise(resolve => { started = resolve; });
    const pending = signedRequest({ ...args, wallet: { request: ({ params }) => {
      started();
      return new Promise(resolve => { finish = async () => resolve(await owner.signMessage(getBytes(params[0]))); });
    } } });
    await ready;
    clearBrowserSessions();
    await finish();
    await assert.rejects(pending, /Wallet changed/);
    assert.equal(exchanges, 0);
    const result = await signedRequest({ ...args, wallet: { request: ({ params }) => owner.signMessage(getBytes(params[0])) } });
    assert.equal(result.signer, owner.address.toLowerCase());
    assert.equal(exchanges, 1);
  } finally {
    clearBrowserSessions();
    globalThis.fetch = originalFetch;
    delete globalThis.location;
  }
});
