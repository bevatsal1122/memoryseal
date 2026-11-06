// Deterministic layout: only explicit parent IDs create edges, never proximity.
export function memoryGraph(memories) {
  const records = new Map(memories.map(m => [m.id, m]));
  const nodes = [...records.values()].map(memory => ({id: memory.id, memory, external: false}));
  const missing = new Set();
  for (const m of records.values()) if (m.parent_id && !records.has(m.parent_id)) missing.add(m.parent_id);
  for (const id of missing) nodes.push({id, external: true});
  nodes.sort((a, b) => a.id.localeCompare(b.id));
  const edges = [...records.values()].filter(m => m.parent_id).map(m => ({source:m.parent_id, target:m.id}));
  const degree = new Map();
  for (const e of edges) for (const id of [e.source,e.target]) degree.set(id,(degree.get(id)||0)+1);
  const size = Math.max(780, Math.sqrt(nodes.length) * 145);
  const height = size * .65;
  nodes.forEach((n,i) => {
    const angle = i * 2.3999632297;
    const radius = Math.sqrt((i + 0.5)/Math.max(nodes.length,1)) * size * .36;
    n.x = size/2 + Math.cos(angle)*radius; n.y = height/2 + Math.sin(angle)*radius*.65;
    n.r = n.external ? 15 : 25 + Math.min(18, (degree.get(n.id)||0)*4);
  });
  const byId = new Map(nodes.map(n => [n.id,n]));
  for(let iteration=0;iteration<180;iteration++) {
    const forces = nodes.map(n=>({x:(size/2-n.x)*.002,y:(height/2-n.y)*.002}));
    for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++) {
      const a=nodes[i],b=nodes[j], dx=a.x-b.x,dy=a.y-b.y,d=Math.max(1,Math.hypot(dx,dy));
      const force=Math.min(12, 6000/(d*d)+Math.max(0,a.r+b.r+48-d)*.12);
      forces[i].x+=dx/d*force;forces[i].y+=dy/d*force;
      forces[j].x-=dx/d*force;forces[j].y-=dy/d*force;
    }
    for(const edge of edges) {
      const a=byId.get(edge.source),b=byId.get(edge.target);
      if(a===b)continue;
      const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy)),force=(d-a.r-b.r-65)*.035;
      const ai=nodes.indexOf(a),bi=nodes.indexOf(b);
      forces[ai].x+=dx/d*force;forces[ai].y+=dy/d*force;
      forces[bi].x-=dx/d*force;forces[bi].y-=dy/d*force;
    }
    nodes.forEach((n,i)=>{n.x=Math.max(n.r+20,Math.min(size-n.r-20,n.x+forces[i].x));n.y=Math.max(n.r+20,Math.min(height-n.r-20,n.y+forces[i].y));});
  }
  return {nodes, edges, size, height};
}
export function memoryState(m) {
  return m.status === 'quarantined' ? 'review' : m.lineage_eligible === false ? 'withheld' : 'available';
}
