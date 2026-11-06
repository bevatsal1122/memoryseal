import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { privateKeyToAccount } from "viem/accounts";
import { MemoryEvents, MemoryEventsV2, MemoryEventsV3, MemoryEventsV4, MemoryEventsV5, MemoryEventsV6, MemoryEventsV7, findEvent, findMemoryEvents, matchesEvent, publicValues, publishMemoryEvent, verifyEventProof, verifyQuarantineProof } from "../provenance.mjs";

test("v7 origin acknowledgement is signed by the agent", async () => {
  const id = "12345678-1234-1234-1234-123456789abc", account = privateKeyToAccount("0x" + "1".repeat(64));
  const actor = account.address.toLowerCase(), owner = "0x" + "a".repeat(40), commitment = "b".repeat(64), policy_version = 2;
  const body = JSON.stringify({ event_id: id, commitment, policy_version });
  const hash = createHash("sha256").update(body).digest("hex"), nonce = "a".repeat(32);
  const message = `MemorySeal request v1\nmemoryseal-local\nPOST\n/memories/${id}/attest-origin\n${hash}\n1793890000\n${nonce}`;
  const event = {schema: "memoryseal.memory-event.v7", event_type: "memory_origin_attested", event_id: id,
    memory_id: id, agent_id: id, owner, actor_address: actor, agent_address: actor,
    source_type: "agent", commitment, parent_id: null, trust_class: "untrusted", status: "quarantined", policy_version,
    request_audience: "memoryseal-local", request_timestamp: "1793890000", request_nonce: nonce,
    request_body_sha256: hash, request_signature: (await account.signMessage({message})).toLowerCase()};
  await verifyEventProof(event);
  let selected;
  await publishMemoryEvent({createEntity: async schema => {selected = schema; return {};}}, event);
  assert.equal(selected, MemoryEventsV7);
  await assert.rejects(verifyEventProof({...event, commitment: "d".repeat(64)}), /invalid public request proof/);
  await assert.rejects(verifyEventProof({...event, actor_address: owner}), /invalid origin actor/);
});

test("v6 signature binds event ID, commitment and policy version", async () => {
  const id = "12345678-1234-1234-1234-123456789abc", account = privateKeyToAccount("0x" + "1".repeat(64));
  const owner = account.address.toLowerCase(), commitment = "b".repeat(64), policy_version = 2;
  const body = JSON.stringify({ event_id: id, commitment, policy_version });
  const hash = createHash("sha256").update(body).digest("hex"), nonce = "a".repeat(32);
  const message = `MemorySeal request v1\nmemoryseal-local\nPOST\n/memories/${id}/quarantine-event\n${hash}\n1793890000\n${nonce}`;
  const event = {schema: "memoryseal.memory-event.v6", event_type: "memory_quarantined", event_id: id,
    memory_id: id, agent_id: id, owner, actor_address: owner, agent_address: "0x" + "c".repeat(40),
    source_type: "agent", commitment, parent_id: null, trust_class: "untrusted", status: "quarantined", policy_version,
    request_audience: "memoryseal-local", request_timestamp: "1793890000", request_nonce: nonce,
    request_body_sha256: hash, request_signature: (await account.signMessage({message})).toLowerCase()};
  await verifyQuarantineProof(event);
  let selected;
  await publishMemoryEvent({createEntity: async schema => {selected = schema; return {};}}, event);
  assert.equal(selected, MemoryEventsV6);
  for (const altered of [{event_id: "abcdefab-1234-1234-1234-123456789abc"}, {commitment: "d".repeat(64)}, {policy_version: 3}]) {
    await assert.rejects(verifyQuarantineProof({...event, ...altered}), /invalid public request proof/);
  }
});

test("v5 quarantine validates the owner's signed request", async () => {
  const id = "12345678-1234-1234-1234-123456789abc";
  const account = privateKeyToAccount("0x" + "1".repeat(64));
  const owner = account.address.toLowerCase();
  const bodyHash = createHash("sha256").update("{}").digest("hex");
  const audience = "memoryseal-local", timestamp = "1793890000", nonce = "a".repeat(32);
  const message = `MemorySeal request v1\n${audience}\nPOST\n/memories/${id}/quarantine\n${bodyHash}\n${timestamp}\n${nonce}`;
  const event = { schema: "memoryseal.memory-event.v5", event_type: "memory_quarantined",
    event_id: id, memory_id: id, agent_id: id, owner, actor_address: owner,
    agent_address: "0x" + "c".repeat(40), source_type: "agent", commitment: "b".repeat(64),
    parent_id: null, trust_class: "untrusted", status: "quarantined", policy_version: 2,
    request_audience: audience, request_timestamp: timestamp, request_nonce: nonce,
    request_body_sha256: bodyHash, request_signature: (await account.signMessage({ message })).toLowerCase() };
  await verifyQuarantineProof(event);
  let selected;
  await publishMemoryEvent({ createEntity: async schema => { selected = schema; return {}; } }, event);
  assert.equal(selected, MemoryEventsV5);
  await assert.rejects(verifyQuarantineProof({ ...event, request_nonce: "b".repeat(32) }), /signer mismatch/);
  await assert.rejects(verifyQuarantineProof({ ...event, memory_id: "abcdefab-1234-1234-1234-123456789abc" }), /signer mismatch/);
  await assert.rejects(verifyQuarantineProof({ ...event, request_body_sha256: "d".repeat(64) }), /invalid public request proof/);
});

test("quarantine event is owner attributed and contains only public fields", async () => {
  const id = "12345678-1234-1234-1234-123456789abc";
  const owner = "0x" + "a".repeat(40);
  const event = { schema: "memoryseal.memory-event.v4", event_type: "memory_quarantined",
    event_id: id, memory_id: id, agent_id: id, owner, actor_address: owner,
    agent_address: "0x" + "c".repeat(40), source_type: "agent", commitment: "b".repeat(64),
    parent_id: null, trust_class: "untrusted", status: "quarantined", policy_version: 2,
    content: "private" };
  const values = publicValues(event);
  assert.equal(values.actor_address, owner);
  assert.equal(values.event_type, "memory_quarantined");
  assert.equal(values.content, undefined);
  assert.throws(() => publicValues({...event, actor_address: "0x" + "d".repeat(40)}));
  assert.throws(() => publicValues({...event, status: "accepted"}));
  assert.throws(() => publicValues({...event, event_type: "memory_created"}));
  let selected;
  await publishMemoryEvent({ createEntity: async (schema) => { selected = schema; return {}; } }, event);
  assert.equal(selected, MemoryEventsV4);
});

test("publishes only permitted fields and filters by creator", async () => {
  const id = "12345678-1234-1234-1234-123456789abc";
  const event = { schema: "memoryseal.memory-event.v1", event_type: "memory_created",
    event_id: id, memory_id: id, agent_id: id, owner: "0x" + "a".repeat(40),
    commitment: "b".repeat(64), parent_id: null, trust_class: "untrusted", status: "quarantined",
    policy_version: 1, content: "sensitive" };
  const writer = { createEntity: async (_schema, values, options) => {
    assert.equal(values.content, undefined);
    assert.equal(options.flags.readonly, true);
    return { entityKey: "0x123" };
  }};
  assert.equal((await publishMemoryEvent(writer, event)).entityKey, "0x123");
  const row = Object.fromEntries(Object.entries(publicValues(event)).map(([key, value]) => [key, { value }]));
  assert.equal(matchesEvent(row, event), true);
  row.commitment.value = "c".repeat(64);
  assert.equal(matchesEvent(row, event), false);
  let creator;
  const query = { from() { return this; }, createdBy(value) { creator = value; return this; },
    where() { return this; }, limit() { return this; }, async fetch() { return { entities: [], skipped: 0 }; } };
  await findMemoryEvents({ select: () => query }, event.owner, id);
  assert.equal(creator, event.owner);
  await findEvent({ select: () => query }, event.owner, id);
  await assert.rejects(publishMemoryEvent(writer, { ...event, commitment: "bad" }));
  const v2 = { ...event, schema: "memoryseal.memory-event.v2", source_type: "external" };
  assert.equal(publicValues(v2).source_type, "external");
  const v2row = Object.fromEntries(Object.entries(publicValues(v2)).map(([key, value]) => [key, { value }]));
  assert.equal(matchesEvent(v2row, v2), true);
  v2row.source_type.value = "agent";
  assert.equal(matchesEvent(v2row, v2), false);
  await assert.rejects(publishMemoryEvent(writer, { ...v2, source_type: "https://private.example" }));
  await publishMemoryEvent({ createEntity: async schema => assert.equal(schema, MemoryEventsV2) }, v2);
  const v3 = { ...v2, schema: "memoryseal.memory-event.v3", agent_address: "0x" + "d".repeat(40) };
  const v3values = publicValues(v3);
  assert.equal(v3values.agent_address, v3.agent_address);
  assert.equal(v3values.content, undefined);
  const v3row = Object.fromEntries(Object.entries(v3values).map(([key, value]) => [key, { value }]));
  assert.equal(matchesEvent(v3row, v3), true);
  v3row.agent_address.value = "0x" + "e".repeat(40);
  assert.equal(matchesEvent(v3row, v3), false);
  assert.throws(() => publicValues({ ...v3, agent_address: "not-an-address" }), /invalid agent address/);
  await publishMemoryEvent({ createEntity: async schema => assert.equal(schema, MemoryEventsV3) }, v3);

  let usedSchema, mismatchMode, pageLimit;
  const recordingQuery = { from(schema, options) { usedSchema = schema; mismatchMode = options?.onMismatch; return this; }, createdBy() { return this; },
    where() { return this; }, limit(value) { pageLimit = value; return this; }, async fetch() { return { entities: [], skipped: 0 }; } };
  await findEvent({ select: () => recordingQuery }, event.owner, id, v2.schema);
  assert.equal(usedSchema, MemoryEventsV2);
  assert.equal(mismatchMode, "throw");
  assert.equal(pageLimit, 2);
  await findEvent({ select: () => recordingQuery }, event.owner, id, event.schema);
  assert.equal(usedSchema, MemoryEvents);
});

test("event lookup rejects skipped or malformed query pages", async () => {
  const chain = { from() { return this; }, createdBy() { return this; }, where() { return this; },
    limit() { return this; }, async fetch() { return { entities: [], skipped: 1 }; } };
  await assert.rejects(findEvent({ select: () => chain }, "0x" + "1".repeat(40), "12345678-1234-1234-1234-123456789abc"), /incomplete/);
});
