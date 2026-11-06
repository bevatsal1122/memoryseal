export default function WorkspaceGuide({
  agents,
  capabilities,
  quarantined,
  onNavigate,
}) {
  const steps = [
    {
      view: "agents",
      title: "Register an agent",
      detail: "Set its identity and collection permissions together.",
      done: agents > 0,
      icon: "◇",
    },
    {
      view: "workbench",
      title: "Create your first memory",
      detail: "Open the playground with your agent wallet.",
      icon: "▷",
    },
  ];
  return (
    <div className="workspace-guide">
      <div className="guide-heading">
        <div>
          <h2>{agents ? "Quick actions" : "Get started"}</h2>
        </div>
      </div>
      <div className="guide-steps">
        {steps.map((step, index) => (
          <button
            key={step.view}
            onClick={() => onNavigate(step.view)}
            className="guide-step"
          >
            <span className="guide-number">
              {step.done ? "✓" : `0${index + 1}`}
            </span>
            <span>
              <b>{step.title}</b>
              <small>{step.detail}</small>
            </span>
            <span aria-hidden="true">↗</span>
          </button>
        ))}
      </div>
      <div className="workspace-shortcuts">
        <button onClick={() => onNavigate("memories")}>
          <span className="shortcut-icon peach">▤</span>
          <span>
            <b>
              {quarantined
                ? `${quarantined} memories need review`
                : "Explore your memories"}
            </b>
            <small>Read memories and review exceptions</small>
          </span>
          <span aria-hidden="true">→</span>
        </button>
        <button onClick={() => onNavigate("vault")}>
          <span className="shortcut-icon lavender">▣</span>
          <span>
            <b>Need client-held encryption?</b>
            <small>Create a vault with keys on your device</small>
          </span>
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </div>
  );
}
