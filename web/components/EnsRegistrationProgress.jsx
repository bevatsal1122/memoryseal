const stages = [
  {key: "registration", label: "Register name"},
  {key: "resolver", label: "Create resolver"},
  {key: "attachment", label: "Connect name"},
  {key: "address", label: "Verify address"},
];

export default function EnsRegistrationProgress({ registration }) {
  const complete = registration.state === "registered";
  const stopped = ["failed", "cancelled"].includes(registration.state);
  const completed = complete ? 4 : Math.max(0, stages.findIndex(step => step.key === registration.step));
  const percent = completed * 25;
  const title = complete ? "ENS ready" : registration.state === "failed" ? "Needs attention" : registration.state === "cancelled" ? "Registration cancelled" : registration.message ? "Waiting to retry" : registration.state === "queued" ? "Queued for registration" : "Setting up ENS";
  return <section className={`ens-progress${complete ? " is-complete" : ""}${stopped ? " is-stopped" : ""}`} aria-label="ENS registration">
    <header className="ens-progress-header">
      <div><span className="ens-progress-eyebrow">SEPOLIA · ENS</span><strong className="ens-progress-name">{registration.name}</strong></div>
      <span className="ens-progress-badge">{complete ? "✓ Ready" : `${completed} / 4 steps`}</span>
    </header>
    {!complete && <>
    <div className="ens-progress-caption"><span role="status">{title}</span><b>{percent}%</b></div>
    <div className="ens-progress-track" role="progressbar" aria-label="Verified ENS setup progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={`${completed} of 4 steps verified. ${title}`}>
      <div className="ens-progress-fill" style={{width: `${percent}%`}} />
    </div>
    <ol className="ens-progress-steps">
      {stages.map((step, i) => <li key={step.key} className={i < completed ? "is-done" : !stopped && !complete && i === completed ? "is-current" : ""} aria-current={!complete && !stopped && i === completed ? "step" : undefined}>
        <span className="ens-progress-dot" aria-hidden="true">{i < completed ? "✓" : i + 1}</span><span>{step.label}</span>
      </li>)}
    </ol>
    </>}
    {!complete && registration.message && <p className="ens-progress-message">{registration.message}</p>}
    {!!registration.transactions?.length && <details className="ens-progress-transactions"><summary>View transactions <span aria-hidden="true">↗</span></summary><div>
      {registration.transactions.map((hash, i) => <a key={hash} href={`https://sepolia.etherscan.io/tx/${hash}`} target="_blank" rel="noreferrer">{stages[i]?.label || `Transaction ${i + 1}`} ↗</a>)}
    </div></details>}
  </section>;
}
