"use client";
import { Brand } from "../components/design/Landing";
export default function ErrorPage({ reset }) {
  return (
    <main className="recovery-page">
      <Brand />
      <span className="label-stamp">WORKSPACE INTERRUPTED</span>
      <h1>
        Let’s get you
        <br />
        back on track.
      </h1>
      <p>
        The interface couldn’t finish rendering. Try opening it again. If a
        signed action was already submitted, check its status before retrying
        that action.
      </p>
      <button className="neo-button lime" onClick={reset}>
        Try opening again <span aria-hidden="true">↻</span>
      </button>
      <p className="connection-note">
        An encryption identity may need to be restored from its backup after
        recovery.
      </p>
    </main>
  );
}
