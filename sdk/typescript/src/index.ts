export * from "./crypto.js";
import { recoverMessageAddress } from "viem";
export const canonical = (value: unknown): string =>
  JSON.stringify(value, (_key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
        )
      : v,
  );
const objectHash = (value: unknown) =>
  sha256(new TextEncoder().encode(canonical(value)));
import {
  hex,
  sha256,
  sealRecord,
  rewrapRecord,
  unwrapKey,
  type Identity,
  type Scope,
  type EncryptedRecord,
  type WrappedKey,
} from "./crypto.js";
export type Signer = {
  address: string;
  signMessage: (message: Uint8Array) => Promise<string>;
};
export type EIP1193 = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
};
export function walletSigner(wallet: EIP1193, address: string): Signer {
  return {
    address,
    async signMessage(message) {
      const accounts = (await wallet.request({
        method: "eth_accounts",
      })) as string[];
      if (accounts[0]?.toLowerCase() !== address.toLowerCase())
        throw new Error("Wallet account changed");
      return (await wallet.request({
        method: "personal_sign",
        params: ["0x" + hex(message), address],
      })) as string;
    },
  };
}
export function chainAsset(chainId: number, token: string): string {
  if (
    !Number.isSafeInteger(chainId) ||
    chainId <= 0 ||
    !/^0x[0-9a-fA-F]{40}$/.test(token) ||
    /^0x0{40}$/i.test(token)
  )
    throw new Error("Invalid chain asset");
  return `eip155:${chainId}/erc20:${token.toLowerCase()}`;
}
export class GatewayError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export class WriteOutcomeUnknown extends Error {
  constructor(
    public requestId: string,
    public payload: unknown,
  ) {
    super("Write may have committed; retry the exact payload and ID");
  }
}
export type CapabilityInput = {
  agent_id: string;
  operation: "read" | "write" | "transfer";
  resource: string;
  max_amount?: string | null;
  expires_at?: string | null;
};
export type WriteInput = {
  agent_id: string;
  namespace: string;
  content: string;
  source_type: "agent" | "external";
  source_reference?: string | null;
  parent_id?: string | null;
  request_id?: string;
};
export type VaultRow = EncryptedRecord & {
  revision: number;
  status: string;
  cipher_digest: string;
};
export type Agent = {
  id: string;
  signing_address: string;
  ens_name?: string | null;
  revoked: boolean;
  policy_chain_id?: number | null;
};
export type Capability = CapabilityInput & {
  id: string;
  revoked: boolean;
  policy_version: number;
};
export type Organization = {
  id: string;
  name: string;
  owner_address: string;
  version: number;
  role: "owner" | "admin" | "auditor";
};
export type MemoryMetadata = {
  id: string;
  agent_id: string;
  namespace: string;
  status: string;
  commitment: string;
  policy_version: number;
  inference_status: string;
};
export type Chain = {
  chain_id: number;
  name: string;
  registry: string;
  executor: string;
};
export class MemorySealClient {
  private origin: string;
  private epochFloor = new Map<string, number>();
  constructor(
    public signer: Signer,
    baseUrl: string,
    public audience = "memoryseal-local",
    // Browser fetch requires the global receiver, not this client instance.
    private fetcher: typeof fetch = (...args) => globalThis.fetch(...args),
  ) {
    const u = new URL(baseUrl);
    if (
      u.username ||
      u.password ||
      u.search ||
      u.hash ||
      u.pathname !== "/" ||
      !["http:", "https:"].includes(u.protocol)
    )
      throw new Error("Invalid gateway URL");
    if (
      u.protocol !== "https:" &&
      !["localhost", "127.0.0.1", "[::1]"].includes(u.hostname)
    )
      throw new Error("Remote gateways require HTTPS");
    this.origin = u.origin;
  }
  async request<T = Record<string, unknown>>(
    method: string,
    path: string,
    payload?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    if (!path.startsWith("/") || path.startsWith("//") || path.includes("#"))
      throw new Error("Invalid request path");
    signal?.throwIfAborted();
    const body = payload === undefined ? "" : JSON.stringify(payload),
      timestamp = String(Math.floor(Date.now() / 1000)),
      nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
    const message = [
      "MemorySeal request v1",
      this.audience,
      method,
      path,
      await sha256(new TextEncoder().encode(body)),
      timestamp,
      nonce,
    ].join("\n");
    const signature = await this.signer.signMessage(
      new TextEncoder().encode(message),
    );
    signal?.throwIfAborted();
    const timeoutSignal = AbortSignal.timeout(180000);
    const requestSignal = signal
      ? AbortSignal.any([signal, timeoutSignal])
      : timeoutSignal;
    const r = await this.fetcher(this.origin + path, {
      method,
      redirect: "error",
      signal: requestSignal,
      headers: {
        "content-type": "application/json",
        "x-memoryseal-address": this.signer.address,
        "x-memoryseal-signature": signature,
        "x-memoryseal-timestamp": timestamp,
        "x-memoryseal-nonce": nonce,
      },
      ...(payload === undefined ? {} : { body }),
    });
    const reader = r.body?.getReader();
    if (!reader) throw new Error("Missing gateway response");
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 24 * 1024 * 1024)
          throw new Error("Gateway response too large");
        chunks.push(value);
      }
    } finally {
      await reader.cancel();
    }
    const raw = new Uint8Array(size);
    let at = 0;
    for (const chunk of chunks) {
      raw.set(chunk, at);
      at += chunk.length;
    }
    const text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      throw new GatewayError(r.status, "Invalid gateway response");
    }
    if (!r.ok)
      throw new GatewayError(
        r.status,
        typeof data.detail === "string"
          ? data.detail
          : `Gateway error ${r.status}`,
      );
    return data;
  }
  listAgents() {
    return this.request<{ agents: Agent[] }>("GET", "/agents");
  }
  agentAccess() {
    return this.request("GET", "/agent-access");
  }
  registerAgent(
    signing_address: string,
    ens_name?: string,
    policy_chain_id?: number,
  ) {
    return this.request<Agent>("POST", "/agents/register", {
      signing_address,
      ens_name,
      policy_chain_id,
    });
  }
  revokeAgent(id: string) {
    return this.request("POST", `/agents/${encodeURIComponent(id)}/revoke`, {});
  }
  listCapabilities() {
    return this.request<{ capabilities: Capability[]; policy_version: number }>(
      "GET",
      "/capabilities",
    );
  }
  grant(input: CapabilityInput) {
    return this.request("POST", "/capabilities/grant", input);
  }
  revoke(id: string) {
    return this.request(
      "POST",
      `/capabilities/${encodeURIComponent(id)}/revoke`,
      {},
    );
  }
  listMemories(filters: Record<string, string | number> = {}) {
    return this.request(
      "GET",
      "/memories?" +
        new URLSearchParams(
          Object.entries(filters).map(([k, v]) => [k, String(v)]),
        ),
    );
  }
  inspectMemory(id: string) {
    return this.request("GET", `/memories/${encodeURIComponent(id)}`);
  }
  reviewMemory(
    id: string,
    event_id: string,
    commitment: string,
    policy_version: number,
  ) {
    return this.request(
      "POST",
      `/memories/${encodeURIComponent(id)}/review-event`,
      { event_id, commitment, policy_version },
    );
  }
  quarantineMemory(
    id: string,
    event_id: string,
    commitment: string,
    policy_version: number,
  ) {
    return this.request(
      "POST",
      `/memories/${encodeURIComponent(id)}/quarantine-event`,
      { event_id, commitment, policy_version },
    );
  }
  async writeMemory(input: WriteInput) {
    const payload = {
      ...input,
      request_id: input.request_id || crypto.randomUUID(),
    };
    try {
      return await this.request("POST", "/memory/write", payload);
    } catch (e) {
      if (!(e instanceof GatewayError) || e.status >= 500 || e.status === 408)
        throw new WriteOutcomeUnknown(payload.request_id, payload);
      throw e;
    }
  }
  readMemory(agent_id: string, namespace: string, offset = 0, limit = 100) {
    return this.request("POST", "/memory/read", {
      agent_id,
      namespace,
      offset,
      limit,
    });
  }
  simulateTransfer(
    agent_id: string,
    asset: string,
    amount: string,
    policy_version: number,
  ) {
    return this.request("POST", "/actions/simulate-transfer", {
      agent_id,
      asset,
      amount,
      policy_version,
    });
  }
  provenanceEvents(id: string) {
    return this.request(
      "GET",
      `/memories/${encodeURIComponent(id)}/provenance-events`,
    );
  }
  provenanceAction(
    id: string,
    eventId: string,
    action: "publish" | "reconcile" | "observe",
  ) {
    return this.request(
      "POST",
      `/memories/${encodeURIComponent(id)}/provenance-events/${encodeURIComponent(eventId)}/${action}`,
      {},
    );
  }
  chains() {
    return this.request<{ chains: Chain[] }>("GET", "/chains");
  }
  observeDeployment(chainId: number) {
    return this.request(
      "GET",
      `/onchain/observe-deployment?chain_id=${chainId}`,
    );
  }
  observeTransfer(chainId: number, input: Record<string, unknown>) {
    return this.request(
      "POST",
      `/actions/observe-onchain?chain_id=${chainId}`,
      input,
    );
  }
  organizations() {
    return this.request<{ organizations: Organization[] }>(
      "GET",
      "/organizations",
    );
  }
  createOrganization(name: string) {
    return this.request<Organization>("POST", "/organizations", { name });
  }
  organization(id: string) {
    return this.request("GET", `/organizations/${encodeURIComponent(id)}`);
  }
  setMember(
    id: string,
    address: string,
    role: "admin" | "auditor" | "remove",
    expected_version: number,
  ) {
    return this.request(
      "POST",
      `/organizations/${encodeURIComponent(id)}/members`,
      { address, role, expected_version },
    );
  }
  registerOrganizationAgent(
    id: string,
    signing_address: string,
    policy_chain_id?: number,
  ) {
    return this.request(
      "POST",
      `/organizations/${encodeURIComponent(id)}/agents`,
      { signing_address, policy_chain_id },
    );
  }
  grantOrganization(id: string, input: CapabilityInput) {
    return this.request(
      "POST",
      `/organizations/${encodeURIComponent(id)}/capabilities`,
      input,
    );
  }
  revokeOrganization(id: string, kind: "agent" | "capability", itemId: string) {
    return this.request(
      "POST",
      `/organizations/${encodeURIComponent(id)}/revoke/${kind}/${encodeURIComponent(itemId)}`,
      {},
    );
  }
  registerEncryptionIdentity(
    public_key: string,
    expected_fingerprint?: string,
  ) {
    return this.request("POST", "/vault/identity", {
      public_key,
      expected_fingerprint,
    });
  }
  encryptionIdentity(address: string) {
    return this.request<{
      address: string;
      public_key: string;
      fingerprint: string;
    }>("GET", `/vault/identity/${address.toLowerCase()}`);
  }
  vaultNamespaces() {
    return this.request<{ namespaces: Scope[] }>("GET", "/vault/namespaces");
  }
  async createVault(
    scope: Scope,
    fingerprint: string,
    envelopes: Record<string, WrappedKey>,
  ) {
    const epoch_signature = await this.signEpoch(
      scope,
      1,
      fingerprint,
      envelopes,
    );
    return this.request("POST", "/vault/namespaces", {
      id: scope.id,
      owner_address: scope.owner_address,
      namespace: scope.namespace,
      expected_version: 0,
      fingerprint,
      envelopes,
      epoch_signature,
    });
  }
  async rotateVault(
    scope: Scope,
    fingerprint: string,
    envelopes: Record<string, WrappedKey>,
  ) {
    const epoch_signature = await this.signEpoch(
      scope,
      scope.active_version + 1,
      fingerprint,
      envelopes,
    );
    return this.request("POST", `/vault/namespaces/${scope.id}/rotate`, {
      expected_version: scope.active_version,
      fingerprint,
      envelopes,
      epoch_signature,
    });
  }
  async signEpoch(
    scope: Scope,
    version: number,
    fingerprint: string,
    envelopes: Record<string, WrappedKey>,
  ) {
    if (this.signer.address.toLowerCase() !== scope.owner_address.toLowerCase())
      throw new Error("Only the owner signs namespace key epochs");
    const hashes = Object.fromEntries(
      await Promise.all(
        Object.entries(envelopes).map(async ([a, e]) => [
          a,
          await objectHash(e),
        ]),
      ),
    );
    return this.signer.signMessage(
      new TextEncoder().encode(
        canonical([
          "memoryseal:vault-epoch:v1",
          scope.id,
          scope.owner_address.toLowerCase(),
          scope.namespace,
          version,
          fingerprint,
          hashes,
        ]),
      ),
    );
  }
  async vaultKey(
    scope: Scope,
    identity: Identity,
    version = scope.active_version,
  ) {
    const e = await this.request<{
      envelope: WrappedKey;
      fingerprint: string;
      manifest: unknown[];
      signature: `0x${string}`;
    }>("GET", `/vault/namespaces/${scope.id}/epochs/${version}`);
    const floor = this.epochFloor.get(scope.id) || 0;
    if (scope.active_version < floor)
      throw new Error("Namespace key version rolled back");
    this.epochFloor.set(scope.id, scope.active_version);
    const hashes = e.manifest[6] as Record<string, string>;
    const expected = [
      "memoryseal:vault-epoch:v1",
      scope.id,
      scope.owner_address.toLowerCase(),
      scope.namespace,
      version,
      e.fingerprint,
      hashes,
    ];
    if (
      canonical(expected) !== canonical(e.manifest) ||
      hashes[this.signer.address.toLowerCase()] !==
        (await objectHash(e.envelope)) ||
      (
        await recoverMessageAddress({
          message: canonical(e.manifest),
          signature: e.signature,
        })
      ).toLowerCase() !== scope.owner_address.toLowerCase()
    )
      throw new Error("Invalid owner-signed key epoch");
    return unwrapKey(
      identity,
      e.envelope,
      scope.id,
      version,
      this.signer.address,
      e.fingerprint,
    );
  }
  vaultRecords(scope: Scope, after = "", oldOnly = false) {
    return this.request<{
      records: VaultRow[];
      next_after: string | null;
      active_version: number;
    }>(
      "GET",
      `/vault/namespaces/${scope.id}/records?` +
        new URLSearchParams({ after, old_only: String(oldOnly) }),
    );
  }
  async writeVault(
    scope: Scope,
    agent_id: string,
    key: Uint8Array,
    content: string,
  ) {
    const record = await sealRecord(scope, key, content);
    return this.submitVault(scope, { ...record, agent_id });
  }
  async submitVault(
    scope: Scope,
    payload: EncryptedRecord & { agent_id: string },
  ) {
    try {
      return await this.request(
        "POST",
        `/vault/namespaces/${scope.id}/records`,
        payload,
      );
    } catch (e) {
      if (!(e instanceof GatewayError) || e.status >= 500 || e.status === 408)
        throw new WriteOutcomeUnknown(payload.id, payload);
      throw e;
    }
  }
  reviewVault(scope: Scope, row: VaultRow, release: boolean) {
    return this.request(
      "POST",
      `/vault/namespaces/${scope.id}/records/${row.id}/review`,
      {
        expected_revision: row.revision,
        cipher_digest: row.cipher_digest,
        release,
      },
    );
  }
  vaultEvents(scope: Scope, id: string) {
    return this.request<{
      events: {
        id: string;
        event_type: string;
        state: string;
        entity_key: string | null;
      }[];
    }>("GET", `/vault/namespaces/${scope.id}/records/${id}/events`);
  }
  vaultEventAction(
    scope: Scope,
    id: string,
    eventId: string,
    action: "publish" | "reconcile" | "observe",
  ) {
    return this.request(
      "POST",
      `/vault/namespaces/${scope.id}/records/${id}/events/${eventId}/${action}`,
      {},
    );
  }
  rotationStatus(scope: Scope) {
    return this.request("GET", `/vault/namespaces/${scope.id}/rotation`);
  }
  /** Resume at any time. Writes continue using the active epoch. Conflict stops this batch. */
  async migrateVaultBatch(scope: Scope, identity: Identity) {
    const page = await this.vaultRecords(scope, "", true);
    if (page.active_version !== scope.active_version)
      throw new Error("Active key changed; refresh scope");
    const newKey = await this.vaultKey(scope, identity);
    let migrated = 0;
    for (const row of page.records) {
      const oldKey = await this.vaultKey(scope, identity, row.key_version);
      const replacement = await rewrapRecord(scope, oldKey, newKey, row);
      await this.request(
        "POST",
        `/vault/namespaces/${scope.id}/records/${row.id}/rewrap`,
        {
          expected_revision: row.revision,
          key_version: scope.active_version,
          envelope: replacement.envelope,
        },
      );
      migrated++;
    }
    return { migrated, status: await this.rotationStatus(scope) };
  }
}
