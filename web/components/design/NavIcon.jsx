/** Consistent 20px navigation icons, independent of system font glyphs. */
export default function NavIcon({ name }) {
  const paths = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    memories: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>,
    agents: <><rect x="4" y="7" width="16" height="13" rx="3" /><path d="M12 3v4M1 12v4m22-4v4M9 16h6" /><path d="M8 11v1m8-1v1" /></>,
    permissions: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
    teams: <><circle cx="9" cy="7" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 4v3" /></>,
    vault: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>,
    activity: <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
    workbench: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3m6 0h4" /></>,
    demo: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="m10 8 6 4-6 4Z" /></>,
    settings: <><path d="M4 7h16M4 17h16" /><rect x="7" y="4" width="4" height="6" rx="1" fill="var(--paper)" /><rect x="14" y="14" width="4" height="6" rx="1" fill="var(--paper)" /></>,
  };
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[name]}</svg>;
}
