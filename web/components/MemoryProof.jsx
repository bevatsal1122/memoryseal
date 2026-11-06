"use client";
const txUrl = hash => /^0x[\da-f]{64}$/i.test(hash || "") ? `https://rabdi.explorer.arkiv.network/tx/${hash}` : null;
export const proofLabel = state => ({published: "Published", pending: "Queued", publishing: "Publishing…", uncertain: "Needs attention"}[state] || "Not available");
export default function MemoryProof({memory, observation, history, eventObservations, onObserve,
  onHistory, onObserveEvent, onPublishEvent, onReconcileEvent, onParent, onChildren, busy}) {
  const proof = memory.provenance;
  const link = txUrl(proof?.transaction_hash);
  return <details className="memory-proof" onToggle={e => {
    if (e.target === e.currentTarget && e.currentTarget.open && !history && !busy) onHistory();
  }}>
    <summary>Proof · {proofLabel(proof?.state)}</summary>
    <p>Creation record: {proofLabel(proof?.state)}{link && <> · <a href={link} target="_blank" rel="noopener noreferrer">View transaction ↗</a></>}</p>
    {proof?.state === "published" && <button disabled={busy} onClick={onObserve}>Verify published record</button>}
    {observation && <p role="status">Record check: {observation === "matched" ? "Matches the saved metadata" : observation}</p>}
    <p className="muted">Public proof contains metadata, not memory content. Publication does not establish that the content is true.</p>
    {history?.events.filter(e => e.event_type !== "memory_created").map(e => <p key={e.event_id}>
      {e.event_type.replaceAll("memory_", "").replaceAll("_", " ")} · {proofLabel(e.state)}
      {txUrl(e.transaction_hash) && <> · <a href={txUrl(e.transaction_hash)} target="_blank" rel="noopener noreferrer">View transaction ↗</a></>}
    </p>)}
    <details><summary>Technical details and recovery</summary>
      <p>Inference: {memory.inference_status}. {memory.auto_accepted ? "Accepted under the owner’s Standard policy." : memory.creation_reason}</p>
      <p>Agent-signed origin acknowledgements are distinct from hardware attestation.</p>
      <pre>{JSON.stringify({memory_id: memory.id, request_id: memory.request_id, policy_version: memory.policy_version,
        commitment: memory.commitment, source: memory.source_type, trust: memory.trust_class,
        inference_request: memory.inference_reference, analysis: memory.analysis, provenance: proof}, null, 2)}</pre>
      <div className="inline">{memory.parent_id && <button disabled={busy} onClick={onParent}>Related parent</button>}
        <button disabled={busy} onClick={onChildren}>Related memories</button>
        <button disabled={busy} onClick={onHistory}>Refresh event details</button></div>
      {history?.events.map(e => <div key={e.event_id} className="proof-event">
        <small>{e.event_type} · {e.state} · {e.event_id}</small>
        {e.state === "pending" && <button disabled={busy} onClick={() => onPublishEvent(e.event_id)}>Publish now</button>}
        {e.state === "uncertain" && <button disabled={busy} onClick={() => onReconcileEvent(e.event_id)}>Look up existing submission</button>}
        {e.state === "published" && e.event_type !== "memory_created" && <button disabled={busy} onClick={() => onObserveEvent(e.event_id)}>Verify this event</button>}
        {eventObservations[e.event_id] && <small>{eventObservations[e.event_id]}</small>}
      </div>)}
    </details>
  </details>;
}
