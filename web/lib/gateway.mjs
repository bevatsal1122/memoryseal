import { browserRead } from "./browser-session.mjs";
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");

export function gatewayOrigin(api, page = globalThis.location) {
  let url;
  try { url = new URL(api); } catch { throw new Error("Invalid gateway URL."); }
  const loopback = host => ["localhost", "127.0.0.1", "[::1]"].includes(host);
  if (!(["http:", "https:"].includes(url.protocol)) || url.username || url.password ||
      url.search || url.hash || url.pathname !== "/") throw new Error("Invalid gateway URL.");
  if (url.protocol === "http:" && (!loopback(url.hostname) || (page && !loopback(page.hostname)))) {
    throw new Error(loopback(url.hostname)
      ? "This hosted website is configured to use a local gateway. Deploy the Python gateway over HTTPS, set NEXT_PUBLIC_GATEWAY_URL to its public URL, and rebuild the frontend. For local testing, open the locally hosted dashboard instead."
      : "The configured gateway uses HTTP. Set NEXT_PUBLIC_GATEWAY_URL to the gateway’s HTTPS URL and rebuild the frontend.");
  }
  if (page && page.protocol !== "https:" && !loopback(page.hostname)) {
    throw new Error("Hosted dashboards require HTTPS.");
  }
  return url.origin;
}

export async function signedRequest({ account, method, path, payload, api, audience, wallet, signal, useSession = false }) {
  signal?.throwIfAborted();
  const origin = gatewayOrigin(api);
  if (useSession && method === "GET") return browserRead({ account, path, api: origin, audience, wallet, signal });
  const body = payload === undefined ? "" : JSON.stringify(payload);
  const digest = hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))));
  const timestamp = Math.floor(Date.now() / 1000);
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  const message = `MemorySeal request v1\n${audience}\n${method}\n${path}\n${digest}\n${timestamp}\n${nonce}`;
  const encoded = "0x" + hex(new TextEncoder().encode(message));
  const signature = await wallet.request({ method: "personal_sign", params: [encoded, account] });
  signal?.throwIfAborted();
  const response = await fetch(origin + path, { method, redirect: "error", headers: {
    "Content-Type": "application/json", "X-Memoryseal-Address": account,
    "X-Memoryseal-Timestamp": String(timestamp), "X-Memoryseal-Nonce": nonce,
    "X-Memoryseal-Signature": signature,
  }, signal, ...(payload === undefined ? {} : { body }) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : `Request failed (${response.status})`);
  }
  return response.json();
}
