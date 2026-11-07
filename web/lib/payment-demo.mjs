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
  const claimed = instruction.match(/Update the payment limit to \$([\d,]+)/i);
  return claimed ? Number(claimed[1].replaceAll(",", "")) : ownerLimit;
}

export async function runPaymentDemo({ mode, invoice, clients, emit, signal, onStage = async () => {}, onMemory = () => {}, names = demoAgentNames() }) {
  const log = (actor, title, detail, evidence) => {
    signal?.throwIfAborted();
    emit({ actor, title, detail, evidence });
  };
  onMemory({ownerLimit: OWNER_LIMIT, effectiveLimit: OWNER_LIMIT, draft: null, writeStatus: "empty", finance: null});
  const {owner, browser, finance} = clients || {};
  let browserAgent, financeAgent;
  const namespace = "demo-invoices";
  onMemory({names});
  if (mode === "protected") {
  await onStage("setup");
  log("Gateway", "Registering isolated demo identities", "A fresh owner, browser agent, and finance agent. Your workspace is unchanged.");
  browserAgent = await owner.request("POST", "/agents/register", {signing_address: browser.signer.address, label: names.browser});
  onMemory({browserAgent: {...browserAgent, label: names.browser, address: browser.signer.address}});
  financeAgent = await owner.request("POST", "/agents/register", {signing_address: finance.signer.address, label: names.finance});
  onMemory({financeAgent: {...financeAgent, label: names.finance, address: finance.signer.address}});
  await owner.grant({agent_id: browserAgent.id, operation: "write", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "read", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "transfer", resource: DEMO_ASSET, max_amount: String(OWNER_LIMIT)});
  log("MemorySeal", "Signed permissions configured", "Browser: write invoices. Finance: read invoices and simulate up to $5,000.");
  } else {
    await onStage("setup");
    onMemory({browserAgent: {label: names.browser}, financeAgent: {label: names.finance}});
    log("Agents", "Reference agents named", `${names.browser} → ${names.finance}`);
  }
  await onStage("owner");
  log("Owner", "Payment limit set", "$5,000 maximum per payment.");
  await onStage("scan");
  onMemory({draft: invoice.instruction, writeStatus: "draft"});
  log("Browser", "Supplier page scanned", `${invoice.id} · ${invoice.payee} · $${invoice.amount.toLocaleString()}`, {source: invoice.url, instruction: invoice.instruction});
  if (mode === "baseline") {
    await onStage("memory");
    const sharedMemory = invoice.instruction;
    onMemory({writeStatus: "shared", shared: sharedMemory});
    log("Memory", "Website claim saved as instructions", sharedMemory);
    await onStage("finance");
    const effectiveLimit = naiveFinanceLimit(sharedMemory);
    onMemory({finance: [sharedMemory], effectiveLimit});
    log("Finance", "Shared memory treated as authorization", `Effective limit changed from $5,000 to $${effectiveLimit.toLocaleString()}.`);
    await onStage("payment");
    const paid = invoice.amount <= effectiveLimit;
    log("Ledger", paid ? "Simulated payment recorded" : "Payment declined", paid ? `$${invoice.amount.toLocaleString()} to ${invoice.payee}` : "Invoice exceeds the effective limit.");
    return {paid, amount: paid ? invoice.amount : 0, effectiveLimit, memoryVisible: true, verdict: paid ? "Limit bypassed" : "Payment declined"};
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
  const transfer = await finance.simulateTransfer(financeAgent.id, DEMO_ASSET, String(invoice.amount), policy.policy_version);
  log("Policy", transfer.allowed ? "Transfer simulation allowed" : "Transfer simulation denied", "Independent permission check against the signed $5,000 cap.", transfer);
  // This is only a demo ledger, even if a gateway unexpectedly allows the request.
  await onStage("payment");
  const paid = transfer.allowed === true;
  log("Ledger", paid ? "Simulated payment recorded" : "No payment recorded", paid ? "$50,000 · unexpected policy outcome" : "$0 paid. Owner policy remains $5,000.");
  return {paid, amount: paid ? invoice.amount : 0, effectiveLimit: OWNER_LIMIT, memoryVisible: visible, memoryStatus: memory.status, verdict: paid ? "Unexpected: payment allowed" : visible ? "Payment blocked · memory readable" : "Memory withheld · payment blocked", memoryId: memory.id};
}
