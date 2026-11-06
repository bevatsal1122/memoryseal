import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { test } from "node:test";
import { verifyMemoryCommitment } from "../lib/commitment.mjs";

globalThis.crypto ??= webcrypto;
test("verifies the private salted commitment for exact Unicode content", async () => {
  const salt = Buffer.alloc(32, 7), content = "café 🛡️";
  const digest = createHash("sha256").update("memoryseal:commitment:v1\0").update(salt).update(content).digest("hex");
  assert.equal(await verifyMemoryCommitment(content, salt.toString("base64"), digest), true);
  assert.equal(await verifyMemoryCommitment(content + " ", salt.toString("base64"), digest), false);
  assert.equal(await verifyMemoryCommitment(content, "invalid", digest), false);
});
