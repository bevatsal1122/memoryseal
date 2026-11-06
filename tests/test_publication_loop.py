from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal.db import Base
from memoryseal.models import ProvenanceOutbox
from memoryseal.publication_loop import tick


def test_scheduler_publishes_once_then_only_reconciles_with_backoff(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(ProvenanceOutbox(id="event", memory_id="memory", payload="{}"))
        db.commit()
    sent, looked = [], []

    def publish(db, *, event_id, model):
        sent.append(event_id)
        db.get(model, event_id).state = "uncertain"
        db.commit()

    def reconcile(db, event_id, *, model):
        looked.append(event_id)
        if len(looked) == 2:
            db.get(model, event_id).state = "published"
            db.commit()

    tick(sessions, now=100, publish=publish, reconcile=reconcile)
    tick(sessions, now=101, publish=publish, reconcile=reconcile)
    tick(sessions, now=115, publish=publish, reconcile=reconcile)
    tick(sessions, now=145, publish=publish, reconcile=reconcile)
    tick(sessions, now=10000, publish=publish, reconcile=reconcile)
    assert sent == ["event"]
    assert looked == ["event", "event"]


def test_stale_claim_lookup_never_resends_and_fresh_claim_is_left_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all(
            [
                ProvenanceOutbox(
                    id="old",
                    memory_id="m",
                    payload="{}",
                    state="publishing",
                    publishing_started_at=1,
                ),
                ProvenanceOutbox(
                    id="new",
                    memory_id="m",
                    payload="{}",
                    state="publishing",
                    publishing_started_at=199,
                ),
            ]
        )
        db.commit()
    looked = []

    def never_send(*args, **kwargs):
        raise AssertionError("uncertain event resent")

    tick(
        sessions,
        now=200,
        publish=never_send,
        reconcile=lambda db, event_id, **kwargs: looked.append(event_id),
    )
    assert looked == ["old"]
    with sessions() as db:
        assert db.get(ProvenanceOutbox, "new").state == "publishing"
        assert db.get(ProvenanceOutbox, "old").state == "uncertain"
