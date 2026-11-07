"use client";
import ActionNotice from "./ActionNotice";
import { proofLabel } from "./MemoryProof";
import { signedRequest } from "../lib/gateway.mjs";
import { useEffect, useMemo, useState } from "react";
import {
  MemorySealClient,
  walletSigner,
  generateIdentity,
  exportIdentity,
  importIdentity,
  newKey,
  keyFingerprint,
  sha256,
  unb64,
  wrapKey,
  sealRecord,
  openRecord,
} from "../../sdk/typescript/dist/index.js";

export default function TeamVaultPanel({ account, signal, mode }) {
  const sdk = useMemo(() => {
    const signer = walletSigner(window.ethereum, account);
    const client = new MemorySealClient(
      {
        address: account,
        signMessage: async (message) => {
          signal.throwIfAborted();
          const s = await signer.signMessage(message);
          signal.throwIfAborted();
          return s;
        },
      },
      process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8000",
      process.env.NEXT_PUBLIC_GATEWAY_AUDIENCE || "memoryseal-local",
    );
    const signedSdkRequest = client.request.bind(client);
    client.request = (method, path, payload) => method !== "GET"
      ? signedSdkRequest(method, path, payload, signal)
      : signedRequest({
      account, method, path, payload, signal, wallet: window.ethereum, useSession: true,
      api: process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8000",
      audience: process.env.NEXT_PUBLIC_GATEWAY_AUDIENCE || "memoryseal-local",
    });
    return client;
  }, [account, signal]);
  const [agentOptions, setAgentOptions] = useState([]);
  const [recipient, setRecipient] = useState("");
  const [recipientPin, setRecipientPin] = useState("");
  const [pinConfirmed, setPinConfirmed] = useState(false);
  const [setupRegistered, setSetupRegistered] = useState(false);
  const [teamTab, setTeamTab] = useState("members");
  const [teamsLoaded, setTeamsLoaded] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [orgs, setOrgs] = useState([]),
    [org, setOrg] = useState(null),
    [name, setName] = useState(""),
    [member, setMember] = useState(""),
    [role, setRole] = useState("auditor"),
    [agent, setAgent] = useState(""),
    [grant, setGrant] = useState({
      agent_id: "",
      operation: "read",
      resource: "",
      max_amount: "",
    });
  const [identity, setIdentity] = useState(null),
    [password, setPassword] = useState(""),
    [backedUp, setBackedUp] = useState(false),
    [fingerprint, setFingerprint] = useState(""),
    [scopes, setScopes] = useState([]),
    [scopeId, setScopeId] = useState(""),
    [namespace, setNamespace] = useState(""),
    [owner, setOwner] = useState(account.toLowerCase()),
    [pins, setPins] = useState(""),
    [rows, setRows] = useState([]),
    [next, setNext] = useState(null),
    [content, setContent] = useState(""),
    [writer, setWriter] = useState(""),
    [pending, setPending] = useState(null),
    [rotation, setRotation] = useState(null),
    [checked, setChecked] = useState({});
  useEffect(() => {
    if (!pending && (!identity || backedUp)) return;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [pending, identity, backedUp]);
  const [vaultSetupMode, setVaultSetupMode] = useState("create");
  const [pendingKeyStale, setPendingKeyStale] = useState(false);
  const [provenance, setProvenance] = useState({});
  const scope = scopes.find((s) => s.id === scopeId);
  useEffect(() => { run(async () => {
    if (mode === "teams") await loadOrgs();
    else {
      await loadScopes();
      const access = await sdk.request("GET", "/agent-access");
      setAgentOptions(access.agents.filter(a => !a.revoked));
      if (access.agents.length === 1) setWriter(access.agents[0].id);
    }
  }); }, [account, mode]);
  useEffect(() => { if (scope && identity) run(() => readRows()); }, [scopeId, identity]);
  useEffect(() => {
    if (identity && fingerprint) setPins(p => p || `${account.toLowerCase()} ${fingerprint}`);
  }, [identity, fingerprint, account]);
  async function run(fn) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      signal.throwIfAborted();
      await fn();
    } catch (e) {
      setError(e.message || "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  async function loadOrgs() {
    const list = (await sdk.organizations()).organizations;
    setOrgs(list);
    setTeamsLoaded(true);
    const current = list.find(o => o.id === org?.id);
    if (current || list.length === 1) await loadOrg(current?.id || list[0].id);
    else setOrg(null);
  }
  async function loadOrg(id) {
    setOrg(await sdk.organization(id));
  }
  async function loadScopes() {
    const list = (await sdk.vaultNamespaces()).namespaces;
    setScopes(list);
    setScopeId(current => list.some(s => s.id === current) ? current : list.length === 1 ? list[0].id : "");
    return list;
  }
  async function installIdentity(i) {
    setIdentity(i);
    const nextFingerprint = await sha256(unb64(i.publicKey));
    setFingerprint(nextFingerprint);
    setPins(`${account.toLowerCase()} ${nextFingerprint}`);
    setSetupRegistered(false);
    setRows([]);
  }
  function download(value) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `memoryseal-encryption-${account.slice(2, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function makeEpoch(s) {
    const key = newKey(),
      envelopes = {};
    const entries = pins.trim().split(/\n+/).filter(Boolean);
    for (const line of entries) {
      const [address, pin, ...extra] = line.trim().split(/\s+/);
      if (
        extra.length ||
        !/^0x[0-9a-fA-F]{40}$/.test(address) ||
        !/^[0-9a-f]{64}$/.test(pin || "")
      )
        throw new Error(
          "Each recipient line needs an address and independently checked fingerprint",
        );
      const a = address.toLowerCase();
      const publicIdentity = await sdk.encryptionIdentity(a);
      envelopes[a] = await wrapKey(
        key,
        publicIdentity.public_key,
        pin,
        s.id,
        s.active_version,
        a,
      );
    }
    return { fingerprint: await keyFingerprint(key), envelopes };
  }
  async function readRows(after = "") {
    if (!identity) throw new Error("Unlock your encryption identity first");
    const page = await sdk.vaultRecords(scope, after);
    const result = [];
    for (const row of page.records) {
      try {
        const key = await sdk.vaultKey(scope, identity, row.key_version);
        const opened = await openRecord(scope, key, row);
        result.push({ ...row, content: opened.content });
      } catch {
        result.push({
          ...row,
          decryptionError:
            "Unable to decrypt or commitment mismatch. Do not approve this record.",
        });
      }
    }
    setRows(result);
    setChecked({});
    setNext(page.next_after);
  }
  return (
    <section className={`agent-workbench ${mode === "teams" ? "organization-workspace" : "vault-workspace"}`}>
      <ActionNotice message={error} onClose={() => setError("")} />
      {notice && (
        <p role="status" className="detail">
          {notice}
        </p>
      )}
      {mode === "teams" ? (
        <>

          <div className="organization-toolbar"><div><span className="organization-eyebrow">WORKSPACE DIRECTORY</span><h2>Your organizations</h2></div><button className="organization-refresh" disabled={busy} onClick={() => run(loadOrgs)} aria-label="Refresh organizations">↻ Refresh</button></div>
          {!teamsLoaded && <p role="status">{busy ? "Loading organizations…" : "Organizations could not be loaded. Try Refresh."}</p>}
          {teamsLoaded && <div className="organization-directory">
            <div className="organization-list">
              {orgs.length === 0 ? <div className="organization-empty"><div className="organization-art" aria-hidden="true"><span>◎</span><span>◇</span><span>⊞</span></div><h3>Make room for your team.</h3><p>Bring agents and collaborators into one organization.</p></div> : orgs.map(o => <button key={o.id} className={`organization-choice ${org?.id === o.id ? "selected" : ""}`} disabled={busy} aria-pressed={org?.id === o.id} onClick={() => run(() => loadOrg(o.id))}><span className="organization-avatar" aria-hidden="true">{o.name.slice(0,1).toUpperCase()}</span><span className="organization-choice-name"><b>{o.name}</b><small>{o.role}</small></span><span aria-hidden="true">↗</span></button>)}
            </div>
            {!orgs.some(o => o.role === "owner") && <form className="organization-create" onSubmit={e => {e.preventDefault(); if (!name.trim() || busy) return; run(async () => {const created = await sdk.createOrganization(name.trim()); setName(""); await loadOrgs(); await loadOrg(created.id); setTeamTab("members");});}}>
              <span className="organization-eyebrow">NEW ORGANIZATION</span><h3>Start a team</h3><label htmlFor="organization-name">Organization name</label><input id="organization-name" placeholder="e.g. Research collective" value={name} maxLength={100} required disabled={busy} onChange={e => setName(e.target.value)} /><button disabled={busy || !name.trim()}>{busy ? "Please wait…" : "Create organization ↗"}</button><small>You’ll be the owner · one wallet signature</small>
            </form>}
          </div>}
          {org && (
            <>
              <div className="organization-selected">
                <div className="organization-selected-title"><span className="organization-avatar" aria-hidden="true">{org.name.slice(0,1).toUpperCase()}</span><div><h3>{org.name}</h3><span className="organization-role">{org.role}</span></div></div>
                <div className="organization-stats"><span><b>{org.members.length}</b> collaborators</span><span><b>{org.agents.filter(a => !a.revoked).length}</b> active agents</span></div>
              </div>
              <details className="organization-identity"><summary>Organization details</summary><p>Owner: {org.owner_address}</p><p>Membership version: {org.version}</p></details>
              <nav className="operation-tabs" aria-label="Team sections">{["members", "agents", "permissions"].map(tab => <button key={tab} aria-current={teamTab === tab ? "page" : undefined} onClick={() => setTeamTab(tab)}>{tab.charAt(0).toUpperCase()+tab.slice(1)}</button>)}</nav>
              {teamTab === "members" && <div className="organization-members">{org.members.length === 0 ? <p>No collaborators added yet.</p> : org.members.map(m => <div className="organization-member" key={m.address}><span className="organization-member-address">{m.address}</span><span className="organization-role">{m.role}</span></div>)}</div>}
              {org.role === "owner" && teamTab === "members" && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await sdk.setMember(org.id, member, role, org.version);
                      await loadOrg(org.id);
                    });
                  }}
                >
                  <h3>Membership</h3>
                  <input
                    aria-label="Member wallet"
                    placeholder="Member wallet address"
                    value={member}
                    onChange={(e) => setMember(e.target.value)}
                    required
                  />
                  <select
                    aria-label="Member role"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    <option>auditor</option>
                    <option>admin</option>
                    <option>remove</option>
                  </select>
                  <button disabled={busy}>Save member</button>
                </form>
              )}
              {org.role !== "auditor" && (
                <>
                  <div hidden={teamTab !== "agents"}><h3>Add team agent</h3>
                  <div className="inline">
                    <input
                      aria-label="Organization agent wallet"
                      value={agent}
                      onChange={(e) => setAgent(e.target.value)}
                      placeholder="Agent signing address"
                    />
                    <button
                      disabled={busy || !agent}
                      onClick={() =>
                        run(async () => {
                          await sdk.registerOrganizationAgent(org.id, agent);
                          await loadOrg(org.id);
                        })
                      }
                    >
                      Register
                    </button>
                  </div>
                  </div><div hidden={teamTab !== "permissions"}><h3>Collection permissions</h3>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      run(async () => {
                        await sdk.grantOrganization(org.id, {
                          ...grant,
                          max_amount:
                            grant.operation === "transfer"
                              ? grant.max_amount
                              : null,
                        });
                        await loadOrg(org.id);
                      });
                    }}
                  >
                    <select
                      aria-label="Organization agent"
                      required
                      value={grant.agent_id}
                      onChange={(e) =>
                        setGrant({ ...grant, agent_id: e.target.value })
                      }
                    >
                      <option value="">Choose agent</option>
                      {org.agents
                        .filter((a) => !a.revoked)
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.signing_address}
                          </option>
                        ))}
                    </select>
                    <select
                      aria-label="Operation"
                      value={grant.operation}
                      onChange={(e) =>
                        setGrant({ ...grant, operation: e.target.value })
                      }
                    >
                      {["read", "write", "transfer"].map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                    <input
                      aria-label="Capability resource"
                      required
                      placeholder="Exact namespace or chain-scoped asset"
                      value={grant.resource}
                      onChange={(e) =>
                        setGrant({ ...grant, resource: e.target.value })
                      }
                    />
                    {grant.operation === "transfer" && (
                      <input
                        aria-label="Maximum amount"
                        required
                        pattern="[0-9]+"
                        placeholder="Maximum base units"
                        value={grant.max_amount}
                        onChange={(e) =>
                          setGrant({ ...grant, max_amount: e.target.value })
                        }
                      />
                    )}
                    <button disabled={busy}>Save permission</button>
                  </form>
                  </div>
                </>
              )}
              {teamTab !== "members" && <h3>{teamTab === "agents" ? "Team agents" : "Active permissions"}</h3>}
              {teamTab === "agents" && org.agents.map((a) => (
                <div className="row" key={a.id}>
                  <span>
                    {a.signing_address} · {a.revoked ? "revoked" : "active"}
                  </span>
                  {org.role !== "auditor" && (
                    <button
                      disabled={busy || a.revoked}
                      onClick={() =>
                        run(async () => {
                          await sdk.revokeOrganization(org.id, "agent", a.id);
                          await loadOrg(org.id);
                        })
                      }
                    >
                      Revoke agent
                    </button>
                  )}
                </div>
              ))}
              {teamTab === "permissions" && org.capabilities.map((c) => (
                <div className="row" key={c.id}>
                  <span>
                    {c.operation} · {c.resource} · {c.max_amount || "namespace"}{" "}
                    · {c.revoked ? "revoked" : "active"}
                  </span>
                  {org.role !== "auditor" && (
                    <button
                      disabled={busy || c.revoked}
                      onClick={() =>
                        run(async () => {
                          await sdk.revokeOrganization(
                            org.id,
                            "capability",
                            c.id,
                          );
                          await loadOrg(org.id);
                        })
                      }
                    >
                      Revoke grant
                    </button>
                  )}
                </div>
              ))}
            </>
          )}
        </>
      ) : (
        <>
          <div className="vault-progress" aria-label="Encryption setup status">
            <span className={identity ? "complete" : ""}>
              {identity ? "✓" : "01"} Identity{" "}
              {identity ? "unlocked" : "locked"}
            </span>
            <span className={backedUp ? "complete" : ""}>
              {backedUp ? "✓" : "02"}{" "}
              {backedUp ? "Backup available" : "Back up your key"}
            </span>
            <span className={scope ? "complete" : ""}>
              {scope ? "✓" : "03"}{" "}
              {scope ? "Collection selected" : "Choose a collection"}
            </span>
          </div>
          <div className="vault-setup-grid">
          <details className="vault-identity-card" open={!identity || !backedUp}>
            <summary>{identity ? "Identity & backup" : "Unlock your vault"}<span className="vault-lock-state">{identity ? "Unlocked" : "Locked"}</span></summary>
            <div className="vault-identity-body">
            <div className="vault-mode-tabs" role="group" aria-label="Vault identity setup">
              <button type="button" aria-pressed={vaultSetupMode === "create"} onClick={() => setVaultSetupMode("create")}>{identity ? "Manage identity" : "Create new"}</button>
              <button type="button" aria-pressed={vaultSetupMode === "restore"} onClick={() => setVaultSetupMode("restore")}>Restore backup</button>
            </div>
            <label htmlFor="vault-backup-password">Backup passphrase</label>
            <input
              id="vault-backup-password"
              type="password"
              autoComplete="new-password"
              aria-label="Encryption backup passphrase"
              placeholder="At least 12 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <div className="inline vault-create-actions" hidden={vaultSetupMode !== "create"}>
              <button disabled={busy || password.length < 12 || setupRegistered} onClick={() => run(async () => {
                const nextIdentity = identity || await generateIdentity();
                await installIdentity(nextIdentity);
                if (!backedUp) { download(await exportIdentity(nextIdentity, password)); setBackedUp(true); }
                await sdk.registerEncryptionIdentity(nextIdentity.publicKey);
                setSetupRegistered(true);
                setNotice("Vault identity registered. Keep your downloaded backup and passphrase safe.");
              })}>{setupRegistered ? "Identity registered" : "Create & back up identity"}</button>
              {identity && <button disabled={busy || password.length < 12} onClick={() => run(async () => {download(await exportIdentity(identity, password)); setBackedUp(true);})}>Download backup again</button>}
            </div>
            <label className="vault-restore-upload" hidden={vaultSetupMode !== "restore"}>
              Encrypted backup file
              <input
                type="file"
                accept="application/json"
                disabled={busy || password.length < 12}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    run(async () => {
                      if (file.size > 10000)
                        throw new Error("Backup file too large");
                      await installIdentity(
                        await importIdentity(
                          JSON.parse(await file.text()),
                          password,
                        ),
                      );
                      setBackedUp(true);
                    });
                }}
              />
            </label>
            {identity && (
              <button
                disabled={busy || !!pending}
                onClick={() => {
                  setIdentity(null);
                  setRows([]);
                  setPassword("");
                  setFingerprint("");
                  setBackedUp(false);
                  setSetupRegistered(false);
                  setPins("");
                }}
              >
                Lock encryption identity
              </button>
            )}
            {fingerprint && (
              <details className="vault-fingerprint"><summary>Public fingerprint</summary><code>{fingerprint}</code></details>
            )}
            <p className="vault-backup-note">Keep your backup and passphrase. Both are needed to restore access after a refresh.</p>
            </div>
          </details>
          <div className="vault-collections-card">
            <header><h3>Collections</h3></header>
            <div className="vault-collections-body">
              <div className="vault-collection-picker"><label htmlFor="vault-collection-picker">Your collections</label><button disabled={busy} onClick={() => run(loadScopes)} aria-label="Refresh collections">↻ Refresh</button></div>
          <select
            id="vault-collection-picker" aria-label="Encrypted collection"
            disabled={busy || !!pending}
            value={scopeId}
            onChange={(e) => {
              setScopeId(e.target.value);
              setRows([]);
              setRotation(null);
            }}
          >
            <option value="">Choose collection</option>
            {scopes.map((s) => (
              <option key={s.id} value={s.id}>
                {s.namespace} · key v{s.active_version}
              </option>
            ))}
          </select>

          <details className="vault-create-collection">
            <summary>Create collection & manage recipients</summary>
            <p>
              Include each recipient’s wallet and verified fingerprint. Permissions alone do not share keys; revocation cannot erase downloaded keys.
            </p>
            <div className="vault-field-pair">
            <label>
              Owner wallet
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value.toLowerCase())}
              />
            </label>
            <label>
              Collection name
              <input
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
              />
            </label>
            </div>
            <div className="recipient-picker">
              <h3>People with a key</h3>
              {pins.trim().split(/\n+/).filter(Boolean).map(line => <div className="row" key={line}><small>{line.split(" ")[0]}</small><button disabled={busy} onClick={() => setPins(p => p.split("\n").filter(l => l !== line).join("\n"))}>Remove</button></div>)}
              <label htmlFor="vault-recipient">Recipient wallet</label>
              <input id="vault-recipient" value={recipient} onChange={e => {setRecipient(e.target.value); setRecipientPin(""); setPinConfirmed(false);}} placeholder="0x…" />
              <button disabled={busy || !/^0x[0-9a-fA-F]{40}$/.test(recipient)} onClick={() => run(async () => {const result = await sdk.encryptionIdentity(recipient); setRecipientPin(await sha256(unb64(result.public_key))); setPinConfirmed(false);})}>Look up public identity</button>
              {recipientPin && <><small>Fingerprint: {recipientPin}</small><label><input type="checkbox" checked={pinConfirmed} onChange={e => setPinConfirmed(e.target.checked)} /> I verified this fingerprint with the recipient.</label><button disabled={busy || !pinConfirmed} onClick={() => {setPins(p => [...p.split("\n").filter(l => l && !l.startsWith(recipient.toLowerCase() + " ")), `${recipient.toLowerCase()} ${recipientPin}`].join("\n")); setRecipient(""); setRecipientPin(""); setPinConfirmed(false);}}>Add recipient</button></>}
              <details><summary>Advanced recipient list</summary><textarea aria-label="Verified recipient addresses and fingerprints" value={pins} onChange={e => setPins(e.target.value)} rows={3} /></details>
            </div>
            <button
              disabled={
                busy ||
                !identity ||
                !namespace ||
                owner !== account.toLowerCase()
              }
              onClick={() =>
                run(async () => {
                  const s = {
                    id: crypto.randomUUID(),
                    owner_address: owner,
                    namespace,
                    active_version: 1,
                  };
                  const epoch = await makeEpoch(s);
                  await sdk.createVault(s, epoch.fingerprint, epoch.envelopes);
                  await loadScopes();
                  setScopeId(s.id);
                })
              }
            >
              Create private collection
            </button>
          </details>
            </div>
          </div>
          </div>
          {scope && (
            <>
              <div className="detail">
                Owner: {scope.owner_address} · active key v
                {scope.active_version}
              </div>
              <div className="workbench-grid">
                <article>
                  <h3>Write an encrypted observation</h3>
                  <label>
                    Agent
                    <select disabled={!!pending} value={writer} onChange={e => setWriter(e.target.value)}><option value="">Choose agent</option>{agentOptions.filter(a => a.owner_address.toLowerCase() === scope.owner_address.toLowerCase()).map(a => <option key={a.id} value={a.id}>{a.label || a.ens_name || a.signing_address}</option>)}</select>
                  </label>
                  <label>
                    Private content
                    <textarea
                      disabled={!!pending}
                      rows={5}
                      value={content}
                      onChange={(e) => setContent(e.target.value)}
                    />
                  </label>
                  <button
                    disabled={busy || !identity || !content || !writer}
                    onClick={() =>
                      run(async () => {
                        let payload = pending;
                        if (!payload) {
                          const key = await sdk.vaultKey(scope, identity);
                          payload = {
                            ...(await sealRecord(scope, key, content)),
                            agent_id: writer,
                          };
                          setPending(payload);
                        }
                        let result;
                        try {
                          result = await sdk.submitVault(scope, payload);
                        } catch (e) {
                          setPendingKeyStale(
                            e.status === 409 &&
                              e.message.includes("stale key version"),
                          );
                          throw e;
                        }
                        setNotice(
                          `Encrypted memory ${payload.id}: ${result.status}.`,
                        );
                        setPending(null);
                        setPendingKeyStale(false);
                        setContent("");
                      })
                    }
                  >
                    {pending
                      ? "Retry exact encrypted write"
                      : "Save private memory"}
                  </button>
                  {pending && pendingKeyStale && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const current = (await loadScopes()).find(
                            (s) => s.id === scope.id,
                          );
                          if (!current)
                            throw new Error("Namespace access unavailable");
                          const key = await sdk.vaultKey(current, identity);
                          setPending({
                            ...(await sealRecord(
                              current,
                              key,
                              content,
                              pending.id,
                            )),
                            agent_id: pending.agent_id,
                          });
                          setPendingKeyStale(false);
                          setNotice(
                            "Re-encrypted the rejected attempt with the current key. Sign its retry to submit.",
                          );
                        })
                      }
                    >
                      Refresh key and re-encrypt rejected attempt
                    </button>
                  )}
                  {pending && (
                    <p>
                      Pending ID: {pending.id}. Keep this page open; retries
                      retain the exact ciphertext.
                    </p>
                  )}
                </article>
                <article>
                  <h3>Read and review</h3>
                  <button
                    disabled={busy || !identity}
                    onClick={() => run(() => readRows())}
                  >
                    Refresh memories
                  </button>
                  <p>
                    Readers need both permission and a key.
                  </p>
                  {scope.can_manage && (
                    <>
                      <details><summary>Security · rotate encryption key</summary>
                      <p>
                        New writes use the new key immediately. Migrate older records before retiring backups.
                      </p>
                      <button
                        disabled={
                          busy ||
                          !identity ||
                          !!pending ||
                          scope.owner_address !== account.toLowerCase()
                        }
                        onClick={() =>
                          run(async () => {
                            const epoch = await makeEpoch({
                              ...scope,
                              active_version: scope.active_version + 1,
                            });
                            await sdk.rotateVault(
                              scope,
                              epoch.fingerprint,
                              epoch.envelopes,
                            );
                            await loadScopes();
                            setRotation(await sdk.rotationStatus(scope));
                          })
                        }
                      >
                        Rotate to a fresh key
                      </button>
                      <button
                        disabled={busy || !identity}
                        onClick={() =>
                          run(async () => {
                            setRotation(
                              (await sdk.migrateVaultBatch(scope, identity))
                                .status,
                            );
                          })
                        }
                      >
                        Migrate next batch (one signature)
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () =>
                            setRotation(await sdk.rotationStatus(scope)),
                          )
                        }
                      >
                        Refresh progress
                      </button>
                      {rotation && (
                        <p>
                          Active v{rotation.active_version} ·{" "}
                          {rotation.remaining} records still use older keys
                        </p>
                      )}
                      </details>
                    </>
                  )}
                </article>
              </div>
              {rows.map((row) => (
                <article className="detail" key={row.id}>
                  <b>
                    {row.status} · key v{row.key_version}
                  </b>
                  <small>{row.id}</small>
                  {row.decryptionError ? (
                    <p role="alert">{row.decryptionError}</p>
                  ) : (
                    <p style={{ whiteSpace: "pre-wrap" }}>{row.content}</p>
                  )}
                  {scope.can_manage && (
                    <>
                      <label>
                        <input
                          type="checkbox"
                          checked={!!checked[row.id]}
                          onChange={(e) =>
                            setChecked({
                              ...checked,
                              [row.id]: e.target.checked,
                            })
                          }
                        />{" "}
                        I reviewed this exact content for sharing. It grants no
                        action authority.
                      </label>
                      <button
                        disabled={
                          busy || !!row.decryptionError || !checked[row.id]
                        }
                        onClick={() =>
                          run(async () => {
                            await sdk.reviewVault(scope, row, true);
                            await readRows();
                          })
                        }
                      >
                        Allow sharing
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await sdk.reviewVault(scope, row, false);
                            await readRows();
                          })
                        }
                      >
                        Quarantine
                      </button>
                      <details><summary>Proof and recovery</summary>
                      <p>
                        Only lifecycle metadata is published—not private content or keys.
                      </p>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            const events = (
                              await sdk.vaultEvents(scope, row.id)
                            ).events;
                            setProvenance((p) => ({ ...p, [row.id]: events }));
                          })
                        }
                      >
                        Load provenance events
                      </button>
                      {provenance[row.id]?.map((e) => (
                        <div key={e.id}>
                          <small>
                            {e.event_type.replaceAll("_", " ")} · {proofLabel(e.state)} · {e.entity_key || e.id}
                          </small>
                          {["pending", "uncertain", "published"].includes(
                            e.state,
                          ) && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                run(async () => {
                                  const result = await sdk.vaultEventAction(
                                    scope,
                                    row.id,
                                    e.id,
                                    e.state === "pending"
                                      ? "publish"
                                      : e.state === "uncertain"
                                        ? "reconcile"
                                        : "observe",
                                  );
                                  setNotice(
                                    `Provenance result: ${result.state}`,
                                  );
                                  const events = (
                                    await sdk.vaultEvents(scope, row.id)
                                  ).events;
                                  setProvenance((p) => ({
                                    ...p,
                                    [row.id]: events,
                                  }));
                                })
                              }
                            >
                              {e.state === "pending"
                                ? "Publish metadata"
                                : e.state === "uncertain"
                                  ? "Reconcile without republishing"
                                  : "Check public record"}
                            </button>
                          )}
                        </div>
                      ))}
                      </details>
                    </>
                  )}
                </article>
              ))}
              {next && (
                <button
                  disabled={busy}
                  onClick={() => run(() => readRows(next))}
                >
                  Next encrypted records
                </button>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
