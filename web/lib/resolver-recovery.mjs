// Public transaction context only; verification always re-reads the chain.
const prefix = "memoryseal.resolver.v1.";
const addressPattern = /^0x[0-9a-fA-F]{40}$/;
const hashPattern = /^0x[0-9a-fA-F]{64}$/;

function key(owner) {
  if (!addressPattern.test(owner)) throw new Error("Invalid wallet address.");
  return prefix + owner.toLowerCase();
}

function validDeployment(value, owner) {
  return value && value.chainId === "11155111" && addressPattern.test(value.owner) &&
    value.owner.toLowerCase() === owner.toLowerCase() && addressPattern.test(value.resolver) &&
    hashPattern.test(value.transactionHash) && /^(0|[1-9][0-9]{0,77})$/.test(value.salt) &&
    typeof value.parentName === "string" && value.parentName.length > 0 && value.parentName.length <= 255 &&
    typeof value.label === "string" && value.label.length > 0 && value.label.length <= 255;
}

function validAttachment(value, deployment) {
  return value && value.chainId === deployment.chainId && value.owner?.toLowerCase() === deployment.owner.toLowerCase() &&
    value.resolver?.toLowerCase() === deployment.resolver.toLowerCase() && value.parentName === deployment.parentName &&
    value.label === deployment.label && addressPattern.test(value.registry) && hashPattern.test(value.transactionHash);
}

export function saveResolverRecovery(storage, owner, deployment, attachment = null) {
  if (!validDeployment(deployment, owner) || (attachment && !validAttachment(attachment, deployment))) throw new Error("Invalid resolver recovery context.");
  // Whitelist fields so private wallet or gateway data cannot be stored accidentally.
  const pick = (object, fields) => Object.fromEntries(fields.map(field => [field, object[field]]));
  const safeDeployment = pick(deployment, ["owner", "chainId", "resolver", "salt", "transactionHash", "parentName", "label"]);
  const safeAttachment = attachment && pick(attachment, ["owner", "chainId", "resolver", "transactionHash", "parentName", "label", "registry", "name"]);
  storage.setItem(key(owner), JSON.stringify({ deployment: safeDeployment, attachment: safeAttachment }));
}

export function loadResolverRecovery(storage, owner) {
  const raw = storage.getItem(key(owner));
  if (!raw) return null;
  if (raw.length > 4096) throw new Error("Resolver recovery data is invalid.");
  let value;
  try { value = JSON.parse(raw); } catch { throw new Error("Resolver recovery data is invalid."); }
  if (!validDeployment(value?.deployment, owner) || (value.attachment && !validAttachment(value.attachment, value.deployment))) throw new Error("Resolver recovery data is invalid.");
  return value;
}
