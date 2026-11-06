"""Owner quarantine must revoke future memory reads and append provenance."""

import base64
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.client import MemorySealClient
from memoryseal.config import settings
from memoryseal.db import Base, get_session
from memoryseal.inference import InferenceResult, ThreatAnalysis
from memoryseal.models import ProvenanceOutbox
from memoryseal.outbox_worker import publish_one
from memoryseal.provenance_verify import compare_event, verify_quarantine_request


def test_owner_quarantine_withholds_descendants_and_adds_a_public_event(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'quarantine.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("mock"))
    monkeypatch.setattr(settings, "zero_g_model", "mock")
    monkeypatch.setattr(settings, "require_connection_attestation", False)
    monkeypatch.setattr(settings, "allow_unbound_inference", True)
    monkeypatch.setattr(settings, "zero_g_experimental_bridge", False)
    monkeypatch.setattr(settings, "zero_g_provider_address", None)
    monkeypatch.setattr(settings, "zero_g_tee_signer", None)
    monkeypatch.setattr(settings, "zero_g_signature_base_url", None)
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)
    monkeypatch.setattr(settings, "require_onchain_memory", False)

    class Classifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def analyze(self, **_kwargs):
            return InferenceResult(
                ThreatAnalysis(
                    category="observation",
                    risk="low",
                    suspicious_instruction=False,
                    conflicts_with=[],
                    recommendation="accept",
                ),
                "request",
                "response",
                "0x" + "1" * 40,
                True,
                "testnet",
            )

        def close(self):
            pass

    monkeypatch.setattr("memoryseal.memory_service.ZeroGClassifier", Classifier)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            accounts = [Account.create() for _ in range(3)]

            def sdk(account):
                return MemorySealClient(
                    "http://testserver",
                    account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                )

            with sdk(accounts[0]) as owner, sdk(accounts[1]) as agent, sdk(accounts[2]) as outsider:
                agent_id = owner.register_agent(agent.address)["id"]
                owner.grant(agent_id, "write", "scope")
                owner.grant(agent_id, "read", "scope")
                parent = agent.write_memory(
                    agent_id, "scope", "private parent", source_type="agent"
                )
                child = agent.write_memory(
                    agent_id, "scope", "private child", source_type="agent", parent_id=parent["id"]
                )
                assert len(agent.read_memory(agent_id, "scope")["memories"]) == 2
                with pytest.raises(httpx.HTTPStatusError) as denied:
                    outsider.quarantine_memory(parent["id"])
                assert denied.value.response.status_code == 404
                changed = owner.quarantine_memory(parent["id"])
                assert changed["changed"] is True and changed["status"] == "quarantined"
                assert agent.read_memory(agent_id, "scope")["memories"] == []
                assert (
                    owner.list_memories(memory_id=child["id"])["memories"][0]["lineage_eligible"]
                    is False
                )
                inspection = owner.inspect_memory(parent["id"])
                assert inspection["content"] == "private parent"
                assert owner.quarantine_memory(parent["id"])["changed"] is False
                events = owner.memory_provenance_events(parent["id"])["events"]
                assert {e["event_type"] for e in events} == {"memory_created", "memory_quarantined"}
                assert all(e["state"] == "pending" for e in events)
                assert (
                    owner.observe_memory_provenance_event(parent["id"], changed["event_id"])[
                        "observation"
                    ]
                    == "not_published"
                )
                with pytest.raises(httpx.HTTPStatusError) as denied_event:
                    outsider.observe_memory_provenance_event(parent["id"], changed["event_id"])
                assert denied_event.value.response.status_code == 404
                with pytest.raises(httpx.HTTPStatusError) as wrong_memory:
                    owner.observe_memory_provenance_event(child["id"], changed["event_id"])
                assert wrong_memory.value.response.status_code == 404
                creation = owner.list_memories(memory_id=parent["id"])["memories"][0]["provenance"]
                assert creation["event_id"] != changed["event_id"]
                with sessions() as session:
                    entry = session.scalar(
                        select(ProvenanceOutbox).where(ProvenanceOutbox.id == changed["event_id"])
                    )
                    event = json.loads(entry.payload)
                    assert event["schema"] == "memoryseal.memory-event.v5"
                    assert event["actor_address"] == owner.address.lower()
                    assert verify_quarantine_request(event, owner.address)
                    assert not verify_quarantine_request(
                        event | {"memory_id": child["id"]}, owner.address
                    )
                    entity = "0x" + "a" * 64
                    report = {
                        "schema": event["schema"],
                        "creator": "0x" + "b" * 40,
                        "records": [event | {"entity_key": entity}],
                    }
                    comparison = compare_event(
                        report,
                        publisher=report["creator"],
                        memory_id=parent["id"],
                        entity_key=entity,
                        content="private parent",
                        salt_base64=inspection["commitment_salt"],
                        event_type="memory_quarantined",
                        expected_owner=owner.address,
                    )
                    assert comparison["matches"] is True
                    assert comparison["owner_request_signature_valid"] is True
                    interop = subprocess.run(
                        [
                            "node",
                            "--input-type=module",
                            "-e",
                            "import {verifyQuarantineProof} from './provenance.mjs'; let s=''; for await (const c of process.stdin) s+=c; await verifyQuarantineProof(JSON.parse(s));",
                        ],
                        input=json.dumps(event),
                        text=True,
                        capture_output=True,
                        check=False,
                        cwd=Path(__file__).resolve().parents[1] / "integrations/arkiv",
                        env={
                            key: os.environ[key]
                            for key in ("PATH", "HOME", "TMPDIR")
                            if key in os.environ
                        },
                        timeout=15,
                    )
                    assert interop.returncode == 0, interop.stderr
                    assert event["status"] == "quarantined"
                    assert "private parent" not in entry.payload and "scope" not in entry.payload
                    publisher = Account.create()
                    monkeypatch.setattr(
                        settings, "arkiv_private_key", SecretStr(publisher.key.hex())
                    )
                    monkeypatch.setattr(settings, "arkiv_creator_address", None)
                    sent = []

                    def fake_publish(_command, **kwargs):
                        sent.append(json.loads(kwargs["input"]))
                        return SimpleNamespace(stdout=json.dumps({"entityKey": "0x" + "a" * 64}))

                    assert (
                        publish_one(session, memory_id=parent["id"], runner=fake_publish)
                        == "published"
                    )
                    assert (
                        publish_one(session, memory_id=parent["id"], runner=fake_publish)
                        == "published"
                    )
                    assert {event["event_type"] for event in sent} == {
                        "memory_created",
                        "memory_quarantined",
                    }
                monkeypatch.setattr(
                    "memoryseal.api.observe_published",
                    lambda entry: (
                        "matched" if entry.event_type == "memory_quarantined" else "conflict"
                    ),
                )
                assert owner.observe_memory_provenance_event(parent["id"], changed["event_id"]) == {
                    "event_id": changed["event_id"],
                    "observation": "matched",
                }
                assert (
                    owner.observe_memory_provenance_event(parent["id"], creation["event_id"])[
                        "observation"
                    ]
                    == "conflict"
                )
                root = agent.write_memory(agent_id, "scope", "race parent", source_type="agent")
                assert root["status"] == "accepted"
                started, resume = Event(), Event()
                original_analyze = Classifier.analyze

                def wait_for_quarantine(self, **kwargs):
                    started.set()
                    if not resume.wait(timeout=5):
                        raise TimeoutError("quarantine did not finish")
                    return original_analyze(self, **kwargs)

                monkeypatch.setattr(Classifier, "analyze", wait_for_quarantine)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(
                        agent.write_memory,
                        agent_id,
                        "scope",
                        "race child",
                        source_type="agent",
                        parent_id=root["id"],
                    )
                    try:
                        assert started.wait(timeout=5)
                        assert owner.quarantine_memory(root["id"])["changed"] is True
                    finally:
                        resume.set()
                    raced = pending.result(timeout=10)
                assert raced["status"] == "quarantined"
                metadata = owner.list_memories(memory_id=raced["id"])["memories"][0]
                assert (
                    metadata["creation_reason"]
                    == "parent memory has quarantined or invalid ancestry"
                )
                assert metadata["lineage_eligible"] is False
                monkeypatch.setattr(Classifier, "analyze", original_analyze)
                concurrent_root = agent.write_memory(
                    agent_id, "scope", "concurrent quarantine", source_type="agent"
                )
                with sdk(accounts[0]) as second_owner, ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(client.quarantine_memory, concurrent_root["id"])
                        for client in (owner, second_owner)
                    ]
                    outcomes = [future.result(timeout=10) for future in futures]
                assert sorted(result["changed"] for result in outcomes) == [False, True]
                concurrent_events = owner.memory_provenance_events(concurrent_root["id"])["events"]
                assert (
                    sum(event["event_type"] == "memory_quarantined" for event in concurrent_events)
                    == 1
                )
                bound = agent.write_memory(
                    agent_id, "scope", "bound event memory", source_type="agent"
                )
                version = owner.list_capabilities()["policy_version"]
                event_id = str(uuid4())
                with pytest.raises(httpx.HTTPStatusError) as stale:
                    owner.quarantine_memory_signed(
                        bound["id"],
                        event_id=event_id,
                        commitment=bound["commitment"],
                        policy_version=version + 1,
                    )
                assert stale.value.response.status_code == 409
                with pytest.raises(httpx.HTTPStatusError) as tampered:
                    owner.quarantine_memory_signed(
                        bound["id"], event_id=event_id, commitment="0" * 64, policy_version=version
                    )
                assert tampered.value.response.status_code == 409
                result = owner.quarantine_memory_signed(
                    bound["id"],
                    event_id=event_id,
                    commitment=bound["commitment"],
                    policy_version=version,
                )
                assert result["event_id"] == event_id and result["changed"] is True
                with sessions() as session:
                    bound_event = json.loads(session.get(ProvenanceOutbox, event_id).payload)
                assert bound_event["schema"] == "memoryseal.memory-event.v6"
                assert verify_quarantine_request(bound_event, owner.address)
                page = {
                    "schema": bound_event["schema"],
                    "creator": "0x" + "b" * 40,
                    "records": [
                        bound_event | {"entity_key": entity, "policy_version": str(version)}
                    ],
                }
                bound_comparison = compare_event(
                    page,
                    publisher=page["creator"],
                    memory_id=bound["id"],
                    entity_key=entity,
                    content="bound event memory",
                    salt_base64=owner.inspect_memory(bound["id"])["commitment_salt"],
                    event_type="memory_quarantined",
                    expected_owner=owner.address,
                )
                assert (
                    bound_comparison["matches"]
                    and bound_comparison["owner_request_signature_valid"]
                )
                for field, value in (
                    ("event_id", str(uuid4())),
                    ("commitment", "0" * 64),
                    ("policy_version", version + 1),
                ):
                    assert not verify_quarantine_request(
                        bound_event | {field: value}, owner.address
                    )
                interop_bound = subprocess.run(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        "import {verifyQuarantineProof} from './provenance.mjs'; let s=''; for await (const c of process.stdin) s+=c; await verifyQuarantineProof(JSON.parse(s));",
                    ],
                    input=json.dumps(bound_event),
                    text=True,
                    capture_output=True,
                    check=False,
                    cwd=Path(__file__).resolve().parents[1] / "integrations/arkiv",
                    env={
                        key: os.environ[key]
                        for key in ("PATH", "HOME", "TMPDIR")
                        if key in os.environ
                    },
                    timeout=15,
                )
                assert interop_bound.returncode == 0, interop_bound.stderr
                original = agent.write_memory(
                    agent_id, "scope", "agent signed example", source_type="agent"
                )
                origin_event_id = str(uuid4())
                origin_args = {
                    "event_id": origin_event_id,
                    "commitment": original["commitment"],
                    "policy_version": original["policy_version"],
                }
                with pytest.raises(httpx.HTTPStatusError) as wrong_agent:
                    outsider.attest_memory_origin(original["id"], **origin_args)
                assert wrong_agent.value.response.status_code == 404
                with pytest.raises(httpx.HTTPStatusError) as wrong_author:
                    outsider.author_commitment_salt(original["id"])
                assert wrong_author.value.response.status_code == 404
                with pytest.raises(httpx.HTTPStatusError) as wrong_commitment:
                    agent.attest_memory_origin(
                        original["id"], **(origin_args | {"commitment": "0" * 64})
                    )
                assert wrong_commitment.value.response.status_code == 409
                with pytest.raises(ValueError, match="does not match"):
                    agent.attest_memory_origin_verified(
                        original["id"], content="different content", **origin_args
                    )
                with sessions() as session:
                    assert session.get(ProvenanceOutbox, origin_event_id) is None
                attested = agent.attest_memory_origin_verified(
                    original["id"], content="agent signed example", **origin_args
                )
                assert attested["changed"] and attested["event_id"] == origin_event_id
                assert not agent.attest_memory_origin(original["id"], **origin_args)["changed"]
                with sessions() as session:
                    origin = json.loads(session.get(ProvenanceOutbox, origin_event_id).payload)
                assert origin["schema"] == "memoryseal.memory-event.v7"
                assert verify_quarantine_request(origin, agent.address)
                assert not verify_quarantine_request(origin, owner.address)
                assert not verify_quarantine_request(
                    origin | {"commitment": "0" * 64}, agent.address
                )
                page = {
                    "schema": origin["schema"],
                    "creator": "0x" + "b" * 40,
                    "records": [
                        origin
                        | {"entity_key": entity, "policy_version": str(origin["policy_version"])}
                    ],
                }
                comparison = compare_event(
                    page,
                    publisher=page["creator"],
                    memory_id=original["id"],
                    entity_key=entity,
                    content="agent signed example",
                    salt_base64=owner.inspect_memory(original["id"])["commitment_salt"],
                    event_type="memory_origin_attested",
                    expected_owner=owner.address,
                    expected_agent=agent.address,
                )
                assert comparison["matches"] and comparison["agent_request_signature_valid"]
                interop_origin = subprocess.run(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        "import {verifyEventProof} from './provenance.mjs'; let s=''; for await (const c of process.stdin) s+=c; await verifyEventProof(JSON.parse(s));",
                    ],
                    input=json.dumps(origin),
                    text=True,
                    capture_output=True,
                    check=False,
                    cwd=Path(__file__).resolve().parents[1] / "integrations/arkiv",
                    env={
                        key: os.environ[key]
                        for key in ("PATH", "HOME", "TMPDIR")
                        if key in os.environ
                    },
                    timeout=15,
                )
                assert interop_origin.returncode == 0, interop_origin.stderr
                revoked_memory = agent.write_memory(
                    agent_id, "scope", "revocation example", source_type="agent"
                )
                owner.revoke_agent(agent_id)
                with pytest.raises(httpx.HTTPStatusError) as revoked_opening:
                    agent.author_commitment_salt(revoked_memory["id"])
                assert revoked_opening.value.response.status_code == 403
                with pytest.raises(httpx.HTTPStatusError) as revoked:
                    agent.attest_memory_origin(
                        revoked_memory["id"],
                        event_id=str(uuid4()),
                        commitment=revoked_memory["commitment"],
                        policy_version=revoked_memory["policy_version"],
                    )
                assert revoked.value.response.status_code == 403
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
