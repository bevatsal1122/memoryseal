import assert from "node:assert/strict";
import { test } from "node:test";
import { loadResolverRecovery, saveResolverRecovery } from "../lib/resolver-recovery.mjs";

test("recovers only public transaction context for the connected owner", () => {
  const values = new Map();
  const storage = { setItem: (key, value) => values.set(key, value), getItem: key => values.get(key) ?? null };
  const owner = `0x${"1".repeat(40)}`, other = `0x${"2".repeat(40)}`;
  const deployment = { owner, chainId: "11155111", resolver: other, salt: "42", transactionHash: `0x${"a".repeat(64)}`, parentName: "example.eth", label: "browser", secret: "do not store" };
  const attachment = { ...deployment, registry: owner, transactionHash: `0x${"b".repeat(64)}`, name: "browser.example.eth" };
  saveResolverRecovery(storage, owner, deployment, attachment);
  const recovered = loadResolverRecovery(storage, owner);
  assert.equal(recovered.deployment.salt, "42");
  assert.equal(recovered.attachment.registry, owner);
  assert.equal(recovered.deployment.secret, undefined);
  assert.equal(loadResolverRecovery(storage, other), null);
  assert.throws(() => saveResolverRecovery(storage, owner, deployment, { ...attachment, resolver: owner }), /Invalid/);
  values.set(`memoryseal.resolver.v1.${owner}`, "bad json");
  assert.throws(() => loadResolverRecovery(storage, owner), /invalid/);
});
