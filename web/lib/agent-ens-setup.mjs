import { normalize } from 'viem/ens';
import { isAddress, zeroAddress } from 'viem';
export const AGENT_ENS_PARENT = process.env.NEXT_PUBLIC_ENS_PARENT || 'memoryseal.eth';
export function agentEnsName(label) {
  const normalized = normalize(label.trim());
  if (!normalized || normalized.includes('.')) throw new Error('Choose one ENS label, such as research.');
  return normalize(`${normalized}.${AGENT_ENS_PARENT}`);
}

// Durable checkpoints prevent a retry from resending any known transaction.
// deps provides wallet-backed operations; tests supply an isolated chain model.
export async function provisionAgentEns(job, deps, save, progress = () => {}) {
  if (!isAddress(job.owner) || !isAddress(job.agentAddress) || job.agentAddress.toLowerCase() === zeroAddress) throw new Error('A nonzero agent address is required.');
  await deps.assertWallet(job.owner);
  const observed = await deps.inspect(job);
  if (observed.parentOwner.toLowerCase() !== job.owner.toLowerCase()) throw new Error(`Register ${job.parentName} on Sepolia with this wallet first, or connect its owner wallet.`);
  if (observed.registry.toLowerCase() === zeroAddress || !observed.canRegister) throw new Error(`${job.parentName} needs a canonical subregistry and your wallet needs its registrar role.`);
  const stages = ['registration','resolver','attachment','address'];
  for (const stage of stages) {
    progress(stage);
    if (job[stage]?.uncertain) throw new Error(`The ${stage} submission did not return a transaction hash. Check wallet activity before recovering this setup; it will not be sent again automatically.`);
    if (!job[stage]) {
      await deps.assertWallet(job.owner);
      // Persist intent before requesting a transaction. Explicit wallet rejection
      // is safe to retry; ambiguous transport errors must not create duplicates.
      try { job[stage] = await deps.submit(stage, job, () => {
        job[stage] = {uncertain:true}; save({...job});
      }); save({...job}); }
      catch(error) {
        let reason = error;
        while (reason && reason.code !== 4001 && reason.name !== 'UserRejectedRequestError') reason = reason.cause;
        if (reason) { delete job[stage]; save({...job}); }
        throw error;
      }
    }
    await deps.wait(job[stage].transactionHash);
    await deps.assertWallet(job.owner);
    const result = await deps.verify(stage, job);
    if (result?.matches === false) throw new Error(`ENS ${stage} verification failed.`);
  }
  progress('verify');
  const result = await deps.resolve(job);
  if (!result.matches) throw new Error('The ENS name does not resolve to the agent wallet yet. Resume to check again.');
  return job;
}
