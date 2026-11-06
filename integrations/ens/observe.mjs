import { createEnsClient, observeAgentAddress } from "./identity.mjs";

const rpcUrl = process.env.MEMORYSEAL_ENS_RPC_URL;
const network = process.env.MEMORYSEAL_ENS_NETWORK;
const chainId = { mainnet: 1, sepolia: 11155111 }[network];
if (!rpcUrl || !chainId) throw new Error("ENS RPC and supported network are required");
let input = "";
for await (const chunk of process.stdin) input += chunk;
if (input.length > 4096) throw new Error("request too large");
const { name, expectedAddress } = JSON.parse(input);
// Disable CCIP HTTP callbacks in the server to avoid untrusted offchain URLs.
const client = createEnsClient({ network, rpcUrl, ccipRead: false });
const result = await observeAgentAddress(client, { name, expectedAddress, expectedChainId: chainId });
console.log(JSON.stringify(result));
