// Read-only bearer sessions survive refresh in this tab; private keys never enter storage.
const STORAGE_KEY = "memoryseal.browser-sessions.v1";
function storedSessions() {
  try {
    const value = JSON.parse(globalThis.sessionStorage?.getItem(STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}
function persist(key, entry) {
  try {
    const entries = storedSessions();
    if (entry) entries[key] = {token: entry.token, expires_at: entry.expires_at};
    else delete entries[key];
    globalThis.sessionStorage?.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch { /* Storage blocked: keep the in-memory session working. */ }
}
function usable(entry) {
  return entry && typeof entry.token === "string" && entry.token.length > 0 &&
    Number.isFinite(entry.expires_at) && entry.expires_at * 1000 > Date.now() + 5000;
}
const sessionKey = (api, audience, account) => `${api}|${audience}|${account.toLowerCase()}`;
export function hasBrowserSession({api, audience, account}) {
  const key = sessionKey(api, audience, account);
  return !!(usable(sessions.get(key)) || usable(storedSessions()[key]));
}
const sessions = new Map();
let generation = 0;
const hex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");

export function clearBrowserSessions() {
  generation++;
  for (const entry of sessions.values()) {
    if (entry.token) fetch(entry.api + "/auth/logout", {
      method: "POST", headers: { Authorization: `Bearer ${entry.token}` },
      redirect: "error", keepalive: true,
    }).catch(() => {});
  }
  sessions.clear();
  try { globalThis.sessionStorage?.removeItem(STORAGE_KEY); } catch { /* unavailable */ }
}

async function json(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to sign in. Please try again.");
  return body;
}

export async function browserRead({ account, path, api, audience, wallet, signal, method = "GET", payload, allowLogin = true }) {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("#")) throw new Error("Invalid request path");
  const key = sessionKey(api, audience, account);
  const currentGeneration = generation;
  const check = () => {
    signal?.throwIfAborted();
    if (currentGeneration !== generation) throw new Error("Wallet changed. Please reconnect.");
  };
  async function login() {
    const challenge = await json(await fetch(api + "/auth/challenge", {
      method: "POST", redirect: "error", signal,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ address: account }),
    }));
    check();
    // Check the complete human-readable message before asking the wallet to sign.
    const expected = `Sign in to MemorySeal\n\nWebsite: ${globalThis.location.origin}\nWallet: ${account.toLowerCase()}\nGateway audience: ${audience}\n\nAllow this browser to read your workspace for 30 minutes.\nThis does not authorize transfers or permission changes.\n\nIssued at: ${challenge.issued_at}\nSign before: ${challenge.sign_before}\nNonce: ${challenge.challenge}`;
    if (challenge.message !== expected) throw new Error("Gateway login configuration does not match this website.");
    const signature = await wallet.request({ method: "personal_sign", params: [
      "0x" + hex(new TextEncoder().encode(expected)), account,
    ] });
    check();
    const result = await json(await fetch(api + "/auth/session", {
      method: "POST", redirect: "error", signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge: challenge.challenge, signature }),
    }));
    check();
    return { ...result, api };
  }
  for (let attempt = 0; attempt < 2; attempt++) {
    check();
    let entry = sessions.get(key);
    if (!entry) {
      const saved = storedSessions()[key];
      if (usable(saved)) { entry = {...saved, api}; sessions.set(key, entry); }
      else persist(key, null);
    }
    if (!entry || (!entry.pending && !usable(entry))) {
      persist(key, null);
      if (!allowLogin) throw new Error("Session expired. Please reconnect.");
      entry = { pending: login() };
      sessions.set(key, entry);
    }
    if (entry.pending) {
      const pending = entry;
      try {
        entry = await pending.pending;
        check();
        sessions.set(key, entry);
        persist(key, entry);
      } catch (error) {
        if (sessions.get(key) === pending) sessions.delete(key);
        throw error;
      }
    }
    check();
    const response = await fetch(api + path, { method, body: payload === undefined ? undefined : JSON.stringify(payload), signal, redirect: "error", cache: "no-store",
      headers: { Authorization: `Bearer ${entry.token}`, ...(payload === undefined ? {} : { "Content-Type": "application/json" }) },
    });
    check();
    if (response.status === 401) {
      persist(key, null);
      if (sessions.get(key) === entry) sessions.delete(key);
      if (allowLogin && attempt === 0) continue;
    }
    return json(response);
  }
}
