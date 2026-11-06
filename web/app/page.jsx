"use client";

import { useEffect, useRef, useState } from "react";
import { useWorkspaceNavigation } from "../lib/workspace-navigation";
import WorkspaceGuide from "../components/design/WorkspaceGuide";
import Landing from "../components/design/Landing";
import Brand from "../components/design/Brand";
import NavIcon from "../components/design/NavIcon";
import AgentWorkbench from "../components/AgentWorkbench";
import TeamVaultPanel from "../components/TeamVaultPanel";
import { normalize } from "viem/ens";
import { verifyMemoryCommitment } from "../lib/commitment.mjs";
import {
  loadResolverRecovery,
  saveResolverRecovery,
} from "../lib/resolver-recovery.mjs";
import { clearBrowserSessions } from "../lib/browser-session.mjs";
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
  registerAgentSubname,
  verifyAgentSubname,
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

function MemoryEvidence({
  memory,
  observation,
  history,
  eventObservations,
  onObserve,
  onHistory,
  onObserveEvent,
  onPublishEvent,
  onReconcileEvent,
  onParent,
  onChildren,
  busy,
}) {
  const analysis = memory.analysis;
  const evidence = analysis?.evidence;
  return (
    <details>
      <summary>Analysis and provenance</summary>
      <p className="muted">
        Memory ID: {memory.id} · policy version {memory.policy_version}
      </p>
      <p className="muted">
        Write request ID: {memory.request_id || "Not recorded"}
      </p>
      <p className="muted">
        Original gateway decision reason:{" "}
        {memory.creation_reason || "Not recorded"}. Current read eligibility is
        checked separately.
      </p>
      <p className="muted">
        Parent memory: {memory.parent_id || "None"} · commitment:{" "}
        {memory.commitment}
      </p>
      <div className="inline">
        {memory.parent_id && (
          <button disabled={busy} onClick={onParent}>
            Show parent
          </button>
        )}
        <button disabled={busy} onClick={onChildren}>
          Show children
        </button>
      </div>
      <p className="muted">
        Inference request: {memory.inference_reference || "Not available"}
      </p>
      {analysis ? (
        <>
          <p>
            Classifier category: {analysis.category || "not available"} · risk:{" "}
            {analysis.risk} · recommendation: {analysis.recommendation} ·
            suspicious instruction:{" "}
            {analysis.suspicious_instruction ? "yes" : "no"}
          </p>
          <p className="muted">
            Reported conflicts:{" "}
            {analysis.conflicts_with?.length
              ? analysis.conflicts_with.join(", ")
              : "None"}
          </p>
          {evidence?.inference_transport === "experimental_bridge" && (
            <p className="muted">
              Experimental 0G bridge: this result is unverified and remains
              quarantined. The gateway trusts the configured bridge executable;
              its output does not independently prove provider attestation,
              plaintext binding, or which model executed.
            </p>
          )}
          {evidence?.bridge_reported_provider && (
            <p className="muted">
              Bridge-reported selected provider:{" "}
              {evidence.bridge_reported_provider}. This is an assertion from the
              configured executable, not independent evidence.
            </p>
          )}
          {evidence?.bridge_receipt_signer_matched === true && (
            <p className="muted">
              A bridge-reported encrypted-response receipt was signed by the
              configured signer. This does not independently bind the receipt to
              the submitted memory or establish attestation.
            </p>
          )}
          {evidence?.bridge_receipt_binding_matched === true && (
            <p className="muted">
              The receipt hashes match encrypted artifacts reported by the
              bridge. This hash check alone does not establish what those
              artifacts contain or that they were sent on the wire.
            </p>
          )}
          {evidence?.bridge_receipt_challenge_matched === true && (
            <p className="muted">
              The signed request artifacts include this inference attempt’s
              random challenge. This helps detect replay but does not establish
              plaintext binding or provider attestation.
            </p>
          )}
          {evidence?.bridge_receipt_response_choices_matched === true && (
            <p className="muted">
              The returned choices matched the independently opened, signed
              response ciphertext using a bridge-reported ephemeral key. This
              does not establish that the request plaintext was correct or that
              the provider was attested.
            </p>
          )}
          {evidence?.bridge_receipt_request_messages_matched === true && (
            <p className="muted">
              The signed request ciphertext matches the submitted messages using
              bridge-reported sealing material. This does not attest the
              recipient key or prove which service received the request.
            </p>
          )}
          {evidence?.bridge_quote_recipient_key_matched === true && (
            <p className="muted">
              The request key matched a strict provider-verifier result. This is
              a gateway observation that trusts the configured verifier, RPC and
              bridge; live execution is not established.
            </p>
          )}
          {evidence && (
            <p className="muted">
              0G {evidence.network} · router verification:{" "}
              {evidence.router_verified === true
                ? "reported successful"
                : evidence.router_verified === false
                  ? "reported failed"
                  : "not available"}{" "}
              · provider: {evidence.provider || "not available"} · response key:{" "}
              {evidence.response_key || "not available"}
            </p>
          )}
          {Number.isInteger(evidence?.policy_snapshot_version) && (
            <p className="muted">
              Gateway-reported policy snapshot: version{" "}
              {evidence.policy_snapshot_version} · stored memory version:{" "}
              {memory.policy_version}.{" "}
              {memory.inference_status === "stale"
                ? "Policy changed or a capability expired during inference; treat this result as stale."
                : "Snapshot metadata is not proof of request binding."}
            </p>
          )}
          {evidence?.gateway_connection_attested === true && (
            <p className="muted">
              Gateway reports a strict-verifier certificate match on its
              inference connection: SHA-256{" "}
              {evidence.gateway_certificate_sha256}. This trusts the configured
              verifier and does not independently attest the provider response.
            </p>
          )}
          {evidence?.provider_record_matched === true && (
            <p className="muted">
              Configured provider pins matched the observed 0G service record
              before inference. The configured RPC is trusted.
            </p>
          )}
          {evidence?.pinned_signature_verified !== undefined && (
            <p className="muted">
              Pinned signer check:{" "}
              {evidence.pinned_signature_verified
                ? "matched response text"
                : "failed"}
              . The provider and signer are operator-configured; this does not
              verify the request or attestation.
            </p>
          )}
          <p className="muted">
            Analysis and reported conflicts are advisory. Local policy is
            separate from onchain enforcement. Router-reported verification is
            not independent verification.
          </p>
        </>
      ) : (
        <p className="muted">
          {memory.analysis_state === "invalid"
            ? "Stored classifier analysis is invalid. This memory is withheld from agent reads."
            : "No classifier analysis available."}
        </p>
      )}
      <p className="muted">
        Publishing uses the configured Arkiv test wallet and publishes event
        metadata, never memory content. Uncertain events are checked without
        resubmitting.
      </p>
      <button disabled={busy} onClick={onHistory}>
        Show provenance events
      </button>
      {history?.events.some(
        (e) => e.event_type === "memory_origin_attested",
      ) && (
        <p className="muted">
          An agent signed a gateway-supplied commitment. This does not prove the
          content is true or that the agent independently verified it.
        </p>
      )}
      {history && (
        <div>
          {history.events.length === 0 && <p className="muted">No events</p>}
          {history.events.map((e) => (
            <div key={e.event_id}>
              <small>
                {e.event_type}: {e.state} · {e.event_id}
              </small>
              {e.state === "pending" && (
                <button
                  disabled={busy}
                  onClick={() => onPublishEvent(e.event_id)}
                >
                  Publish public metadata
                </button>
              )}
              {e.state === "uncertain" && (
                <button
                  disabled={busy}
                  onClick={() => onReconcileEvent(e.event_id)}
                >
                  Reconcile without republishing
                </button>
              )}
              <button
                disabled={busy || e.state !== "published"}
                onClick={() => onObserveEvent(e.event_id)}
              >
                Check this Arkiv event
              </button>
              {eventObservations[e.event_id] && (
                <small>
                  Current query: {eventObservations[e.event_id]}. This is an RPC
                  observation, not proof of permanence or truth.
                </small>
              )}
            </div>
          ))}
          {history.truncated && <p className="muted">List truncated</p>}
        </div>
      )}
      <p className="muted">
        Creation event ID: {memory.provenance?.event_id || "Not available"}
      </p>
      <p className="muted">
        Arkiv transaction:{" "}
        {memory.provenance?.transaction_hash || "Not available"}
        {/^0x[0-9a-fA-F]{64}$/.test(memory.provenance?.transaction_hash || "") && (
          <>
            {" · "}
            <a
              href={`https://rabdi.explorer.arkiv.network/tx/${memory.provenance.transaction_hash}`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="View Arkiv transaction in explorer (opens in a new tab)"
            >
              View transaction ↗
            </a>
          </>
        )}
      </p>
      <p className="muted">
        Arkiv creator: {memory.provenance?.creator_address || "Not recorded"}
      </p>
      <button
        disabled={busy || memory.provenance?.state !== "published"}
        onClick={onObserve}
      >
        Check Arkiv record
      </button>
      {observation && (
        <p className="muted">
          Current Arkiv query: {observation}. This is an RPC observation, not
          proof of permanence or truth.
        </p>
      )}
    </details>
  );
}

function eventDescription(event) {
  if (event.event_type === "namespace_access_denied")
    return `${event.reason} · namespace ${event.resource} · agent ${event.actor}`;
  if (event.event_type === "transfer_simulated" && event.details) {
    const d = event.details;
    const limits =
      d.capabilities
        .map(
          (cap) =>
            `${cap.max_amount ?? "none"} base units${cap.expires_at ? ` (expires ${cap.expires_at})` : ""}`,
        )
        .join(", ") || "no unrevoked grant";
    return `Simulation · agent ${d.agent_id} · requested ${d.amount} ${d.asset} · limit ${limits} · requested policy ${d.requested_policy_version} · ${event.reason}`;
  }
  if (
    (event.event_type === "capability_granted" ||
      event.event_type === "capability_revoked") &&
    event.details
  ) {
    const d = event.details;
    return `${event.reason} · agent ${d.agent_id} · ${d.operation} ${d.resource}${d.max_amount === null ? "" : ` · limit ${d.max_amount} base units`}${d.expires_at ? ` · expires ${d.expires_at}` : ""}`;
  }
  if (
    event.event_type === "onchain_transfer_observed" ||
    event.event_type === "onchain_transfer_revert_observed"
  ) {
    try {
      const detail = JSON.parse(event.reason);
      return `RPC observation${event.event_type === "onchain_transfer_revert_observed" ? " · reverted, cause unknown" : " · transfer event matched"} · ${detail.amount} base units · token ${detail.token} · block ${detail.block_number}`;
    } catch {
      return "RPC observation";
    }
  }
  return event.reason;
}

export default function Dashboard() {
  const [session, setSession] = useState(0);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const wallet = window.ethereum;
    if (!wallet?.on) return;
    const reset = () => {
      clearBrowserSessions();
      controller.current.abort();
      controller.current = new AbortController();
      setSession((value) => value + 1);
    };
    window.addEventListener("memoryseal:signout", reset);
    wallet.on("accountsChanged", reset);
    wallet.on("chainChanged", reset);
    wallet.on("disconnect", reset);
    return () => {
      window.removeEventListener("memoryseal:signout", reset);
      wallet.removeListener?.("accountsChanged", reset);
      wallet.removeListener?.("chainChanged", reset);
      wallet.removeListener?.("disconnect", reset);
    };
  }, []);
  return <DashboardSession key={session} signal={controller.current.signal} />;
}

function DashboardSession({ signal }) {
  const request = (account, method, path, payload) =>
    signedRequest({
      account,
      method,
      path,
      payload,
      api,
      audience,
      wallet: window.ethereum,
      useSession: true,
      signal,
    });
  const [account, setAccount] = useState("");
  const [view, setView] = useWorkspaceNavigation();
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
  const [ensExpiry, setEnsExpiry] = useState("");
  const [ensRegistration, setEnsRegistration] = useState(null);
  const [ensRegistrationCheck, setEnsRegistrationCheck] = useState(null);
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
  async function refresh(owner) {
    // Read requests share the browser login session.
    const [agents, capabilities, memories, events] = await Promise.all([
      request(owner, "GET", "/agents"),
      request(owner, "GET", "/capabilities"),
      request(owner, "GET", "/memories"),
      request(owner, "GET", "/events"),
    ]);
    setData({
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
    const result = await request(
      account,
      "GET",
      memorySearchPath(filter, offset),
    );
    setMemoryPage(result);
    setMemoryOffset(offset);
    setAppliedFilter(filter);
    setDetail(null);
  }
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
    ["workbench", "Agent console"],
    ["settings", "Integrations"],
  ];
  const activeAgents = data?.agents.filter((a) => !a.revoked).length || 0;
  const quarantineCount =
    data?.memories.filter((m) => m.status === "quarantined").length || 0;
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
            <Brand />
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
                <button
                  className="refresh-button"
                  disabled={busy}
                  onClick={() => window.dispatchEvent(new Event("memoryseal:signout"))}
                >
                  Sign out
                </button>
                <span className="wallet-chip">
                  {account.slice(0, 6)}…{account.slice(-4)}
                </span>
                <button
                  className="refresh-button"
                  disabled={busy}
                  onClick={() => run(() => refresh(account))}
                >
                  {busy ? "Loading…" : "↻  Refresh"}
                </button>
              </div>
            </div>
            {error && (
              <div role="alert" className="alert">
                {error}
              </div>
            )}
            <div className="workspace-heading">
              <div>
                <h1 tabIndex={-1}>
                  {nav.find((item) => item[0] === view)?.[1]}
                  <span className="heading-dot">.</span>
                </h1>
                <p>
                  {
                    {
                      teams:
                        "Manage your team’s gateway access and permissions.",
                      vault:
                        "Keep encryption keys and private content on your device.",
                      overview:
                        "Your agents, memories, and permissions at a glance.",
                      memories:
                        "Explore what your agents have recorded and review the details.",
                      agents:
                        "Manage the identities that participate in your workspace.",
                      permissions:
                        "Define what each agent can read, write, and do.",
                      activity:
                        "Follow the decisions and actions in your workspace.",
                      workbench:
                        "Write, read, and execute with your registered agent wallet.",
                      settings:
                        "Check connections and manage advanced onchain controls.",
                    }[view]
                  }
                </p>
              </div>
            </div>
            {["overview", "memories", "workbench"].includes(view) &&
              data.memories.some(
                (m) => m.inference_status === "unverified",
              ) && (
                <div className="trust-notice">
                  <span>!</span>
                  <div>
                    <b>Unverified inference</b>
                    <p>
                      Model results are not independently verified. Sharing
                      requires quarantine clearance through explicit owner
                      review. Use synthetic data while independent inference
                      verification is incomplete.
                    </p>
                  </div>
                  <button onClick={() => setView("memories")}>
                    Review memories ↗
                  </button>
                </div>
              )}
            <div hidden={view !== "teams" && view !== "vault"}>
              <TeamVaultPanel
                key={account}
                account={account}
                signal={signal}
                mode={view === "teams" ? "teams" : "vault"}
              />
            </div>
            <div hidden={view !== "workbench"}>
              <AgentWorkbench
                account={account}
                request={request}
                signal={signal}
              />
            </div>
            {view === "overview" && (
              <WorkspaceGuide
                agents={activeAgents}
                capabilities={
                  data.capabilities.filter(
                    (c) =>
                      capabilityActive(c) &&
                      data.agents.some(
                        (a) => a.id === c.agent_id && !a.revoked,
                      ),
                  ).length
                }
                quarantined={quarantineCount}
                onNavigate={setView}
              />
            )}
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
                ].map(([id, label, description]) => (
                  <button
                    key={id}
                    aria-current={integrationTab === id ? "page" : undefined}
                    onClick={() => setIntegrationTab(id)}
                  >
                    <b>{label}</b>
                    <small>{description}</small>
                  </button>
                ))}
              </nav>
            )}
            <section className="panel-setup">
              <h2>Integration configuration</h2>
              <p className="muted">
                Check the gateway’s current configuration before running the
                live demo. This does not test service availability, balances,
                wallet ownership, deployed contracts or attestation.
              </p>
              <button
                disabled={busy}
                onClick={() =>
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
                }
              >
                Check configuration
              </button>
              {integrationReadiness && (
                <div className="detail">
                  <p>
                    ENS Sepolia:{" "}
                    {integrationReadiness.ens_sepolia_configured
                      ? "configured"
                      : "not configured"}{" "}
                    · 0G router:{" "}
                    {integrationReadiness.zero_g_router_configured
                      ? "configured"
                      : "not configured"}
                  </p>
                  {integrationReadiness.connection_attestation_required ? (
                    <p>
                      Gateway connection check required · verifier{" "}
                      {integrationReadiness.connection_attestation_available
                        ? "configured"
                        : "not configured"}
                      . Availability does not prove a successful check.
                    </p>
                  ) : (
                    <p>
                      Gateway connection check disabled. Inference can send
                      content without this pre-send verification; use only
                      non-sensitive test data.
                    </p>
                  )}
                  <p>
                    Inference request binding:{" "}
                    {integrationReadiness.request_binding_verification_supported
                      ? "supported"
                      : "not verified"}
                    .{" "}
                    {integrationReadiness.unbound_inference_allowed
                      ? "Test-only compatibility is enabled; unbound results can become agent-readable."
                      : "Unbound results are withheld unless the owner explicitly reviews an eligible observation for sharing."}
                  </p>
                  {integrationReadiness.zero_g_experimental_bridge && (
                    <p>
                      Experimental 0G bridge enabled. Results remain unverified
                      and quarantined; this check does not validate the
                      executable or provider.
                    </p>
                  )}
                  <p>
                    Arkiv publisher key:{" "}
                    {integrationReadiness.arkiv_publisher_configured
                      ? "present"
                      : "not configured"}{" "}
                    · Sepolia action observer:{" "}
                    {integrationReadiness.onchain_observer_configured
                      ? "configured"
                      : "not configured"}
                  </p>
                  <small>
                    Configuration can change after this check. The publisher
                    key’s validity and funding are not checked.
                  </small>
                </div>
              )}
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
            </section>
            <div className="stats">
              <div>
                <small>AGENTS</small>
                <strong>{data.agents.length}</strong>
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
                <small>QUARANTINED (LATEST 100)</small>
                <strong>
                  {
                    data.memories.filter((m) => m.status === "quarantined")
                      .length
                  }
                </strong>
              </div>
              <div>
                <small>POLICY VERSION</small>
                <strong>{data.version}</strong>
              </div>
            </div>
            <div className="grid">
              <section className="panel-agents">
                <div className="section-head">
                  <div>
                    <h2>Agents</h2>
                  </div>
                </div>
                {data.agents.length === 0 ? (
                  <p className="muted">No agents registered yet.</p>
                ) : (
                  data.agents.map((a) => (
                    <div className="row" key={a.id}>
                      <div>
                        <b>{a.ens_name || "Agent"}</b>
                        <small>{a.signing_address}</small>
                        <small>
                          ENS{" "}
                          {ensObservations[a.id]
                            ? `${ensObservations[a.id].matches ? "address matched" : "address mismatch"} at block ${ensObservations[a.id].blockNumber}`
                            : "not checked"}
                        </small>
                        {a.ens_name && (
                          <button
                            className="inspect"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                const result = await request(
                                  account,
                                  "POST",
                                  `/agents/${a.id}/observe-ens`,
                                  {},
                                );
                                setEnsObservations((prev) => ({
                                  ...prev,
                                  [a.id]: result.observation,
                                }));
                              })
                            }
                          >
                            Check ENS address
                          </button>
                        )}
                      </div>
                      {a.revoked ? (
                        <span className="pill">Revoked</span>
                      ) : (
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await request(
                                account,
                                "POST",
                                `/agents/${a.id}/revoke`,
                                {},
                              );
                              await refresh(account);
                            })
                          }
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  ))
                )}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await request(account, "POST", "/agents/register", {
                        signing_address: address,
                        ens_name: ensName || null,
                        policy_chain_id: agentPolicyChain
                          ? Number(agentPolicyChain)
                          : null,
                      });
                      setAddress("");
                      setEnsName("");
                      await refresh(account);
                    });
                  }}
                >
                  <label htmlFor="agent-address">Agent signing address</label>
                  <input
                    id="agent-address"
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="0x…"
                    required
                  />
                  <label htmlFor="agent-policy-chain">
                    Policy chain ID (optional)
                  </label>
                  <input
                    id="agent-policy-chain"
                    type="number"
                    min="1"
                    step="1"
                    value={agentPolicyChain}
                    onChange={(e) => setAgentPolicyChain(e.target.value)}
                    placeholder="Default deployment"
                  />
                  <label htmlFor="agent-name">
                    ENS name (optional, unverified)
                  </label>
                  <input
                    id="agent-name"
                    value={ensName}
                    onChange={(e) => setEnsName(e.target.value)}
                    placeholder="browser.example.eth"
                  />
                  <button disabled={busy}>Register agent</button>
                </form>
              </section>
              <section className="panel-permissions">
                <h2>Memory acceptance</h2>
                <p className="muted">
                  Strict is the default. Standard automatically accepts low-risk agent observations
                  in an exact namespace, even when inference is unverified. Conflicts, instructions,
                  external sources and failed analysis stay quarantined. This grants no permissions.
                </p>
                {(data.acceptanceRules || []).map((rule) => (
                  <p key={`${rule.agent_id}:${rule.namespace}`}>
                    {data.agents.find((agent) => agent.id === rule.agent_id)?.ens_name || rule.agent_id}
                    {" · "}{rule.namespace}{" · "}{rule.mode}
                  </p>
                ))}
                <form onSubmit={(event) => {
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
                  <label htmlFor="acceptance-agent">Agent</label>
                  <select id="acceptance-agent" name="agent_id" required defaultValue="">
                    <option value="" disabled>Choose agent</option>
                    {data.agents.filter((agent) => !agent.revoked).map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.ens_name || agent.signing_address}</option>
                    ))}
                  </select>
                  <label htmlFor="acceptance-namespace">Exact namespace</label>
                  <input id="acceptance-namespace" name="namespace" required maxLength={200} placeholder="research" />
                  <label htmlFor="acceptance-mode">Acceptance mode</label>
                  <select id="acceptance-mode" name="mode" defaultValue="strict">
                    <option value="strict">Strict — require existing verification rules</option>
                    <option value="standard">Standard — allow low-risk unverified observations</option>
                  </select>
                  <p className="muted">Applies to new writes. Existing quarantined memories still need review.
                    Returning to strict withholds unreviewed memories accepted through Standard.</p>
                  <button disabled={busy}>Sign acceptance policy</button>
                </form>
                <h2>Capabilities</h2>
                <p className="muted">
                  Only an owner-signed grant changes authority.
                </p>
                {data.capabilities.length === 0 ? (
                  <p className="muted">No permissions granted.</p>
                ) : (
                  data.capabilities.map((c) => (
                    <div className="row" key={c.id}>
                      <div>
                        <b>
                          {c.operation} · {c.resource}
                        </b>
                        <small>
                          {c.agent_id.slice(0, 8)} ·{" "}
                          {c.max_amount == null
                            ? "Namespace access"
                            : `Limit ${c.max_amount} base units`}
                        </small>
                        <small>Expires: {c.expires_at || "Never"} (UTC)</small>
                      </div>
                      {c.revoked ? (
                        <span className="pill">Revoked</span>
                      ) : !capabilityActive(c) ? (
                        <span className="pill">Expired</span>
                      ) : (
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await request(
                                account,
                                "POST",
                                `/capabilities/${c.id}/revoke`,
                                {},
                              );
                              await refresh(account);
                            })
                          }
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  ))
                )}
                <form
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
                  <label htmlFor="grant-agent">Grant a capability</label>
                  <select
                    id="grant-agent"
                    required
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                  >
                    <option value="">Choose agent</option>
                    {data.agents.map((a) => (
                      <option value={a.id} key={a.id}>
                        {a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  <div className="inline">
                    <select
                      value={operation}
                      onChange={(e) => setOperation(e.target.value)}
                      aria-label="Operation"
                    >
                      <option value="write">Write</option>
                      <option value="read">Read</option>
                      <option value="transfer">Transfer</option>
                    </select>
                    <input
                      value={resource}
                      onChange={(e) => setResource(e.target.value)}
                      placeholder="Namespace or asset"
                      aria-label="Namespace or asset"
                      required
                    />
                  </div>
                  {operation === "transfer" && (
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]+"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder="Limit in base units"
                      aria-label="Limit in base units"
                      required
                    />
                  )}
                  <label htmlFor="local-expiry">
                    Expiry (optional, local time)
                  </label>
                  <input
                    id="local-expiry"
                    type="datetime-local"
                    value={localExpiry}
                    onChange={(e) => setLocalExpiry(e.target.value)}
                  />
                  <button disabled={busy}>Sign grant</button>
                </form>
              </section>
              <section className="panel-memories">
                <h2>Memory explorer</h2>
                <p className="muted">
                  Source claims are evidence, never permission. Search matches
                  metadata, not encrypted content. Status filters use the stored
                  status; accepted records can still be withheld if their
                  recorded ancestry is unsafe. Quarantining signs the event ID,
                  memory commitment and current policy version. The queued
                  public record also includes the gateway audience, timestamp
                  and nonce.
                </p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(() => searchMemories(memoryFilter));
                  }}
                >
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
                        {a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  <label htmlFor="search-namespace">Exact namespace</label>
                  <input
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
                  <small>
                    An empty result does not rule out an in-flight write. Retry
                    an uncertain write with the same request ID.
                  </small>
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
                  <button disabled={busy}>Search memories</button>
                </form>
                <p className="muted">
                  {appliedFilter.memoryId
                    ? `Viewing memory ${appliedFilter.memoryId}. `
                    : appliedFilter.parentId
                      ? `Viewing children of ${appliedFilter.parentId}. `
                      : ""}
                  Showing {memoryPage.memories.length} records starting at{" "}
                  {memoryOffset + 1}.
                </p>
                {memoryPage.memories.length === 0 ? (
                  <p className="muted">No matching memories.</p>
                ) : (
                  memoryPage.memories.map((m) => (
                    <div className="row" key={m.id}>
                      <div>
                        <b>{m.category.replaceAll("_", " ")}</b>
                        <small>
                          {m.namespace} · {m.source_type} · {m.trust_class}
                        </small>
                        <small>
                          Agent:{" "}
                          {data.agents.find((a) => a.id === m.agent_id)
                            ?.ens_name || m.agent_id}{" "}
                          · {m.created_at}
                        </small>
                        <small>
                          Inference: {m.inference_status}
                          {m.auto_accepted && " · Accepted under owner’s Standard policy"}
                          {m.owner_reviewed
                            ? " · Owner reviewed for sharing"
                            : ""}
                        </small>
                        {m.status === "accepted" &&
                          m.lineage_eligible === false && (
                            <small>
                              Withheld from agent reads: this memory or its
                              ancestry is quarantined, invalid, or lacks an
                              eligible inference status.
                            </small>
                          )}
                        <small>
                          Provenance: {m.provenance?.state || "unavailable"}
                          {m.provenance?.entity_key
                            ? ` · ${m.provenance.entity_key}`
                            : ""}
                        </small>
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
                      <div>
                        <span
                          className={
                            "pill " +
                            (m.status === "quarantined" ? "warning" : "")
                          }
                        >
                          {m.status}
                        </span>
                        <button
                          className="inspect"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              setCommitmentCheck(null);
                              setDetail(
                                await request(
                                  account,
                                  "GET",
                                  `/memories/${m.id}`,
                                ),
                              );
                            })
                          }
                        >
                          Inspect
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
                  <div className="detail">
                    <b>Memory content</b>
                    <p>{detail.content}</p>
                    <small>
                      Source: {detail.source_reference || "Not supplied"} ·{" "}
                      {detail.trust_class}
                    </small>
                    <p className="muted">
                      This is a claim or observation. It does not grant
                      permission. The commitment salt stays in this browser;
                      sharing it can expose the content to guessing.
                    </p>
                    <button
                      disabled={busy}
                      onClick={() =>
                        run(async () =>
                          setCommitmentCheck(
                            await verifyMemoryCommitment(
                              detail.content,
                              detail.commitment_salt,
                              detail.commitment,
                            ),
                          ),
                        )
                      }
                    >
                      Check content commitment locally
                    </button>
                    {commitmentCheck !== null && (
                      <p>
                        Content {commitmentCheck ? "matches" : "does not match"}{" "}
                        the gateway commitment. This does not establish truth or
                        authorship; compare it separately with the Arkiv event.
                      </p>
                    )}
                    {detail.status === "quarantined" && (
                      <div className="detail">
                        <b>Owner review for sharing</b>
                        <p>
                          Only a low-risk agent observation can be released.
                          First read its content and check its commitment above.
                          Your signature approves this exact memory for agents
                          with read access; it does not verify the model, grant
                          permissions, or authorize a transfer. Signed review
                          metadata is public when published to Arkiv.
                        </p>
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
                          Sign owner review and allow sharing
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
                  </div>
                )}
              </section>
              <section className="panel-ens">
                <h2>Agent name record</h2>
                <p className="muted">
                  Set an agent address on a parent name’s current ENSv2
                  resolver. This creates an owner-managed resolver record, not
                  an owned subname token. The flow only accepts currently
                  unlinked records; a record could be linked by another
                  transaction before yours is included.
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
                    <option value="1">Ethereum mainnet</option>
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
                        {a.ens_name || a.signing_address}
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
                  <label htmlFor="ens-expiry">
                    Owned subname expiry (local time, required)
                  </label>
                  <input
                    id="ens-expiry"
                    type="datetime-local"
                    value={ensExpiry}
                    onChange={(e) => setEnsExpiry(e.target.value)}
                  />
                  <p className="muted">
                    On Sepolia, register a never-used label to your connected
                    wallet. The parent needs a canonical subregistry and your
                    wallet needs its registrar role. The new token inherits its
                    resolver; its initial roles permit renewal, resolver and
                    subregistry changes, and transfer. Registry root role
                    holders may also retain control.
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        if (!ensExpiry)
                          throw new Error("Choose a future subname expiry.");
                        const result = await registerAgentSubname(
                          window.ethereum,
                          {
                            owner: account,
                            chainId: ensNetwork,
                            parentName: ensParent,
                            label: ensLabel,
                            expiry: expiryValues(ensExpiry).seconds,
                          },
                        );
                        setEnsRegistration({
                          ...result,
                          parentName: ensParent,
                          label: ensLabel,
                          chainId: ensNetwork,
                        });
                        setEnsRegistrationCheck(null);
                      })
                    }
                  >
                    Register owned subname on Sepolia
                  </button>
                  {ensRegistration && (
                    <div className="detail">
                      <b>{ensRegistration.name}</b>
                      <p className="muted">
                        Registration transaction:{" "}
                        {ensRegistration.transactionHash}
                      </p>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          run(async () =>
                            setEnsRegistrationCheck(
                              await verifyAgentSubname(
                                window.ethereum,
                                ensRegistration,
                              ),
                            ),
                          )
                        }
                      >
                        Verify registration
                      </button>
                      {ensRegistrationCheck && (
                        <p>
                          {ensRegistrationCheck.matches
                            ? "Owner and registry matched"
                            : "Owner or registry did not match"}{" "}
                          at block {ensRegistrationCheck.blockNumber}. Later
                          changes or reorganizations remain possible.
                        </p>
                      )}
                    </div>
                  )}
                  <div className="detail">
                    <b>Dedicated resolver (Sepolia)</b>
                    <p className="muted">
                      Deploy a separate resolver for this agent name, verify its
                      deployment, then attach it to an owned subname. Attaching
                      it changes the records visible through any inherited
                      resolver. ENS permissions apply across every name using
                      the resolver; avoid sharing it with other names. These
                      transactions do not grant MemorySeal capabilities. Public
                      transaction details are saved in this browser for the
                      connected wallet when storage is available; the latest
                      deployment replaces the previous saved workflow.
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
                          Grant or revoke the selected agent’s ability to set
                          the public memoryseal.config text key. This applies to
                          all names served by this resolver. Do not share it
                          with other names. This is not a memory or action
                          permission; root roles can retain access after
                          key-specific revocation.
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
                        An unowned child can still be reserved. This observation
                        does not create a token, verify all registration
                        conditions, or grant MemorySeal access.
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
              </section>
              <section className="panel-onchain">
                <h2>Protected transfers</h2>
                <p className="muted">
                  These owner-signed transactions set a per-transfer token limit
                  in the contract. Gateway permissions are managed separately.
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
                        {a.ens_name || a.signing_address}
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
                    Uses the token and chain above. The approved contract can
                    spend up to this allowance from your wallet. Nonzero
                    approvals require a fresh gateway check of the executor and
                    local contract build; use 0 to revoke. The check trusts the
                    configured RPC and artifacts, and can change before
                    inclusion. Some tokens require setting an existing allowance
                    to 0 before changing it.
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
                        {a.ens_name || a.signing_address}
                      </option>
                    ))}
                  </select>
                  <input
                    value={memoryNamespace}
                    onChange={(e) => setMemoryNamespace(e.target.value)}
                    placeholder="Exact namespace"
                    aria-label="Exact namespace"
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
              </section>
              <section className="panel-activity">
                <h2>Decision trail</h2>
                {data.events.length === 0 ? (
                  <p className="muted">No activity yet.</p>
                ) : (
                  data.events.map((e) => (
                    <div className="row" key={e.id}>
                      <div>
                        <b>{e.event_type.replaceAll("_", " ")}</b>
                        <small>
                          {eventDescription(e)} · policy {e.policy_version}
                        </small>
                      </div>
                      <span className="pill">{e.decision}</span>
                    </div>
                  ))
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
