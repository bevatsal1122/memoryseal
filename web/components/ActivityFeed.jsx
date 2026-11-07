"use client";
import {useState} from "react";

const pretty = value => String(value || "").replaceAll("_", " ");
const short = value => value?.length > 20 ? `${value.slice(0,8)}…${value.slice(-6)}` : value;
function parsed(event) {
  if (event.details) return event.details;
  try { const value=JSON.parse(event.reason); return value && typeof value==='object'&&!Array.isArray(value)?value:{}; } catch { return {}; }
}
function group(type) {
  if(type.startsWith('memory_'))return 'Memories';
  if(type.includes('transfer'))return 'Transfers';
  if(type.startsWith('ens_'))return 'ENS';
  if(type.startsWith('agent_'))return 'Agents';
  return 'Permissions';
}
const titles={memory_created:'Memory saved',memory_reviewed:'Memory approved for sharing',memory_quarantined:'Memory held for review',memory_inspected:'Memory opened',memory_origin_attested:'Origin acknowledged',memory_author_salt_disclosed:'Content check requested',ens_address_observed:'ENS address checked',transfer_simulated:'Transfer permission checked',onchain_transfer_observed:'Transfer observed onchain',onchain_transfer_revert_observed:'Reverted transfer observed',capability_granted:'Permission granted',capability_revoked:'Permission revoked',agent_setup:'Agent configured',agent_revoked:'Agent revoked',acceptance_policy_changed:'Acceptance policy updated',namespace_access_denied:'Collection access denied'};
function summary(e,d) {
  if(e.event_type==='ens_address_observed')return d.name ? `${d.name} → ${short(d.resolvedAddress) || 'No address'}` : 'ENS lookup recorded';
  if(e.event_type==='transfer_simulated')return e.decision==='allowed'?'The requested transfer passed the workspace permission check. No funds were sent.':'The requested transfer did not pass the workspace permission check.';
  if(e.event_type==='onchain_transfer_observed')return 'The configured RPC reported a matching transfer.';
  if(e.event_type==='onchain_transfer_revert_observed')return 'The configured RPC reported a reverted transaction.';
  if(e.event_type.startsWith('capability_')&&d.operation)return `${pretty(d.operation)} · ${d.resource}`;
  if(e.reason?.trim().startsWith('{'))return '';
  return e.reason || '';
}
function date(value) {const d=new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value||'')?value:`${value}Z`);return Number.isNaN(d.getTime())?'':d.toLocaleString();}
export default function ActivityFeed({events, agents, busy, showHeading = true, onMemory, onAgents, onPermissions, onEns, onTransfers}) {
  const [filter,setFilter]=useState('All');
  const visible=events.filter(e=>filter==='All'||group(e.event_type)===filter);
  return <div className="activity-feed">
    <div className="activity-feed-header">{showHeading && <h2>Recent activity</h2>}<span>{events.length} events</span></div>
    <nav className="activity-filters" aria-label="Filter activity">{['All','Memories','Agents','Permissions','ENS','Transfers'].map(value=><button key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}>{value}</button>)}</nav>
    {visible.length===0&&<p className="muted">No {filter==='All'?'':filter.toLowerCase()+' '}activity yet.</p>}
    {visible.map(e=>{
      const d=parsed(e),kind=group(e.event_type);
      const agent=agents.find(a=>a.id===(d.agent_id || (kind==='Agents'||kind==='ENS'?e.resource:null)) || a.signing_address?.toLowerCase()===e.actor?.toLowerCase());
      const negative=['denied','quarantined','mismatch','reverted'].includes(e.decision);
      const positive=['allowed','accepted','match'].includes(e.decision);
      const tx=/^0x[\da-f]{64}$/i.test(e.resource||'')&&Number(d.chain_id)===11155111?`https://sepolia.etherscan.io/tx/${e.resource}`:null;
      return <article key={e.id} className="activity-event">
        <span className={`activity-event-icon ${negative?'attention':''}`} aria-hidden="true">{{Memories:'◇',Agents:'◎',Permissions:'⊞',ENS:'↗',Transfers:'⇄'}[kind]}</span>
        <div className="activity-event-body"><div className="activity-event-top"><h3>{titles[e.event_type]||pretty(e.event_type)}</h3><span className={`activity-result ${negative?'attention':positive?'positive':''}`}>{e.decision==='quarantined'?'Held for review':pretty(e.decision)}</span></div>
          <div className="activity-event-meta"><time>{date(e.created_at)}</time>{agent&&<span>{agent.label||agent.ens_name||short(agent.signing_address)}</span>}<span>Policy {e.policy_version}</span></div>
          <p className="activity-event-summary">{summary(e,d)}</p>
          <div className="activity-event-actions">
            {kind==='Memories'&&e.resource&&<button disabled={busy} onClick={()=>onMemory(e.resource)}>Open memory ↗</button>}
            {kind==='Agents'&&<button disabled={busy} onClick={onAgents}>Manage agents ↗</button>}
            {kind==='Permissions'&&<button disabled={busy} onClick={onPermissions}>Manage permissions ↗</button>}
            {kind==='ENS'&&<><button disabled={busy} onClick={()=>onEns(agent,d)}>Manage ENS ↗</button>{(d.name || agent?.ens_name) && <a href={`https://explorer.ens.dev/${encodeURIComponent(d.name || agent.ens_name)}`} target="_blank" rel="noopener noreferrer">ENS explorer ↗</a>}</>}
            {kind==='Transfers'&&<button disabled={busy} onClick={onTransfers}>Transfer controls ↗</button>}
            {tx&&<a href={tx} target="_blank" rel="noopener noreferrer">View transaction ↗</a>}
          </div>
        </div>
      </article>;
    })}
  </div>;
}
