"""Single-event Arkiv publisher with conservative handling of uncertain writes."""

import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from eth_account import Account
from eth_utils import is_address
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from memoryseal.arkiv_runner import run_arkiv
from memoryseal.config import settings
from memoryseal.models import ProvenanceOutbox, VaultOutbox

PUBLISHER = Path(__file__).resolve().parents[2] / "integrations/arkiv/publish.mjs"


def base_env() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "NODE_EXTRA_CA_CERTS",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    if settings.arkiv_access_key:
        env["MEMORYSEAL_ARKIV_ACCESS_KEY"] = settings.arkiv_access_key.get_secret_value()
    return env


def publisher_env() -> dict[str, str] | None:
    if not settings.arkiv_private_key or not settings.arkiv_private_key.get_secret_value():
        return None
    if settings.arkiv_creator_address:
        try:
            actual = Account.from_key(settings.arkiv_private_key.get_secret_value()).address
        except (ValueError, TypeError):
            return None
        if actual.lower() != settings.arkiv_creator_address.lower():
            return None
    env = base_env()
    env["MEMORYSEAL_ARKIV_PRIVATE_KEY"] = settings.arkiv_private_key.get_secret_value()
    return env


def observer_env(creator: str | None = None) -> dict[str, str] | None:
    creator = creator or settings.arkiv_creator_address
    if not creator and settings.arkiv_private_key:
        try:
            creator = Account.from_key(settings.arkiv_private_key.get_secret_value()).address
        except (ValueError, TypeError):
            return None
    if not creator or not is_address(creator) or int(creator, 16) == 0:
        return None
    env = base_env()
    env["MEMORYSEAL_ARKIV_CREATOR_ADDRESS"] = creator
    return env


def publish_one(
    session: Session,
    *,
    memory_id: str | None = None,
    event_id: str | None = None,
    runner=run_arkiv,
    model=ProvenanceOutbox,
) -> str | None:
    """Claim one event; an interrupted publish is uncertain and never auto-retried.

    The operator must reconcile uncertain/publishing events against Arkiv before
    resetting them to pending. This avoids treating a timeout as a failed write.
    """
    env = publisher_env()
    if env is None:
        return "not_configured"
    try:
        creator = Account.from_key(env["MEMORYSEAL_ARKIV_PRIVATE_KEY"]).address.lower()
    except (ValueError, TypeError):
        return "not_configured"
    query = select(model.id).where(model.state == "pending")
    if event_id is not None:
        query = query.where(model.id == event_id)
    if memory_id is not None:
        query = query.where(model.memory_id == memory_id)
    else:
        # Do not let an event bound to an older creator starve unrelated events.
        # Targeted publishes still report creator_mismatch for that specific item.
        query = query.where(
            or_(
                model.creator_address.is_(None),
                model.creator_address == creator,
            )
        )
    entry_id = session.scalar(query.order_by(model.created_at).limit(1))
    if entry_id is None:
        if memory_id is not None:
            return "not_pending"
        other_pending = session.scalar(select(model.id).where(model.state == "pending").limit(1))
        return "creator_mismatch" if other_pending is not None else None
    attempt_id = str(uuid4())
    result = session.execute(
        update(model)
        .where(
            model.id == entry_id,
            model.state == "pending",
            or_(
                model.creator_address.is_(None),
                model.creator_address == creator,
            ),
        )
        .values(state="publishing", creator_address=creator, attempt_id=attempt_id)
    )
    if result.rowcount != 1:
        session.rollback()
        current = session.get(model, entry_id)
        if (
            current is not None
            and current.state == "pending"
            and current.creator_address is not None
            and current.creator_address != creator
        ):
            return "creator_mismatch"
        return "state_changed"
    session.commit()
    session.expire_all()
    entry = session.get(model, entry_id)
    if entry is None or entry.state != "publishing" or entry.attempt_id != attempt_id:
        return "state_changed"
    payload = entry.payload
    try:
        response = runner(
            ["node", str(PUBLISHER)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
            env=env,
        )
        receipt = json.loads(response.stdout)
        entity_key = receipt["entityKey"]
        tx_hash = receipt.get("txHash")
        if not isinstance(entity_key, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", entity_key):
            raise ValueError("invalid Arkiv entity key")
        if tx_hash is not None and (
            not isinstance(tx_hash, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash)
        ):
            raise ValueError("invalid Arkiv transaction hash")
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        changed = session.execute(
            update(model)
            .where(
                model.id == entry_id,
                model.state == "publishing",
                model.attempt_id == attempt_id,
                model.creator_address == creator,
                model.payload == payload,
            )
            .values(state="uncertain")
        )
        session.commit()
        return "uncertain" if changed.rowcount == 1 else "state_changed"
    changed = session.execute(
        update(model)
        .where(
            model.id == entry_id,
            model.state == "publishing",
            model.attempt_id == attempt_id,
            model.creator_address == creator,
            model.payload == payload,
        )
        .values(state="published", entity_key=entity_key, transaction_hash=tx_hash)
    )
    session.commit()
    return "published" if changed.rowcount == 1 else "state_changed"


def recover_interrupted(session: Session, event_id: str, *, model=ProvenanceOutbox) -> str:
    """Move a stopped worker's in-flight claim to uncertain, without sending anything.

    The operator must establish that the worker and its child process have stopped.
    """
    changed = session.execute(
        update(model)
        .where(model.id == event_id, model.state == "publishing")
        .values(state="uncertain")
    )
    session.commit()
    return "uncertain" if changed.rowcount == 1 else "not_publishing"


def reconcile_one(
    session: Session, event_id: str, *, runner=run_arkiv, model=ProvenanceOutbox
) -> str:
    """Read Arkiv only; never republish an ambiguous event automatically."""
    entry = session.get(model, event_id)
    if entry is None or entry.state != "uncertain":
        raise ValueError("event must exist and be uncertain")
    creator = entry.creator_address or settings.arkiv_creator_address
    if not creator:
        return "not_configured"
    env = observer_env(creator)
    if env is None:
        return "not_configured"
    observed_creator = env["MEMORYSEAL_ARKIV_CREATOR_ADDRESS"].lower()
    original_creator = entry.creator_address
    original_payload = entry.payload
    try:
        response = runner(
            ["node", str(PUBLISHER), "--lookup-only"],
            input=original_payload,
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
            env=env,
        )
        result = json.loads(response.stdout)
        if result.get("found") is False:
            return "uncertain"
        key = result["entityKey"]
        if (
            result.get("reconciled") is not True
            or not isinstance(key, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]{64}", key)
        ):
            raise ValueError("invalid reconciliation result")
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return "uncertain"
    changed = session.execute(
        update(model)
        .where(
            model.id == event_id,
            model.state == "uncertain",
            model.creator_address == original_creator,
            model.payload == original_payload,
        )
        .values(state="published", entity_key=key, creator_address=observed_creator)
    )
    if changed.rowcount != 1:
        session.rollback()
        return "uncertain"
    session.commit()
    return "published"


def observe_published(entry: ProvenanceOutbox, *, runner=run_arkiv) -> str:
    """Compare a published event with the current Arkiv query, without mutating it."""
    if entry.state != "published" or not entry.entity_key:
        return "not_published"
    creator = entry.creator_address or settings.arkiv_creator_address
    if not creator:
        return "not_configured"
    env = observer_env(creator)
    if env is None:
        return "not_configured"
    try:
        response = runner(
            ["node", str(PUBLISHER), "--lookup-only"],
            input=entry.payload,
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
            env=env,
        )
        result = json.loads(response.stdout)
        if result.get("conflict") is True:
            return "conflict"
        if result.get("found") is False:
            return "not_found"
        key = result.get("entityKey")
        if result.get("reconciled") is not True or not isinstance(key, str):
            return "unavailable"
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", key):
            return "unavailable"
        return "matched" if key.lower() == entry.entity_key.lower() else "conflict"
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, AttributeError):
        return "unavailable"


def main():
    import argparse

    from memoryseal.db import SessionLocal, engine
    from memoryseal.migrations import migrate

    parser = argparse.ArgumentParser(
        description="Publish one pending event or reconcile an uncertain event"
    )
    parser.add_argument(
        "--vault", action="store_true", help="operate on encrypted-vault provenance"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--reconcile", metavar="EVENT_ID")
    actions.add_argument(
        "--memory-id", metavar="MEMORY_ID", help="publish the pending event for this memory only"
    )
    actions.add_argument(
        "--recover-interrupted",
        metavar="EVENT_ID",
        help="mark a stopped worker's publishing event uncertain; never retries it",
    )
    args = parser.parse_args()
    migrate(engine)
    model = VaultOutbox if args.vault else ProvenanceOutbox
    with SessionLocal() as session:
        if args.reconcile:
            outcome = reconcile_one(session, args.reconcile, model=model)
        elif args.recover_interrupted:
            outcome = recover_interrupted(session, args.recover_interrupted, model=model)
        else:
            outcome = publish_one(session, memory_id=args.memory_id, model=model)
    print(outcome or "empty")


if __name__ == "__main__":
    main()
