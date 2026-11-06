import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { test } from "node:test";
import ganache from "ganache";
import { Contract, JsonRpcProvider } from "ethers";

const exec = promisify(execFile);
test("deployment reports local hashes and deploys the expected contracts", async () => {
  const server = ganache.server({ logging: { quiet: true }, chain: { chainId: 1337 } });
  await server.listen(0, "127.0.0.1");
  const port = server.address().port;
  const accounts = server.provider.getInitialAccounts();
  const key = Object.values(accounts)[0].secretKey;
  const provider = new JsonRpcProvider(`http://127.0.0.1:${port}`);
  try {
    const { stdout } = await exec(process.execPath, ["scripts/deploy.mjs"], {
      cwd: new URL("..", import.meta.url).pathname,
      env: { ...process.env, MEMORYSEAL_RPC_URL: `http://127.0.0.1:${port}`,
        MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: "1337", MEMORYSEAL_REGISTRY_ADDRESS: "" },
    });
    const records = stdout.split("\n").filter(line => line.startsWith('{"step"')).map(JSON.parse);
    const signed = records.filter(record => record.step === "deployment_signed");
    assert.equal(signed.length, 2);
    assert.equal(signed[1].nonce, signed[0].nonce + 1);
    for (const record of signed) {
      const receipt = await provider.getTransactionReceipt(record.transaction);
      assert.equal(receipt.status, 1);
      assert.equal(receipt.contractAddress.toLowerCase(), record.address.toLowerCase());
      assert.notEqual(await provider.getCode(record.address), "0x");
    }
    assert(!stdout.includes(key));
    const tokenRun = await exec(process.execPath, ["scripts/deploy.mjs", "--with-test-token"], {
      cwd: new URL("..", import.meta.url).pathname,
      env: { ...process.env, MEMORYSEAL_RPC_URL: `http://127.0.0.1:${port}`,
        MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: "1337", MEMORYSEAL_REGISTRY_ADDRESS: signed[0].address },
    });
    const tokenRecords = tokenRun.stdout.split("\n").filter(line => line.includes('"step":"deployment_signed"')).map(JSON.parse);
    const tokenRecord = tokenRecords.find(record => record.contract === "TestToken");
    assert(tokenRecord);
    const token = new Contract(tokenRecord.address, ["function balanceOf(address) view returns (uint256)", "function decimals() view returns (uint8)"], provider);
    assert.equal(await token.decimals(), 18n);
    assert.equal(await token.balanceOf(Object.keys(accounts)[0]), 1_000_000n * 10n ** 18n);
    const onlyToken = await exec(process.execPath, ["scripts/deploy.mjs", "--test-token-only"], {
      cwd: new URL("..", import.meta.url).pathname,
      env: { ...process.env, MEMORYSEAL_RPC_URL: `http://127.0.0.1:${port}`,
        MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: "1337", MEMORYSEAL_REGISTRY_ADDRESS: "" },
    });
    const onlySigned = onlyToken.stdout.split("\n").filter(line => line.includes('"step":"deployment_signed"')).map(JSON.parse);
    assert.equal(onlySigned.length, 1);
    assert.equal(onlySigned[0].contract, "TestToken");
    assert.equal((await provider.getTransactionReceipt(onlySigned[0].transaction)).status, 1);
    const baseEnv = { ...process.env, MEMORYSEAL_RPC_URL: `http://127.0.0.1:${port}`,
      MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: "1337" };
    const resumed = await exec(process.execPath, ["scripts/deploy.mjs"], {
      cwd: new URL("..", import.meta.url).pathname,
      env: { ...baseEnv, MEMORYSEAL_REGISTRY_ADDRESS: signed[0].address },
    });
    assert.match(resumed.stdout, /registry_runtime_matched/);
    assert.equal(resumed.stdout.split("\n").filter(line => line.includes('"step":"deployment_signed"')).length, 1);
    await assert.rejects(exec(process.execPath, ["scripts/deploy.mjs"], {
      cwd: new URL("..", import.meta.url).pathname,
      env: { ...baseEnv, MEMORYSEAL_REGISTRY_ADDRESS: signed[1].address },
    }), /Registry runtime does not match/);
  } finally { provider.destroy(); await server.close(); }
});

test("lost broadcast response retains the hash and stops before another deployment", async () => {
  const { createServer } = await import("node:http");
  const chain = ganache.provider({ logging: { quiet: true }, chain: { chainId: 1337 } });
  const key = Object.values(chain.getInitialAccounts())[0].secretKey;
  let sends = 0;
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const payload = JSON.parse(Buffer.concat(chunks));
    const handle = async (call) => {
      try {
        const result = await chain.request({ method: call.method, params: call.params ?? [] });
        if (call.method === "eth_sendRawTransaction") {
          sends++;
          return { jsonrpc: "2.0", id: call.id, error: { code: -32000, message: "response lost" } };
        }
        return { jsonrpc: "2.0", id: call.id, result };
      } catch (error) {
        return { jsonrpc: "2.0", id: call.id, error: { code: -32000, message: error.message } };
      }
    };
    const output = Array.isArray(payload) ? await Promise.all(payload.map(handle)) : await handle(payload);
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify(output));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  try {
    let failure;
    try {
      await exec(process.execPath, ["scripts/deploy.mjs"], {
        cwd: new URL("..", import.meta.url).pathname,
        env: { ...process.env, MEMORYSEAL_RPC_URL: `http://127.0.0.1:${server.address().port}`,
          MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: "1337", MEMORYSEAL_REGISTRY_ADDRESS: "" },
      });
      assert.fail("expected uncertain submission");
    } catch (error) { failure = error; }
    const signed = failure.stdout.split("\n").filter(Boolean).map(JSON.parse)[0];
    const uncertain = failure.stderr.split("\n").find(line => line.startsWith('{"step"'));
    assert.equal(signed.step, "deployment_signed");
    assert.equal(JSON.parse(uncertain).transaction, signed.transaction);
    assert.equal(sends, 1);
    const receipt = await chain.request({ method: "eth_getTransactionReceipt", params: [signed.transaction] });
    assert.equal(receipt.status, "0x1");
    assert.equal(receipt.contractAddress.toLowerCase(), signed.address.toLowerCase());
    assert(!failure.stdout.includes(key) && !failure.stderr.includes(key));
  } finally {
    await new Promise(resolve => server.close(resolve));
    await chain.disconnect();
  }
});
