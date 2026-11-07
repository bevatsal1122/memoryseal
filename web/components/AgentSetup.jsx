"use client";
import CollectionInput from "./CollectionInput";
import ActionNotice from "./ActionNotice";
import PolicyChainSelect from "./PolicyChainSelect";
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
    setBusy(true); setError("");
    try {
    const body = pending || {
      request_id: crypto.randomUUID(), policy_version: version,
      signing_address: fields.get("address"), label: fields.get("label"),
      namespace: fields.get("namespace"), operations: fields.getAll("operations"),
      acceptance: mode, ens_name: null, sponsored_ens: true,
      policy_chain_id: fields.get("chain") ? Number(fields.get("chain")) : null,
    };
    setPending(body);
      await request(account, "POST", "/agents/setup", body);
      setPending(null); form.reset(); setMode("strict");
      await onComplete();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="guided-form agent-setup">
    <header className="agent-setup-header">
      <div><span className="setup-kicker">AGENT SETUP</span><h3>Add an agent</h3></div>

    </header>
    <ActionNotice message={error} onClose={() => setError("")} />
    <fieldset disabled={busy || !!pending}>
      <section className="setup-section" aria-labelledby="setup-identity-title">
        <div className="setup-section-title"><span aria-hidden="true">01</span><h4 id="setup-identity-title">Agent identity</h4></div>
        <div className="setup-fields">
          <div className="setup-field">
            <label htmlFor="setup-label">Agent name</label>
            <input id="setup-label" name="label" placeholder="Research agent" required maxLength={80} />
          </div>
          <div className="setup-field">
            <label htmlFor="setup-address">Agent wallet address</label>
            <input id="setup-address" name="address" placeholder="0x…" required pattern="0x[a-fA-F0-9]{40}" />
          </div>
        </div>
      </section>
      <section className="setup-section" aria-labelledby="setup-access-title">
        <div className="setup-section-title"><span aria-hidden="true">02</span><h4 id="setup-access-title">Memory access</h4></div>
        <div className="setup-fields">
          <div className="setup-field">
            <label htmlFor="setup-collection">Collection</label>
            <CollectionInput id="setup-collection" name="namespace" placeholder="research" required maxLength={128} />

          </div>
          <div className="setup-field">
            <label htmlFor="setup-mode">Memory acceptance</label>
            <select id="setup-mode" value={mode} onChange={e => setMode(e.target.value)}>
              <option value="strict">Strict verification</option>
              <option value="standard">Standard acceptance</option>
            </select>
          </div>
        </div>
        <fieldset className="setup-permissions">
          <legend>Allowed actions</legend>
          <div className="setup-fields">
            <label className="setup-permission"><input type="checkbox" name="operations" value="read" defaultChecked /><span><b>Read memories</b></span></label>
            <label className="setup-permission"><input type="checkbox" name="operations" value="write" defaultChecked /><span><b>Write memories</b></span></label>
          </div>
        </fieldset>
        {mode === "standard" && <p className="setup-mode-notice">Includes unverified low-risk observations. Risky content stays withheld.</p>}
      </section>
      <section className="setup-section" aria-labelledby="setup-naming-title">
        <div className="setup-section-title"><span aria-hidden="true">03</span><h4 id="setup-naming-title">Policy network</h4></div>
        <div className="setup-fields">
          <div className="setup-field"><label htmlFor="setup-chain">Policy network</label><PolicyChainSelect account={account} request={request} /></div>
        </div>
      </section>
    </fieldset>
    <p className="muted">Your agent’s ENS name is registered automatically. No ENS transactions to sign.</p>
    <footer className="agent-setup-footer">

      <div className="inline">
        {pending && !busy && <button type="button" onClick={() => {setPending(null); setError("");}}>Edit setup</button>}
        <button disabled={busy}>{busy ? "Setting up agent…" : pending ? "Resume agent setup" : "Create agent"}</button>
      </div>
    </footer>
  </form>;
}
