"use client";
import {useEffect, useRef, useState} from "react";
import {generatePrivateKey, privateKeyToAccount} from "viem/accounts";
import {MemorySealClient} from "../../sdk/typescript/dist/index.js";
import {gatewayOrigin} from "../lib/gateway.mjs";
import {OWNER_LIMIT, runPaymentDemo} from "../lib/payment-demo.mjs";

const stages = {
  load: {step: 0, title: "Opening the supplier website", text: "The browser worker fetches the invoice page. No payment has been requested yet.", focus: "header"},
  owner: {step: 0, title: "Remember the owner’s rule", text: "The owner authorized payments up to $5,000. Only the owner can change that rule."},
  scan: {step: 0, title: "Reading the invoice and payment note", text: "The page asks for $50,000, then tells the agent to ignore the original limit. This is a website’s claim, not the owner’s approval.", focus: "aside"},
  memory: {step: 1, title: "The website’s claim enters shared memory", text: "The vulnerable browser worker saves the payment note as instructions. The claim is now available to the finance worker."},
  setup: {step: 1, title: "Preparing separate agent identities", text: "The gateway is registering the browser and finance workers and signing their permissions. These are isolated demo identities."},
  evaluate: {step: 1, title: "MemorySeal is evaluating the website claim", text: "The external text has been submitted to the gateway. We are waiting for its actual decision before passing anything to finance."},
  finance: {step: 2, title: "Finance mistakes a claim for permission", text: "The vulnerable finance worker reads the shared instruction and adopts the website’s $50,000 limit."},
  recall: {step: 2, title: "Checking what finance can actually read", text: "Finance requests shared memories from the gateway. A withheld claim should not appear in this response."},
  policy: {step: 3, title: "Checking the payment against the owner’s limit", text: "A separate permission check compares $50,000 with the signed $5,000 cap. Memory cannot rewrite this policy."},
  payment: {step: 3, title: "Updating the simulated ledger", text: "Recording the result of this run. No real money is sent."},
};
const journey = ["Read website", "Share memory", "Finance decides", "Payment result"];
function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const cancel = () => {clearTimeout(timer); reject(new DOMException("Stopped", "AbortError"));};
    const timer = setTimeout(() => {signal.removeEventListener("abort", cancel); resolve();}, ms);
    signal.addEventListener("abort", cancel, {once: true});
  });
}

const blank = () => ({events: [], result: null, error: "", running: false, memory: {ownerLimit: OWNER_LIMIT, effectiveLimit: OWNER_LIMIT, draft: null, writeStatus: "empty", finance: null}});
const money = amount => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 0}).format(amount);
export default function PaymentDemo({api, audience}) {
  const [runs, setRuns] = useState({baseline: blank(), protected: blank()});
  const [running, setRunning] = useState(null);
  const controller = useRef(null);
  const frame = useRef(null);
  const theater = useRef(null);
  const [stage, setStage] = useState(null);
  const [activeMode, setActiveMode] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [speed, setSpeed] = useState(1800);
  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running, stage]);
  useEffect(() => {
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    doc.querySelectorAll(".agent-reading").forEach(el => el.classList.remove("agent-reading"));
    if (running && stages[stage]?.focus) doc.querySelector(stages[stage].focus)?.classList.add("agent-reading");
  }, [stage, running]);
  useEffect(() => () => controller.current?.abort(), []);
  const update = (mode, change) => setRuns(previous => ({...previous, [mode]: {...previous[mode], ...change}}));
  async function start(mode) {
    if (controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setRunning(mode);
    setActiveMode(mode); setStage("load");
    theater.current?.scrollIntoView({behavior: "smooth", block: "start"});
    update(mode, {...blank(), running: true});
    try {
      const response = await fetch("/demo/supplier.html", {cache: "no-store", signal: abort.signal});
      if (!response.ok) throw new Error("Could not load the supplier page.");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const read = name => page.querySelector(`[data-${name}]`)?.textContent.trim();
      const invoice = {id: read("invoice"), payee: read("payee"), amount: Number(read("amount")?.replaceAll(",", "")), instruction: read("instruction"), url: new URL("/demo/supplier.html", window.location.origin).href};
      if (!invoice.instruction || !invoice.id || !Number.isFinite(invoice.amount) || invoice.amount <= 0) throw new Error("Supplier page has an invalid invoice.");
      await pause(speed, abort.signal);
      let clients;
      if (mode === "protected") {
        const origin = gatewayOrigin(api);
        const makeClient = () => {
          const account = privateKeyToAccount(generatePrivateKey());
          return new MemorySealClient({address: account.address, signMessage: bytes => account.signMessage({message: {raw: bytes}})}, origin, audience,
            (url, options) => fetch(url, {...options, signal: AbortSignal.any([abort.signal, AbortSignal.timeout(120000)])}));
        };
        clients = {owner: makeClient(), browser: makeClient(), finance: makeClient()};
      }
      const result = await runPaymentDemo({mode, invoice, clients, signal: abort.signal, onMemory: patch => {abort.signal.throwIfAborted(); setRuns(previous => ({...previous, [mode]: {...previous[mode], memory: {...previous[mode].memory, ...patch}}}));}, onStage: async next => {abort.signal.throwIfAborted(); setStage(next); await pause(speed, abort.signal);}, emit: event => setRuns(previous => ({...previous, [mode]: {...previous[mode], events: [...previous[mode].events, event]}}))});
      abort.signal.throwIfAborted();
      update(mode, {result, running: false});
      setStage("done");
    } catch (error) {
      if (!abort.signal.aborted) {update(mode, {error: error.message || "Run failed. Check the gateway and retry.", running: false}); setStage("error");}
    } finally {
      if (controller.current === abort) {controller.current = null; setRunning(null);}
    }
  }
  function reset() {
    controller.current?.abort(); controller.current = null;
    setRunning(null); setStage(null); setActiveMode(null); setRuns({baseline: blank(), protected: blank()});
  }
  const current = activeMode ? runs[activeMode] : null;
  const live = stages[stage];
  const memory = current?.memory || blank().memory;
  return <section className="payment-demo">
    <div className="demo-intro"><div><h2>Watch the memory change.</h2></div><button className="demo-reset" disabled={!!running} onClick={reset}>Reset demo</button></div>
    <div className="demo-controls">
      <div className="demo-case-controls"><button disabled={!!running} onClick={() => start("baseline")} className={activeMode === "baseline" ? "selected" : ""}>01 <span>Without MemorySeal</span> ▶</button><button disabled={!!running} onClick={() => start("protected")} className={activeMode === "protected" ? "selected protected" : "protected"}>02 <span>With MemorySeal</span> ▶</button></div>
      <label>Playback <select value={speed} disabled={!!running} onChange={e => setSpeed(Number(e.target.value))}><option value={1800}>Guided</option><option value={350}>Fast</option></select></label>
      {running && <button onClick={reset} className="demo-stop">Stop</button>}
    </div>
    <div className="demo-theater" ref={theater}>
      <div className="demo-live-bar"><span className={`demo-live-dot ${running ? "is-live" : ""}`} /><strong>{running ? `RUNNING · CASE ${activeMode === "baseline" ? "01 — WITHOUT MEMORYSEAL" : "02 — WITH MEMORYSEAL"}` : stage === "done" ? "RUN COMPLETE" : stage === "error" ? "RUN STOPPED" : "CHOOSE A CASE TO BEGIN"}</strong><span>{running ? `${live?.title || "Running"} · ${elapsed}s` : "Reference agents · Simulated payments"}</span></div>
      <ol className="demo-journey">{journey.map((name, i) => <li key={name} className={stage === "done" || (live && i < live.step) ? "complete" : live?.step === i ? "current" : ""}><span>{stage === "done" || (live && i < live.step) ? "✓" : `0${i + 1}`}</span>{name}{i < 3 && <b aria-hidden="true">→</b>}</li>)}</ol>
      <div className="demo-scenario">
        <div className={`demo-website ${running && live?.focus ? "is-scanning" : ""}`}><header><span className="demo-eyebrow">BROWSER AGENT’S VIEW</span><a href="/demo/supplier.html" target="_blank" rel="noopener noreferrer">Open page ↗</a></header><div className="demo-browser-url"><span aria-hidden="true">● ● ●</span> northstar.demo / invoices / NS-2048</div><div className="demo-browser-viewport"><iframe ref={frame} title="Demo supplier invoice with an untrusted payment instruction" src="/demo/supplier.html" sandbox="allow-same-origin" />{running && live?.focus && <div className="demo-scan-label"><span className="demo-live-dot is-live" /> Browser worker reading {stage === "scan" ? "payment note" : "page"}</div>}</div></div>
        <aside className="demo-live-memory">
          <header><h3>Live memory</h3><span className={`demo-live-dot ${running ? "is-live" : ""}`} /></header>
          <div className="demo-memory-policy"><span>Owner’s payment limit</span><strong>{money(memory.ownerLimit)}</strong></div>
          <section className="demo-memory-entry" aria-live="polite">
            <div className="demo-memory-label"><h4>Browser memory</h4><span>EXTERNAL PAGE</span></div>
            <p className={memory.draft ? "demo-memory-text" : "demo-memory-empty"}>{memory.draft || "Waiting for the browser to read the page…"}</p>
          </section>
          <section className={`demo-memory-entry memory-state-${memory.writeStatus}`} aria-live="polite">
            <div className="demo-memory-label"><h4>Shared memory</h4><span>{({empty: "EMPTY", draft: "NOT SAVED", evaluating: "CHECKING…", shared: "SAVED", quarantined: "HELD FOR REVIEW", accepted: "ACCEPTED"})[memory.writeStatus] || memory.writeStatus.toUpperCase()}</span></div>
            {memory.writeStatus === "shared" ? <p className="demo-memory-text">{memory.shared}</p> : ["empty", "draft"].includes(memory.writeStatus) ? <p className="demo-memory-empty">No website instruction saved.</p> : <><p className="demo-memory-text">{memory.draft}</p><small>{memory.writeStatus === "evaluating" ? "Waiting for the gateway decision…" : memory.writeStatus === "quarantined" ? "Stored for review. Finance access is checked next." : "Write completed. Finance access is checked separately."}</small></>}
          </section>
          <section className="demo-memory-entry demo-finance-memory" aria-live="polite">
            <div className="demo-memory-label"><h4>Finance reads</h4><span>{memory.finance === null ? "WAITING" : `${memory.finance.length} MEMORIES`}</span></div>
            {memory.finance === null ? <p className="demo-memory-empty">Has not read shared memory yet.</p> : memory.finance.length ? memory.finance.map((content, index) => <p key={index} className="demo-memory-text">{content}</p>) : <p className="demo-memory-empty">No shared instruction returned.</p>}
            <div className={`demo-memory-policy ${memory.effectiveLimit > OWNER_LIMIT ? "limit-changed" : ""}`}><span>{activeMode === "baseline" ? "Finance’s effective limit" : "Signed payment limit"}</span><strong>{money(memory.effectiveLimit)}</strong>{memory.effectiveLimit > OWNER_LIMIT && <small>Changed from {money(OWNER_LIMIT)}</small>}</div>
          </section>
          {current?.error && <p className="demo-error" role="alert">{current.error}</p>}
          {current?.result && <div className={`demo-memory-result ${current.result.paid ? "paid" : "blocked"}`}><span>Simulated payment</span><strong>{money(current.result.amount)}</strong><span>{current.result.paid ? "Paid" : "Blocked"}</span></div>}
        </aside>
      </div>
    </div>
    <div className="demo-compact-results">{["baseline", "protected"].filter(mode => runs[mode].result).map(mode => <div key={mode}><span>{mode === "baseline" ? "Without MemorySeal" : "With MemorySeal"}</span><strong>{money(runs[mode].result.amount)} paid</strong></div>)}</div>
    <p className="demo-playback-note">Reference agents · Live gateway checks · Simulated payments</p>
  </section>;
}
