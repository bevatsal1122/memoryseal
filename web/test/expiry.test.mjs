import assert from "node:assert/strict";
import { test } from "node:test";
import { capabilityActive, expiryValues } from "../lib/expiry.mjs";

test("capability expiry is converted and expired grants are not active", () => {
  const now = Date.parse("2026-01-01T00:00:00Z");
  assert.deepEqual(expiryValues("", now), { iso: null, seconds: "0" });
  assert.deepEqual(expiryValues("2026-01-01T00:01:00Z", now), { iso: "2026-01-01T00:01:00.000Z", seconds: "1767225660" });
  assert.throws(() => expiryValues("2025-01-01T00:00:00Z", now), /future/);
  assert.equal(capabilityActive({ revoked: false, expires_at: "2026-01-01T00:01:00" }, now), true);
  assert.equal(capabilityActive({ revoked: false, expires_at: "2026-01-01T00:00:00" }, now), false);
  assert.equal(capabilityActive({ revoked: true, expires_at: null }, now), false);
  assert.equal(capabilityActive({ revoked: false, expires_at: "invalid" }, now), false);
});
