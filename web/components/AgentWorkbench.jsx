"use client";
import ActionNotice from "./ActionNotice";
import SavedMemoryModal from "./SavedMemoryModal";

import { useEffect, useState } from "react";
import { parseUnits } from "viem";
import { capabilityActive } from "../lib/expiry.mjs";
import { verifyMemoryCommitment } from "../lib/commitment.mjs";
import {
  executeProtectedTransfer,
  onchainVersion,
  onchainReceipt,
} from "../lib/chain.mjs";

export default function AgentWorkbench({ account, request, signal }) {
  const [operation, setOperation] = useState("write");
  const [access, setAccess] = useState(null);
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [namespace, setNamespace] = useState("research");
  const [content, setContent] = useState("");
  const [source, setSource] = useState("agent");
  const [parentId, setParentId] = useState("");
  const [attempt, setAttempt] = useState(null);
  const [written, setWritten] = useState(null);
  const [showSaved, setShowSaved] = useState(false);
  const [savedDraft, setSavedDraft] = useState(null);
  const [tokenDecimals, setTokenDecimals] = useState(null);
  const [ack, setAck] = useState(null);
  const [ackId, setAckId] = useState(null);
  const [page, setPage] = useState(null);
  const [readScope, setReadScope] = useState(null);
  const [asset, setAsset] = useState("");
  const [amount, setAmount] = useState("");
  const [simulation, setSimulation] = useState(null);
  const [networks, setNetworks] = useState([]);
  const [chain, setChain] = useState({
    registry: "",
    executor: "",
    chainId: "11155111",
    token: "",
    recipient: "",
    amount: "",
    policyVersion: "",
  });
  const [chainResult, setChainResult] = useState(null);
  useEffect(() => {
    if (!attempt || written) return;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [attempt, written]);
  const selected = access?.agents.find((a) => a.id === agentId);
  const call = (method, path, payload) =>
    request(account, method, path, payload);
  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      signal?.throwIfAborted();
      await fn();
    } catch (e) {
      setError(e.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { run(load); }, [account]);
  const collections = [...new Set((selected?.capabilities || []).filter(c => capabilityActive(c) && c.operation === (operation === "read" ? "read" : "write")).map(c => c.resource))];
  useEffect(() => {
    if (!attempt && collections.length && !collections.includes(namespace)) {
      let remembered;
      try { remembered = sessionStorage.getItem(`collection:${account}:${agentId}`); } catch {}
      setNamespace(collections.includes(remembered) ? remembered : collections[0]);
    }
  }, [agentId, operation, collections.join("|"), !!attempt]);
  useEffect(() => { if (agentId && namespace) {try {sessionStorage.setItem(`collection:${account}:${agentId}`, namespace);} catch {}} }, [account, agentId, namespace]);
  async function loadContracts() {
    const [r, list] = await Promise.all([call("GET", "/integrations/readiness"), call("GET", "/chains")]);
    setNetworks(list.chains);
    setChain(p => ({...p, registry:r.onchain_registry || "", executor:r.onchain_executor || "", chainId:String(r.onchain_chain_id || 11155111)}));
  }
  useEffect(() => { if (operation === "transfer" && !networks.length) run(loadContracts); }, [operation]);
  async function decimals() {
    if (!/^0x[0-9a-fA-F]{40}$/.test(chain.token)) throw new Error("Choose a valid token address.");
    if (BigInt(await window.ethereum.request({method:"eth_chainId"})) !== BigInt(chain.chainId)) throw new Error("Switch your wallet to the selected network.");
    const raw = await window.ethereum.request({method:"eth_call", params:[{to:chain.token, data:"0x313ce567"}, "latest"]});
    if (!/^0x[0-9a-fA-F]{64}$/.test(raw) || BigInt(raw) > 36n) throw new Error("Could not verify token decimals.");
    return Number(BigInt(raw));
  }
  useEffect(() => {
    let active = true; setTokenDecimals(null);
    if (/^0x[0-9a-fA-F]{40}$/.test(chain.token)) decimals().then(d => {if(active)setTokenDecimals(d);}).catch(() => {});
    return () => {active = false;};
  }, [chain.token, chain.chainId]);
  async function preparedChainArgs() {
    const d = await decimals();
    if (!/^\d+(\.\d+)?$/.test(chain.amount) || (chain.amount.split(".")[1]?.length || 0) > d) throw new Error("Enter a positive amount within the token’s decimal precision.");
    const policyVersion = await onchainVersion(window.ethereum, chain.registry, chain.chainId, selected.owner_address);
    return {...chainArgs(), amount:parseUnits(chain.amount, d).toString(), policyVersion};
  }
  useEffect(() => {
    if (!chainResult?.transactionHash || !["pending", "submitted"].includes(chainResult.status)) return;
    let active = true;
    const timer = setInterval(async () => {
      try {const status = await onchainReceipt(window.ethereum, chainResult.executor, chainResult.chainId, chainResult.transactionHash, chainResult.agent);
        if (active) setChainResult(p => p?.transactionHash === chainResult.transactionHash ? {...p, status} : p);
      } catch {}
    }, 4000);
    return () => {active = false; clearInterval(timer);};
  }, [chainResult?.transactionHash, chainResult?.status]);
  async function load() {
    const value = await call("GET", "/agent-access");
    setAccess(value);
    if (!value.agents.some((a) => a.id === agentId))
      setAgentId(value.agents[0]?.id || "");
  }
  async function write() {
    const body = attempt || {
      agent_id: agentId,
      namespace,
      content,
      source_type: source,
      parent_id: parentId || null,
      request_id: crypto.randomUUID(),
    };
    setAttempt(body);
    const result = await call("POST", "/memory/write", body);
    setWritten(result); setShowSaved(true); setSavedDraft(body); setAttempt(null); setContent(""); setParentId(""); setAck(null); setAckId(null);
  }
  async function read(offset = 0, scope = { agentId, namespace }) {
    const value = await call("POST", "/memory/read", {
      agent_id: scope.agentId,
      namespace: scope.namespace,
      offset,
      limit: 25,
    });
    setReadScope(scope);
    setPage(value);
  }
  function updateChain(key, value) {
    setChain((prev) => ({ ...prev, [key]: value }));
  }
  const chainArgs = () => ({
    ...chain,
    owner: selected.owner_address,
    agent: account,
    observeDeployment: async () =>
      (
        await call(
          "GET",
          `/onchain/observe-deployment?chain_id=${chain.chainId}`,
        )
      ).observation,
  });
  return (
    <section className="agent-workbench" data-operation={operation}>
      <div className="section-head">
        <div>
          <h2>Agent playground</h2>

        </div>
        <button disabled={busy} onClick={() => run(load)}>
          Refresh access
        </button>
      </div>
      <ActionNotice message={error} onClose={() => setError("")} />
      {access && access.agents.length === 0 && (
        <div className="detail">
          This wallet has no agent registrations. Connect a registered agent
          wallet, or register this address from your owner wallet in Agents.
        </div>
      )}
      {access?.agents.length > 0 && (
        <>
          <label htmlFor="workbench-agent">Agent registration</label>
          <select
            id="workbench-agent"
            disabled={busy || !!attempt}
            value={agentId}
            onChange={(e) => {
              setAgentId(e.target.value);
              setPage(null);
              setReadScope(null);
              setSimulation(null);
              setChainResult(null);
            }}
          >
            {access.agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label || a.ens_name || a.id.slice(0, 8)}
                {a.revoked ? " · revoked" : ""}
              </option>
            ))}
          </select>
        </>
      )}
      {selected && (
        <>
          <details className="agent-access-card">
            <summary>Agent permissions <span>{selected.capabilities.filter(c => !selected.revoked && capabilityActive(c)).length} active</span></summary>
            <div className="agent-access-heading">
              <div><small>AGENT IDENTITY</small><h3>{selected.label || selected.ens_name || "Registered agent"}</h3></div>
              <span className={`access-status ${selected.revoked ? "inactive" : ""}`}>{selected.revoked ? "Revoked" : "Registered"}</span>
            </div>
            <dl className="agent-access-meta"><div><dt>Owner wallet</dt><dd title={selected.owner_address}>{selected.owner_address.slice(0,8)}…{selected.owner_address.slice(-6)}</dd></div><div><dt>Policy version</dt><dd>{selected.policy_version}</dd></div></dl>
            <div className="agent-grant-list">
              {selected.capabilities.length === 0 && <p>No permissions granted yet.</p>}
              {selected.capabilities.map(c => {
                const state = selected.revoked ? "Agent revoked" : c.revoked ? "Revoked" : capabilityActive(c) ? "Active" : "Expired";
                return <div className={`agent-grant ${state !== "Active" ? "inactive" : ""}`} key={c.id}>
                  <span className="agent-grant-icon" aria-hidden="true">{c.operation === "read" ? "↗" : c.operation === "write" ? "+" : "⇄"}</span>
                  <div className="agent-grant-description"><b>{c.operation.charAt(0).toUpperCase()+c.operation.slice(1)}</b><span>{c.resource}</span>
                    {c.max_amount && <small>Maximum {c.max_amount} base units</small>}
                    {c.expires_at && <small>Expires {new Date(/[zZ]|[+-]\d\d:\d\d$/.test(c.expires_at) ? c.expires_at : `${c.expires_at}Z`).toLocaleString()}</small>}
                  </div><span className={`access-status ${state !== "Active" ? "inactive" : ""}`}>{state}</span>
                </div>;
              })}
            </div>

          </details>
          <nav className="operation-tabs" aria-label="Agent operations">
            {[
              ["write", "Write memory"],
              ["read", "Read memories"],
              ["simulate", "Simulate permission"],
              ["transfer", "Onchain transfer"],
            ].map(([id, label]) => (
              <button
                key={id}
                aria-current={operation === id ? "page" : undefined}
                onClick={() => setOperation(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="workbench-grid">
            <article className="operation-write">
              <h3>New memory</h3>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(write);
                }}
              >
                <label htmlFor="wb-namespace">Collection</label>
                <select id="wb-namespace" required disabled={!!attempt} value={namespace} onChange={e => setNamespace(e.target.value)}>
                  {!collections.includes(namespace) && <option value={namespace}>{namespace || "Choose collection"}</option>}
                  {collections.map(n => <option key={n} value={n}>{n}</option>)}
                </select>
                {!collections.length && <p>No active write permission. Ask the owner to grant collection access.</p>}
                <label htmlFor="wb-content">Memory content</label>
                <textarea
                  id="wb-content"
                  required
                  disabled={!!attempt}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  maxLength={32768}
                  rows={5}
                />
                <details><summary>Advanced: source and related memory</summary>
                <label htmlFor="wb-source">Source</label>
                <select
                  id="wb-source"
                  disabled={!!attempt}
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="agent">Agent observation</option>
                  <option value="external">External content</option>
                </select>
                <label htmlFor="wb-parent">Parent memory ID (optional)</label>
                <input
                  id="wb-parent"
                  disabled={!!attempt}
                  value={parentId}
                  onChange={(e) => setParentId(e.target.value)}
                  placeholder="Link a new version to its predecessor"
                />
                </details>
                <button disabled={busy || selected.revoked || !collections.length}>
                  {busy ? "Saving…" : attempt ? "Retry same save" : "Save memory"}
                </button>
              </form>
              {attempt && (
                <div className="detail">
                  <small>Write request ID: {attempt.request_id}</small>
                  <p>
                    Write not confirmed. Retry this request without reloading.
                  </p>
                </div>
              )}
              {written && (
                <>
                  <button type="button" className="saved-memory-reopen" onClick={() => setShowSaved(true)}>View saved memory</button>
                  <SavedMemoryModal open={showSaved} onClose={() => setShowSaved(false)} written={written}>
                  <h3>Additional proof <span>(optional)</span></h3>
                  <p className="muted">Acknowledgement requires two wallet signatures.</p>
                  <button
                    disabled={busy || !!ack}
                    onClick={() =>
                      run(async () => {
                        const opening = await call(
                          "POST",
                          `/memories/${written.id}/author-commitment-salt`,
                          {},
                        );
                        if (
                          opening.id !== written.id ||
                          opening.commitment !== written.commitment ||
                          !(await verifyMemoryCommitment(
                            savedDraft.content,
                            opening.commitment_salt,
                            written.commitment,
                          ))
                        )
                          throw new Error(
                            "Content does not match the recorded commitment.",
                          );
                        const eventId = ackId || crypto.randomUUID();
                        setAckId(eventId);
                        setAck(
                          await call(
                            "POST",
                            `/memories/${written.id}/attest-origin`,
                            {
                              event_id: eventId,
                              commitment: written.commitment,
                              policy_version: written.policy_version,
                            },
                          ),
                        );
                      })
                    }
                  >
                    Check content and sign acknowledgement
                  </button>
                  {ack && (
                    <p>
                      Signed acknowledgement queued for publication.
                    </p>
                  )}
                  </SavedMemoryModal>
                </>
              )}
            </article>
            <article className="operation-read">
              <h3>Shared memories</h3>
              <label htmlFor="wb-read-namespace">Collection</label>
              <input
                id="wb-read-namespace"
                value={namespace}
                disabled={!!attempt}
                onChange={(e) => setNamespace(e.target.value)}
                maxLength={128}
              />
              {attempt && (
                <p className="muted">
                  Finish the pending write before changing its namespace.
                </p>
              )}
              <button
                disabled={busy || selected.revoked}
                onClick={() => run(() => read())}
              >
                Read memories
              </button>
              {page && (
                <div className="detail">
                  <b>{readScope.namespace}</b>
                  {page.memories.length === 0 && <p>No readable memories.</p>}
                  {page.memories.map((m) => (
                    <div key={m.id}>
                      <small>
                        {m.id} · {m.trust_class}
                      </small>
                      <p>{m.content}</p>
                    </div>
                  ))}
                  {page.next_offset !== null && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(() => read(page.next_offset, readScope))
                      }
                    >
                      Read next page
                    </button>
                  )}
                </div>
              )}
            </article>
            <article className="operation-simulate">
              <h3>Permission check</h3>
              <p className="muted">
                Checks workspace permissions without sending tokens.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(async () => {
                    const current = await call("GET", "/agent-access");
                    setAccess(current);
                    const a = current.agents.find((a) => a.id === agentId);
                    if (!a)
                      throw new Error("Agent registration is unavailable");
                    setSimulation(
                      await call("POST", "/actions/simulate-transfer", {
                        agent_id: agentId,
                        asset,
                        amount,
                        policy_version: a.policy_version,
                      }),
                    );
                  });
                }}
              >
                <label htmlFor="wb-asset">Asset or token address</label>
                <input
                  id="wb-asset"
                  required
                  value={asset}
                  onChange={(e) => setAsset(e.target.value)}
                />
                <label htmlFor="wb-amount">Amount in base units</label>
                <input
                  id="wb-amount"
                  required
                  pattern="[0-9]+"
                  inputMode="numeric"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
                <button disabled={busy || selected.revoked}>
                  Simulate transfer
                </button>
              </form>
              {simulation && (
                <div className="detail">
                  <b>
                    {simulation.allowed ? "Allowed locally" : "Denied locally"}
                  </b>
                  <p>
                    {simulation.reason} · Executed:{" "}
                    {simulation.executed ? "yes" : "no"}
                  </p>
                </div>
              )}
            </article>
          </div>
          <article className="detail operation-transfer">
            <h3>Protected transfer</h3>
            <p>
              Requires the owner’s onchain grant and token allowance. If submission is uncertain, check wallet activity before retrying.
            </p>
            <label>
              Configured chain
              <select
                value={chain.chainId}
                disabled={busy || !!chainResult?.transactionHash}
                onChange={(e) => {
                  const c = networks.find(
                    (n) => String(n.chain_id) === e.target.value,
                  );
                  if (c)
                    setChain((p) => ({
                      ...p,
                      chainId: String(c.chain_id),
                      registry: c.registry,
                      executor: c.executor,
                      policyVersion: "",
                    }));
                }}
              >
                <option value="">Choose chain</option>
                {networks.map((n) => (
                  <option key={n.chain_id} value={n.chain_id}>
                    {n.name} ({n.chain_id})
                  </option>
                ))}
              </select>
            </label>
            <div className="workbench-grid">
              {[
                ["registry", "Registry"],
                ["executor", "Executor"],
                ["chainId", "Expected chain ID"],
                ["token", "Token address"],
                ["recipient", "Recipient"],
                ["amount", "Token amount"],
                ["policyVersion", "Onchain policy version"],
              ].filter(([key]) => !["registry", "executor", "chainId", "policyVersion"].includes(key)).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={chain[key]}
                    onChange={(e) => updateChain(key, e.target.value)}
                  />
                </label>
              ))}
            </div>

            <details><summary>Advanced checks</summary>
            <div className="inline">
              <button
                disabled={busy}
                onClick={() =>
                  run(async () =>
                    updateChain(
                      "policyVersion",
                      await onchainVersion(
                        window.ethereum,
                        chain.registry,
                        chain.chainId,
                        selected.owner_address,
                      ),
                    ),
                  )
                }
              >
                Read policy version
              </button>
              <button
                disabled={
                  busy || selected.revoked || !!chainResult?.transactionHash
                }
                onClick={() =>
                  run(async () =>
                    setChainResult(
                      await executeProtectedTransfer(window.ethereum, {
                        ...(await preparedChainArgs()),
                        simulateOnly: true,
                      }),
                    ),
                  )
                }
              >
                Simulate onchain call
              </button>
            </div></details><div className="inline">
              <button
                disabled={
                  busy || selected.revoked || !!chainResult?.transactionHash
                }
                onClick={() =>
                  run(async () => {
                    const transactionHash = await executeProtectedTransfer(
                      window.ethereum,
                      await preparedChainArgs(),
                    );
                    setChainResult({
                      transactionHash,
                      executor: chain.executor,
                      chainId: chain.chainId,
                      agent: account,
                      status: "submitted",
                    });
                  })
                }
              >
                Sign protected transfer
              </button>
            </div>
            {chainResult && (
              <div className="detail">
                {chainResult.simulated ? (
                  "Simulation passed. No tokens were sent."
                ) : (
                  <>
                    <p>Transaction: {chainResult.transactionHash}</p>
                    <p>Status: {chainResult.status}</p>
                    {chainResult.status !== "submitted" &&
                      chainResult.status !== "pending" && (
                        <button
                          disabled={busy}
                          onClick={() => setChainResult(null)}
                        >
                          Start another transfer
                        </button>
                      )}
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const status = await onchainReceipt(
                            window.ethereum,
                            chainResult.executor,
                            chainResult.chainId,
                            chainResult.transactionHash,
                            chainResult.agent,
                          );
                          setChainResult({ ...chainResult, status });
                        })
                      }
                    >
                      Check receipt
                    </button>
                  </>
                )}
              </div>
            )}
          </article>
        </>
      )}
    </section>
  );
}
