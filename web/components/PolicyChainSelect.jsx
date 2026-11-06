"use client";
import { useEffect, useRef, useState } from "react";
import { policyChainOptions } from "../lib/policy-chain-options";

export default function PolicyChainSelect({ account, request }) {
  const requestRef = useRef(request);
  requestRef.current = request;
  const [networks, setNetworks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setNetworks([]);
    requestRef.current(account, "GET", "/chains").then(result => {
      if (active) setNetworks(result.chains);
    }).catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [account, retry]);
  const configured = new Set(networks.map(n => Number(n.chain_id)));
  return <>
    <select id="setup-chain" name="chain" defaultValue="" aria-describedby={loading || error ? "setup-chain-help" : undefined} aria-busy={loading}>
      <option value="">Use configured default</option>
      {networks.length > 0 && <optgroup label="Available on this gateway">
        {networks.map(n => <option key={n.chain_id} value={n.chain_id}>{policyChainOptions.find(c => c.id === Number(n.chain_id))?.name || n.name} · {n.chain_id}</option>)}
      </optgroup>}
      {[false, true].map(testnet => <optgroup key={String(testnet)} label={testnet ? "Other testnets" : "Other mainnets"}>
        {policyChainOptions.filter(c => c.testnet === testnet && !configured.has(c.id)).map(c => <option key={c.id} value={c.id} disabled>{c.name} · {c.id} — {loading ? "Checking availability" : error ? "Availability unknown" : "Not configured"}</option>)}
      </optgroup>)}
    </select>
    {(loading || error) && <small id="setup-chain-help">{loading ? "Loading configured networks…" : "Couldn’t load network availability. You can still use the configured default."}</small>}
    {error && <button type="button" onClick={() => setRetry(n => n + 1)}>Retry networks</button>}
  </>;
}
