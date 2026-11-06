import { isAddress } from "viem";
import { connectArkiv, connectArkivReader, findEvent, matchesEvent, publicValues, publishMemoryEvent, verifyEventProof } from "./provenance.mjs";

// One event is read from stdin. Credentials remain in environment variables.
const privateKey = process.env.MEMORYSEAL_ARKIV_PRIVATE_KEY;
const lookupOnly = process.argv.includes("--lookup-only");
const creator = process.env.MEMORYSEAL_ARKIV_CREATOR_ADDRESS;
if (lookupOnly ? !creator || !isAddress(creator) : !privateKey) throw new Error("Arkiv creator or publisher key is required");
let input = "";
for await (const chunk of process.stdin) input += chunk;
if (input.length > 16384) throw new Error("event too large");
const event = JSON.parse(input);
publicValues(event);
await verifyEventProof(event);
const accessKey = process.env.MEMORYSEAL_ARKIV_ACCESS_KEY;
const connection = lookupOnly ? { reader: connectArkivReader({ accessKey }) } : connectArkiv({ privateKey, accessKey });
const { reader, writer } = connection;
// A prior request may have succeeded despite a lost response. Search by
// immutable creator and event ID before publishing again.
const results = await findEvent(reader, lookupOnly ? creator : connection.account.address, event.event_id, event.schema);
const matches = results.entities;
if (matches.length > 1 || (matches.length === 1 && !matchesEvent(matches[0], event))) {
  if (!lookupOnly) throw new Error("duplicate or conflicting provenance records");
  console.log(JSON.stringify({ conflict: true }));
} else if (matches.length === 1) {
  console.log(JSON.stringify({ entityKey: matches[0].$key, txHash: null, reconciled: true }));
} else if (lookupOnly) {
  console.log(JSON.stringify({ found: false }));
} else {
  const result = await publishMemoryEvent(writer, event);
  console.log(JSON.stringify({ entityKey: result.entityKey, txHash: result.txHash, reconciled: false }));
}
