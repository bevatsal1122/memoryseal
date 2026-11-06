const features = [
  [
    "01",
    "Agent identities",
    "Know who’s in your workspace.",
    "Register agents and connect readable ENS names to their signing addresses.",
    "↗",
  ],
  [
    "02",
    "Scoped permissions",
    "Give access. Set boundaries.",
    "Choose what each agent can read, write, and do. Revoke access when plans change.",
    "⊞",
  ],
  [
    "03",
    "Memory review",
    "Keep questionable context apart.",
    "Inspect sources, review quarantined memories, and follow their provenance.",
    "▤",
  ],
  [
    "04",
    "Encrypted vault",
    "Your content. Your keys.",
    "Encrypt on your device, share with selected recipients, and rotate namespace keys.",
    "▣",
  ],
  [
    "05",
    "Team controls",
    "Collaborate with clear roles.",
    "Delegate workspace administration and give auditors visibility without granting content access.",
    "◇",
  ],
  [
    "06",
    "EVM integrations",
    "Make the chain explicit.",
    "Manage configured deployments and inspect onchain policies separately from gateway access.",
    "⌁",
  ],
];
export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        ✳
      </span>
      <span>
        memoryseal<span className="brand-dot">.</span>
      </span>
    </span>
  );
}
export default function Landing({ busy, error, onConnect }) {
  return (
    <div className="launch-page">
      <a className="skip-link" href="#landing-content">
        Skip to content
      </a>
      <nav className="launch-nav" aria-label="Main navigation">
        <a href="#" aria-label="MemorySeal home">
          <Brand />
        </a>
        <div className="launch-nav-links">
          <a href="#features">The toolkit</a>
          <a href="#how-it-works">How it works</a>
        </div>
        <button className="neo-button" disabled={busy} onClick={onConnect}>
          {busy ? "Connecting…" : "Connect wallet"}
          <span aria-hidden="true">↗</span>
        </button>
      </nav>
      {error && (
        <div className="alert launch-error" role="alert">
          <b>Couldn’t open your workspace.</b>
          <p>{error}</p>
          <small>
            Check your wallet connection and that the configured gateway is
            running, then try again.
          </small>
        </div>
      )}
      <div id="landing-content" className="launch-hero">
        <div className="launch-copy">
          <span className="label-stamp">AGENT MEMORY, WITH BOUNDARIES</span>
          <h1>
            Shared memory.
            <br />
            <span className="highlight">Your rules.</span>
          </h1>
          <p>
            A home for your agents’ context, permissions, and proof. Let them
            work together while you stay in control.
          </p>
          <div className="launch-actions">
            <button
              className="neo-button lime"
              disabled={busy}
              onClick={onConnect}
            >
              {busy ? "Check your wallet…" : "Open workspace"}
              <span aria-hidden="true">↗</span>
            </button>
            <a href="#how-it-works">
              See how it works <span aria-hidden="true">↓</span>
            </a>
          </div>
          <p className="connection-note">
            Connect an EVM wallet. Review requests before signing.
            <br />
            Development preview · Your configured gateway
          </p>
        </div>
        <div
          className="memory-map"
          aria-label="Illustration: agent memories pass through your access rules before sharing"
        >
          <div className="map-caption">
            <span>THE MEMORY CONTROL PLANE</span>
            <span aria-hidden="true">✳</span>
          </div>
          <div className="map-agent">
            <span className="avatar lavender">⌘</span>
            <div>
              <b>Research agent</b>
              <small>Writes an observation</small>
            </div>
            <span className="map-tag">WRITE</span>
          </div>
          <div className="map-connector" aria-hidden="true">
            ↓
          </div>
          <div className="map-policy">
            <span aria-hidden="true">✳</span>
            <div>
              <small>YOUR WORKSPACE</small>
              <b>MemorySeal</b>
              <p>Identity → Permission → Review</p>
            </div>
            <span className="policy-check" aria-hidden="true">
              ✓
            </span>
          </div>
          <div className="map-branches">
            <div>
              <span aria-hidden="true">↓</span>
              <div className="map-result">
                <span className="result-icon lime">✓</span>
                <b>Share context</b>
                <small>With authorized agents</small>
              </div>
            </div>
            <div>
              <span aria-hidden="true">↓</span>
              <div className="map-result peach">
                <span className="result-icon">!</span>
                <b>Hold for review</b>
                <small>When trust is unresolved</small>
              </div>
            </div>
          </div>
          <div className="map-note">
            MEMORY IS EVIDENCE. POLICY IS AUTHORITY.
          </div>
          <span className="map-sticker" aria-hidden="true">
            YOU SET
            <br />
            THE RULES ↗
          </span>
        </div>
      </div>
      <div className="principle-strip">
        <span>CONTEXT WITHOUT BLIND TRUST</span>
        <span aria-hidden="true">✳</span>
        <span>PERMISSIONS YOU CONTROL</span>
        <span aria-hidden="true">✳</span>
        <span>KEYS ON YOUR DEVICE</span>
      </div>
      <section className="launch-section" id="features">
        <div className="section-heading">
          <div>
            <span className="eyebrow">ONE WORKSPACE. CLEAR BOUNDARIES.</span>
            <h2>
              Everything has
              <br />
              its place.
            </h2>
          </div>
          <p>
            From an agent’s first memory to a team’s shared vault. Connected
            tools, without mixing up access, trust, and ownership.
          </p>
        </div>
        <div className="toolkit-grid">
          {features.map(([number, title, lead, description, icon]) => (
            <article key={number}>
              <div className="toolkit-top">
                <span>{number} /</span>
                <span className="toolkit-icon" aria-hidden="true">
                  {icon}
                </span>
              </div>
              <h3>{title}</h3>
              <b>{lead}</b>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="launch-workflow" id="how-it-works">
        <div className="section-heading">
          <div>
            <span className="eyebrow">FROM SETUP TO SHARED CONTEXT</span>
            <h2>
              Start small.
              <br />
              Stay in control.
            </h2>
          </div>
          <p>
            Choose ordinary memories for review and analysis, or the encrypted
            vault when content should stay on your device.
          </p>
        </div>
        <ol className="workflow-steps">
          <li>
            <span>01</span>
            <h3>Connect & register</h3>
            <p>
              Open your wallet-owned workspace and register your agent’s signing
              address.
            </p>
          </li>
          <li>
            <span>02</span>
            <h3>Define access</h3>
            <p>
              Grant a specific namespace and operation. Share only what the
              agent needs.
            </p>
          </li>
          <li>
            <span>03</span>
            <h3>Write, review, share</h3>
            <p>
              Use the agent console or SDK. Review memories and inspect the
              decision trail.
            </p>
          </li>
        </ol>
      </section>
      <section className="launch-cta">
        <span aria-hidden="true">✳</span>
        <div>
          <h2>Give context a home.</h2>
          <p>Build your workspace, one permission at a time.</p>
        </div>
        <button className="neo-button" disabled={busy} onClick={onConnect}>
          {busy ? "Connecting…" : "Let’s get started"}
          <span aria-hidden="true">↗</span>
        </button>
      </section>
      <footer className="launch-footer">
        <Brand />
        <p>Memory is evidence. Policy is authority.</p>
        <a href="#landing-content">Back to top ↑</a>
      </footer>
    </div>
  );
}
