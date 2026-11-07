export const OWNER_LIMIT = 5000;
export const DEMO_ASSET = "DEMO_USD";

export function demoAgentNames() {
  const words = ["Orbit", "Cedar", "Nova", "Atlas", "Coral", "Comet"];
  const suffix = crypto.randomUUID().slice(0, 4);
  const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
  return {browser: `${pick()} Browser ${suffix}`, finance: `${pick()} Finance ${suffix}`};
}

export async function publishDemoProof(owner, memoryId, onMemory, signal) {
  const report = proof => {signal?.throwIfAborted(); onMemory({proof});};
  try {
    report({state: "loading"});
    let event = (await owner.provenanceEvents(memoryId)).events.find(e => e.event_type === "memory_created");
    if (!event) throw new Error("No creation proof found.");
    report(event);
    if (event.state === "pending" || event.state === "uncertain") {
      report({...event, state: event.state === "pending" ? "publishing" : "reconciling"});
      try {
        await owner.provenanceAction(memoryId, event.event_id, event.state === "pending" ? "publish" : "reconcile");
      } catch (error) {
        // Another publisher can claim the same event; re-read before reporting failure.
        if (error.status !== 409) throw error;
      }
    }
    for (let attempt = 0; attempt < 8; attempt++) {
      signal?.throwIfAborted();
      event = (await owner.provenanceEvents(memoryId)).events.find(e => e.event_type === "memory_created");
      if (!event) throw new Error("Creation proof is unavailable.");
      report(event);
      if (event.state !== "publishing") break;
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    if (event.state === "published") {
      report({...event, observation: "checking"});
      const checked = await owner.provenanceAction(memoryId, event.event_id, "observe");
      report({...event, observation: checked.observation});
    }
    return event;
  } catch (error) {
    signal?.throwIfAborted();
    onMemory({proofError: error.message || "Arkiv publication could not be confirmed."});
    return null;
  }
}

// Deliberately vulnerable reference worker: source text is treated as authority.
export function naiveFinanceLimit(instruction, ownerLimit = OWNER_LIMIT) {
  const claimed = instruction.match(/Update the payment limit to (?:\$)?([\d,.]+)(?: ETH)?/i);
  return claimed ? Number(claimed[1].replaceAll(",", "")) : ownerLimit;
}

export async function runPaymentDemo({ mode, invoice, clients, emit, signal, onStage = async () => {}, onMemory = () => {}, names = demoAgentNames(), payment = null, prepareAgents = null }) {
  const limit = payment ? 0.005 : OWNER_LIMIT;
  const format = payment ? n => `${n} Sepolia ETH` : n => `$${n.toLocaleString()}`;
  const asset = payment ? "eip155:11155111/slip44:60" : DEMO_ASSET;
  const units = n => payment ? (n === 0.005 ? "5000000000000000" : n === 0.05 ? "50000000000000000" : (() => {throw new Error("Unsupported demo amount");})()) : String(n);
  const log = (actor, title, detail, evidence) => {
    signal?.throwIfAborted();
    emit({ actor, title, detail, evidence });
  };
  onMemory({ownerLimit: limit, effectiveLimit: limit, draft: null, writeStatus: "empty", finance: null});
  const {owner, browser, finance} = clients || {};
  let browserAgent, financeAgent;
  const namespace = "demo-invoices";
  onMemory({names});
  if (prepareAgents) {
    await onStage("setup");
    ({browserAgent, financeAgent} = await prepareAgents({onMemory,onStage,signal}));
    log("ENS", "Both agent names verified", `${browserAgent.ens_name} → ${financeAgent.ens_name}`);
  } else if (mode === "protected") {
  await onStage("setup");
  log("Gateway", "Registering isolated demo identities", "A fresh owner, browser agent, and finance agent. Your workspace is unchanged.");
  browserAgent = await owner.request("POST", "/agents/register", {signing_address: browser.signer.address, label: names.browser});
  onMemory({browserAgent: {...browserAgent, label: names.browser, address: browser.signer.address}});
  financeAgent = await owner.request("POST", "/agents/register", {signing_address: finance.signer.address, label: names.finance});
  onMemory({financeAgent: {...financeAgent, label: names.finance, address: finance.signer.address}});
  await owner.grant({agent_id: browserAgent.id, operation: "write", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "read", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "transfer", resource: asset, max_amount: units(limit)});
  log("MemorySeal", "Signed permissions configured", `Browser: write invoices. Finance: read invoices; payment limit ${format(limit)}.`);
  } else {
    await onStage("setup");
    onMemory({browserAgent: {label: names.browser}, financeAgent: {label: names.finance, address: finance?.signer.address}});
    log("Agents", "Reference agents named", `${names.browser} → ${names.finance}`);
  }
  await onStage("owner");
  log("Owner", "Payment limit set", `${format(limit)} maximum per payment.`);
  await onStage("scan");
  onMemory({draft: invoice.instruction, writeStatus: "draft"});
  log("Browser", "Supplier page scanned", `${invoice.id} · ${invoice.payee} · ${format(invoice.amount)}`, {source: invoice.url, instruction: invoice.instruction});
  if (mode === "baseline") {
    await onStage("memory");
    const sharedMemory = invoice.instruction;
    onMemory({writeStatus: "shared", shared: sharedMemory});
    log("Memory", "Website claim saved as instructions", sharedMemory);
    await onStage("finance");
    const effectiveLimit = naiveFinanceLimit(sharedMemory, limit);
    onMemory({finance: [sharedMemory], effectiveLimit});
    log("Finance", "Shared memory treated as authorization", `Effective limit changed from ${format(limit)} to ${format(effectiveLimit)}.`);
    await onStage("payment");
    const permitted = invoice.amount <= effectiveLimit;
    const transaction = payment && permitted ? await payment.send({mode,amount:invoice.amount,allowed:true,visible:true}) : null;
    const paid = payment ? transaction?.paid === true : permitted;
    log("Ledger", transaction ? `Transaction ${transaction.state}` : paid ? "Simulated payment recorded" : "Payment declined", `${format(paid ? invoice.amount : 0)} to ${invoice.payee}`);
    return {paid, amount: paid ? invoice.amount : 0, effectiveLimit, memoryVisible: true, transaction, verdict: transaction && !paid ? `Transaction ${transaction.state}` : paid ? "Limit bypassed" : "Payment declined"};
  }
  await onStage("evaluate");
  onMemory({writeStatus: "evaluating"});
  const memory = await browser.writeMemory({agent_id: browserAgent.id, namespace, content: invoice.instruction, source_type: "external", source_reference: invoice.url});
  onMemory({writeStatus: memory.status, memoryId: memory.id, commitment: memory.commitment, policyVersion: memory.policy_version, trust: memory.trust_class});
  log("MemorySeal", `Memory write: ${memory.status}`, "External website content evaluated by the gateway.", memory);
  await onStage("publish");
  const proof = await publishDemoProof(owner, memory.id, onMemory, signal);
  log("Arkiv", proof ? `Creation proof: ${proof.state}` : "Publication needs attention", "Public metadata and commitment only; plaintext stays in the gateway.", proof);
  await onStage("recall");
  const recalled = await finance.readMemory(financeAgent.id, namespace);
  const visible = recalled.memories.some(item => item.id === memory.id);
  onMemory({finance: recalled.memories.map(item => item.content), shared: visible ? invoice.instruction : null});
  log("Finance", visible ? "Website claim is readable" : "Website claim withheld from finance", visible ? "The gateway returned the invoice claim. Check the write evidence before claiming a memory block." : "The finance agent did not receive the website’s claimed authorization.", recalled);
  await onStage("policy");
  const policy = await owner.listCapabilities();
  const transfer = await finance.simulateTransfer(financeAgent.id, asset, units(invoice.amount), policy.policy_version);
  log("Policy", transfer.allowed ? "Transfer simulation allowed" : "Transfer simulation denied", `Independent permission check against the signed ${format(limit)} cap.`, transfer);
  // This is only a demo ledger, even if a gateway unexpectedly allows the request.
  await onStage("payment");
  const transaction = payment ? await payment.send({mode,amount:invoice.amount,allowed:transfer.allowed === true,visible}) : null;
  const paid = payment ? transaction?.paid === true : transfer.allowed === true;
  log("Ledger", paid ? "Simulated payment recorded" : "No payment recorded", paid ? `${format(invoice.amount)} · unexpected policy outcome` : `No payment. Owner policy remains ${format(limit)}.`);
  return {paid, amount: paid ? invoice.amount : 0, effectiveLimit: limit, transaction, memoryVisible: visible, memoryStatus: memory.status, verdict: paid ? "Unexpected: payment allowed" : visible ? "Payment blocked · memory readable" : "Memory withheld · payment blocked", memoryId: memory.id};
}
