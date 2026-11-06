import { readFile, mkdir, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const modules = process.env.MEMORYSEAL_NODE_MODULES || join(root, "node_modules");
const require = createRequire(join(modules, "package.json"));
const solc = require("solc");
const names = ["MemoryPolicyRegistry", "ProtectedTransfer"];
const sources = Object.fromEntries(await Promise.all(names.map(async name => [
  `src/${name}.sol`, { content: await readFile(join(root, "src", `${name}.sol`), "utf8") },
])));
if (process.argv.includes("--with-test-token")) {
  sources["test/Token.sol"] = { content: await readFile(join(root, "test", "Token.sol"), "utf8") };
}
const input = { language: "Solidity", sources, settings: { optimizer: { enabled: true, runs: 200 },
  evmVersion: "shanghai", outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object", "evm.deployedBytecode.immutableReferences"] } } } };
const output = JSON.parse(solc.compile(JSON.stringify(input), { import: name => {
  try { return { contents: readFileSync(join(modules, name), "utf8") }; }
  catch { return { error: `Import not found: ${name}` }; }
}}));
for (const error of output.errors ?? []) {
  if (error.severity === "error") console.error(error.formattedMessage);
}
if ((output.errors ?? []).some(error => error.severity === "error")) process.exit(1);
await mkdir(join(root, "artifacts"), { recursive: true });
if (process.argv.includes("--with-test-token")) {
  const artifact = output.contracts["test/Token.sol"].Token;
  await writeFile(join(root, "artifacts", "TestToken.json"), JSON.stringify({
    contractName: "Token", compiler: solc.version(), abi: artifact.abi,
    bytecode: `0x${artifact.evm.bytecode.object}`,
    deployedBytecode: `0x${artifact.evm.deployedBytecode.object}`,
    immutableReferences: artifact.evm.deployedBytecode.immutableReferences,
  }, null, 2) + "\n");
}
for (const name of names) {
  const artifact = output.contracts[`src/${name}.sol`][name];
  await writeFile(join(root, "artifacts", `${name}.json`), JSON.stringify({
    contractName: name, compiler: solc.version(), abi: artifact.abi,
    bytecode: `0x${artifact.evm.bytecode.object}`,
    deployedBytecode: `0x${artifact.evm.deployedBytecode.object}`,
    immutableReferences: artifact.evm.deployedBytecode.immutableReferences,
  }, null, 2) + "\n");
}
console.log(`Compiled ${names.join(", ")} with ${solc.version()}`);
