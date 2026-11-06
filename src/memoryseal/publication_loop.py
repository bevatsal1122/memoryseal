"""Single-host outbox scheduler. Ambiguous submissions are looked up, never resent."""

import fcntl
import logging
import threading
import time
from pathlib import Path

from sqlalchemy import select

from memoryseal.models import ProvenanceOutbox, VaultOutbox
from memoryseal.outbox_worker import publish_one, reconcile_one, recover_interrupted

log = logging.getLogger(__name__)


def tick(sessions, *, now=None, publish=publish_one, reconcile=reconcile_one):
    now = int(time.time()) if now is None else now
    for model in (ProvenanceOutbox, VaultOutbox):
        with sessions() as db:
            # The publisher's subprocess timeout is 60s. Never recover a fresh claim.
            stuck = db.scalars(select(model).where(model.state == "publishing")).all()
            for row in stuck:
                if row.publishing_started_at is None:
                    row.publishing_started_at = now  # legacy claim: first give it a grace period
                elif now - row.publishing_started_at > 180:
                    recover_interrupted(db, row.id, model=model)
            db.commit()
            row = db.scalar(
                select(model)
                .where(
                    model.state.in_(["pending", "uncertain"]),
                    model.next_check_at <= now,
                )
                .order_by(model.next_check_at, model.created_at)
                .limit(1)
            )
            if row is None:
                continue
            event_id, state, attempts = row.id, row.state, row.check_attempts
            # Persist backoff before external work, including crash paths.
            row.check_attempts = attempts + 1
            row.next_check_at = now + min(3600, 15 * 2 ** min(attempts, 8))
            db.commit()
            if state == "pending":
                publish(db, event_id=event_id, model=model)
            else:
                reconcile(db, event_id, model=model)


class PublicationLoop:
    def __init__(self, sessions, database_path):
        self.sessions = sessions
        self.path = Path(str(database_path) + ".publisher.lock")
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="arkiv-outbox")
        self.thread.start()

    def run(self):
        # OS lock is released on crash; separate gateway processes cannot run two schedulers.
        with self.path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            while not self.stop_event.is_set():
                try:
                    tick(self.sessions)
                except Exception:  # noqa: BLE001 - keep scheduler alive without logging secrets
                    log.warning("Publication scheduler paused after an error; retrying later")
                self.stop_event.wait(10)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=130)
