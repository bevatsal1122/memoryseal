/** Verify exact UTF-8 content against the private salt and v1 commitment locally. */
export async function verifyMemoryCommitment(content, saltBase64, commitment) {
  if (typeof content !== "string" || typeof saltBase64 !== "string" || !/^[0-9a-f]{64}$/.test(commitment)) return false;
  try {
    const raw = atob(saltBase64);
    if (raw.length !== 32) return false;
    const salt = Uint8Array.from(raw, value => value.charCodeAt(0));
    const prefix = new TextEncoder().encode("memoryseal:commitment:v1\0");
    const payload = new TextEncoder().encode(content);
    const bytes = new Uint8Array(prefix.length + salt.length + payload.length);
    bytes.set(prefix); bytes.set(salt, prefix.length); bytes.set(payload, prefix.length + salt.length);
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const actual = Array.from(digest, value => value.toString(16).padStart(2, "0")).join("");
    return actual === commitment;
  } catch { return false; }
}
