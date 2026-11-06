import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import ganache from "../../contracts/node_modules/ganache/dist/node/core.js";
import { BrowserProvider, ContractFactory } from "../../contracts/node_modules/ethers/lib.esm/index.js";
import { approveTokenAllowance, tokenAllowance, onchainCapability, onchainReceipt, onchainVersion, revokeOnchainAgent, revokeOnchainLimit, revokeOnchainMemory, setOnchainLimit, setOnchainMemory } from "../lib/chain.mjs";
import { keccak256, toUtf8Bytes } from "../../contracts/node_modules/ethers/lib.esm/index.js";

test("wallet grants and revokes the real registry on a local chain", async () => {
  const wallet = ganache.provider({ logging: { quiet: true } });
  const provider = new BrowserProvider(wallet);
  try {
    const owner = await provider.getSigner(0), agent = await provider.getSigner(1), token = await provider.getSigner(2);
    const artifact = JSON.parse(await readFile(new URL("../../contracts/artifacts/MemoryPolicyRegistry.json", import.meta.url)));
    const registry = await new ContractFactory(artifact.abi, artifact.bytecode, owner).deploy();
    await registry.waitForDeployment();
    const args = { registry: await registry.getAddress(), chainId: String((await provider.getNetwork()).chainId),
      owner: await owner.getAddress(), agent: await agent.getAddress(), token: await token.getAddress(), amount: "2000000000000000000" };
    assert.equal(await onchainVersion(wallet, args.registry, args.chainId, args.owner), "0");
    const executorArtifact = JSON.parse(await readFile(new URL("../../contracts/artifacts/ProtectedTransfer.json", import.meta.url)));
    const tokenArtifact = JSON.parse(await readFile(new URL("../../contracts/artifacts/TestToken.json", import.meta.url)));
    const executorContract = await new ContractFactory(executorArtifact.abi, executorArtifact.bytecode, owner).deploy(args.registry);
    const testToken = await new ContractFactory(tokenArtifact.abi, tokenArtifact.bytecode, owner).deploy();
    await executorContract.waitForDeployment(); await testToken.waitForDeployment();
    const allowanceArgs = { owner: args.owner, chainId: args.chainId, token: await testToken.getAddress(), executor: await executorContract.getAddress(), registry: args.registry, amount: "2000" };
    const observed = { chain_id: Number(args.chainId), executor: allowanceArgs.executor, registry: args.registry,
      matches: true, registry_code_matches_local: true, executor_code_matches_local: true };
    allowanceArgs.observeDeployment = async () => observed;
    await assert.rejects(approveTokenAllowance(wallet, { ...allowanceArgs, observeDeployment: async () => ({ ...observed, executor_code_matches_local: false }) }), /does not match/);
    await assert.rejects(approveTokenAllowance(wallet, { ...allowanceArgs, observeDeployment: async () => ({ ...observed, chain_id: 1 }) }), /does not match/);
    const approval = await approveTokenAllowance(wallet, allowanceArgs);
    assert.equal(await onchainReceipt(wallet, allowanceArgs.token, args.chainId, approval, args.owner), "included");
    assert.equal((await tokenAllowance(wallet, allowanceArgs)).amount, "2000");
    await approveTokenAllowance(wallet, { ...allowanceArgs, amount: "0", observeDeployment: async () => { throw new Error("observer unavailable"); } });
    assert.equal((await tokenAllowance(wallet, allowanceArgs)).amount, "0");
    await assert.rejects(approveTokenAllowance(wallet, { ...allowanceArgs, executor: args.agent, observeDeployment: async () => ({ ...observed, executor: args.agent }) }), /No contract/);
    await approveTokenAllowance(wallet, { ...allowanceArgs, executor: args.agent, amount: "0" });
    const expiry = String(Math.floor(Date.now() / 1000) + 3600);
    const tx = await setOnchainLimit(wallet, { ...args, expiry });
    assert.equal(await onchainReceipt(wallet, args.registry, args.chainId, tx, args.owner), "included");
    assert.equal(await onchainVersion(wallet, args.registry, args.chainId, args.owner), "1");
    assert.equal((await registry.transferCapabilities(args.owner, args.agent, args.token)).maxAmount, 2000000000000000000n);
    const capability = await onchainCapability(wallet, args);
    assert.equal(capability.maxAmount, "2000000000000000000");
    assert.equal(capability.version, "1");
    assert.equal(capability.expiresAt, expiry);
    assert.equal(capability.revoked, false);
    const revoked = await revokeOnchainLimit(wallet, args);
    assert.equal(await onchainReceipt(wallet, args.registry, args.chainId, revoked, args.owner), "included");
    assert.equal((await registry.transferCapabilities(args.owner, args.agent, args.token)).revoked, true);
    assert.equal((await onchainCapability(wallet, args)).revoked, true);
    const memoryArgs = { ...args, namespace: "research", canRead: true, canWrite: false, expiry };
    const memoryTx = await setOnchainMemory(wallet, memoryArgs);
    assert.equal(await onchainReceipt(wallet, args.registry, args.chainId, memoryTx, args.owner), "included");
    assert.equal(await registry.canAccessMemory(args.owner, args.agent, keccak256(toUtf8Bytes("research")), false), true);
    assert.equal((await registry.memoryCapabilities(args.owner, args.agent, keccak256(toUtf8Bytes("research")))).expiresAt, BigInt(expiry));
    assert.equal(await registry.canAccessMemory(args.owner, args.agent, keccak256(toUtf8Bytes("research")), true), false);
    await revokeOnchainMemory(wallet, memoryArgs);
    assert.equal(await registry.canAccessMemory(args.owner, args.agent, keccak256(toUtf8Bytes("research")), false), false);
    const revokedAgent = await revokeOnchainAgent(wallet, args);
    assert.equal(await onchainReceipt(wallet, args.registry, args.chainId, revokedAgent, args.owner), "included");
    assert.equal((await onchainCapability(wallet, args)).agentRevoked, true);
    await assert.rejects(setOnchainLimit(wallet, { ...args, chainId: "1" }), /network/);
  } finally { await wallet.disconnect(); }
});
