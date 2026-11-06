import { Brand } from "../components/design/Landing";
export default function NotFound() {
  return (
    <main className="recovery-page">
      <Brand />
      <span className="label-stamp">404 / PAGE NOT FOUND</span>
      <h1>
        This memory
        <br />
        isn’t here.
      </h1>
      <p>
        The page may have moved, or the address may be incomplete. Your
        workspace is still one click away.
      </p>
      <a className="neo-button lime" href="/">
        Back to MemorySeal <span aria-hidden="true">↗</span>
      </a>
    </main>
  );
}
