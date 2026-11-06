import { isAddress } from "viem";
import { connectArkivReader, findMemoryEvents } from "./provenance.mjs";

// Read-only public query; neither a wallet nor local MemorySeal database is needed.
const [creator, memoryId, schema = "memoryseal.memory-event.v3"] = process.argv.slice(2);
if (!isAddress(creator ?? "") || /^0x0{40}$/i.test(creator) ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(memoryId ?? "")) {
  throw new Error("Usage: node query.mjs CREATOR_ADDRESS MEMORY_UUID [SCHEMA]");
}
const result = await findMemoryEvents(connectArkivReader({ accessKey: process.env.MEMORYSEAL_ARKIV_ACCESS_KEY }), creator, memoryId, schema);
const fields = ["event_id", "memory_id", "owner", "agent_id", "agent_address", "actor_address", "event_type", "commitment", "parent_id", "trust_class", "status", "policy_version", "source_type", "request_audience", "request_timestamp", "request_nonce", "request_body_sha256", "request_signature"];
const records = result.entities.map(row => ({ entity_key: row.$key,
  ...Object.fromEntries(fields.filter(key => row[key] !== undefined).map(key => [key, row[key].value])) }));
console.log(JSON.stringify({ schema, creator, block_number: String(result.blockNumber), skipped: result.skipped,
  records, complete: false, note: "One page only; absence or a match is not proof of completeness, permanence, or truth." }));
