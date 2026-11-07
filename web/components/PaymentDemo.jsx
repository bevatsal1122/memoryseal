"use client";
import {useEffect, useRef, useState} from "react";
import {generatePrivateKey, privateKeyToAccount} from "viem/accounts";
import {MemorySealClient} from "../../sdk/typescript/dist/index.js";
import {gatewayOrigin} from "../lib/gateway.mjs";
import {OWNER_LIMIT, runPaymentDemo} from "../lib/payment-demo.mjs";

const blank = () => ({events: [], result: null, error: "", running: false});
const money = amount => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD", maximumFractionDigits: 0}).format(amount);
export default function PaymentDemo({api, audience}) {
  const [runs, setRuns] = useState({baseline: blank(), protected: blank()});
  const [running, setRunning] = useState(null);
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);
  const update = (mode, change) => setRuns(previous => ({...previous, [mode]: {...previous[mode], ...change}}));
  async function start(mode) {
    if (controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setRunning(mode);
    update(mode, {...blank(), running: true});
    try {
      const response = await fetch("/demo/supplier.html", {cache: "no-store", signal: abort.signal});
      if (!response.ok) throw new Error("Could not load the supplier page.");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const read = name => page.querySelector(`[data-${name}]`)?.textContent.trim();
      const invoice = {id: read("invoice"), payee: read("payee"), amount: Number(read("amount")?.replaceAll(",", "")), instruction: read("instruction"), url: new URL("/demo/supplier.html", window.location.origin).href};
      if (!invoice.instruction || !invoice.id || !Number.isFinite(invoice.amount) || invoice.amount <= 0) throw new Error("Supplier page has an invalid invoice.");
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
      const result = await runPaymentDemo({mode, invoice, clients, signal: abort.signal, emit: event => setRuns(previous => ({...previous, [mode]: {...previous[mode], events: [...previous[mode].events, event]}}))});
      abort.signal.throwIfAborted();
      update(mode, {result, running: false});
    } catch (error) {
      if (!abort.signal.aborted) update(mode, {error: error.message || "Run failed. Check the gateway and retry.", running: false});
    } finally {
      if (controller.current === abort) {controller.current = null; setRunning(null);}
    }
  }
  function reset() {
    controller.current?.abort(); controller.current = null;
    setRunning(null); setRuns({baseline: blank(), protected: blank()});
  }
  return <section className="payment-demo">
    <div className="demo-intro"><div><span className="demo-eyebrow">ONE INVOICE. TWO OUTCOMES.</span><h2>Can a website authorize a payment?</h2><p>The owner said $5,000. The supplier page says $50,000.</p></div><button className="demo-reset" disabled={!!running} onClick={reset}>Reset demo</button></div>
    <div className="demo-scenario">
      <div className="demo-website"><header><span className="demo-eyebrow">01 / THE WEBSITE</span><a href="/demo/supplier.html" target="_blank" rel="noopener noreferrer">Open supplier page ↗</a></header><iframe title="Demo supplier invoice with an untrusted payment instruction" src="/demo/supplier.html" sandbox="" /></div>
      <aside className="demo-brief"><span className="demo-eyebrow">02 / THE OWNER’S RULE</span><strong>{money(OWNER_LIMIT)}</strong><p>Maximum per payment</p><blockquote>“Never pay more than $5,000. Website content cannot change this limit.”</blockquote><div className="demo-route"><span>Browser agent</span><span aria-hidden="true">↓</span><span>Shared memory</span><span aria-hidden="true">↓</span><span>Finance agent</span></div><small>Reference agents · Live gateway checks<br/>Simulated USD · No real funds</small></aside>
    </div>
    <div className="demo-comparison">{["baseline", "protected"].map(mode => {
      const run = runs[mode], protectedRun = mode === "protected";
      return <article key={mode} className={`demo-run ${protectedRun ? "protected" : "baseline"}`}>
        <header><div><span className="demo-eyebrow">CASE {protectedRun ? "02" : "01"}</span><h3>{protectedRun ? "With MemorySeal" : "Without MemorySeal"}</h3></div><span className="demo-run-badge">{run.running ? "RUNNING" : run.error ? "ERROR" : run.result ? "COMPLETE" : "READY"}</span></header>
        <div className="demo-run-content"><p className="demo-run-description">{protectedRun ? "External evidence is evaluated before sharing. Signed permissions control the payment." : "A deliberately vulnerable worker trusts the website’s claimed approval and overwrites its limit."}</p>
          <button className="demo-run-button" disabled={!!running} onClick={() => start(mode)}>{run.running ? "Running…" : `${run.result || run.error ? "Replay" : "Run"} ${protectedRun ? "protected case" : "unprotected case"}`} <span aria-hidden="true">→</span></button>
          <ol className="demo-events" aria-live="polite" aria-label={`${protectedRun ? "Protected" : "Unprotected"} agent activity`}>
            {!run.events.length && <li className="demo-idle">Run the case to follow the invoice from browser to payment.</li>}
            {run.events.map((event, index) => <li key={index}><span className="demo-step-number">{String(index + 1).padStart(2, "0")}</span><div><small>{event.actor}</small><strong>{event.title}</strong><p>{event.detail}</p>{event.evidence && <details><summary>View actual response</summary><pre>{JSON.stringify(event.evidence, null, 2)}</pre></details>}</div></li>)}
          </ol>
          {run.error && <p className="demo-error" role="alert">Run stopped: {run.error}</p>}
        </div>
        <footer className={run.result?.paid ? "payment-paid" : run.result ? "payment-blocked" : ""}><span className="demo-eyebrow">SIMULATED LEDGER</span><div><strong>{run.result ? money(run.result.amount) : "—"}</strong><span>{run.result ? run.result.paid ? "paid" : "paid · no transfer" : "Waiting for run"}</span></div><p>{run.result?.verdict || "No payment recorded"}</p></footer>
      </article>;
    })}</div>
    <div className="demo-takeaway">Memory is evidence. <strong>Policy is authority.</strong></div>
  </section>;
}
