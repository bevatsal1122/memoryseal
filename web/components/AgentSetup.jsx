"use client";
import CollectionInput from "./CollectionInput";
import ActionNotice from "./ActionNotice";
import PolicyChainSelect from "./PolicyChainSelect";
import { useEffect, useState } from "react";
import { AGENT_ENS_PARENT, agentEnsName, provisionAgentEns } from "../lib/agent-ens-setup.mjs";
import { agentEnsWallet } from "../lib/agent-ens-wallet.mjs";

export default function AgentSetup({ account, version, request, onComplete }) {
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("strict");
  const [ensLabel, setEnsLabel] = useState("");
  const [progress, setProgress] = useState("");
  const [ensJob, setEnsJob] = useState(null);
  const storageKey = `memoryseal:agent-setup:sepolia:${account.toLowerCase()}`;
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (saved?.job?.owner?.toLowerCase() === account.toLowerCase() && saved?.body?.request_id) {
        setPending(saved.body); setEnsJob(saved.job); setEnsLabel(saved.job.label);
      }
    } catch { /* A new setup can proceed without saved state. */ }
  }, [storageKey, account]);
  function saveSetup(body, job) {
    // Refuse to submit if recovery context cannot be saved before the wallet call.
    localStorage.setItem(storageKey, JSON.stringify({body, job}));
    setEnsJob({...job});
  }
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
      acceptance: mode, ens_name: agentEnsName(ensLabel),
      policy_chain_id: fields.get("chain") ? Number(fields.get("chain")) : null,
    };
    const job = ensJob || {
      owner: account, agentAddress: body.signing_address, parentName: AGENT_ENS_PARENT,
      label: body.ens_name.slice(0, -(AGENT_ENS_PARENT.length + 1)),
      expiry: String(Math.floor(Date.now()/1000) + 365*24*60*60),
      salt: BigInt("0x" + crypto.randomUUID().replaceAll("-", "")).toString(),
    };
    if (job.owner.toLowerCase() !== account.toLowerCase() || job.agentAddress.toLowerCase() !== body.signing_address.toLowerCase() || `${job.label}.${job.parentName}` !== body.ens_name) throw new Error("Saved ENS setup does not match this agent.");
    setPending(body); saveSetup(body, job);
    await provisionAgentEns(job, agentEnsWallet(window.ethereum, account), next => saveSetup(body, next), setProgress);
    setProgress("permissions");
      if (!job.gatewayStarted) {
        const policy = await request(account, "GET", "/capabilities");
        body.policy_version = policy.policy_version;
        job.gatewayStarted = true;
        saveSetup(body, job); setPending({...body});
      }
      await request(account, "POST", "/agents/setup", body);
      localStorage.removeItem(storageKey); setPending(null); setEnsJob(null); setEnsLabel(""); form.reset(); setMode("strict"); setProgress("complete");
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
        <div className="setup-section-title"><span aria-hidden="true">03</span><h4 id="setup-naming-title">ENS & policy chain</h4></div>
        <div className="setup-fields">
          <div className="setup-field"><label htmlFor="setup-ens">ENS subname · Sepolia</label><input id="setup-ens" name="ens" placeholder="research" value={ensLabel} onChange={e => setEnsLabel(e.target.value)} required maxLength={63} /><small>{ensLabel || "research"}.{AGENT_ENS_PARENT}</small></div>
          <div className="setup-field"><label htmlFor="setup-chain">Policy network</label><PolicyChainSelect account={account} request={request} /></div>
        </div>
      </section>
    </fieldset>
    {pending && <div className="detail"><b>{pending.ens_name}</b><p>Agent wallet: {pending.signing_address}</p>
      <p role="status">{({registration:"Registering subname…", resolver:"Creating its resolver…", attachment:"Attaching resolver…", address:"Setting agent address…", verify:"Checking ENS address…", permissions:"Saving agent and permissions…"})[progress] || "Setup saved. Resume to continue."}</p>
      {Object.entries(ensJob || {}).filter(([,v]) => v?.transactionHash).map(([step,v]) => <p key={step}><a target="_blank" rel="noreferrer" href={`https://sepolia.etherscan.io/tx/${v.transactionHash}`}>{step} transaction ↗</a></p>)}
    </div>}
    {!pending && <p className="muted">Registers the subname on Sepolia, sets its agent address, then adds memory permissions. Confirm each transaction in your wallet using test ETH.</p>}
    <footer className="agent-setup-footer">

      <div className="inline">
        {pending && !busy && !["registration","resolver","attachment","address"].some(step => ensJob?.[step]) && <button type="button" onClick={() => {localStorage.removeItem(storageKey); setPending(null); setEnsJob(null); setError("");}}>Edit setup</button>}
        <button disabled={busy}>{busy ? "Setting up agent…" : pending ? "Resume agent setup" : "Register ENS and add agent"}</button>
      </div>
    </footer>
  </form>;
}
