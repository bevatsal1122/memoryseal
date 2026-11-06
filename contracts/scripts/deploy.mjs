import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ContractFactory, JsonRpcProvider, Wallet, getCreateAddress, isAddress, keccak256 } from "ethers";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const { MEMORYSEAL_RPC_URL: url, MEMORYSEAL_DEPLOYER_KEY: key, MEMORYSEAL_CHAIN_ID: chainId } = process.env;
if (!url || !key || !chainId || !/^\d+$/.test(chainId)) throw new Error("Set RPC URL, deployer key, and expected chain ID");
const provider = new JsonRpcProvider(url);
if ((await provider.getNetwork()).chainId !== BigInt(chainId)) throw new Error("RPC chain ID mismatch");
const tokenOnly = process.argv.includes("--test-token-only");
if (tokenOnly && process.argv.includes("--with-test-token")) throw new Error("Choose one test-token deployment mode");
const withTestToken = tokenOnly || process.argv.includes("--with-test-token");
if (withTestToken && ![11155111n, 1337n].includes(BigInt(chainId))) throw new Error("Test token deployment is limited to Sepolia and the local test chain");
if (withTestToken) {
  const tokenArtifact = JSON.parse(await readFile(join(root, "artifacts", "TestToken.json"), "utf8"));
  if (tokenArtifact.contractName !== "Token" || !/^0x[0-9a-fA-F]+$/.test(tokenArtifact.bytecode)) throw new Error("Invalid test token artifact");
}
const wallet = new Wallet(key, provider);
let nonce = await provider.getTransactionCount(wallet.address, "pending");
async function deploy(name, args = []) {
  const artifact = JSON.parse(await readFile(join(root, "artifacts", `${name}.json`), "utf8"));
  const request = await new ContractFactory(artifact.abi, artifact.bytecode).getDeployTransaction(...args);
  const populated = await wallet.populateTransaction({ ...request, nonce });
  const raw = await wallet.signTransaction(populated);
  const transaction = keccak256(raw);
  const address = getCreateAddress({ from: wallet.address, nonce });
  // Print the locally derived hash before broadcasting, so it survives lost RPC responses.
  console.log(JSON.stringify({ step: "deployment_signed", contract: name, chainId, address, transaction, nonce }));
  let response;
  try {
    response = await provider.broadcastTransaction(raw);
    if (response.hash.toLowerCase() !== transaction.toLowerCase()) throw new Error("hash mismatch");
  } catch {
    console.error(JSON.stringify({ step: "submission_uncertain", contract: name, transaction, address }));
    throw new Error("Deployment submission uncertain; inspect the printed hash before retrying");
  }
  let receipt;
  try { receipt = await response.wait(); }
  catch { throw new Error(`Deployment receipt unavailable; inspect ${transaction} before retrying`); }
  if (!receipt || receipt.status !== 1 || receipt.contractAddress?.toLowerCase() !== address.toLowerCase()) {
    throw new Error(`Deployment not confirmed at expected address; inspect ${transaction}`);
  }
  nonce += 1;
  return { address, transaction };
}
if (tokenOnly) {
  const testToken = await deploy("TestToken");
  console.log(JSON.stringify({ chainId, testToken }, null, 2));
} else {
  let registry;
  if (process.env.MEMORYSEAL_REGISTRY_ADDRESS) {
    const address = process.env.MEMORYSEAL_REGISTRY_ADDRESS;
    if (!isAddress(address)) throw new Error("Invalid registry address");
    const artifact = JSON.parse(await readFile(join(root, "artifacts", "MemoryPolicyRegistry.json"), "utf8"));
    if (typeof artifact.deployedBytecode !== "string" || !/^0x[0-9a-fA-F]+$/.test(artifact.deployedBytecode) ||
        !artifact.immutableReferences || Object.keys(artifact.immutableReferences).length !== 0) {
      throw new Error("Registry runtime artifact missing or invalid; recompile contracts");
    }
    const block = await provider.send("eth_getBlockByNumber", ["latest", false]);
    const code = await provider.send("eth_getCode", [address, block.number]);
    const rechecked = await provider.send("eth_getBlockByNumber", [block.number, false]);
    if (!block.hash || rechecked?.hash?.toLowerCase() !== block.hash.toLowerCase()) throw new Error("Registry observation block reorganized");
    if (typeof code !== "string" || code.toLowerCase() !== artifact.deployedBytecode.toLowerCase()) throw new Error("Registry runtime does not match the local artifact");
    console.log(JSON.stringify({ step: "registry_runtime_matched", chainId, address, block: block.number, blockHash: block.hash }));
    registry = { address, transaction: null };
  } else {
    registry = await deploy("MemoryPolicyRegistry");
    console.log(JSON.stringify({ step: "registry_deployed", chainId, ...registry }));
  }
  const executor = await deploy("ProtectedTransfer", [registry.address]);
  const testToken = withTestToken ? await deploy("TestToken") : null;
  console.log(JSON.stringify({ chainId, registry, executor, ...(testToken ? { testToken } : {}) }, null, 2));

}
