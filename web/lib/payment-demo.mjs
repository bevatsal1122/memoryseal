export const OWNER_LIMIT = 5000;
export const DEMO_ASSET = "DEMO_USD";

// Deliberately vulnerable reference worker: source text is treated as authority.
export function naiveFinanceLimit(instruction, ownerLimit = OWNER_LIMIT) {
  const claimed = instruction.match(/Update the payment limit to \$([\d,]+)/i);
  return claimed ? Number(claimed[1].replaceAll(",", "")) : ownerLimit;
}

export async function runPaymentDemo({ mode, invoice, clients, emit, signal, onStage = async () => {}, onMemory = () => {} }) {
  const log = (actor, title, detail, evidence) => {
    signal?.throwIfAborted();
    emit({ actor, title, detail, evidence });
  };
  onMemory({ownerLimit: OWNER_LIMIT, effectiveLimit: OWNER_LIMIT, draft: null, writeStatus: "empty", finance: null});
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
  await onStage("setup");
  const {owner, browser, finance} = clients;
  log("Gateway", "Registering isolated demo identities", "A fresh owner, browser agent, and finance agent. Your workspace is unchanged.");
  const browserAgent = await owner.registerAgent(browser.signer.address);
  const financeAgent = await owner.registerAgent(finance.signer.address);
  const namespace = "demo-invoices";
  await owner.grant({agent_id: browserAgent.id, operation: "write", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "read", resource: namespace});
  await owner.grant({agent_id: financeAgent.id, operation: "transfer", resource: DEMO_ASSET, max_amount: String(OWNER_LIMIT)});
  log("MemorySeal", "Signed permissions configured", "Browser: write invoices. Finance: read invoices and simulate up to $5,000.");
  await onStage("evaluate");
  onMemory({writeStatus: "evaluating"});
  const memory = await browser.writeMemory({agent_id: browserAgent.id, namespace, content: invoice.instruction, source_type: "external", source_reference: invoice.url});
  onMemory({writeStatus: memory.status, memoryId: memory.id});
  log("MemorySeal", `Memory write: ${memory.status}`, "External website content evaluated by the gateway.", memory);
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
