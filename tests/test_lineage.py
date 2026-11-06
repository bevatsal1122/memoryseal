"""Recorded ancestry must fail closed without scanning unrelated memories."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from memoryseal.config import settings
from memoryseal.db import Base
from memoryseal.memory_service import readable_lineage
from memoryseal.models import Memory


def test_ancestry_handles_large_batches_cycles_and_missing_parents(monkeypatch):
    monkeypatch.setattr(settings, "allow_unbound_inference", True)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    def memory(
        memory_id,
        parent=None,
        status="accepted",
        namespace="n",
        inference="router_verified",
        category="observation",
        analysis_json='{"category":"observation","risk":"low",'
        '"suspicious_instruction":false,"conflicts_with":[],"recommendation":"accept"}',
        source_type="agent",
    ):
        return Memory(
            id=memory_id,
            owner_address="owner",
            agent_id="agent",
            namespace=namespace,
            source_type=source_type,
            category=category,
            trust_class="untrusted",
            status=status,
            inference_status=inference,
            analysis_json=analysis_json,
            ciphertext=b"x",
            encryption_nonce=b"n",
            commitment="c",
            salt=b"s",
            parent_id=parent,
            policy_version=1,
        )

    with Session(engine) as session:
        session.add_all([memory(str(i)) for i in range(501)])
        session.add_all(
            [
                memory("bad", status="quarantined"),
                memory("child", "bad"),
                memory("cycle-a", "cycle-b"),
                memory("cycle-b", "cycle-a"),
                memory("other", namespace="other"),
                memory("cross-namespace", "other"),
                memory("orphan", "absent"),
                memory("legacy", inference="not_configured"),
                memory("legacy-child", "legacy"),
                memory("legacy-instruction", category="instruction"),
                memory("instruction-child", "legacy-instruction"),
                memory(
                    "conflict",
                    analysis_json='{"category":"observation","risk":"low",'
                    '"suspicious_instruction":false,"conflicts_with":["policy"],'
                    '"recommendation":"accept"}',
                ),
                memory("conflict-child", "conflict"),
                memory("invalid-analysis", analysis_json="{"),
                memory("missing-analysis", analysis_json=None),
                memory("external", source_type="external"),
                memory("external-child", "external"),
                memory(
                    "high-risk",
                    analysis_json='{"category":"observation","risk":"high","suspicious_instruction":false,"conflicts_with":[],"recommendation":"accept"}',
                ),
                memory("high-risk-child", "high-risk"),
                memory(
                    "suspicious",
                    analysis_json='{"category":"observation","risk":"low","suspicious_instruction":true,"conflicts_with":[],"recommendation":"accept"}',
                ),
                memory(
                    "recommended-quarantine",
                    analysis_json='{"category":"observation","risk":"low","suspicious_instruction":false,"conflicts_with":[],"recommendation":"quarantine"}',
                ),
                memory(
                    "analysis-instruction",
                    analysis_json='{"category":"instruction","risk":"low","suspicious_instruction":false,"conflicts_with":[],"recommendation":"accept"}',
                ),
                memory("unrelated"),
            ]
        )
        session.commit()
        queries = []
        event.listen(engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
        requested = [str(i) for i in range(501)] + [
            "child",
            "cycle-a",
            "cross-namespace",
            "orphan",
            "legacy",
            "legacy-child",
            "legacy-instruction",
            "instruction-child",
            "conflict-child",
            "invalid-analysis",
            "missing-analysis",
            "external-child",
            "high-risk-child",
            "suspicious",
            "recommended-quarantine",
            "analysis-instruction",
        ]
        result = readable_lineage(session, "owner", "n", requested)
        assert result == {str(i) for i in range(501)}
        assert len(queries) == 2
        monkeypatch.setattr(settings, "allow_unbound_inference", False)
        assert readable_lineage(session, "owner", "n", ["0"]) == set()
    engine.dispose()
