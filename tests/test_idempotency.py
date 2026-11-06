import base64
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import httpx
import pytest
from eth_account import Account
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from memoryseal import auth, memory_service
from memoryseal.api import app
from memoryseal.client import MemorySealClient, MemoryWriteOutcomeUnknown
from memoryseal.config import settings
from memoryseal.db import Base, get_session
from memoryseal.inference import InferenceResult, ThreatAnalysis
from memoryseal.models import AuditEvent, Memory, ProvenanceOutbox


def test_concurrent_retries_create_one_memory_and_enforce_conflicts(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'idempotency.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "zero_g_model", "test")
    monkeypatch.setattr(settings, "require_connection_attestation", False)
    monkeypatch.setattr(settings, "allow_unbound_inference", True)
    monkeypatch.setattr(settings, "zero_g_experimental_bridge", False)
    for field in (
        "zero_g_provider_address",
        "zero_g_tee_signer",
        "zero_g_signature_base_url",
        "zero_g_registry_rpc_url",
    ):
        monkeypatch.setattr(settings, field, None)
    barrier = Barrier(2)
    classifier_calls = []

    class Classifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def analyze(self, **_kwargs):
            classifier_calls.append(True)
            barrier.wait(timeout=5)
            return InferenceResult(
                ThreatAnalysis(
                    category="observation",
                    risk="low",
                    suspicious_instruction=False,
                    conflicts_with=[],
                    recommendation="accept",
                ),
                "request",
                "key",
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
            owner_account, agent_account = Account.create(), Account.create()

            def client(account):
                return MemorySealClient(
                    "http://testserver",
                    account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                )

            owner = client(owner_account)
            agent_id = owner.register_agent(agent_account.address)["id"]
            owner.grant(agent_id, "write", "scope")
            request_id = str(uuid4())

            def send():
                with sessions() as session:
                    item = memory_service.write(
                        session,
                        agent_id=agent_id,
                        signer=agent_account.address.lower(),
                        namespace="scope",
                        content="private text",
                        source_type="agent",
                        source_reference=None,
                        parent_id=None,
                        request_id=request_id,
                    )
                    return item.id

            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = [
                    future.result() for future in [pool.submit(send), pool.submit(send)]
                ]
            assert first == second
            assert len(classifier_calls) == 2
            conflict_id = str(uuid4())

            def conflicting_send(content):
                with sessions() as session:
                    try:
                        item = memory_service.write(
                            session,
                            agent_id=agent_id,
                            signer=agent_account.address.lower(),
                            namespace="scope",
                            content=content,
                            source_type="agent",
                            source_reference=None,
                            parent_id=None,
                            request_id=conflict_id,
                        )
                        return item.id
                    except HTTPException as exc:
                        return exc.status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(conflicting_send, ["first", "second"]))
            assert sum(isinstance(result, str) for result in outcomes) == 1
            assert 409 in outcomes
            assert len(classifier_calls) == 4
            with client(agent_account) as agent:
                with pytest.raises(httpx.HTTPStatusError) as conflict:
                    agent.write_memory(
                        agent_id,
                        "scope",
                        "different text",
                        source_type="agent",
                        request_id=request_id,
                    )
                assert conflict.value.response.status_code == 409
            monkeypatch.setattr(settings, "zero_g_api_key", None)
            monkeypatch.setattr(settings, "zero_g_model", None)

            with client(agent_account) as retry_client:
                original_request = retry_client._request
                lost = False

                def lose_response(*args, **kwargs):
                    nonlocal lost
                    response = original_request(*args, **kwargs)
                    if not lost:
                        lost = True
                        raise httpx.ReadError("response lost after commit")
                    return response

                monkeypatch.setattr(retry_client, "_request", lose_response)
                with pytest.raises(MemoryWriteOutcomeUnknown) as unknown:
                    retry_client.write_memory(
                        agent_id, "scope", "lost response", source_type="agent"
                    )
                retry = retry_client.write_memory(
                    agent_id,
                    "scope",
                    "lost response",
                    source_type="agent",
                    request_id=unknown.value.request_id,
                )
                assert retry["request_id"] == unknown.value.request_id
            with sessions() as session:
                assert session.scalar(select(func.count()).select_from(Memory)) == 3
                assert session.scalar(select(func.count()).select_from(ProvenanceOutbox)) == 3
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.event_type == "memory_created")
                    )
                    == 3
                )
                memory = session.get(Memory, first)
                assert "private text" not in memory.request_digest
            owner.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_unknown_error_exposes_request_id_and_does_not_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    with MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(MemoryWriteOutcomeUnknown) as error:
            client.write_memory("agent", "scope", "private", source_type="agent")
        import json

        assert json.loads(calls[0].content)["request_id"] == error.value.request_id
        assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(408, json={"detail": "timeout"}),
        httpx.Response(200, json={"request_id": "wrong"}),
        httpx.Response(200, json=[]),
    ],
)
def test_ambiguous_write_response_preserves_retry_id(response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(MemoryWriteOutcomeUnknown) as error:
            client.write_memory("agent", "scope", "private", source_type="agent")
        import json

        assert json.loads(calls[0].content)["request_id"] == error.value.request_id
        assert len(calls) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"id": str(uuid4()), "status": "accepted"},
        {"id": "invalid", "status": "accepted", "lineage_eligible": True},
        {"id": str(uuid4()), "status": "accepted", "lineage_eligible": "true"},
        {"id": str(uuid4()), "status": "unknown", "lineage_eligible": False},
    ],
)
def test_incomplete_write_result_is_an_uncertain_outcome(fields):
    import json

    def handler(request):
        request_id = json.loads(request.content)["request_id"]
        return httpx.Response(200, json={"request_id": request_id, **fields})

    with MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(MemoryWriteOutcomeUnknown) as error:
            client.write_memory("agent", "scope", "private", source_type="agent")
        assert str(UUID(error.value.request_id)) == error.value.request_id
