import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ganache from "ganache";
import { BrowserProvider, ContractFactory, parseUnits } from "ethers";
import solc from "solc";

function compile() {
  const sources = Object.fromEntries(["MemoryPolicyRegistry.sol", "ProtectedTransfer.sol"].map(name => [
    `src/${name}`, { content: readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8") },
  ]));
  sources["test/Token.sol"] = { content: `// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
contract Token is ERC20 { constructor() ERC20("Test USD", "TUSD") { _mint(msg.sender, 1000000 ether); } }` };
  const input = { language: "Solidity", sources, settings: { evmVersion: "shanghai", outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } } } };
  const output = JSON.parse(solc.compile(JSON.stringify(input), { import: (name) => {
    try { return { contents: readFileSync(new URL(`../node_modules/${name}`, import.meta.url), "utf8") }; }
    catch { return { error: `Cannot find ${name}` }; }
  }}));
  const errors = (output.errors ?? []).filter(e => e.severity === "error");
  assert.deepEqual(errors, []);
  return output.contracts;
}

test("onchain transfer enforces owner policy, current version, expiry and revocation", async () => {
  const compiled = compile();
  const chain = ganache.provider({ logging: { quiet: true } });
  const provider = new BrowserProvider(chain);
  const owner = await provider.getSigner(0), agent = await provider.getSigner(1), recipient = await provider.getSigner(2);
  async function deploy(file, name, args = []) {
    const artifact = compiled[file][name];
    const contract = await new ContractFactory(artifact.abi, artifact.evm.bytecode.object, owner).deploy(...args);
    await contract.waitForDeployment();
    return contract;
  }
  try {
    const registry = await deploy("src/MemoryPolicyRegistry.sol", "MemoryPolicyRegistry");
    const token = await deploy("test/Token.sol", "Token");
    const executor = await deploy("src/ProtectedTransfer.sol", "ProtectedTransfer", [await registry.getAddress()]);
    const ownerAddr = await owner.getAddress(), agentAddr = await agent.getAddress();
    const tokenAddr = await token.getAddress(), recipientAddr = await recipient.getAddress();
    await (await token.approve(await executor.getAddress(), parseUnits("10000", 18))).wait();
    await (await registry.setTransferCapability(agentAddr, tokenAddr, parseUnits("100", 18), 0)).wait();
    const run = executor.connect(agent);
    await assert.rejects(run.execute.staticCall(ownerAddr, tokenAddr, recipientAddr, parseUnits("2000", 18), 1));
    await (await registry.setTransferCapability(agentAddr, tokenAddr, parseUnits("2000", 18), 0)).wait();
    await assert.rejects(run.execute.staticCall(ownerAddr, tokenAddr, recipientAddr, parseUnits("100", 18), 1));
    await (await run.execute(ownerAddr, tokenAddr, recipientAddr, parseUnits("2000", 18), 2)).wait();
    assert.equal(await token.balanceOf(recipientAddr), parseUnits("2000", 18));
    await (await registry.revokeTransferCapability(agentAddr, tokenAddr)).wait();
    await assert.rejects(run.execute.staticCall(ownerAddr, tokenAddr, recipientAddr, 1, 3));
    const block = await provider.getBlock("latest");
    await (await registry.setTransferCapability(agentAddr, tokenAddr, 100, block.timestamp + 10)).wait();
    await chain.request({ method: "evm_increaseTime", params: [11] });
    await chain.request({ method: "evm_mine", params: [] });
    await assert.rejects(run.execute.staticCall(ownerAddr, tokenAddr, recipientAddr, 1, 4));
    await assert.rejects(executor.connect(recipient).execute.staticCall(ownerAddr, tokenAddr, recipientAddr, 1, 4));
  } finally { await chain.disconnect(); }
});
