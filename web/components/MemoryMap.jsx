"use client";
import {useId, useMemo, useRef, useState} from "react";
import {memoryGraph, memoryState} from "../lib/memory-map.mjs";
const labels = {available:"Available",review:"Needs review",withheld:"Withheld"};
export default function MemoryMap({memories, agents, busy, onInspect, onParent}) {
  const graph = useMemo(()=>memoryGraph(memories),[memories]);
  const [selected,setSelected]=useState(null);
  const [camera,setCamera]=useState({zoom:1,x:0,y:0});
  const drag=useRef(null);
  const arrow=useId().replaceAll(":","");
  const node=graph.nodes.find(n=>n.id===selected);
  const connected=new Set([selected]);
  for(const e of graph.edges) if(e.source===selected || e.target===selected){connected.add(e.source);connected.add(e.target);}
  const byId=new Map(graph.nodes.map(n=>[n.id,n]));
  const name=m=>agents.find(a=>a.id===m.agent_id)?.label || agents.find(a=>a.id===m.agent_id)?.ens_name || "Agent";
  const zoom=delta=>setCamera(c=>({...c,zoom:Math.max(.65,Math.min(3,c.zoom+delta))}));
  return <section className="memory-map" aria-label="Memory relationship map">
    <div className="memory-map-heading"><div><h3>Memory map</h3><p>{memories.length} memories · {graph.edges.length} parent links · current results</p></div>
      <div className="memory-map-controls"><button type="button" aria-label="Zoom out" onClick={()=>zoom(-.25)}>−</button><button type="button" aria-label="Zoom in" onClick={()=>zoom(.25)}>+</button><button type="button" onClick={()=>setCamera({zoom:1,x:0,y:0})}>Reset view</button></div>
    </div>
    <div className="memory-map-canvas">
      {!memories.length ? <div className="memory-map-empty"><b>Your memories will appear here</b><p>Save a memory in Playground to start your map.</p></div> : <svg viewBox={`0 0 ${graph.size} ${graph.height}`} role="group" aria-label="Select a memory bubble to see its connections" onPointerDown={e=>{
        if(e.target.closest('[data-node]'))return;
        const rect=e.currentTarget.getBoundingClientRect();
        drag.current={x:e.clientX,y:e.clientY,camera,scale:Math.max(graph.size/rect.width,graph.height/rect.height)};e.currentTarget.setPointerCapture(e.pointerId);
      }} onPointerMove={e=>{if(!drag.current)return;const d=drag.current;setCamera({...d.camera,x:d.camera.x+(e.clientX-d.x)*d.scale,y:d.camera.y+(e.clientY-d.y)*d.scale});}} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
        <defs><marker id={arrow} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="currentColor"/></marker></defs>
        <g transform={`translate(${graph.size/2+camera.x} ${graph.height/2+camera.y}) scale(${camera.zoom}) translate(${-graph.size/2} ${-graph.height/2})`}>
          {graph.edges.map(e=>{const a=byId.get(e.source),b=byId.get(e.target);const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy));return <line key={`${e.source}-${e.target}`} className={`memory-map-edge ${selected && (e.source===selected || e.target===selected)?"highlight":""}`} x1={a.x+dx/d*(a.r+4)} y1={a.y+dy/d*(a.r+4)} x2={b.x-dx/d*(b.r+9)} y2={b.y-dy/d*(b.r+9)} markerEnd={`url(#${arrow})`} opacity={selected&&!connected.has(e.source)&&!connected.has(e.target)?.18:1}/>;})}
          {graph.nodes.map(n=><g key={n.id} data-node="true" role="button" tabIndex={0} aria-pressed={selected===n.id} aria-label={n.external?"Parent outside current results":`${n.memory.namespace}, ${name(n.memory)}, ${labels[memoryState(n.memory)]}`} transform={`translate(${n.x} ${n.y})`} className={`memory-map-node ${n.external?"external":memoryState(n.memory)} ${selected===n.id?"selected":""}`} opacity={selected&&!connected.has(n.id)?.35:1} onClick={()=>setSelected(n.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(n.id);}}}>
            <title>{n.external?"Parent outside current results":`${n.memory.namespace} · ${name(n.memory)} · ${labels[memoryState(n.memory)]}`}</title>
            <circle r={n.r}/><text textAnchor="middle" dy=".35em">{n.external?"↗":memoryState(n.memory)==="review"?"!":memoryState(n.memory)==="withheld"?"−":"✦"}</text>
            {!n.external&&<text className="memory-map-label" textAnchor="middle" y={n.r+18}>{n.memory.namespace.length>17?n.memory.namespace.slice(0,15)+"…":n.memory.namespace}</text>}
          </g>)}
        </g>
      </svg>}
      <span className="memory-map-hint">Drag to explore · arrows point to derived memories</span>
    </div>
    <div className="memory-map-footer"><div className="memory-map-legend"><span className="available">Available</span><span className="review">Needs review</span><span className="withheld">Withheld</span><span className="external">Parent outside results</span></div><small>Larger bubbles have more visible links.</small></div>
    {node && <div className="memory-map-selection" aria-live="polite"><div><b>{node.external?"Parent outside current results":`${node.memory.namespace} · ${name(node.memory)}`}</b><p>{node.external?"This parent is outside the current filters or page.":`${labels[memoryState(node.memory)]} · ${node.memory.category || "Memory"}`}</p></div><button disabled={busy} onClick={()=>node.external?onParent(node.id):onInspect(node.memory)}>{node.external?"Find parent":"Open memory"}</button><button aria-label="Clear selection" onClick={()=>setSelected(null)}>×</button></div>}
  </section>;
}
