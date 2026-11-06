"use client";
import { useState } from "react";

export default function AgentSetup({ account, version, request, onComplete }) {
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("strict");
  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const body = pending || {
      request_id: crypto.randomUUID(), policy_version: version,
      signing_address: fields.get("address"), label: fields.get("label"),
      namespace: fields.get("namespace"), operations: fields.getAll("operations"),
      acceptance: mode, ens_name: fields.get("ens") || null,
      policy_chain_id: fields.get("chain") ? Number(fields.get("chain")) : null,
    };
    setPending(body); setBusy(true); setError("");
    try {
      await request(account, "POST", "/agents/setup", body);
      setPending(null); form.reset(); setMode("strict");
      await onComplete();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="guided-form">
    <h3>Add an agent</h3>
    <p className="muted">Give it a name and collection access. One wallet signature approves this setup.</p>
    {error && <p role="alert">{error}</p>}
    <fieldset disabled={busy || !!pending}>
      <label htmlFor="setup-label">Agent name</label>
      <input id="setup-label" name="label" placeholder="Research agent" required maxLength={80} />
      <label htmlFor="setup-address">Agent wallet address</label>
      <input id="setup-address" name="address" placeholder="0x…" required pattern="0x[a-fA-F0-9]{40}" />
      <small>Use the public address of the wallet your agent signs with.</small>
      <label htmlFor="setup-collection">Collection</label>
      <input id="setup-collection" name="namespace" placeholder="research" required maxLength={128} />
      <div className="inline">
        <label><input type="checkbox" name="operations" value="read" defaultChecked /> Read</label>
        <label><input type="checkbox" name="operations" value="write" defaultChecked /> Write</label>
      </div>
      <label htmlFor="setup-mode">Memory acceptance</label>
      <select id="setup-mode" value={mode} onChange={e => setMode(e.target.value)}>
        <option value="strict">Strict — keep existing verification requirements</option>
        <option value="standard">Standard — automatically accept eligible observations</option>
      </select>
      {mode === "standard" && <p className="muted">Allows low-risk unverified observations in this collection. Instructions and conflicts still need review. Grants no transfer authority.</p>}
      <details><summary>Advanced: ENS and chain</summary>
        <label htmlFor="setup-ens">Existing ENS name (optional)</label><input id="setup-ens" name="ens" placeholder="research.example.eth" />
        <label htmlFor="setup-chain">Policy chain ID (optional)</label><input id="setup-chain" name="chain" type="number" min="1" placeholder="Configured default" />
      </details>
    </fieldset>
    <button disabled={busy}>{busy ? "Waiting for confirmation…" : pending ? "Retry same setup" : "Add agent and permissions"}</button>
    {pending && !busy && <button type="button" onClick={() => {setPending(null); setError("");}}>Edit setup</button>}
  </form>;
}
