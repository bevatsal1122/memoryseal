/** Client-held AES-256-GCM keys, P-256 ECDH wrapping and encrypted identity backups. */
export type Identity = { publicKey: string; privateKey: CryptoKey };
export type Envelope = { nonce: string; ciphertext: string };
export type WrappedKey = Envelope & {
  ephemeral_public_key: string;
  recipient_fingerprint: string;
};
export type Scope = {
  id: string;
  owner_address: string;
  namespace: string;
  active_version: number;
};
export type EncryptedRecord = {
  id: string;
  commitment: string;
  key_version: number;
  envelope: Envelope;
};
const utf8 = new TextEncoder();
export const b64 = (bytes: Uint8Array) =>
  btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));
export const unb64 = (s: string) =>
  Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const bytes = (a: Uint8Array): ArrayBuffer => Uint8Array.from(a).buffer;
export const hex = (a: Uint8Array) =>
  Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
export const sha256 = async (a: Uint8Array) =>
  hex(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes(a))));
export const newKey = () => crypto.getRandomValues(new Uint8Array(32));
export const keyFingerprint = async (key: Uint8Array) => {
  if (key.length !== 32) throw new Error("AES-256 key required");
  return sha256(key);
};
const aes = (key: Uint8Array) =>
  crypto.subtle.importKey("raw", bytes(key), "AES-GCM", false, [
    "encrypt",
    "decrypt",
  ]);
async function encrypt(
  key: Uint8Array,
  plaintext: Uint8Array,
  aad: string,
): Promise<Envelope> {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  return {
    nonce: b64(nonce),
    ciphertext: b64(
      new Uint8Array(
        await crypto.subtle.encrypt(
          {
            name: "AES-GCM",
            iv: bytes(nonce),
            additionalData: utf8.encode(aad),
          },
          await aes(key),
          bytes(plaintext),
        ),
      ),
    ),
  };
}
async function decrypt(key: Uint8Array, envelope: Envelope, aad: string) {
  const nonce = unb64(envelope.nonce);
  if (nonce.length !== 12) throw new Error("Invalid nonce");
  return new Uint8Array(
    await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes(nonce), additionalData: utf8.encode(aad) },
      await aes(key),
      bytes(unb64(envelope.ciphertext)),
    ),
  );
}
export async function generateIdentity(): Promise<Identity> {
  const pair = await crypto.subtle.generateKey(
    { name: "ECDH", namedCurve: "P-256" },
    true,
    ["deriveBits"],
  );
  return {
    publicKey: b64(
      new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey)),
    ),
    privateKey: pair.privateKey,
  };
}
const importPublic = (s: string) =>
  crypto.subtle.importKey(
    "spki",
    bytes(unb64(s)),
    { name: "ECDH", namedCurve: "P-256" },
    false,
    [],
  );
const wrapContext = (
  scopeId: string,
  version: number,
  address: string,
  fingerprint: string,
) =>
  JSON.stringify([
    "memoryseal:wrap:v1",
    scopeId,
    version,
    address.toLowerCase(),
    fingerprint,
  ]);
async function wrappingKey(
  privateKey: CryptoKey,
  publicKey: string,
  context: string,
) {
  const shared = await crypto.subtle.deriveBits(
    { name: "ECDH", public: await importPublic(publicKey) },
    privateKey,
    256,
  );
  const input = await crypto.subtle.importKey("raw", shared, "HKDF", false, [
    "deriveBits",
  ]);
  return new Uint8Array(
    await crypto.subtle.deriveBits(
      {
        name: "HKDF",
        hash: "SHA-256",
        salt: new Uint8Array(32),
        info: utf8.encode(context),
      },
      input,
      256,
    ),
  );
}
/** Pin the recipient fingerprint through a trusted channel before wrapping. */
export async function wrapKey(
  key: Uint8Array,
  publicKey: string,
  pinnedFingerprint: string,
  scopeId: string,
  version: number,
  address: string,
): Promise<WrappedKey> {
  if ((await sha256(unb64(publicKey))) !== pinnedFingerprint)
    throw new Error("Recipient identity fingerprint mismatch");
  const ephemeral = await generateIdentity();
  const context = wrapContext(scopeId, version, address, pinnedFingerprint);
  const envelope = await encrypt(
    await wrappingKey(ephemeral.privateKey, publicKey, context),
    key,
    context,
  );
  return {
    ...envelope,
    ephemeral_public_key: ephemeral.publicKey,
    recipient_fingerprint: pinnedFingerprint,
  };
}
export async function unwrapKey(
  identity: Identity,
  envelope: WrappedKey,
  scopeId: string,
  version: number,
  address: string,
  expectedKeyFingerprint: string,
) {
  if (
    (await sha256(unb64(identity.publicKey))) !== envelope.recipient_fingerprint
  )
    throw new Error("Wrong encryption identity");
  const context = wrapContext(
    scopeId,
    version,
    address,
    envelope.recipient_fingerprint,
  );
  const key = await decrypt(
    await wrappingKey(
      identity.privateKey,
      envelope.ephemeral_public_key,
      context,
    ),
    envelope,
    context,
  );
  if ((await keyFingerprint(key)) !== expectedKeyFingerprint)
    throw new Error("Namespace key fingerprint mismatch");
  return key;
}
const recordContext = (
  scope: Scope,
  id: string,
  version: number,
  commitment: string,
) =>
  JSON.stringify([
    "memoryseal:vault:v1",
    scope.id,
    scope.owner_address.toLowerCase(),
    scope.namespace,
    id,
    version,
    commitment,
  ]);
async function commitment(content: string, salt: Uint8Array) {
  const prefix = utf8.encode("memoryseal:commitment:v1\0"),
    data = utf8.encode(content),
    joined = new Uint8Array(prefix.length + salt.length + data.length);
  joined.set(prefix);
  joined.set(salt, prefix.length);
  joined.set(data, prefix.length + salt.length);
  return sha256(joined);
}
export async function sealRecord(
  scope: Scope,
  key: Uint8Array,
  content: string,
  id: string = crypto.randomUUID(),
  salt: Uint8Array = crypto.getRandomValues(new Uint8Array(32)),
): Promise<EncryptedRecord> {
  if (salt.length !== 32 || utf8.encode(content).length > 24000)
    throw new Error("Invalid salt or content too large");
  const hash = await commitment(content, salt);
  return {
    id,
    key_version: scope.active_version,
    commitment: hash,
    envelope: await encrypt(
      key,
      utf8.encode(JSON.stringify({ content, salt: b64(salt) })),
      recordContext(scope, id, scope.active_version, hash),
    ),
  };
}
export async function openRecord(
  scope: Scope,
  key: Uint8Array,
  record: EncryptedRecord,
): Promise<{ content: string; salt: Uint8Array }> {
  const raw = await decrypt(
    key,
    record.envelope,
    recordContext(scope, record.id, record.key_version, record.commitment),
  );
  const value = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(raw),
  );
  const salt = unb64(value.salt);
  if (
    typeof value.content !== "string" ||
    salt.length !== 32 ||
    (await commitment(value.content, salt)) !== record.commitment
  )
    throw new Error("Content commitment mismatch");
  return { content: value.content, salt };
}
export async function rewrapRecord(
  scope: Scope,
  oldKey: Uint8Array,
  newKey: Uint8Array,
  record: EncryptedRecord,
) {
  const { content, salt } = await openRecord(scope, oldKey, record);
  return sealRecord(
    scope,
    newKey,
    content,
    record.id as `${string}-${string}-${string}-${string}-${string}`,
    salt,
  );
}
async function passwordKey(password: string, salt: Uint8Array) {
  if (password.length < 12)
    throw new Error("Use a backup passphrase of at least 12 characters");
  const input = await crypto.subtle.importKey(
    "raw",
    utf8.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  return new Uint8Array(
    await crypto.subtle.deriveBits(
      {
        name: "PBKDF2",
        hash: "SHA-256",
        salt: bytes(salt),
        iterations: 600000,
      },
      input,
      256,
    ),
  );
}
export async function exportIdentity(identity: Identity, password: string) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const value = {
    publicKey: identity.publicKey,
    privateKey: await crypto.subtle.exportKey("jwk", identity.privateKey),
  };
  return {
    format: "memoryseal.identity.v1",
    salt: b64(salt),
    ...(await encrypt(
      await passwordKey(password, salt),
      utf8.encode(JSON.stringify(value)),
      "memoryseal.identity.v1",
    )),
  };
}
export async function importIdentity(
  backup: { format: string; salt: string; nonce: string; ciphertext: string },
  password: string,
): Promise<Identity> {
  if (
    backup.format !== "memoryseal.identity.v1" ||
    unb64(backup.salt).length !== 16
  )
    throw new Error("Invalid encrypted backup");
  const value = JSON.parse(
    new TextDecoder().decode(
      await decrypt(
        await passwordKey(password, unb64(backup.salt)),
        backup,
        "memoryseal.identity.v1",
      ),
    ),
  );
  const privateKey = await crypto.subtle.importKey(
    "jwk",
    value.privateKey,
    { name: "ECDH", namedCurve: "P-256" },
    true,
    ["deriveBits"],
  );
  const { d: ignored, ...publicJwk } = value.privateKey;
  publicJwk.key_ops = [];
  const publicKey = await crypto.subtle.importKey(
    "jwk",
    publicJwk,
    { name: "ECDH", namedCurve: "P-256" },
    true,
    [],
  );
  if (
    b64(new Uint8Array(await crypto.subtle.exportKey("spki", publicKey))) !==
    value.publicKey
  )
    throw new Error("Backup key pair mismatch");
  return { publicKey: value.publicKey, privateKey };
}

/** Verify a commitment opening locally without sending its salt or content. */
export async function verifyMemoryCommitment(
  content: string,
  saltBase64: string,
  expected: string,
): Promise<boolean> {
  try {
    const salt = unb64(saltBase64);
    return (
      salt.length === 32 &&
      /^[0-9a-f]{64}$/.test(expected) &&
      (await commitment(content, salt)) === expected
    );
  } catch {
    return false;
  }
}
