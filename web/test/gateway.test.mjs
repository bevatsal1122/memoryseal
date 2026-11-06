import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { Wallet, getBytes } from "../../contracts/node_modules/ethers/lib.esm/index.js";
import { signedRequest } from "../lib/gateway.mjs";
import { memorySearchPath } from "../lib/memory-search.mjs";

test("browser request format authenticates with gateway and enforces ownership", async () => {
  const api = process.env.MEMORYSEAL_TEST_GATEWAY;
  if (!api) throw new Error("MEMORYSEAL_TEST_GATEWAY is required");
  const owner = Wallet.createRandom(), agent = Wallet.createRandom(), other = Wallet.createRandom();
  function signer(wallet) {
    return { async request({ method, params }) {
      assert.equal(method, "personal_sign");
      assert.equal(params[1], wallet.address);
      return wallet.signMessage(getBytes(params[0]));
    }};
  }
  const call = (wallet, method, path, payload) => signedRequest({ account: wallet.address, method,
    path, payload, api, audience: "memoryseal-local", wallet: signer(wallet) });
  const preflight = await fetch(api + "/agents", { method: "OPTIONS", headers: {
    Origin: "http://localhost:3000", "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "x-memoryseal-address,x-memoryseal-signature,x-memoryseal-timestamp,x-memoryseal-nonce,content-type",
  }});
  assert.equal(preflight.status, 200);
  const created = await call(owner, "POST", "/agents/register", { signing_address: agent.address });
  assert.equal((await call(owner, "GET", "/agents")).agents[0].id, created.id);
  assert.equal((await call(other, "GET", "/agents")).agents.length, 0);
  const limit = "100000000000000000000";
  const transferGrant = await call(owner, "POST", "/capabilities/grant", {
    agent_id: created.id, operation: "transfer", resource: "TEST", max_amount: limit,
  });
  const caps = await call(owner, "GET", "/capabilities");
  assert.equal(caps.capabilities.find(cap => cap.id === transferGrant.id).max_amount, limit);
  const action = { agent_id: created.id, asset: "TEST", amount: limit, policy_version: transferGrant.policy_version };
  const simulation = await call(agent, "POST", "/actions/simulate-transfer", action);
  assert.equal(simulation.allowed, true);
  assert.equal(simulation.executed, false);
  const denied = await call(agent, "POST", "/actions/simulate-transfer", { ...action, amount: (BigInt(limit) + 1n).toString() });
  assert.equal(denied.allowed, false);
  const observation = { agent_id: created.id, transaction_hash: "0x" + "a".repeat(64), token: agent.address, max_amount: limit, expires_at: 0, policy_version: 1 };
  await assert.rejects(call(other, "POST", "/actions/observe-onchain-grant", observation), /agent not found/);
  await assert.rejects(call(owner, "POST", "/actions/observe-onchain-grant", observation), /onchain registry observer is not configured/);
  const namespace = "audit & café";
  await call(owner, "POST", "/capabilities/grant", { agent_id: created.id, operation: "write", resource: namespace });
  const writeRequestId = randomUUID();
  const parent = await call(agent, "POST", "/memory/write", { agent_id: created.id, namespace, content: "First observation", source_type: "agent", request_id: writeRequestId });
  const child = await call(agent, "POST", "/memory/write", { agent_id: created.id, namespace, content: "Later observation", source_type: "agent", parent_id: parent.id });
  await assert.rejects(call(other, "POST", `/memories/${parent.id}/quarantine`, {}), /memory not found/);
  assert.equal((await call(owner, "POST", `/memories/${parent.id}/quarantine`, {})).changed, false);
  const latest = await call(owner, "GET", "/capabilities");
  const signedQuarantine = { event_id: randomUUID(), commitment: parent.commitment, policy_version: latest.policy_version };
  assert.equal((await call(owner, "POST", `/memories/${parent.id}/quarantine-event`, signedQuarantine)).changed, false);
  await assert.rejects(call(other, "POST", `/memories/${parent.id}/quarantine-event`, signedQuarantine), /memory not found/);
  const events = await call(owner, "GET", `/memories/${parent.id}/provenance-events`);
  assert.equal(events.events.length, 1);
  assert.equal(events.events[0].event_type, "memory_created");
  const eventPath = `/memories/${parent.id}/provenance-events/${events.events[0].event_id}/observe`;
  assert.equal((await call(owner, "POST", eventPath, {})).observation, "not_published");
  await assert.rejects(call(other, "POST", eventPath, {}), /memory not found/);
  const params = new URLSearchParams({ namespace, agent_id: created.id, parent_id: parent.id, limit: "1", offset: "0" });
  const path = `/memories?${params}`;
  const filtered = await call(owner, "GET", path);
  assert.deepEqual(filtered.memories.map(memory => memory.id), [child.id]);
  assert.equal(filtered.next_offset, null);
  assert.equal((await call(other, "GET", path)).memories.length, 0);
  const recoveryPath = memorySearchPath({ agent: created.id, namespace, requestId: ` ${writeRequestId} ` });
  assert.deepEqual((await call(owner, "GET", recoveryPath)).memories.map(memory => memory.id), [parent.id]);
  assert.equal((await call(other, "GET", recoveryPath)).memories.length, 0);
  await call(owner, "POST", `/agents/${created.id}/revoke`, {});
  assert.equal((await call(owner, "GET", "/agents")).agents[0].revoked, true);
});
