"""Durable, single-signer Sepolia registration queue. No private key in responses."""
import json
import os
import re
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select, text

from memoryseal.config import settings
from memoryseal.models import Agent, EnsRegistrationJob
from memoryseal.publication_loop import PublicationLoop

SCRIPT = Path(__file__).resolve().parents[2] / 'integrations/ens/sponsor.mjs'
STAGES = ('registration', 'resolver', 'attachment', 'address')


def allocate_name(db, agent, parent):
    prefix = re.sub(r'[^a-z0-9]+', '-', (agent.label or 'agent').lower()).strip('-')[:24] or 'agent'
    for _ in range(100):
        label = f'{prefix}-{10000 + secrets.randbelow(90000)}'
        name = f'{label}.{parent}'
        if not db.scalar(select(EnsRegistrationJob.agent_id).where(EnsRegistrationJob.name == name)) and not db.scalar(select(Agent.id).where(Agent.ens_name == name)):
            return label, name
    raise HTTPException(409, 'Could not allocate an available ENS name; please retry')


def enqueue(db, agent):
    if not settings.ens_auto_register:
        return None
    if not settings.ens_registrar_private_key or settings.ens_network != 'sepolia' or not settings.ens_rpc_url:
        raise HTTPException(503, 'Automatic ENS registration is not configured')
    if int(agent.signing_address, 16) == 0:
        raise HTTPException(422, 'A nonzero agent address is required for ENS')
    since = datetime.now(UTC) - timedelta(days=1)
    query = select(func.count()).select_from(EnsRegistrationJob).where(EnsRegistrationJob.created_at >= since)
    total = db.scalar(query)
    personal = db.scalar(query.where(EnsRegistrationJob.owner_address == agent.owner_address))
    if total >= settings.ens_registration_global_day or personal >= settings.ens_registration_per_owner_day:
        raise HTTPException(429, 'Sponsored ENS daily registration limit reached')
    parent = settings.ens_parent
    if not re.fullmatch(r'[a-z0-9-]+\.eth', parent):
        raise HTTPException(503, 'Invalid sponsored ENS parent configuration')
    label, name = allocate_name(db, agent, parent)
    context = dict(parentName=parent, label=label, name=name, agentAddress=agent.signing_address,
                   expiry=str(int(time.time()) + 365 * 86400), salt=str(int(agent.id.replace('-', ''), 16)))
    row = EnsRegistrationJob(agent_id=agent.id, owner_address=agent.owner_address, name=name,
                             context_json=json.dumps(context))
    db.add(row)
    # ens_name is assigned only after successful ownership/record verification.
    agent.ens_name = None
    return row


def public_status(row):
    if not row:
        return None
    context = json.loads(row.context_json)
    return {'name': row.name, 'state': row.state, 'step': STAGES[min(row.stage, 3)],
            'message': row.message, 'chain_id': 11155111,
            'transactions': [context[s]['transactionHash'] for s in STAGES if s in context]}


def adapter(action, **payload):
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ}
    env.update(MEMORYSEAL_ENS_RPC_URL=settings.ens_rpc_url,
               MEMORYSEAL_ENS_PARENT=settings.ens_parent,
               MEMORYSEAL_ENS_REGISTRAR_PRIVATE_KEY=settings.ens_registrar_private_key.get_secret_value(),
               MEMORYSEAL_ENS_REGISTRATION_MAX_FEE_GWEI=str(settings.ens_registration_max_fee_gwei))
    result = subprocess.run(['node', str(SCRIPT)], input=json.dumps({'action': action, **payload}),
                            text=True, capture_output=True, timeout=70, env=env, check=True)
    return json.loads(result.stdout)


def tick(sessions, *, call=adapter, now=None):
    now = int(time.time()) if now is None else now
    with sessions() as db:
        # Never prepare a second job while signed bytes from the first may own
        # the signer's next nonce. One signer, one process, one durable queue.
        row = db.scalar(select(EnsRegistrationJob).where(
            EnsRegistrationJob.state.notin_(['registered', 'failed', 'cancelled'])
        ).order_by(EnsRegistrationJob.created_at, EnsRegistrationJob.agent_id).limit(1))
        if not row or row.next_check_at > now:
            return
        agent = db.get(Agent, row.agent_id)
        if agent.revoked and not row.signed_transaction:
            row.state = 'cancelled'; db.commit(); return
        row.next_check_at = now + min(300, 10 * 2 ** min(row.attempts, 5))
        row.attempts += 1
        db.commit()
        context = json.loads(row.context_json)
        context['stage'] = row.stage
        try:
            if not row.signed_transaction:
                prepared = call('prepare', job=context)
                if prepared.get('state') == 'unavailable' and row.stage == 0:
                    # No transaction has been signed. Reserve another short name
                    # under the same writer lock used by agent creation.
                    db.execute(text('BEGIN IMMEDIATE'))
                    label, name = allocate_name(db, agent, context['parentName'])
                    context.update(label=label, name=name)
                    row.name = name
                    row.context_json = json.dumps(context)
                    row.next_check_at = now
                    db.commit()
                    return
                if not re.fullmatch(r'0x[0-9a-fA-F]+', prepared['raw']) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', prepared['hash']):
                    raise ValueError('Invalid adapter transaction')
                context[STAGES[row.stage]] = prepared['result']
                row.context_json = json.dumps(context)
                row.signed_transaction, row.transaction_hash = prepared['raw'], prepared['hash']
                row.state = 'registering'
                db.commit()  # MUST precede any broadcast, including restart paths.
            receipt = call('broadcast', raw=row.signed_transaction, hash=row.transaction_hash)
            if receipt['state'] == 'reverted':
                row.state = 'failed'; row.message = 'ENS transaction reverted; operator review required.'
            elif receipt['state'] == 'confirmed':
                verified = call('verify', job=context)
                if verified.get('verified') is not True:
                    raise ValueError('ENS verification failed')
                row.stage += 1
                row.signed_transaction = None
                row.transaction_hash = None
                row.attempts = 0
                row.next_check_at = now
                row.message = None
                if row.stage == 4:
                    row.state = 'registered'
                    agent.ens_name = row.name
            db.commit()
        except Exception:
            # Never log subprocess output/environment: they may contain RPC credentials.
            row.message = 'ENS registration is delayed; the service will retry automatically.'
            db.commit()


class EnsRegistrationLoop(PublicationLoop):
    def __init__(self, sessions, database_path):
        super().__init__(sessions, database_path)
        self.path = Path(str(database_path) + '.ens-registrar.lock')

    def run(self):
        import fcntl
        with self.path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            while not self.stop_event.is_set():
                try:
                    tick(self.sessions)
                except Exception:
                    pass
                self.stop_event.wait(5)
