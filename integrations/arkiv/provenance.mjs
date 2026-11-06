import { createPublicClient, createWalletClient, ExpirationTime } from "@arkiv-network/sdk";
import { rabdi } from "@arkiv-network/sdk/chains";
import { defineSchema, str } from "@arkiv-network/sdk/schema";
import { eq } from "@arkiv-network/sdk/query";
import { http, recoverMessageAddress } from "viem";
import { createHash } from "node:crypto";
import { privateKeyToAccount } from "viem/accounts";

// Arkiv is public. Every field is intentionally selected; no free-form payload
// or source URL is accepted by this publisher.
export const MemoryEvents = defineSchema("memoryseal.memory-event.v1", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), event_type: str(), commitment: str(), parent_id: str(),
  trust_class: str(), status: str(), policy_version: str(),
});
export const MemoryEventsV2 = defineSchema("memoryseal.memory-event.v2", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), event_type: str(), commitment: str(), parent_id: str(),
  trust_class: str(), status: str(), policy_version: str(), source_type: str(),
});

export const MemoryEventsV3 = defineSchema("memoryseal.memory-event.v3", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), event_type: str(), commitment: str(), parent_id: str(),
  trust_class: str(), status: str(), policy_version: str(), source_type: str(),
});

export const MemoryEventsV4 = defineSchema("memoryseal.memory-event.v4", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), actor_address: str().indexed(),
  event_type: str(), commitment: str(), parent_id: str(), trust_class: str(),
  status: str(), policy_version: str(), source_type: str(),
});

export const MemoryEventsV5 = defineSchema("memoryseal.memory-event.v5", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), actor_address: str().indexed(),
  event_type: str(), commitment: str(), parent_id: str(), trust_class: str(),
  status: str(), policy_version: str(), source_type: str(), request_audience: str(),
  request_timestamp: str(), request_nonce: str(), request_body_sha256: str(), request_signature: str(),
});

export const MemoryEventsV6 = defineSchema("memoryseal.memory-event.v6", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), actor_address: str().indexed(),
  event_type: str(), commitment: str(), parent_id: str(), trust_class: str(),
  status: str(), policy_version: str(), source_type: str(), request_audience: str(),
  request_timestamp: str(), request_nonce: str(), request_body_sha256: str(), request_signature: str(),
});

export const MemoryEventsV7 = defineSchema("memoryseal.memory-event.v7", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), actor_address: str().indexed(),
  event_type: str(), commitment: str(), parent_id: str(), trust_class: str(),
  status: str(), policy_version: str(), source_type: str(), request_audience: str(),
  request_timestamp: str(), request_nonce: str(), request_body_sha256: str(), request_signature: str(),
});

export const MemoryEventsV8 = defineSchema("memoryseal.memory-event.v8", {
  event_id: str().indexed(), memory_id: str().indexed(), owner: str().indexed(),
  agent_id: str(), agent_address: str().indexed(), actor_address: str().indexed(),
  event_type: str(), commitment: str(), parent_id: str(), trust_class: str(),
  status: str(), policy_version: str(), source_type: str(), request_audience: str(),
  request_timestamp: str(), request_nonce: str(), request_body_sha256: str(), request_signature: str(),
});

function schemaFor(name) {
  if (name === "memoryseal.memory-event.v1") return MemoryEvents;
  if (name === "memoryseal.memory-event.v2") return MemoryEventsV2;
  if (name === "memoryseal.memory-event.v3") return MemoryEventsV3;
  if (name === "memoryseal.memory-event.v4") return MemoryEventsV4;
  if (name === "memoryseal.memory-event.v5") return MemoryEventsV5;
  if (name === "memoryseal.memory-event.v6") return MemoryEventsV6;
  if (name === "memoryseal.memory-event.v7") return MemoryEventsV7;
  if (name === "memoryseal.memory-event.v8") return MemoryEventsV8;
  throw new Error("unsupported provenance schema");
}

export function connectArkiv({ privateKey, accessKey = "" }) {
  const account = privateKeyToAccount(privateKey);
  const chain = rabdi({ accessKey });
  return {
    account,
    reader: createPublicClient({ chain, transport: http() }),
    writer: createWalletClient({ chain, transport: http(), account }),
  };
}

export function connectArkivReader({ accessKey = "" } = {}) {
  return createPublicClient({ chain: rabdi({ accessKey }), transport: http() });
}

export function publicValues(event) {
  const review = event.schema === "memoryseal.memory-event.v8";
  const v6 = event.schema === "memoryseal.memory-event.v6";
  const origin = event.schema === "memoryseal.memory-event.v7";
  const signed = review || origin || v6 || event.schema === "memoryseal.memory-event.v5";
  const quarantine = v6 || event.schema === "memoryseal.memory-event.v5" || event.schema === "memoryseal.memory-event.v4";
  if (!['memoryseal.memory-event.v1', 'memoryseal.memory-event.v2', 'memoryseal.memory-event.v3', 'memoryseal.memory-event.v4', 'memoryseal.memory-event.v5', 'memoryseal.memory-event.v6', 'memoryseal.memory-event.v7', 'memoryseal.memory-event.v8'].includes(event.schema) ||
      (review ? event.event_type !== "memory_reviewed" : origin ? event.event_type !== "memory_origin_attested" : quarantine ? event.event_type !== "memory_quarantined" : event.event_type !== "memory_created")) {
    throw new Error("unsupported provenance event");
  }
  if (!/^[0-9a-f]{64}$/.test(event.commitment) || !/^0x[0-9a-f]{40}$/.test(event.owner)) {
    throw new Error("invalid commitment or owner");
  }
  for (const value of [event.event_id, event.memory_id, event.agent_id]) {
    if (!/^[0-9a-f-]{36}$/.test(value)) throw new Error("invalid identifier");
  }
  if ((v6 || origin || review) && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(event.event_id)) throw new Error("invalid signed event identifier");
  if (event.parent_id !== null && !/^[0-9a-f-]{36}$/.test(event.parent_id)) throw new Error("invalid parent");
  if (!Number.isSafeInteger(event.policy_version) || event.policy_version < 0 ||
      !["accepted", "quarantined"].includes(event.status) || event.trust_class !== "untrusted") {
    throw new Error("invalid metadata");
  }
  if (["memoryseal.memory-event.v3", "memoryseal.memory-event.v4", "memoryseal.memory-event.v5", "memoryseal.memory-event.v6", "memoryseal.memory-event.v7", "memoryseal.memory-event.v8"].includes(event.schema) && !/^0x[0-9a-f]{40}$/.test(event.agent_address)) throw new Error("invalid agent address");
  if (quarantine && (event.actor_address !== event.owner || event.status !== "quarantined")) throw new Error("invalid quarantine actor or status");
  if (review && (event.actor_address !== event.owner || event.status !== "accepted" || event.source_type !== "agent")) throw new Error("invalid review actor or status");
  if (origin && event.actor_address !== event.agent_address) throw new Error("invalid origin actor");
  if (signed) {
    const bodies = (v6 || origin || review) ? [JSON.stringify({event_id: event.event_id, commitment: event.commitment, policy_version: event.policy_version})] : ["", "{}"];
    const validBody = bodies.map(body => createHash("sha256").update(body).digest("hex"));
    if (![event.request_audience, event.request_timestamp, event.request_nonce, event.request_body_sha256, event.request_signature].every(v => typeof v === "string") ||
        !/^[A-Za-z0-9._:-]{1,128}$/.test(event.request_audience) ||
        !/^(0|[1-9][0-9]{0,15})$/.test(event.request_timestamp) || !Number.isSafeInteger(Number(event.request_timestamp)) ||
        !/^[0-9a-f]{32}$/.test(event.request_nonce) || !validBody.includes(event.request_body_sha256) ||
        !/^0x[0-9a-f]{130}$/.test(event.request_signature)) throw new Error("invalid public request proof");
  }
  if (event.schema !== "memoryseal.memory-event.v1" && !["external", "agent"].includes(event.source_type)) throw new Error("invalid source type");
  return {
    event_id: event.event_id, memory_id: event.memory_id, owner: event.owner,
    agent_id: event.agent_id, event_type: event.event_type, commitment: event.commitment,
    parent_id: event.parent_id ?? "", trust_class: event.trust_class, status: event.status,
    policy_version: String(event.policy_version),
    ...(event.schema !== "memoryseal.memory-event.v1" ? { source_type: event.source_type } : {}),
    ...(["memoryseal.memory-event.v3", "memoryseal.memory-event.v4", "memoryseal.memory-event.v5", "memoryseal.memory-event.v6", "memoryseal.memory-event.v7", "memoryseal.memory-event.v8"].includes(event.schema) ? { agent_address: event.agent_address } : {}),
    ...((quarantine || origin || review) ? { actor_address: event.actor_address } : {}),
    ...(signed ? { request_audience: event.request_audience, request_timestamp: event.request_timestamp,
      request_nonce: event.request_nonce, request_body_sha256: event.request_body_sha256,
      request_signature: event.request_signature } : {}),
  };
}

export async function verifyEventProof(event) {
  publicValues(event);
  if (!["memoryseal.memory-event.v5", "memoryseal.memory-event.v6", "memoryseal.memory-event.v7", "memoryseal.memory-event.v8"].includes(event.schema)) return;
  const path = event.schema === "memoryseal.memory-event.v8" ? "review-event" : event.schema === "memoryseal.memory-event.v7" ? "attest-origin" : event.schema === "memoryseal.memory-event.v6" ? "quarantine-event" : "quarantine";
  const message = `MemorySeal request v1\n${event.request_audience}\nPOST\n/memories/${event.memory_id}/${path}\n${event.request_body_sha256}\n${event.request_timestamp}\n${event.request_nonce}`;
  const signer = await recoverMessageAddress({ message, signature: event.request_signature });
  const expected = event.schema === "memoryseal.memory-event.v7" ? event.agent_address : event.owner;
  if (signer.toLowerCase() !== expected) throw new Error("signed request signer mismatch");
}

export const verifyQuarantineProof = verifyEventProof;

export function matchesEvent(row, event) {
  const values = publicValues(event);
  return Object.entries(values).every(([key, value]) => row[key]?.value === value);
}

export async function publishMemoryEvent(writer, event, days = 30) {
  if (!Number.isInteger(days) || days < 1 || days > 365) throw new Error("invalid retention period");
  await verifyEventProof(event);
  return writer.createEntity(schemaFor(event.schema), publicValues(event),
    { expiration: ExpirationTime.fromDays(days), flags: { readonly: true } });
}

export async function findMemoryEvents(reader, trustedCreator, memoryId, schema = "memoryseal.memory-event.v1") {
  return reader.select().from(schemaFor(schema)).createdBy(trustedCreator)
    .where(eq("memory_id", memoryId)).fetch();
}

export async function findEvent(reader, trustedCreator, eventId, schema = "memoryseal.memory-event.v1") {
  // Two rows are sufficient to reject a duplicate. An explicit limit and
  // mismatch errors prevent a truncated or skipped page looking unique.
  const result = await reader.select().from(schemaFor(schema), { onMismatch: "throw" }).createdBy(trustedCreator)
    .where(eq("event_id", eventId)).limit(2).fetch();
  if (result.skipped !== 0 || result.entities.length > 2) throw new Error("incomplete provenance query");
  return result;
}
