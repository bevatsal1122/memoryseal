// Browser datetime-local values are interpreted in the user's local time zone.
export function expiryValues(value, now = Date.now()) {
  if (!value) return { iso: null, seconds: "0" };
  const time = new Date(value).getTime();
  if (!Number.isFinite(time) || Math.floor(time / 1000) <= Math.floor(now / 1000)) {
    throw new Error("Choose an expiry in the future.");
  }
  return { iso: new Date(time).toISOString(), seconds: String(Math.floor(time / 1000)) };
}

export function capabilityActive(capability, now = Date.now()) {
  if (capability.revoked) return false;
  if (!capability.expires_at) return true;
  // SQLite may serialize UTC timestamps without an explicit offset.
  const value = capability.expires_at;
  const timestamp = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`).getTime();
  return Number.isFinite(timestamp) && timestamp > now;
}
