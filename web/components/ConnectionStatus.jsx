export default function ConnectionStatus({ readiness, automatic, busy, onRefresh }) {
  const configured = value => readiness ? value ? "Configured" : "Not configured" : "Not checked";
  const items = [
    ["Proof publication", automatic ? "Automatic" : "Manual", "01"],
    ["ENS names", configured(readiness?.ens_sepolia_configured), "02"],
    ["0G inference", configured(readiness?.zero_g_router_configured), "03"],
    ["Onchain deployment", configured(readiness?.onchain_registry), "04"],
  ];
  return <>
    <div className="settings-panel-heading"><h2>Connections</h2><button disabled={busy} onClick={onRefresh}>{busy ? "Checking…" : "Refresh status"}</button></div>
    <div className="connection-cards">{items.map(([label, value, number]) => <div className="connection-card" key={label}><span className="connection-number">{number}</span><h3>{label}</h3><span className={`connection-value ${value === "Not configured" ? "missing" : ""}`}>{value}</span></div>)}</div>
  </>;
}
export function ConnectionDiagnostics({ readiness: r }) {
  if (!r) return <p className="muted">Refresh status to load diagnostics.</p>;
  const rows = [
    ["Connection verification", r.connection_attestation_required ? r.connection_attestation_available ? "Required · verifier configured" : "Required · verifier missing" : "Disabled · use non-sensitive test data only"],
    ["Request binding", r.request_binding_verification_supported ? "Supported" : "Not verified"],
    ["Unbound results", r.unbound_inference_allowed ? "Test compatibility enabled · may become agent-readable" : "Withheld unless an eligible observation is explicitly reviewed"],
    ["Arkiv publisher key", r.arkiv_publisher_configured ? "Present · validity and funding not checked" : "Not configured"],
    ["Action observer", r.onchain_observer_configured ? "Configured" : "Not configured"],
    ...(r.zero_g_experimental_bridge ? [["Experimental 0G bridge", "Enabled · results unverified and quarantined"]] : []),
  ];
  return <dl className="connection-diagnostics">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}
