import assert from "node:assert/strict";
import { test } from "node:test";
import { signedRequest } from "../lib/gateway.mjs";

test("a wallet session change prevents a pending signature from being sent", async () => {
  const controller = new AbortController();
  let resolveSignature;
  let fetched = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { fetched = true; throw new Error("unexpected fetch"); };
  try {
    const pending = signedRequest({ account: "0x123", method: "POST", path: "/test", payload: {},
      api: "https://example.test", audience: "test", signal: controller.signal,
      wallet: { request: () => new Promise(resolve => { resolveSignature = resolve; }) } });
    // Allow the WebCrypto digest to finish and the wallet prompt to begin.
    while (!resolveSignature) await new Promise(resolve => setImmediate(resolve));
    controller.abort();
    resolveSignature("0xsigned");
    await assert.rejects(pending, { name: "AbortError" });
    assert.equal(fetched, false);
  } finally { globalThis.fetch = originalFetch; }
});
