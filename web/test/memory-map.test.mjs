import {test} from 'node:test';
import assert from 'node:assert/strict';
import {memoryGraph,memoryState} from '../lib/memory-map.mjs';
test('map shows only recorded links and makes filtered-out parents explicit',()=>{
 const memories=[{id:'a',parent_id:null},{id:'b',parent_id:'a'},{id:'c',parent_id:'outside'},{id:'d',parent_id:null}];
 const graph=memoryGraph(memories);
 assert.deepEqual(graph.edges,[{source:'a',target:'b'},{source:'outside',target:'c'}]);
 assert.equal(graph.nodes.find(n=>n.id==='outside').external,true);
 assert.equal(graph.nodes.filter(n=>!n.external).length,4);
 assert.deepEqual(graph,memoryGraph(memories));
 for(const n of graph.nodes)assert.ok(Number.isFinite(n.x)&&Number.isFinite(n.y)&&n.x>=n.r&&n.x<=graph.size-n.r);
 assert.equal(memoryState({status:'accepted',lineage_eligible:false}),'withheld');
 assert.equal(memoryState({status:'quarantined'}),'review');
 assert.equal(memoryGraph([]).nodes.length,0);
});
test('cycles and self-links cannot hang layout',()=>{
 const graph=memoryGraph([{id:'a',parent_id:'b'},{id:'b',parent_id:'a'},{id:'c',parent_id:'c'}]);
 assert.equal(graph.edges.length,3);
 for(const n of graph.nodes)assert.ok(Number.isFinite(n.x)&&Number.isFinite(n.y));
});
