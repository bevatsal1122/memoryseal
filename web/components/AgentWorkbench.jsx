"use client";

import { useEffect, useState } from "react";
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
    setWritten(await call("POST", "/memory/write", body));
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
          <h2>Run the full workflow</h2>
          <p className="muted">
            Connect the Browser, Research, or Finance wallet to act as that
            agent. Owner wallets manage permissions in the other views. Private
            keys never belong in these forms.
          </p>
        </div>
        <button disabled={busy} onClick={() => run(load)}>
          Load my agent access
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
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
                {a.ens_name || a.id}
                {a.revoked ? " · revoked" : ""}
              </option>
            ))}
          </select>
        </>
      )}
      {selected && (
        <>
          <div className="detail">
            <b>{selected.revoked ? "Agent revoked" : "Registered agent"}</b>
            <p>
              Owner: {selected.owner_address} · local policy{" "}
              {selected.policy_version}
            </p>
            <p>
              Permissions are checked again on every request. Listed grants may
              be expired or revoked.
            </p>
            <ul>
              {selected.capabilities.map((c) => (
                <li key={c.id}>
                  {c.operation} · {c.resource}
                  {c.max_amount ? ` · maximum ${c.max_amount} base units` : ""}
                  {c.revoked ? " · revoked" : ""}
                  {c.expires_at ? ` · expires ${c.expires_at}` : ""}
                </li>
              ))}
            </ul>
          </div>
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
              <h3>1. Write a memory</h3>
              <p className="muted">
                Temporary non-private inference: use synthetic content only. A
                successful write may still be quarantined.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(write);
                }}
              >
                <label htmlFor="wb-namespace">Namespace</label>
                <input
                  id="wb-namespace"
                  required
                  disabled={!!attempt}
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  maxLength={128}
                />
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
                <button disabled={busy || selected.revoked || !!written}>
                  {written
                    ? "Memory recorded"
                    : attempt
                      ? "Retry the same write"
                      : "Sign and write"}
                </button>
              </form>
              {attempt && (
                <div className="detail">
                  <small>Write request ID: {attempt.request_id}</small>
                  <p>
                    Keep this ID if a response is lost. Retry uses the exact
                    same content; it does not create a second memory. Do not
                    reload during an uncertain write.
                  </p>
                </div>
              )}
              {written && (
                <div className="detail">
                  <b>{written.status}</b>
                  <p>Memory ID: {written.id}</p>
                  <p>
                    Readable at write time:{" "}
                    {written.lineage_eligible ? "yes" : "no"}
                  </p>
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
                            attempt.content,
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
                      Signed acknowledgement queued. The owner can publish it
                      from the memory’s provenance events.
                    </p>
                  )}
                  <button
                    disabled={busy}
                    onClick={() => {
                      setAttempt(null);
                      setWritten(null);
                      setAck(null);
                      setAckId(null);
                      setContent("");
                      setParentId("");
                    }}
                  >
                    Start a new write
                  </button>
                </div>
              )}
            </article>
            <article className="operation-read">
              <h3>2. Read shared memories</h3>
              <p className="muted">
                Choose the namespace you want to read. Quarantined records
                remain withheld. Unverified observations require explicit owner
                review before sharing; read permission is still required.
              </p>
              <label htmlFor="wb-read-namespace">Namespace</label>
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
                Sign and read namespace
              </button>
              {page && (
                <div className="detail">
                  <b>{readScope.namespace}</b>
                  <p>{page.memories.length} readable memories on this page</p>
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
              <h3>3. Check local transfer permission</h3>
              <p className="muted">
                A simulation does not send tokens. Local permissions and onchain
                permissions are separate.
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
            <h3>4. Protected onchain transfer</h3>
            <p>
              Connect the finance agent wallet on Sepolia. The owner must first
              set the onchain grant and token allowance under Integrations.
              Simulation checks the deployed contract; sending requires a
              separate wallet transaction. Each click on Sign requests a new
              transfer. If submission is uncertain, check wallet activity before
              trying again.
            </p>
            <button
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const r = await call("GET", "/integrations/readiness");
                  setNetworks((await call("GET", "/chains")).chains);
                  setChain((p) => ({
                    ...p,
                    registry: r.onchain_registry || "",
                    executor: r.onchain_executor || "",
                    chainId: String(r.onchain_chain_id || 11155111),
                  }));
                })
              }
            >
              Load configured contracts
            </button>
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
                ["amount", "Amount in base units"],
                ["policyVersion", "Onchain policy version"],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    value={chain[key]}
                    onChange={(e) => updateChain(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
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
                        ...chainArgs(),
                        simulateOnly: true,
                      }),
                    ),
                  )
                }
              >
                Simulate onchain call
              </button>
              <button
                disabled={
                  busy || selected.revoked || !!chainResult?.transactionHash
                }
                onClick={() =>
                  run(async () => {
                    const transactionHash = await executeProtectedTransfer(
                      window.ethereum,
                      chainArgs(),
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
