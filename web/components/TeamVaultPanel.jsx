"use client";
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
    return new MemorySealClient(
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
  }, [account, signal]);
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
  const [pendingKeyStale, setPendingKeyStale] = useState(false);
  const [provenance, setProvenance] = useState({});
  const scope = scopes.find((s) => s.id === scopeId);
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
    setOrgs((await sdk.organizations()).organizations);
  }
  async function loadOrg(id) {
    setOrg(await sdk.organization(id));
  }
  async function loadScopes() {
    const list = (await sdk.vaultNamespaces()).namespaces;
    setScopes(list);
    return list;
  }
  async function installIdentity(i) {
    setIdentity(i);
    setFingerprint(await sha256(unb64(i.publicKey)));
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
    <section className="agent-workbench">
      <div className="section-head">
        <h2>
          {mode === "teams"
            ? "Organization policies"
            : "Client-encrypted memory"}
        </h2>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="detail">
          {notice}
        </p>
      )}
      {mode === "teams" ? (
        <>
          <p>
            One organization belongs to one owner wallet. It includes that
            wallet’s existing gateway agents and policies. Admins manage gateway
            grants; auditors see team metadata. Neither role can sign the
            owner’s onchain transactions.
          </p>
          <div className="inline">
            <input
              aria-label="Organization name"
              placeholder="Organization name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button
              disabled={busy || !name}
              onClick={() =>
                run(async () => {
                  await sdk.createOrganization(name);
                  await loadOrgs();
                })
              }
            >
              Create organization
            </button>
            <button disabled={busy} onClick={() => run(loadOrgs)}>
              Load my organizations
            </button>
          </div>
          <label>
            Organization
            <select
              value={org?.id || ""}
              onChange={(e) => run(() => loadOrg(e.target.value))}
            >
              <option value="">Choose organization</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} · {o.role}
                </option>
              ))}
            </select>
          </label>
          {org && (
            <>
              <div className="detail">
                <b>
                  {org.name} · {org.role}
                </b>
                <p>
                  Owner: {org.owner_address} · membership version {org.version}
                </p>
                {org.members.map((m) => (
                  <p key={m.address}>
                    {m.address} · {m.role}
                  </p>
                ))}
              </div>
              {org.role === "owner" && (
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
                  <button disabled={busy}>Sign membership change</button>
                </form>
              )}
              {org.role !== "auditor" && (
                <>
                  <h3>Register an agent</h3>
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
                  <h3>Grant a capability</h3>
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
                    <button disabled={busy}>Sign grant</button>
                  </form>
                </>
              )}
              <h3>Agents and grants</h3>
              {org.agents.map((a) => (
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
              {org.capabilities.map((c) => (
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
          <p>
            Content is encrypted and decrypted in this browser. The gateway
            stores ciphertext and metadata, and does not send these records to
            0G. Release requires a person to inspect the decrypted content.
            Existing gateway-encrypted memories remain in Memories.
          </p>
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
              {scope ? "Namespace selected" : "Choose a namespace"}
            </span>
          </div>
          <details open>
            <summary>1. Unlock your encryption identity</summary>
            <p>
              Use a separate encryption identity for each wallet. Keep the
              encrypted backup and passphrase: refreshing clears the in-memory
              key. Losing both means losing access. Register recipients’
              identities before sharing keys.
            </p>
            <input
              type="password"
              autoComplete="new-password"
              aria-label="Encryption backup passphrase"
              placeholder="Backup passphrase (at least 12 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <div className="inline">
              <button
                disabled={busy || !!identity}
                onClick={() =>
                  run(async () => {
                    await installIdentity(await generateIdentity());
                    setBackedUp(false);
                  })
                }
              >
                Generate encryption identity
              </button>
              <button
                disabled={busy || !identity || password.length < 12}
                onClick={() =>
                  run(async () => {
                    download(await exportIdentity(identity, password));
                    setBackedUp(true);
                    setNotice(
                      "Encrypted backup downloaded. Keep it and its passphrase separate.",
                    );
                  })
                }
              >
                Download encrypted backup
              </button>
              <button
                disabled={busy || !identity || !backedUp}
                onClick={() =>
                  run(async () => {
                    await sdk.registerEncryptionIdentity(identity.publicKey);
                    setNotice(
                      "Public encryption identity registered. Share only its fingerprint.",
                    );
                  })
                }
              >
                Register public identity
              </button>
            </div>
            <label>
              Restore encrypted backup
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
                }}
              >
                Lock encryption identity
              </button>
            )}
            {fingerprint && (
              <p>
                Public fingerprint: <code>{fingerprint}</code>
              </p>
            )}
          </details>
          <details>
            <summary>
              2. Create a namespace or prepare rotation recipients
            </summary>
            <p>
              Each line: wallet address, then its public-key fingerprint
              verified with that person. Include the owner and every current
              reader/writer who should receive the new key. A read grant alone
              does not distribute a key. Removing a grant does not erase keys
              already downloaded.
            </p>
            <label>
              Owner wallet
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value.toLowerCase())}
              />
            </label>
            <label>
              New namespace
              <input
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
              />
            </label>
            <label>
              Verified recipients
              <textarea
                rows={4}
                value={pins}
                onChange={(e) => setPins(e.target.value)}
                placeholder="0x... fingerprint"
              />
            </label>
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
              Create encrypted namespace
            </button>
          </details>
          <button disabled={busy} onClick={() => run(loadScopes)}>
            Load accessible namespaces
          </button>
          <select
            aria-label="Encrypted namespace"
            disabled={busy || !!pending}
            value={scopeId}
            onChange={(e) => {
              setScopeId(e.target.value);
              setRows([]);
              setRotation(null);
            }}
          >
            <option value="">Choose namespace</option>
            {scopes.map((s) => (
              <option key={s.id} value={s.id}>
                {s.namespace} · key v{s.active_version}
              </option>
            ))}
          </select>
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
                    Agent registration ID
                    <input
                      disabled={!!pending}
                      value={writer}
                      onChange={(e) => setWriter(e.target.value)}
                      placeholder="UUID from Agent console"
                    />
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
                      : "Encrypt locally and sign write"}
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
                    Fetch and decrypt locally
                  </button>
                  <p>
                    Agents receive only released records and need current
                    namespace access plus the relevant key envelope. Managers
                    can inspect quarantine.
                  </p>
                  {scope.can_manage && (
                    <>
                      <h3>Online key rotation</h3>
                      <p>
                        The owner updates recipients above and signs a fresh key
                        version. New writes use it immediately; migrate old
                        records in resumable batches. Keep old identity backups
                        until migration completes.
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
                        Migrate next batch
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () =>
                            setRotation(await sdk.rotationStatus(scope)),
                          )
                        }
                      >
                        Check rotation progress
                      </button>
                      {rotation && (
                        <p>
                          Active v{rotation.active_version} ·{" "}
                          {rotation.remaining} records still use older keys
                        </p>
                      )}
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
                        Sign release
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
                      <p>
                        Public provenance contains commitments and lifecycle
                        metadata, never content or encrypted key envelopes.
                        These are gateway assertions, not independent
                        attestations.
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
                            {e.event_type} · {e.state} · {e.entity_key || e.id}
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
