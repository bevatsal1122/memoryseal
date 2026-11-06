"use client";
const txUrl = hash => /^0x[\da-f]{64}$/i.test(hash || "") ? `https://rabdi.explorer.arkiv.network/tx/${hash}` : null;
const readable = value => typeof value === "string" ? value.replaceAll("_", " ") : value == null ? "Not recorded" : String(value);
export const proofLabel = state => ({published: "Published", pending: "Queued", publishing: "Publishing…", uncertain: "Needs attention"}[state] || "Not available");
function Transaction({hash}) {
  const url = txUrl(hash);
  return url ? <a className="neo-button" href={url} target="_blank" rel="noopener noreferrer">View transaction <span aria-hidden="true">↗</span></a> : null;
}
export default function MemoryProof({memory, observation, history, eventObservations = {}, onObserve,
  onHistory, onObserveEvent, onPublishEvent, onReconcileEvent, onParent, onChildren, busy}) {
  const proof = memory.provenance;
  const analysis = memory.analysis;
  const raw = {memory_id: memory.id, request_id: memory.request_id, policy_version: memory.policy_version,
    commitment: memory.commitment, source: memory.source_type, trust: memory.trust_class,
    inference_request: memory.inference_reference, analysis, provenance: proof};
  return <details className="memory-proof" onToggle={e => {
    if (e.target === e.currentTarget && e.currentTarget.open && !history && !busy) onHistory();
  }}>
    <summary><span>Provenance & review</span><span className="proof-state">{proofLabel(proof?.state)}</span></summary>
    <div className="proof-body">
      <div className="proof-overview">
        <div><span className="proof-label">PUBLIC RECORD</span><h3>{proofLabel(proof?.state)}</h3><p>Publication tracks metadata, not the truth of a memory.</p></div>
        <div className="inline"><Transaction hash={proof?.transaction_hash} />{proof?.state === "published" && <button disabled={busy} onClick={onObserve}>Verify published record</button>}</div>
      </div>
      {observation && <p className="proof-observation" role="status">Record check: {observation === "matched" ? "Matches the saved metadata" : readable(observation)}</p>}
      <div className="proof-facts">
        <div><span className="proof-label">SOURCE</span><strong>{readable(memory.source_type)}</strong></div>
        <div><span className="proof-label">TRUST</span><strong>{readable(memory.trust_class)}</strong></div>
        <div><span className="proof-label">INFERENCE</span><strong>{readable(memory.inference_status)}</strong></div>
        <div><span className="proof-label">POLICY VERSION</span><strong>{memory.policy_version ?? "Not recorded"}</strong></div>
      </div>
      <div className={`proof-assessment ${memory.status === "quarantined" ? "needs-review" : ""}`}>
        <span className="proof-label">REVIEW CONTEXT</span>
        <p>{memory.auto_accepted ? "Accepted under the owner’s Standard policy." : readable(memory.creation_reason)}</p>
        {analysis && <div className="proof-analysis">{[["Risk", analysis.risk], ["Recommendation", analysis.recommendation], ["Category", analysis.category]].filter(([, value]) => value != null).map(([label, value]) => <span key={label}>{label}: <b>{readable(value)}</b></span>)}</div>}
      </div>
      <details className="proof-history" onToggle={e => {
        if (e.target === e.currentTarget && e.currentTarget.open && !history && !busy) onHistory();
      }}>
        <summary>Record history & recovery <span className="proof-count">{history ? history.events.length : ""}</span></summary>
        <div className="proof-history-body">
          <div className="inline">{memory.parent_id && <button disabled={busy} onClick={onParent}>Related parent</button>}<button disabled={busy} onClick={onChildren}>Related memories</button><button disabled={busy} onClick={onHistory}>Refresh event details</button></div>
          {!history && <p className="muted">{busy ? "Loading record history…" : "Load event details to inspect publication history."}</p>}
          {history?.events.length === 0 && <p className="muted">No events recorded.</p>}
          {history?.events.map(e => <div key={e.event_id} className="proof-timeline-event">
            <div className="proof-event-title"><strong>{readable(e.event_type)}</strong><span className="proof-state">{proofLabel(e.state)}</span></div>
            <code>{e.event_id}</code>
            <div className="inline"><Transaction hash={e.transaction_hash} />
              {e.state === "pending" && <button disabled={busy} onClick={() => onPublishEvent(e.event_id)}>Publish now</button>}
              {e.state === "uncertain" && <button disabled={busy} onClick={() => onReconcileEvent(e.event_id)}>Look up existing submission</button>}
              {e.state === "published" && e.event_type !== "memory_created" && <button disabled={busy} onClick={() => onObserveEvent(e.event_id)}>Verify this event</button>}
            </div>
            {eventObservations[e.event_id] && <p role="status">{readable(eventObservations[e.event_id])}</p>}
          </div>)}
        </div>
      </details>
      <details className="proof-raw"><summary>Technical identifiers & raw data</summary>
        <p>Agent-signed origin acknowledgements are distinct from hardware attestation.</p>
        <pre>{JSON.stringify(raw, null, 2)}</pre>
      </details>
      <p className="proof-footnote">Public proof contains metadata, not memory content. Publication does not establish that the content is true.</p>
    </div>
  </details>;
}
