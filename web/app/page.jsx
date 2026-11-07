"use client";

import ConnectionStatus, { ConnectionDiagnostics } from "../components/ConnectionStatus";
import CollectionInput from "../components/CollectionInput";
import ActionNotice from "../components/ActionNotice";
import MemoryContentModal from "../components/MemoryContentModal";

import { useEffect, useRef, useState } from "react";
import { useWorkspaceNavigation } from "../lib/workspace-navigation";
import WorkspaceGuide from "../components/design/WorkspaceGuide";
import Landing from "../components/design/Landing";
import Brand from "../components/design/Brand";
import NavIcon from "../components/design/NavIcon";
import MemoryMap from "../components/MemoryMap";
import ActivityFeed from "../components/ActivityFeed";
import PaymentDemo from "../components/PaymentDemo";
import AgentSetup from "../components/AgentSetup";
import EnsSponsorAdmin from "../components/EnsSponsorAdmin";
import AgentCard from "../components/AgentCard";
import MemoryEvidence from "../components/MemoryProof";
import AgentWorkbench from "../components/AgentWorkbench";
import TeamVaultPanel from "../components/TeamVaultPanel";
import { normalize } from "viem/ens";
import { verifyMemoryCommitment } from "../lib/commitment.mjs";
import {
  loadResolverRecovery,
  saveResolverRecovery,
} from "../lib/resolver-recovery.mjs";
import { clearBrowserSessions, hasBrowserSession } from "../lib/browser-session.mjs";
import { gatewayOrigin, signedRequest } from "../lib/gateway.mjs";
import { memorySearchPath } from "../lib/memory-search.mjs";
import { capabilityActive, expiryValues } from "../lib/expiry.mjs";
import {
  changeDedicatedDelegation,
  verifyDedicatedDelegation,
  deployDedicatedResolver,
  verifyDedicatedResolver,
  attachDedicatedResolver,
  verifyDedicatedAttachment,
  inspectSubnameRegistry,
  writeAgentName,
  verifyAgentName,
} from "../lib/ens.mjs";
import {
  approveTokenAllowance,
  tokenAllowance,
  onchainCapability,
  onchainVersion,
  setOnchainLimit,
  revokeOnchainLimit,
  revokeOnchainAgent,
  setOnchainMemory,
  revokeOnchainMemory,
  onchainReceipt,
} from "../lib/chain.mjs";

const api = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:8000";
const audience = process.env.NEXT_PUBLIC_GATEWAY_AUDIENCE || "memoryseal-local";

export default function Dashboard() {
  const [session, setSession] = useState(0);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const wallet = window.ethereum;
    const reset = () => {
      clearBrowserSessions();
      controller.current.abort();
      controller.current = new AbortController();
      setSession((value) => value + 1);
    };
    window.addEventListener("memoryseal:signout", reset);
    wallet?.on?.("accountsChanged", reset);
    wallet?.on?.("chainChanged", reset);
    wallet?.on?.("disconnect", reset);
    return () => {
      window.removeEventListener("memoryseal:signout", reset);
      wallet?.removeListener?.("accountsChanged", reset);
      wallet?.removeListener?.("chainChanged", reset);
      wallet?.removeListener?.("disconnect", reset);
    };
  }, []);
  return <DashboardSession key={session} signal={controller.current.signal} />;
}

function DashboardSession({ signal }) {
  const request = (account, method, path, payload, allowLogin = true) =>
    signedRequest({
      account,
      method,
      path,
      payload,
      api,
      audience,
      wallet: window.ethereum,
      useSession: true,
      allowLogin,
      signal,
    });
  const searchSequence = useRef(0);
  const [account, setAccount] = useState("");
  const [view, setView] = useWorkspaceNavigation();
  const [devMode, setDevMode] = useState(false);
  useEffect(() => {
    const update = () => setDevMode(new URLSearchParams(window.location.search).get("devmode") === "true");
    update();
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    return () => {window.removeEventListener("popstate", update); window.removeEventListener("hashchange", update);};
  }, []);
  const [integrationTab, setIntegrationTab] = useState("connections");
  const [data, setData] = useState(null);
  const [memoryPage, setMemoryPage] = useState(null);
  const [memoryOffset, setMemoryOffset] = useState(0);
  const [memoryFilter, setMemoryFilter] = useState({
    agent: "",
    namespace: "",
    status: "",
    requestId: "",
  });
  const [appliedFilter, setAppliedFilter] = useState({
    agent: "",
    namespace: "",
    status: "",
    requestId: "",
  });
  const [detail, setDetail] = useState(null);
  const [memoryTitles, setMemoryTitles] = useState({});
  const memoryTitle = m => memoryTitles[`${account}:${m.id}`] || `${m.namespace} · ${(m.category || "memory").replaceAll("_", " ")} #${m.id.slice(0, 8)}`;
  function rememberTitle(content) {
    const text = content.content?.replace(/\s+/g, " ").trim();
    if (text) setMemoryTitles(previous => ({...previous, [`${account}:${content.id}`]: text.length > 80 ? text.slice(0, 77) + "…" : text}));
  }
  const [commitmentCheck, setCommitmentCheck] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentPolicyChain, setAgentPolicyChain] = useState("");
  const [address, setAddress] = useState("");
  const [ensName, setEnsName] = useState("");
  const [ensParent, setEnsParent] = useState("");
  const [ensLabel, setEnsLabel] = useState("");
  const [ensAgent, setEnsAgent] = useState("");
  const [ensNetwork, setEnsNetwork] = useState("11155111");
  const [ensWrite, setEnsWrite] = useState(null);
  const [ensCheck, setEnsCheck] = useState(null);
  const [ensRegistryCheck, setEnsRegistryCheck] = useState(null);
  const [ensResolver, setEnsResolver] = useState(null);
  const [ensResolverCheck, setEnsResolverCheck] = useState(null);
  const [ensAttachment, setEnsAttachment] = useState(null);
  const [ensAttachmentCheck, setEnsAttachmentCheck] = useState(null);
  const [ensDelegation, setEnsDelegation] = useState(null);
  const [ensDelegationCheck, setEnsDelegationCheck] = useState(null);
  const [resolverRecoveryNote, setResolverRecoveryNote] = useState("");
  useEffect(() => {
    if (!account) return;
    try {
      const saved = loadResolverRecovery(window.localStorage, account);
      if (saved) {
        setEnsResolver(saved.deployment);
        setEnsAttachment(saved.attachment);
        setEnsResolverCheck(null);
        setEnsAttachmentCheck(null);
        setResolverRecoveryNote(
          "Recovered public transaction details from this browser. Verify them again before continuing.",
        );
      }
    } catch {
      setResolverRecoveryNote(
        "Could not read resolver recovery data from this browser. Save transaction details manually.",
      );
    }
  }, [account]);
  function rememberResolver(deployment, attachment = null) {
    try {
      saveResolverRecovery(
        window.localStorage,
        account,
        deployment,
        attachment,
      );
      setResolverRecoveryNote(
        "Public transaction details saved in this browser for this wallet. Verification is required again after reload.",
      );
    } catch {
      setResolverRecoveryNote(
        "Could not save resolver recovery data in this browser. Save the transaction details manually.",
      );
    }
  }
  const [configuredChains, setConfiguredChains] = useState([]);
  const [integrationReadiness, setIntegrationReadiness] = useState(null);
  const [deploymentObservation, setDeploymentObservation] = useState(null);
  const [ensObservations, setEnsObservations] = useState({});
  const [provenanceObservations, setProvenanceObservations] = useState({});
  const [provenanceHistory, setProvenanceHistory] = useState({});
  const [eventObservations, setEventObservations] = useState({});
  const [agent, setAgent] = useState("");
  const [operation, setOperation] = useState("write");
  const [resource, setResource] = useState("");
  const [amount, setAmount] = useState("");
  const [localExpiry, setLocalExpiry] = useState("");
  const [transferExpiry, setTransferExpiry] = useState("");
  const [memoryExpiry, setMemoryExpiry] = useState("");
  const [registry, setRegistry] = useState(
    process.env.NEXT_PUBLIC_REGISTRY_ADDRESS || "",
  );
  const [allowanceExecutor, setAllowanceExecutor] = useState("");
  const [allowanceAmount, setAllowanceAmount] = useState("");
  const [allowanceRead, setAllowanceRead] = useState(null);
  const [allowanceTx, setAllowanceTx] = useState(null);
  const [allowanceStatus, setAllowanceStatus] = useState("");
  const [chainId, setChainId] = useState(
    process.env.NEXT_PUBLIC_CHAIN_ID || "",
  );
  const [chainAgent, setChainAgent] = useState("");
  const [token, setToken] = useState("");
  const [chainAmount, setChainAmount] = useState("");
  const [chainVersion, setChainVersion] = useState("");
  const [chainCapability, setChainCapability] = useState(null);
  const [chainTx, setChainTx] = useState("");
  const [chainStatus, setChainStatus] = useState("");
  const [memoryAgent, setMemoryAgent] = useState("");
  const [memoryNamespace, setMemoryNamespace] = useState("");
  const [memoryRead, setMemoryRead] = useState(true);
  const [memoryWrite, setMemoryWrite] = useState(false);
  const [grantHash, setGrantHash] = useState("");
  const [grantVersion, setGrantVersion] = useState("");
  const [grantExpiry, setGrantExpiry] = useState("0");
  const [grantObservation, setGrantObservation] = useState(null);
  const [transferHash, setTransferHash] = useState("");
  const [transferRecipient, setTransferRecipient] = useState("");
  const [transferVersion, setTransferVersion] = useState("");
  const [transferObservation, setTransferObservation] = useState(null);
  const [balanceObservation, setBalanceObservation] = useState(null);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!account || !data?.agents?.some(a => ["queued", "registering"].includes(a.ens_registration?.state))) return;
    const timer = setTimeout(() => {request(account, "GET", "/agents", undefined, false).then(result => setData(current => ({...current, agents: result.agents}))).catch(() => {});}, 10000);
    return () => clearTimeout(timer);
  }, [account, data]);
  async function refresh(owner, allowLogin = true) {
    // Read requests share the browser login session.
    const [agents, capabilities, memories, events, summary] = await Promise.all([
      request(owner, "GET", "/agents", undefined, allowLogin),
      request(owner, "GET", "/capabilities", undefined, allowLogin),
      request(owner, "GET", "/memories", undefined, allowLogin),
      request(owner, "GET", "/events", undefined, allowLogin),
      request(owner, "GET", "/workspace-summary", undefined, allowLogin),
    ]);
    setData({
      summary,
      agents: agents.agents,
      capabilities: capabilities.capabilities,
      acceptanceRules: capabilities.acceptance_rules || [],
      version: capabilities.policy_version,
      memories: memories.memories,
      events: events.events,
    });
    setMemoryPage(memories);
    setMemoryOffset(0);
    setMemoryFilter({ agent: "", namespace: "", status: "", requestId: "" });
    setAppliedFilter({ agent: "", namespace: "", status: "", requestId: "" });
  }
  async function searchMemories(filter, offset = 0) {
    const sequence = ++searchSequence.current;
    const result = await request(
      account,
      "GET",
      memorySearchPath(filter, offset),
    );
    if (sequence !== searchSequence.current || signal.aborted) return;
    setMemoryPage(result);
    setMemoryOffset(offset);
    setAppliedFilter(filter);
    setDetail(null);
  }
  useEffect(() => {
    if (!data || view !== "memories") return;
    const timer = setTimeout(() => { searchMemories(memoryFilter).catch(e => {if (!signal.aborted) setError(e.message);}); }, 400);
    return () => clearTimeout(timer);
  }, [account, view, JSON.stringify(memoryFilter), !!data]);
  useEffect(() => {
    if (!data || view !== "memories" || detail || busy) return;
    const timer = setInterval(() => {
      searchMemories(appliedFilter, memoryOffset).catch(() => {});
    }, 10000);
    return () => clearInterval(timer);
  }, [account, view, !!detail, busy, JSON.stringify(appliedFilter), memoryOffset]);
  useEffect(() => {
    if (!data || view !== "settings") return;
    run(async () => {
      const [ready, chains] = await Promise.all([request(account,"GET","/integrations/readiness"), request(account,"GET","/chains")]);
      setIntegrationReadiness(ready); setConfiguredChains(chains.chains);
      if (!registry) setRegistry(ready.onchain_registry || "");
      if (!chainId) setChainId(String(ready.onchain_chain_id || 11155111));
    });
  }, [account, view, !!data]);
  useEffect(() => {
    let cancelled = false;
    const resume = async () => {
      const wallet = window.ethereum;
      if (!wallet) return;
      const origin = gatewayOrigin(api);
      // eth_accounts checks existing permission without opening a wallet prompt.
      const accounts = await wallet.request({method: "eth_accounts"});
      if (cancelled || signal.aborted || !accounts[0]) return;
      if (!hasBrowserSession({api: origin, audience, account: accounts[0]})) return;
      await refresh(accounts[0], false);
      if (!cancelled && !signal.aborted) setAccount(accounts[0]);
    };
    resume().catch(() => { /* Expired/revoked/offline: leave the normal connect action available. */ });
    return () => { cancelled = true; };
  }, [signal]);

  async function connect() {
    gatewayOrigin(api);
    if (!window.ethereum) throw new Error("Install an EVM wallet to connect.");
    const accounts = await window.ethereum.request({
      method: "eth_requestAccounts",
    });
    if (!accounts[0]) throw new Error("No wallet account selected.");
    setAccount(accounts[0]);
    await refresh(accounts[0]);
  }

  const nav = [
    ["overview", "Overview"],
    ["memories", "Memories"],
    ["agents", "Agents"],
    ["permissions", "Permissions"],
    ["teams", "Organizations"],
    ["vault", "Encrypted vault"],
    ["activity", "Activity"],
    ["workbench", "Playground"],
    ...(devMode ? [["settings", "Settings"]] : []),
  ];
  const activeAgents = data?.agents.filter((a) => !a.revoked).length || 0;
  const quarantineCount =
    data?.summary?.needs_review || 0;
  return (
    <main className={data ? "app-shell" : "landing-shell"}>
      {data && (
        <a className="skip-link" href="#workspace-content">
          Skip to workspace
        </a>
      )}
      {!data ? (
        <Landing busy={busy} error={error} onConnect={() => run(connect)} />
      ) : (
        <>
          <aside className="sidebar">
            <button className="sidebar-home" type="button" aria-label="MemorySeal overview" onClick={() => setView("overview")}>
              <Brand />
            </button>
            <nav className="side-nav" aria-label="Workspace navigation">
              {nav.map(([id, label]) => (
                <button
                  key={id}
                  aria-label={label}
                  title={label}
                  className={`nav-item${view === id ? " active" : ""}${id === "teams" || id === "workbench" ? " nav-section-start" : ""}${id === "settings" ? " nav-settings" : ""}`}
                  aria-current={view === id ? "page" : undefined}
                  onClick={() => setView(id)}
                >
                  <span className="nav-icon" aria-hidden="true">
                    <NavIcon name={id} />
                  </span>
                  <span className="nav-label">{label}</span>
                  {id === "memories" && quarantineCount > 0 && (
                    <span className="nav-count">{quarantineCount}</span>
                  )}
                </button>
              ))}
            </nav>
          </aside>
          <div
            className="workspace"
            id="workspace-content"
            data-view={view}
            data-integration={integrationTab}
          >
            <div className="workspace-topbar">
              <div className="topbar-actions">
                <button className="refresh-button wallet-refresh" disabled={busy}
                  title={`Refresh workspace · ${account}`} aria-label={`Refresh workspace for ${account}`} aria-busy={busy}
                  onClick={() => run(() => refresh(account))}>
                  <span aria-hidden="true">↻</span>
                  <span>{account.slice(0, 6)}…{account.slice(-4)}</span>
                </button>
                <button className="refresh-button" disabled={busy} onClick={() => run(async () => {
                  await window.ethereum.request({method: "wallet_requestPermissions", params: [{eth_accounts: {}}]});
                  clearBrowserSessions(); await connect();
                })}>Switch account</button>
                <button
                  className="refresh-button"
                  disabled={busy}
                  onClick={() => window.dispatchEvent(new Event("memoryseal:signout"))}
                >
                  Sign out
                </button>

              </div>
            </div>
            <ActionNotice message={error} onClose={() => setError("")} />
            <div className="workspace-heading">
              <div>
                <h1 tabIndex={-1}>
                  {nav.find((item) => item[0] === view)?.[1]}
                  <span className="heading-dot">.</span>
                </h1>

              </div>
              {view === "overview" && <WorkspaceGuide onNavigate={setView} />}
            </div>

            <div hidden={view !== "teams" && view !== "vault"}>
              <TeamVaultPanel
                key={account}
                account={account}
                signal={signal}
                mode={view === "teams" ? "teams" : "vault"}
              />
            </div>
            {view === "demo" && <PaymentDemo key={account} api={api} audience={audience} account={account} request={request} />}
            <div hidden={view !== "workbench"}>
              <AgentWorkbench
                account={account}
                request={request}
                signal={signal}
              />
            </div>
            {view === "settings" && (
              <nav
                className="integration-tabs"
                aria-label="Integration sections"
              >
                {[
                  [
                    "connections",
                    "Connections",
                    "Check your gateway configuration",
                  ],
                  ["names", "Agent names", "ENS names and resolvers"],
                  [
                    "policies",
                    "Onchain policies",
                    "Limits, allowances and deployments",
                  ],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    aria-current={integrationTab === id ? "page" : undefined}
                    onClick={() => setIntegrationTab(id)}
                  >
                    <b>{label}</b>
                  </button>
                ))}
              </nav>
            )}
            <section className="panel-setup">
              <ConnectionStatus readiness={integrationReadiness} automatic={data.summary?.auto_publish} busy={busy}
                onRefresh={() =>
                  run(async () => {
                    const ready = await request(
                      account,
                      "GET",
                      "/integrations/readiness",
                    );
                    setIntegrationReadiness(ready);
                    setConfiguredChains(
                      (await request(account, "GET", "/chains")).chains,
                    );
                    if (!registry) setRegistry(ready.onchain_registry || "");
                    if (!chainId)
                      setChainId(String(ready.onchain_chain_id || ""));
                    if (!allowanceExecutor)
                      setAllowanceExecutor(ready.onchain_executor || "");
                  })
                } />
              <details className="settings-diagnostics"><summary>Diagnostics & deployment checks</summary>
              <ConnectionDiagnostics readiness={integrationReadiness} />
              <button
                disabled={busy}
                onClick={() =>
                  run(async () =>
                    setDeploymentObservation(
                      (
                        await request(
                          account,
                          "GET",
                          `/onchain/observe-deployment${chainId ? "?chain_id=" + encodeURIComponent(chainId) : ""}`,
                        )
                      ).observation,
                    ),
                  )
                }
              >
                Check executor registry
              </button>
              {deploymentObservation && (
                <div className="detail">
                  <p>
                    Executor{" "}
                    {deploymentObservation.matches
                      ? "points to the configured registry"
                      : "does not point to the configured registry"}{" "}
                    at block {deploymentObservation.block_number}.
                  </p>
                  <small>
                    Executor: {deploymentObservation.executor} · configured
                    registry: {deploymentObservation.registry} · reported
                    registry: {deploymentObservation.executor_registry}. This
                    trusts the configured RPC and locally compiled artifacts; it
                    does not prove finality or that the code is safe.
                  </small>
                  <p>
                    Registry runtime compared with local build:{" "}
                    {deploymentObservation.registry_code_matches_local === null
                      ? "unavailable"
                      : deploymentObservation.registry_code_matches_local
                        ? "matches"
                        : "differs"}
                    . Executor runtime:{" "}
                    {deploymentObservation.executor_code_matches_local === null
                      ? "unavailable"
                      : deploymentObservation.executor_code_matches_local
                        ? "matches"
                        : "differs"}
                    .
                  </p>
                </div>
              )}
              </details>
            </section>
            <div className="stats">
              <div>
                <small>AGENTS</small>
                <strong>{data.agents.filter(a => !a.revoked).length}</strong>
              </div>
              <div>
                <small>ACTIVE CAPABILITIES</small>
                <strong>
                  {
                    data.capabilities.filter(
                      (c) =>
                        capabilityActive(c) &&
                        data.agents.some(
                          (a) => a.id === c.agent_id && !a.revoked,
                        ),
                    ).length
                  }
                </strong>
              </div>
              <div>
                <small>NEEDS REVIEW</small>
                <strong>
                  {quarantineCount}
                </strong>
              </div>
              <div>
                <small>MEMORIES</small>
                <strong>{data.summary?.memories || 0}</strong>
              </div>
            </div>
            <div className="grid">
              <section className="panel-agents">
                <div className="section-head">
                  <div>
                    <h2>Agents</h2>
                  </div>
                </div>
                {!data.agents.some(a => !a.revoked) ? (
                  <p className="muted">No active agents.</p>
                ) : (
                  data.agents.filter(a => !a.revoked).map((a) => (
                    <AgentCard key={a.id} agent={a} capabilities={data.capabilities}
                      observation={ensObservations[a.id]} busy={busy}
                      onCheckEns={() => {
                        request(account, "GET", `/agents/${a.id}/observe-ens`)
                          .then(result => setEnsObservations(p => ({...p, [a.id]: result.observation})))
                          .catch(error => setEnsObservations(p => ({...p, [a.id]: {error: error.message}})));
                      }}
                      onRevoke={() => run(async () => {
                        await request(account, "POST", `/agents/${a.id}/revoke`, {});
                        await refresh(account);
                      })}
                    />
                  ))
                )}
                <AgentSetup account={account} version={data.version} request={request} onComplete={() => refresh(account)} />
              </section>
              <section className="panel-permissions permission-workspace">
                <div className="permission-layout">
                  <article className="permission-card">
                    <header className="permission-card-header"><span>01</span><h2>Memory acceptance</h2></header>
                <form className="permission-form" onSubmit={(event) => {
                  event.preventDefault();
                  const form = event.currentTarget;
                  const values = new FormData(form);
                  run(async () => {
                    await request(account, "POST", "/acceptance-rules", {
                      agent_id: values.get("agent_id"),
                      namespace: values.get("namespace"),
                      mode: values.get("mode"),
                      policy_version: data.version,
                    });
                    await refresh(account);
                    form.reset();
                  });
                }}>

                    <fieldset disabled={busy}>
                      <div className="permission-fields">
                        <div className="permission-field"><label htmlFor="acceptance-agent">Agent</label>
                          <select id="acceptance-agent" name="agent_id" required defaultValue="">
                            <option value="" disabled>Choose agent</option>
                            {data.agents.filter(a => !a.revoked).map(a => <option key={a.id} value={a.id}>{a.label || a.ens_name || a.signing_address}</option>)}
                          </select>
                        </div>
                        <div className="permission-field"><label htmlFor="acceptance-namespace">Collection</label><CollectionInput id="acceptance-namespace" name="namespace" required maxLength={200} placeholder="research" /></div>
                      </div>
                      <fieldset className="acceptance-choices"><legend>Acceptance mode</legend>
                        <div className="permission-fields">
                          <label className="acceptance-choice"><input type="radio" name="mode" value="strict" defaultChecked /><span><b>Strict</b><small>Existing verification rules</small></span></label>
                          <label className="acceptance-choice"><input type="radio" name="mode" value="standard" /><span><b>Standard</b><small>Low-risk, including unverified</small></span></label>
                        </div>
                      </fieldset>
                    </fieldset>
                    <div className="permission-form-footer"><button disabled={busy}>Sign acceptance policy <span aria-hidden="true">↗</span></button></div>
                  </form>
                  {(data.acceptanceRules || []).length > 0 && <details className="permission-saved-rules"><summary>Saved rules <span>{data.acceptanceRules.length}</span></summary>
                    {data.acceptanceRules.map(rule => <div className="saved-rule" key={`${rule.agent_id}:${rule.namespace}`}><div><b>{data.agents.find(a => a.id === rule.agent_id)?.label || data.agents.find(a => a.id === rule.agent_id)?.ens_name || rule.agent_id}</b><code>{rule.namespace}</code></div><span className="pill">{rule.mode}</span></div>)}
                  </details>}
                </article>
                <article className="permission-card">
                  <header className="permission-card-header"><span>02</span><h2>Add permission</h2></header>
                <form className="permission-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      if (
                        operation === "transfer" &&
                        (!/^[0-9]+$/.test(amount) ||
                          BigInt(amount) <= 0n ||
                          BigInt(amount) >= 2n ** 256n)
                      )
                        throw new Error(
                          "Enter a positive uint256 amount in base units.",
                        );
                      await request(account, "POST", "/capabilities/grant", {
                        agent_id: agent,
                        operation,
                        resource,
                        max_amount: operation === "transfer" ? amount : null,
                        expires_at: expiryValues(localExpiry).iso,
                      });
                      await refresh(account);
                    });
                  }}
                >

                    <fieldset disabled={busy}>
                      <div className="permission-fields">
                        <div className="permission-field"><label htmlFor="grant-agent">Agent</label>
                          <select id="grant-agent" required value={agent} onChange={e => setAgent(e.target.value)}>
                            <option value="">Choose agent</option>
                            {data.agents.filter(a => !a.revoked).map(a => <option value={a.id} key={a.id}>{a.label || a.ens_name || a.signing_address}</option>)}
                          </select>
                        </div>
                        <div className="permission-field"><label htmlFor="grant-operation">Action</label>
                          <select id="grant-operation" value={operation} onChange={e => setOperation(e.target.value)}><option value="write">Write</option><option value="read">Read</option><option value="transfer">Transfer</option></select>
                        </div>
                        <div className="permission-field"><label htmlFor="grant-resource">{operation === "transfer" ? "Asset" : "Collection"}</label>
                          {operation === "transfer" ? <input id="grant-resource" value={resource} onChange={e => setResource(e.target.value)} placeholder="Asset identifier" required /> : <CollectionInput id="grant-resource" value={resource} onChange={e => setResource(e.target.value)} placeholder="research" required />}
                        </div>
                        <div className="permission-field"><label htmlFor="local-expiry">Expiry <span>(optional · local time)</span></label><input id="local-expiry" type="datetime-local" value={localExpiry} onChange={e => setLocalExpiry(e.target.value)} /></div>
                        {operation === "transfer" && <div className="permission-field permission-field-wide"><label htmlFor="grant-amount">Transfer limit <span>(base units)</span></label><input id="grant-amount" type="text" inputMode="numeric" pattern="[0-9]+" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0" required /></div>}
                      </div>
                    </fieldset>
                    <div className="permission-form-footer"><button disabled={busy}>Save permission <span aria-hidden="true">↗</span></button></div>
                  </form>
                </article>
                </div>
                <article className="permission-card permission-current">
                  <header className="permission-card-header"><span>03</span><h2>Current permissions</h2><span className="permission-total">{data.capabilities.filter(c => capabilityActive(c) && data.agents.some(a => a.id === c.agent_id && !a.revoked)).length} active</span></header>
                  <div className="permission-current-body">
                  {!data.capabilities.some(c => !c.revoked && data.agents.some(a => a.id === c.agent_id)) && <div className="permission-empty"><span aria-hidden="true">⊞</span><p>No permissions yet.</p></div>}
                  {data.agents.filter(a => data.capabilities.some(c => c.agent_id === a.id && !c.revoked)).map(a => <details key={a.id} className="permission-group">
                    <summary><span>{a.label || a.ens_name || a.signing_address}</span><span className="permission-group-count">{a.revoked ? "Agent revoked" : `${data.capabilities.filter(c => c.agent_id === a.id && capabilityActive(c)).length} active`}</span></summary>
                    <div className="permission-grant-list">{data.capabilities.filter(c => c.agent_id === a.id && !c.revoked).map(c => <div className="permission-grant" key={c.id}>
                      <span className="permission-action">{c.operation}</span>
                      <div className="permission-grant-info"><code>{c.resource}</code><small>{c.max_amount ? `Limit: ${c.max_amount} base units · ` : ""}{c.expires_at ? `Expires ${new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(c.expires_at) ? c.expires_at : `${c.expires_at}Z`).toLocaleString()}` : "No expiry"}</small></div>
                      {capabilityActive(c) ? <button className="permission-revoke" disabled={busy} onClick={() => run(async () => {await request(account,"POST",`/capabilities/${c.id}/revoke`,{}); await refresh(account);})}>Revoke</button> : <span className="pill">{c.revoked ? "Revoked" : "Expired"}</span>}
                    </div>)}</div>
                  </details>)}
                  </div>
                </article>
              </section>
              <section className="panel-memories">
                <h2>Memories</h2>

                <form
                  className="memory-filters"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(() => searchMemories(memoryFilter));
                  }}
                >
                  <div className="memory-filter-field">
                  <label htmlFor="search-agent">Filter by agent</label>
                  <select
                    id="search-agent"
                    value={memoryFilter.agent}
                    onChange={(e) =>
                      setMemoryFilter({
                        ...memoryFilter,
                        agent: e.target.value,
                      })
                    }
                  >
                    <option value="">All agents</option>
                    {data.agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.label || a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  </div>
                  <div className="memory-filter-field">
                  <label htmlFor="search-namespace">Collection</label>
                  <CollectionInput
                    id="search-namespace"
                    value={memoryFilter.namespace}
                    onChange={(e) =>
                      setMemoryFilter({
                        ...memoryFilter,
                        namespace: e.target.value,
                      })
                    }
                    placeholder="All namespaces"
                  />
                  </div>
                  <div className="memory-filter-field">
                  <label htmlFor="search-request">Write request ID</label>
                  <input
                    id="search-request"
                    value={memoryFilter.requestId}
                    onChange={(e) =>
                      setMemoryFilter({
                        ...memoryFilter,
                        requestId: e.target.value,
                      })
                    }
                    placeholder="UUID (optional)"
                  />

                  </div>
                  <div className="memory-filter-field">
                  <label htmlFor="search-status">Status</label>
                  <select
                    id="search-status"
                    value={memoryFilter.status}
                    onChange={(e) =>
                      setMemoryFilter({
                        ...memoryFilter,
                        status: e.target.value,
                      })
                    }
                  >
                    <option value="">All statuses</option>
                    <option value="accepted">Accepted</option>
                    <option value="quarantined">Quarantined</option>
                  </select>
                  </div>

                </form>
                {(appliedFilter.memoryId || appliedFilter.parentId) && <p className="muted">{appliedFilter.parentId ? "Related memories" : "Selected memory"}</p>}
                <MemoryMap memories={memoryPage.memories} agents={data.agents} busy={busy}
                  onInspect={m => run(async () => {
                    setCommitmentCheck(null);
                    const content = await request(account, "GET", `/memories/${m.id}`);
                    setDetail(content);
                    rememberTitle(content);
                    setCommitmentCheck(await verifyMemoryCommitment(content.content, content.commitment_salt, content.commitment));
                  })}
                  onParent={id => run(() => searchMemories({memoryId: id}))}
                />
                {memoryPage.memories.length === 0 ? (
                  <p className="muted">No matching memories.</p>
                ) : (
                  memoryPage.memories.map((m) => (
                    <div className="row memory-record" key={m.id}>
                      <div className="memory-record-main">
                        <div className="memory-record-heading">
                        <span className="memory-collection">{m.namespace}</span>
                        <h3>{memoryTitle(m)}</h3>
                        <small>{data.agents.find(a => a.id === m.agent_id)?.label || data.agents.find(a => a.id === m.agent_id)?.ens_name || "Agent " + m.agent_id.slice(0, 8)} · {new Date(/[Zz]|[+-]\d{2}:\d{2}$/.test(m.created_at) ? m.created_at : m.created_at + "Z").toLocaleString()}</small>
                        </div>
                        <MemoryEvidence
                          memory={m}
                          observation={provenanceObservations[m.id]}
                          history={provenanceHistory[m.id]}
                          eventObservations={eventObservations}
                          onObserveEvent={(eventId) =>
                            run(async () => {
                              const result = await request(
                                account,
                                "POST",
                                `/memories/${m.id}/provenance-events/${eventId}/observe`,
                                {},
                              );
                              setEventObservations((prev) => ({
                                ...prev,
                                [eventId]: result.observation,
                              }));
                            })
                          }
                          onPublishEvent={(eventId) =>
                            run(async () => {
                              const result = await request(
                                account,
                                "POST",
                                `/memories/${m.id}/provenance-events/${eventId}/publish`,
                                {},
                              );
                              setEventObservations((prev) => ({
                                ...prev,
                                [eventId]: result.state,
                              }));
                              const history = await request(
                                account,
                                "GET",
                                `/memories/${m.id}/provenance-events`,
                              );
                              setProvenanceHistory((prev) => ({
                                ...prev,
                                [m.id]: history,
                              }));
                              await searchMemories(appliedFilter, memoryOffset);
                            })
                          }
                          onReconcileEvent={(eventId) =>
                            run(async () => {
                              const result = await request(
                                account,
                                "POST",
                                `/memories/${m.id}/provenance-events/${eventId}/reconcile`,
                                {},
                              );
                              setEventObservations((prev) => ({
                                ...prev,
                                [eventId]: result.state,
                              }));
                              const history = await request(
                                account,
                                "GET",
                                `/memories/${m.id}/provenance-events`,
                              );
                              setProvenanceHistory((prev) => ({
                                ...prev,
                                [m.id]: history,
                              }));
                            })
                          }
                          onHistory={() =>
                            run(async () => {
                              const result = await request(
                                account,
                                "GET",
                                `/memories/${m.id}/provenance-events`,
                              );
                              setProvenanceHistory((prev) => ({
                                ...prev,
                                [m.id]: result,
                              }));
                            })
                          }
                          busy={busy}
                          onParent={() =>
                            run(() => searchMemories({ memoryId: m.parent_id }))
                          }
                          onChildren={() =>
                            run(() => searchMemories({ parentId: m.id }))
                          }
                          onObserve={() =>
                            run(async () => {
                              const result = await request(
                                account,
                                "POST",
                                `/memories/${m.id}/observe-provenance`,
                                {},
                              );
                              setProvenanceObservations((prev) => ({
                                ...prev,
                                [m.id]: result.observation,
                              }));
                            })
                          }
                        />
                      </div>
                      <div className="memory-record-actions">
                        <span
                          className={
                            "pill " +
                            (m.status === "quarantined" ? "warning" : "")
                          }
                        >
                          {m.status === "quarantined" ? "Needs review" : m.lineage_eligible === false ? "Withheld" : "Available"}
                        </span>
                        <button
                          className="inspect"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setCommitmentCheck(null);
                              const content = await request(account, "GET", `/memories/${m.id}`);
                              setDetail(content);
                    rememberTitle(content);
                              setCommitmentCheck(await verifyMemoryCommitment(content.content, content.commitment_salt, content.commitment));
                            })
                          }
                        >
                          {m.status === "quarantined" ? "Read & review" : "Read memory"}
                        </button>
                        {m.status === "accepted" && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                const policy = await request(
                                  account,
                                  "GET",
                                  "/capabilities",
                                );
                                await request(
                                  account,
                                  "POST",
                                  `/memories/${m.id}/quarantine-event`,
                                  {
                                    event_id: crypto.randomUUID(),
                                    commitment: m.commitment,
                                    policy_version: policy.policy_version,
                                  },
                                );
                                setProvenanceHistory((prev) => {
                                  const next = { ...prev };
                                  delete next[m.id];
                                  return next;
                                });
                                await searchMemories(
                                  appliedFilter,
                                  memoryOffset,
                                );
                              })
                            }
                          >
                            Quarantine
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                )}
                {(memoryOffset > 0 || memoryPage.next_offset !== null) && (
                  <div className="inline">
                    <button
                      disabled={busy || memoryOffset === 0}
                      onClick={() =>
                        run(() =>
                          searchMemories(
                            appliedFilter,
                            Math.max(0, memoryOffset - 100),
                          ),
                        )
                      }
                    >
                      Previous
                    </button>
                    <button
                      disabled={busy || memoryPage.next_offset === null}
                      onClick={() =>
                        run(() =>
                          searchMemories(appliedFilter, memoryPage.next_offset),
                        )
                      }
                    >
                      Next
                    </button>
                  </div>
                )}
                {detail && (
                  <MemoryContentModal title={memoryTitle(detail)} namespace={detail.namespace} onClose={() => {setDetail(null); setCommitmentCheck(null);}}>
                    <h3 className="memory-reader-label">Memory content</h3>
                    <div className="memory-plaintext">{detail.content}</div>
                    <small>
                      Source: {detail.source_reference || "Not supplied"} ·{" "}
                      {detail.trust_class}
                    </small>
                    <p role="status">{commitmentCheck === null ? "Checking saved content…" : commitmentCheck ? "Content integrity checked" : "Content integrity check failed — sharing blocked"}</p>
                    {detail.status === "quarantined" && !detail.review_eligible && <p>This memory does not meet the release requirements.</p>}
                    {detail.status === "quarantined" && detail.review_eligible && (
                      <div className="detail">
                        <b>Owner review for sharing</b>
                        <p>Allow agents with read permission to access this memory.</p>
                        <button
                          disabled={busy || commitmentCheck !== true}
                          onClick={() =>
                            run(async () => {
                              const policy = await request(
                                account,
                                "GET",
                                "/capabilities",
                              );
                              await request(
                                account,
                                "POST",
                                `/memories/${detail.id}/review-event`,
                                {
                                  event_id: crypto.randomUUID(),
                                  commitment: detail.commitment,
                                  policy_version: policy.policy_version,
                                },
                              );
                              setDetail(null);
                              setCommitmentCheck(null);
                              await searchMemories(appliedFilter, memoryOffset);
                            })
                          }
                        >
                          Allow sharing
                        </button>
                      </div>
                    )}
                    <button
                      onClick={() => {
                        setDetail(null);
                        setCommitmentCheck(null);
                      }}
                    >
                      Close
                    </button>
                  </MemoryContentModal>
                )}
              </section>
              <section className="panel-ens">
                <EnsSponsorAdmin account={account} request={request} />
                <h2>Agent names</h2>
                <details className="settings-task"><summary>Manage ENS records & ownership</summary>
                <p className="muted">
                  Sets an address record on the parent resolver; does not create an owned subname.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const result = await writeAgentName(window.ethereum, {
                        owner: account,
                        chainId: ensNetwork,
                        parentName: ensParent,
                        label: ensLabel,
                        agentAddress: ensAgent,
                      });
                      setEnsWrite({
                        ...result,
                        owner: account,
                        chainId: ensNetwork,
                        agentAddress: ensAgent,
                      });
                      setEnsCheck(null);
                    });
                  }}
                >
                  <label htmlFor="ens-network">ENS network</label>
                  <select
                    id="ens-network"
                    value={ensNetwork}
                    onChange={(e) => setEnsNetwork(e.target.value)}
                  >
                    <option value="11155111">Sepolia testnet</option>
                  </select>
                  <label htmlFor="ens-parent">Parent name</label>
                  <input
                    id="ens-parent"
                    value={ensParent}
                    onChange={(e) => setEnsParent(e.target.value)}
                    placeholder="example.eth"
                    required
                  />
                  <label htmlFor="ens-label">Agent label</label>
                  <input
                    id="ens-label"
                    value={ensLabel}
                    onChange={(e) => setEnsLabel(e.target.value)}
                    placeholder="browser"
                    required
                  />
                  <label htmlFor="ens-agent">Agent signing address</label>
                  <select
                    id="ens-agent"
                    value={ensAgent}
                    onChange={(e) => setEnsAgent(e.target.value)}
                    required
                  >
                    <option value="">Choose agent</option>
                    {data.agents.map((a) => (
                      <option key={a.id} value={a.signing_address}>
                        {a.label || a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  <div className="inline">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () =>
                          setEnsRegistryCheck(
                            await inspectSubnameRegistry(window.ethereum, {
                              owner: account,
                              chainId: ensNetwork,
                              parentName: ensParent,
                              label: ensLabel,
                            }),
                          ),
                        )
                      }
                    >
                      Inspect parent registry
                    </button>
                    <button disabled={busy}>Sign ENS record transaction</button>
                  </div>
                  <div className="detail">
                    <b>Dedicated resolver (Sepolia)</b>
                    <p className="muted">
                      Use a dedicated resolver for this name. Attaching it replaces inherited records. ENS changes do not grant memory permissions.
                    </p>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          if (!ensParent || !ensLabel)
                            throw new Error(
                              "Enter the parent name and agent label first.",
                            );
                          const parentName = normalize(ensParent),
                            label = normalize(ensLabel);
                          if (!label || label.includes("."))
                            throw new Error(
                              "Agent label must be one ENS label.",
                            );
                          const bytes = crypto.getRandomValues(
                            new Uint8Array(32),
                          );
                          const salt = BigInt(
                            `0x${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`,
                          ).toString();
                          const result = await deployDedicatedResolver(
                            window.ethereum,
                            { owner: account, chainId: ensNetwork, salt },
                          );
                          const deployment = {
                            ...result,
                            chainId: ensNetwork,
                            parentName,
                            label,
                          };
                          setEnsResolver(deployment);
                          rememberResolver(deployment);
                          setEnsResolverCheck(null);
                          setEnsAttachment(null);
                          setEnsAttachmentCheck(null);
                          setEnsDelegation(null);
                          setEnsDelegationCheck(null);
                        })
                      }
                    >
                      Deploy dedicated resolver
                    </button>
                    {resolverRecoveryNote && (
                      <p className="muted">{resolverRecoveryNote}</p>
                    )}
                    {ensResolver && (
                      <>
                        <p className="muted">
                          Resolver for {ensResolver.label}.
                          {ensResolver.parentName}: {ensResolver.resolver}
                          <br />
                          Deployment transaction: {ensResolver.transactionHash}
                          <br />
                          Salt: {ensResolver.salt}
                        </p>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            run(async () =>
                              setEnsResolverCheck(
                                await verifyDedicatedResolver(
                                  window.ethereum,
                                  ensResolver,
                                ),
                              ),
                            )
                          }
                        >
                          Verify resolver deployment
                        </button>
                        {ensResolverCheck && (
                          <>
                            <p>
                              Deployment verified at block{" "}
                              {ensResolverCheck.blockNumber}. Ownership,
                              implementation and registry state can change
                              afterward.
                            </p>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() =>
                                run(async () => {
                                  const result = await attachDedicatedResolver(
                                    window.ethereum,
                                    {
                                      owner: ensResolver.owner,
                                      chainId: ensResolver.chainId,
                                      parentName: ensResolver.parentName,
                                      label: ensResolver.label,
                                      deployment: ensResolver,
                                    },
                                  );
                                  const attachment = {
                                    ...result,
                                    chainId: ensResolver.chainId,
                                  };
                                  setEnsAttachment(attachment);
                                  rememberResolver(ensResolver, attachment);
                                  setEnsAttachmentCheck(null);
                                })
                              }
                            >
                              Attach resolver to owned subname
                            </button>
                          </>
                        )}
                      </>
                    )}
                    {ensAttachment && (
                      <>
                        <p className="muted">
                          Attachment transaction:{" "}
                          {ensAttachment.transactionHash}
                        </p>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            run(async () =>
                              setEnsAttachmentCheck(
                                await verifyDedicatedAttachment(
                                  window.ethereum,
                                  ensAttachment,
                                ),
                              ),
                            )
                          }
                        >
                          Verify resolver attachment
                        </button>
                        {ensAttachmentCheck && (
                          <p>
                            {ensAttachmentCheck.matches
                              ? "Resolver and owner matched"
                              : "Resolver, owner or registry did not match"}{" "}
                            at block {ensAttachmentCheck.blockNumber}. Later
                            changes remain possible.
                          </p>
                        )}
                      </>
                    )}
                    {ensAttachmentCheck?.matches && (
                      <>
                        <p className="muted">
                          Controls the public memoryseal.config key for every name on this resolver. Root roles may retain access after revocation.
                        </p>
                        <div className="inline">
                          {[true, false].map((grant) => (
                            <button
                              key={String(grant)}
                              type="button"
                              disabled={busy || !ensAgent}
                              onClick={() =>
                                run(async () => {
                                  const result =
                                    await changeDedicatedDelegation(
                                      window.ethereum,
                                      {
                                        owner: account,
                                        chainId: ensResolver.chainId,
                                        deployment: ensResolver,
                                        attachment: ensAttachment,
                                        agent: ensAgent,
                                        grant,
                                      },
                                    );
                                  setEnsDelegation({
                                    ...result,
                                    chainId: ensResolver.chainId,
                                  });
                                  setEnsDelegationCheck(null);
                                })
                              }
                            >
                              {grant
                                ? "Grant identity key"
                                : "Revoke identity key"}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                    {ensDelegation && (
                      <>
                        <p className="muted">
                          Delegation transaction:{" "}
                          {ensDelegation.transactionHash} · agent{" "}
                          {ensDelegation.agent}
                        </p>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            run(async () =>
                              setEnsDelegationCheck(
                                await verifyDedicatedDelegation(
                                  window.ethereum,
                                  ensDelegation,
                                ),
                              ),
                            )
                          }
                        >
                          Verify delegation
                        </button>
                        {ensDelegationCheck && (
                          <p>
                            At block {ensDelegationCheck.blockNumber}:
                            key-scoped role{" "}
                            {ensDelegationCheck.keyRole ? "present" : "absent"};
                            root text role{" "}
                            {ensDelegationCheck.rootRole ? "present" : "absent"}
                            .{" "}
                            {ensDelegationCheck.matches
                              ? "Key role matches the requested change."
                              : "Key role does not match the requested change."}{" "}
                            Other privileges and later changes are not ruled
                            out.
                          </p>
                        )}
                      </>
                    )}
                  </div>
                  {ensRegistryCheck && (
                    <div className="detail">
                      <b>
                        {ensRegistryCheck.name} · ENSv2 observation at block{" "}
                        {ensRegistryCheck.blockNumber}
                      </b>
                      <p>
                        Parent owner: {ensRegistryCheck.parentOwner} · Canonical
                        subregistry: {ensRegistryCheck.registry}
                      </p>
                      <p>
                        Child owner: {ensRegistryCheck.childOwner} · Your wallet{" "}
                        {ensRegistryCheck.canRegister ? "has" : "does not have"}{" "}
                        the registrar root role
                      </p>
                      <small>
                        An unowned name may still be reserved.
                      </small>
                    </div>
                  )}
                </form>
                {ensWrite && (
                  <div className="detail">
                    <b>{ensWrite.name}</b>
                    <p className="muted">
                      Transaction: {ensWrite.transactionHash}
                    </p>
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () =>
                          setEnsCheck(
                            await verifyAgentName(window.ethereum, {
                              owner: ensWrite.owner,
                              chainId: ensWrite.chainId,
                              name: ensWrite.name,
                              agentAddress: ensWrite.agentAddress,
                              transactionHash: ensWrite.transactionHash,
                            }),
                          ),
                        )
                      }
                    >
                      Verify transaction and record
                    </button>
                    {ensCheck && (
                      <p>
                        {ensCheck.matches
                          ? "Address record matches"
                          : "Address record does not match"}{" "}
                        · block {String(ensCheck.blockNumber)}
                      </p>
                    )}
                  </div>
                )}
              </details>
              </section>
              <section className="panel-onchain">
                <h2>Onchain policies</h2>
                <details className="settings-task"><summary>Transfer limits & deployment</summary>
                <p className="muted">
                  Onchain limits are separate from workspace permissions.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const hash = await setOnchainLimit(window.ethereum, {
                        registry,
                        chainId,
                        owner: account,
                        agent: chainAgent,
                        token,
                        amount: chainAmount,
                        expiry: expiryValues(transferExpiry).seconds,
                      });
                      setChainTx(hash);
                      setChainStatus("pending");
                    });
                  }}
                >
                  <label>
                    Configured deployment
                    <select
                      disabled={busy}
                      value={chainId}
                      onChange={(e) => {
                        const c = configuredChains.find(
                          (n) => String(n.chain_id) === e.target.value,
                        );
                        if (c) {
                          setChainId(String(c.chain_id));
                          setRegistry(c.registry || "");
                          setAllowanceExecutor(c.executor || "");
                          setDeploymentObservation(null);
                        }
                      }}
                    >
                      <option value="">Choose chain</option>
                      {configuredChains.map((n) => (
                        <option key={n.chain_id} value={n.chain_id}>
                          {n.name} ({n.chain_id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label htmlFor="registry">Registry address</label>
                  <input
                    id="registry"
                    value={registry}
                    onChange={(e) => setRegistry(e.target.value)}
                    placeholder="0x…"
                    required
                  />
                  <label htmlFor="chain-id">Expected chain ID</label>
                  <input
                    id="chain-id"
                    value={chainId}
                    onChange={(e) => setChainId(e.target.value)}
                    inputMode="numeric"
                    placeholder="11155111"
                    required
                  />
                  <label htmlFor="chain-agent">Agent signing address</label>
                  <select
                    id="chain-agent"
                    value={chainAgent}
                    onChange={(e) => setChainAgent(e.target.value)}
                    required
                  >
                    <option value="">Choose agent</option>
                    {data.agents.map((a) => (
                      <option key={a.id} value={a.signing_address}>
                        {a.label || a.ens_name || a.signing_address}
                        {a.revoked ? " (locally revoked)" : ""}
                      </option>
                    ))}
                  </select>
                  <label htmlFor="token">Token contract address</label>
                  <input
                    id="token"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    placeholder="0x…"
                    required
                  />
                  <label htmlFor="chain-amount">
                    Limit per transfer in token base units
                  </label>
                  <input
                    id="chain-amount"
                    value={chainAmount}
                    onChange={(e) => setChainAmount(e.target.value)}
                    inputMode="numeric"
                    placeholder="100000000"
                    required
                  />
                  <label htmlFor="transfer-expiry">
                    Expiry (optional, local time)
                  </label>
                  <input
                    id="transfer-expiry"
                    type="datetime-local"
                    value={transferExpiry}
                    onChange={(e) => setTransferExpiry(e.target.value)}
                  />
                  <div className="inline">
                    <button disabled={busy}>Sign onchain grant</button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const hash = await revokeOnchainLimit(
                            window.ethereum,
                            {
                              registry,
                              chainId,
                              owner: account,
                              agent: chainAgent,
                              token,
                            },
                          );
                          setChainTx(hash);
                          setChainStatus("pending");
                        })
                      }
                    >
                      Revoke token limit
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const hash = await revokeOnchainAgent(
                            window.ethereum,
                            {
                              registry,
                              chainId,
                              owner: account,
                              agent: chainAgent,
                            },
                          );
                          setChainTx(hash);
                          setChainStatus("pending");
                        })
                      }
                    >
                      Permanently revoke agent onchain
                    </button>
                  </div>
                  <p className="muted">
                    Onchain agent revocation is permanent for this owner and
                    signing address. Gateway revocation is a separate action.
                  </p>
                </form>
                <div className="chain-check">
                  <button
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const result = await onchainCapability(
                          window.ethereum,
                          {
                            registry,
                            chainId,
                            owner: account,
                            agent: chainAgent,
                            token,
                          },
                        );
                        setChainCapability({
                          ...result,
                          registry,
                          chainId,
                          agent: chainAgent,
                          token,
                        });
                      })
                    }
                  >
                    Read onchain capability
                  </button>
                  {chainCapability && (
                    <div className="detail">
                      <b>Capability at block {chainCapability.block}</b>
                      <p>
                        Limit: {chainCapability.maxAmount} base units ·{" "}
                        {chainCapability.agentRevoked
                          ? "agent revoked onchain"
                          : chainCapability.revoked
                            ? "revoked"
                            : chainCapability.maxAmount === "0"
                              ? "no transfer capability"
                              : "not revoked; check expiry"}{" "}
                        · version {chainCapability.version}
                      </p>
                      <small>
                        Agent {chainCapability.agent} · token{" "}
                        {chainCapability.token} · chain{" "}
                        {chainCapability.chainId} · registry{" "}
                        {chainCapability.registry} · expiry{" "}
                        {chainCapability.expiresAt === "0"
                          ? "none"
                          : chainCapability.expiresAt}
                      </small>
                    </div>
                  )}
                  <button
                    disabled={busy}
                    onClick={() =>
                      run(async () =>
                        setChainVersion(
                          await onchainVersion(
                            window.ethereum,
                            registry,
                            chainId,
                            account,
                          ),
                        ),
                      )
                    }
                  >
                    Read onchain version
                  </button>
                  {chainVersion && (
                    <p>Onchain policy version: {chainVersion}</p>
                  )}
                  {chainTx && (
                    <>
                      <p className="muted">
                        Transaction: {chainTx} · {chainStatus}
                      </p>
                      <button
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            const state = await onchainReceipt(
                              window.ethereum,
                              registry,
                              chainId,
                              chainTx,
                              account,
                            );
                            setChainStatus(state);
                            if (state === "included")
                              setChainVersion(
                                await onchainVersion(
                                  window.ethereum,
                                  registry,
                                  chainId,
                                  account,
                                ),
                              );
                          })
                        }
                      >
                        Check transaction
                      </button>
                    </>
                  )}
                </div>
                </details>
                <details className="settings-task"><summary>Token allowances</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const context = {
                        owner: account,
                        chainId,
                        token,
                        registry,
                        executor: allowanceExecutor,
                        amount: allowanceAmount,
                        observeDeployment: async () => {
                          const observed = (
                            await request(
                              account,
                              "GET",
                              `/onchain/observe-deployment${chainId ? "?chain_id=" + encodeURIComponent(chainId) : ""}`,
                            )
                          ).observation;
                          setDeploymentObservation(observed);
                          return observed;
                        },
                      };
                      const transactionHash = await approveTokenAllowance(
                        window.ethereum,
                        context,
                      );
                      setAllowanceTx({ ...context, transactionHash });
                      setAllowanceStatus("pending");
                      setAllowanceRead(null);
                    });
                  }}
                >
                  <label htmlFor="allowance-executor">
                    Token allowance: executor address
                  </label>
                  <input
                    id="allowance-executor"
                    value={allowanceExecutor}
                    onChange={(e) => setAllowanceExecutor(e.target.value)}
                    placeholder="0x…"
                    required
                  />
                  <label htmlFor="allowance-amount">
                    Allowance in token base units
                  </label>
                  <input
                    id="allowance-amount"
                    value={allowanceAmount}
                    onChange={(e) => setAllowanceAmount(e.target.value)}
                    inputMode="numeric"
                    placeholder="0 to revoke"
                    required
                  />
                  <p className="muted">
                    The executor can spend up to this allowance from your wallet. Set 0 to revoke. Some tokens require revoking before changing an allowance.
                  </p>
                  <div className="inline">
                    <button disabled={busy}>Sign token allowance</button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () =>
                          setAllowanceRead({
                            ...(await tokenAllowance(window.ethereum, {
                              owner: account,
                              chainId,
                              token,
                              executor: allowanceExecutor,
                            })),
                            token,
                            executor: allowanceExecutor,
                            chainId,
                          }),
                        )
                      }
                    >
                      Read token allowance
                    </button>
                  </div>
                </form>
                {allowanceTx && (
                  <div className="detail">
                    <p>
                      Approval transaction: {allowanceTx.transactionHash} ·{" "}
                      {allowanceStatus}
                    </p>
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () =>
                          setAllowanceStatus(
                            await onchainReceipt(
                              window.ethereum,
                              allowanceTx.token,
                              allowanceTx.chainId,
                              allowanceTx.transactionHash,
                              allowanceTx.owner,
                            ),
                          ),
                        )
                      }
                    >
                      Check approval receipt
                    </button>
                    <small>
                      An included receipt alone does not prove the allowance
                      changed. Read the allowance separately.
                    </small>
                  </div>
                )}
                {allowanceRead && (
                  <div className="detail">
                    <p>
                      Allowance: {allowanceRead.amount} base units at block{" "}
                      {allowanceRead.block}.
                    </p>
                    <small>
                      Token {allowanceRead.token} · spender{" "}
                      {allowanceRead.executor} · chain {allowanceRead.chainId}.
                      This is a wallet RPC observation, not finality.
                    </small>
                  </div>
                )}
                </details>
                <details className="settings-task"><summary>Memory read & write access</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const hash = await setOnchainMemory(window.ethereum, {
                        registry,
                        chainId,
                        owner: account,
                        agent: memoryAgent,
                        namespace: memoryNamespace,
                        canRead: memoryRead,
                        canWrite: memoryWrite,
                        expiry: expiryValues(memoryExpiry).seconds,
                      });
                      setChainTx(hash);
                      setChainStatus("pending");
                    });
                  }}
                >
                  <label htmlFor="memory-agent">
                    Onchain memory capability
                  </label>
                  <select
                    id="memory-agent"
                    value={memoryAgent}
                    onChange={(e) => setMemoryAgent(e.target.value)}
                    required
                  >
                    <option value="">Choose agent</option>
                    {data.agents.map((a) => (
                      <option key={a.id} value={a.signing_address}>
                        {a.label || a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  <input
                    value={memoryNamespace}
                    onChange={(e) => setMemoryNamespace(e.target.value)}
                    placeholder="Collection"
                    aria-label="Collection"
                    required
                  />
                  <div className="checks">
                    <label>
                      <input
                        type="checkbox"
                        checked={memoryRead}
                        onChange={(e) => setMemoryRead(e.target.checked)}
                      />{" "}
                      Read
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={memoryWrite}
                        onChange={(e) => setMemoryWrite(e.target.checked)}
                      />{" "}
                      Write
                    </label>
                  </div>
                  <label htmlFor="memory-expiry">
                    Expiry (optional, local time)
                  </label>
                  <input
                    id="memory-expiry"
                    type="datetime-local"
                    value={memoryExpiry}
                    onChange={(e) => setMemoryExpiry(e.target.value)}
                  />
                  <p className="muted">
                    Requires matching local and onchain grants when onchain
                    memory enforcement is enabled. Namespace spelling must match
                    exactly.
                  </p>
                  <div className="inline">
                    <button disabled={busy}>Grant onchain memory access</button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          const hash = await revokeOnchainMemory(
                            window.ethereum,
                            {
                              registry,
                              chainId,
                              owner: account,
                              agent: memoryAgent,
                              namespace: memoryNamespace,
                            },
                          );
                          setChainTx(hash);
                          setChainStatus("pending");
                        })
                      }
                    >
                      Revoke onchain memory access
                    </button>
                  </div>
                </form>
                </details>
                <details className="settings-task"><summary>Verify an owner grant</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const selected = data.agents.find(
                        (a) => a.signing_address === chainAgent,
                      );
                      if (!selected)
                        throw new Error("Select the transfer agent above.");
                      if (
                        !/^[0-9]+$/.test(grantVersion) ||
                        !Number.isSafeInteger(Number(grantVersion))
                      )
                        throw new Error("Enter a valid policy version.");
                      if (
                        !/^[0-9]+$/.test(grantExpiry) ||
                        !Number.isSafeInteger(Number(grantExpiry))
                      )
                        throw new Error(
                          "Enter an expiry timestamp in seconds, or zero.",
                        );
                      const context = {
                        agent_id: selected.id,
                        transaction_hash: grantHash,
                        token,
                        max_amount: chainAmount,
                        expires_at: Number(grantExpiry),
                        policy_version: Number(grantVersion),
                      };
                      const result = await request(
                        account,
                        "POST",
                        `/actions/observe-onchain-grant?chain_id=${encodeURIComponent(chainId)}`,
                        context,
                      );
                      setGrantObservation({ ...result, context });
                    });
                  }}
                >
                  <label htmlFor="grant-hash">
                    Observe an owner transfer grant
                  </label>
                  <input
                    id="grant-hash"
                    value={grantHash}
                    onChange={(e) => setGrantHash(e.target.value)}
                    placeholder="Grant transaction hash"
                    required
                  />
                  <input
                    value={grantVersion}
                    onChange={(e) => setGrantVersion(e.target.value)}
                    inputMode="numeric"
                    placeholder="Grant policy version"
                    aria-label="Grant policy version"
                    required
                  />
                  <input
                    value={grantExpiry}
                    onChange={(e) => setGrantExpiry(e.target.value)}
                    inputMode="numeric"
                    placeholder="Expiry as Unix seconds; 0 for none"
                    aria-label="Grant expiry Unix seconds"
                    required
                  />
                  <p className="muted">
                    Uses the selected agent, token and limit above. The gateway
                    checks its configured registry and RPC.
                  </p>
                  <button disabled={busy}>Check owner grant</button>
                  {grantObservation && (
                    <div className="detail">
                      <b>
                        Grant RPC observation:{" "}
                        {grantObservation.observation.status}
                      </b>
                      <p>
                        {grantObservation.observation.grant_verified
                          ? "Matching owner transaction and grant event"
                          : "Grant not verified"}{" "}
                        · transaction{" "}
                        {grantObservation.context.transaction_hash}
                      </p>
                      <small>
                        Agent {grantObservation.context.agent_id} · token{" "}
                        {grantObservation.context.token} · limit{" "}
                        {grantObservation.context.max_amount} base units ·
                        expiry {grantObservation.context.expires_at} · version{" "}
                        {grantObservation.context.policy_version} · registry{" "}
                        {grantObservation.registry} · chain{" "}
                        {grantObservation.chain_id}. RPC observation, not
                        finality.
                      </small>
                    </div>
                  )}
                </form>
                </details>
                <details className="settings-task"><summary>Verify a transfer receipt</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      const selected = data.agents.find(
                        (a) => a.signing_address === chainAgent,
                      );
                      if (!selected)
                        throw new Error("Select the transfer agent above.");
                      if (
                        !Number.isSafeInteger(Number(transferVersion)) ||
                        Number(transferVersion) < 0
                      )
                        throw new Error("Enter a valid policy version.");
                      const context = {
                        agent_id: selected.id,
                        transaction_hash: transferHash,
                        token,
                        recipient: transferRecipient,
                        amount: chainAmount,
                        policy_version: Number(transferVersion),
                      };
                      const result = await request(
                        account,
                        "POST",
                        `/actions/observe-onchain?chain_id=${encodeURIComponent(chainId)}`,
                        context,
                      );
                      setBalanceObservation(null);
                      setTransferObservation({
                        ...result.observation,
                        chain_id: result.chain_id,
                        context,
                      });
                      if (
                        result.observation.transfer_verified ||
                        result.observation.reverted_call_verified
                      )
                        await refresh(account);
                    });
                  }}
                >
                  <label htmlFor="transfer-hash">
                    Observe a protected transfer
                  </label>
                  <input
                    id="transfer-hash"
                    value={transferHash}
                    onChange={(e) => setTransferHash(e.target.value)}
                    placeholder="Transaction hash"
                    required
                  />
                  <input
                    value={transferRecipient}
                    onChange={(e) => setTransferRecipient(e.target.value)}
                    placeholder="Recipient address"
                    aria-label="Transfer recipient"
                    required
                  />
                  <input
                    value={transferVersion}
                    onChange={(e) => setTransferVersion(e.target.value)}
                    inputMode="numeric"
                    placeholder="Policy version at transfer"
                    aria-label="Policy version at transfer"
                    required
                  />
                  <p className="muted">
                    Uses the selected agent, token and amount above. The gateway
                    checks its configured RPC and executor.
                  </p>
                  <button disabled={busy}>Check transfer</button>
                  {transferObservation && (
                    <div className="detail">
                      <p>
                        RPC observation: {transferObservation.status}
                        {transferObservation.transfer_verified
                          ? transferObservation.token_transfer_event_matched
                            ? " · matching executor and token transfer events"
                            : " · executor event matched; token transfer event not matched"
                          : transferObservation.reverted_call_verified
                            ? " · matching reverted call; cause unknown"
                            : " · no matching transfer event or reverted call"}
                      </p>
                      <small>
                        Checked transaction{" "}
                        {transferObservation.context.transaction_hash} · token{" "}
                        {transferObservation.context.token} · recipient{" "}
                        {transferObservation.context.recipient} · amount{" "}
                        {transferObservation.context.amount} base units ·
                        version {transferObservation.context.policy_version}.
                      </small>
                      {transferObservation.transfer_verified && (
                        <>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                const checked = transferObservation;
                                const result = await request(
                                  account,
                                  "POST",
                                  `/actions/observe-token-balance?chain_id=${encodeURIComponent(checked.chain_id)}`,
                                  {
                                    token: checked.context.token,
                                    recipient: checked.context.recipient,
                                    block_number: checked.block_number,
                                  },
                                );
                                const observation = result.observation;
                                const blockMatches =
                                  Boolean(checked.block_hash) &&
                                  result.chain_id === checked.chain_id &&
                                  observation.block_hash?.toLowerCase() ===
                                    checked.block_hash.toLowerCase();
                                setBalanceObservation({
                                  ...observation,
                                  blockMatches,
                                  amount: checked.context.amount,
                                });
                              })
                            }
                          >
                            Check recipient balance around block
                          </button>
                          {balanceObservation && (
                            <p>
                              Recipient balance: {balanceObservation.before} →{" "}
                              {balanceObservation.after} base units · change{" "}
                              {balanceObservation.delta}.{" "}
                              {balanceObservation.blockMatches &&
                              balanceObservation.delta ===
                                BigInt(balanceObservation.amount).toString()
                                ? "Matches the requested amount and receipt block."
                                : "Does not match the requested amount or receipt block."}{" "}
                              Other transactions in the block can affect the
                              balance; the RPC and token are trusted and this is
                              not finality.
                            </p>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </form>
              </details>
              </section>
              <section className="panel-activity">
                <ActivityFeed events={data.events} agents={data.agents} busy={busy} showHeading={view !== "activity"}
                  onMemory={id => {setMemoryFilter({memoryId: id}); setView("memories");}}
                  onAgents={() => setView("agents")}
                  onPermissions={() => setView("permissions")}
                  onEns={(agent, info) => {if (agent) setEnsAgent(agent.signing_address); if (typeof info.name === "string" && info.name.includes(".")) {const [label, ...parent] = info.name.split("."); setEnsLabel(label); setEnsParent(parent.join("."));} setIntegrationTab("names"); setView("settings");}}
                  onTransfers={() => {setIntegrationTab("policies"); setView("settings");}}
                />
              </section>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
