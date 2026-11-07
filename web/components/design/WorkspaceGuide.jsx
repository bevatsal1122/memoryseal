export default function WorkspaceGuide({ onNavigate }) {
  return (
    <nav className="overview-quick-actions" aria-label="Quick actions">
      <button onClick={() => onNavigate("agents")}>Register an agent <span aria-hidden="true">↗</span></button>
      <button onClick={() => onNavigate("workbench")}>Write a memory <span aria-hidden="true">↗</span></button>
    </nav>
  );
}
