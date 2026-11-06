"use client";
import { capabilityActive } from "../lib/expiry.mjs";

export default function AgentCard({ agent, capabilities, observation, busy, onCheckEns, onManageEns, onRevoke }) {
  const grants = agent.revoked ? [] : capabilities.filter(c => c.agent_id === agent.id && capabilityActive(c));
  const collections = [...new Set(grants.filter(c => c.operation === "read" || c.operation === "write").map(c => c.resource))];
  const name = agent.label || agent.ens_name?.split(".")[0] || "Unnamed agent";
  return <article className={`agent-record${agent.revoked ? " is-revoked" : ""}`}>
    <header className="agent-record-header">
      <div className="agent-record-title">
        <span className="agent-monogram" aria-hidden="true">{name.slice(0, 2).toUpperCase()}</span>
        <div><h3>{name}</h3><span className="agent-record-id">ID · {agent.id.slice(0, 8)}</span></div>
      </div>
      <div className="agent-record-actions">
        <span className={`pill ${agent.revoked ? "warning" : ""}`}>{agent.revoked ? "Revoked" : "Registered"}</span>
        {!agent.revoked && <button className="agent-revoke" disabled={busy} onClick={onRevoke}>Revoke access</button>}
      </div>
    </header>
    <dl className="agent-record-facts">
      <div className="agent-record-wallet"><dt>Signing address</dt><dd><code>{agent.signing_address}</code></dd></div>
      <div><dt>Permissions</dt><dd>{grants.length}</dd></div>
      <div><dt>Collections</dt><dd>{collections.length}</dd></div>
    </dl>
    <details className="agent-record-details" onToggle={e => {
      if (e.target === e.currentTarget && e.currentTarget.open && agent.ens_name && !observation) onCheckEns();
    }}>
      <summary>Identity & permissions <span aria-hidden="true">↗</span></summary>
      <div className="agent-record-detail-body">
        <div className="agent-identity-grid">
          <div><span className="proof-label">ENS NAME</span><p className="agent-ens-name">{agent.ens_name || "Not set"}</p>
            {agent.ens_name && <span className="agent-ens-result" role="status">{observation?.error || (observation ? observation.matches ? "Address matched" : "Address mismatch" : "Checking ENS…")}</span>}
          </div>
          <div><span className="proof-label">POLICY NETWORK</span><p>{agent.policy_chain_id ?? "Configured default"}</p></div>
        </div>
        <div className="agent-grants">
          <span className="proof-label">CURRENT PERMISSIONS</span>
          {grants.length ? <ul>{grants.map(c => <li key={c.id}><b>{c.operation}</b><code>{c.resource}</code>{c.max_amount && <span>Limit: {c.max_amount} base units</span>}{c.expires_at && <span>Expires {new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(c.expires_at) ? c.expires_at : `${c.expires_at}Z`).toLocaleString()}</span>}</li>)}</ul> : <p>No active permissions.</p>}
        </div>
        <div className="inline">
          <button disabled={busy} onClick={onManageEns}>Manage ENS name</button>
          {agent.ens_name && <a className="neo-button" href="https://explorer.ens.dev" target="_blank" rel="noopener noreferrer">ENS explorer <span aria-hidden="true">↗</span></a>}
          {observation?.error && <button disabled={busy} onClick={onCheckEns}>Retry ENS check</button>}
        </div>
      </div>
    </details>
  </article>;
}
