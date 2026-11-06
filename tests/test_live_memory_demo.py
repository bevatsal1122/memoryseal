from uuid import uuid4

import pytest

from memoryseal.demo.live_memory import memory_stage_succeeded
from memoryseal.demo.live_memory import run_memory_stage as execute_memory_stage


class FinanceClient:
    address = "finance"

    def read_memory(self, agent_id, namespace):
        assert agent_id == "finance"
        if namespace == "research":
            return {"memories": [{"id": "research", "content": "A research observation"}]}
        assert namespace == "browser-observations"
        return {"memories": []}

    def read_memory_page(self, agent_id, namespace, *, offset, limit):
        assert offset == 0 and limit == 100
        return {**self.read_memory(agent_id, namespace), "next_offset": None}


def run_memory_stage(owner, browser, research, *args, finance=None):
    finance = finance or getattr(owner, "_test_finance", None) or FinanceClient()
    return execute_memory_stage(owner, browser, research, *args, finance=finance)


class AgentClient:
    def __init__(self, address, status):
        self.address, self.status, self.writes, self.attestations = address, status, [], []

    def write_memory(self, agent_id, namespace, content, **kwargs):
        self.writes.append((agent_id, namespace, content, kwargs))
        return {
            "id": self.address,
            "status": self.status,
            "commitment": "a" * 64,
            "policy_version": 1,
        }

    def attest_memory_origin_verified(self, memory_id, **kwargs):
        self.attestations.append((memory_id, kwargs))
        return {"event_id": kwargs["event_id"], "changed": True}

    def read_memory(self, agent_id, namespace):
        return {"memories": [{"id": self.address, "content": "A research observation"}]}

    def read_memory_page(self, agent_id, namespace, *, offset, limit):
        assert offset == 0 and limit == 100
        return {**self.read_memory(agent_id, namespace), "next_offset": None}


class OwnerClient:
    def __init__(self):
        self.matches = True

    def integration_readiness(self):
        return {
            "ens_sepolia_configured": True,
            "zero_g_router_configured": True,
            "connection_attestation_required": True,
            "connection_attestation_available": True,
            "request_binding_verification_supported": True,
            "unbound_inference_allowed": False,
        }

    def list_agents(self):
        return {
            "agents": [
                {
                    "id": name,
                    "signing_address": name,
                    "ens_name": f"{name}.example.eth",
                    "revoked": False,
                }
                for name in ("browser", "research", "finance")
            ]
        }

    def list_capabilities(self):
        return {
            "policy_version": 1,
            "capabilities": [
                {
                    "id": "cap",
                    "agent_id": "finance",
                    "operation": "transfer",
                    "resource": "USDC",
                    "max_amount": 100,
                    "revoked": False,
                }
            ]
            + [
                {
                    "id": f"{role}-{op}-{scope}",
                    "agent_id": role,
                    "operation": op,
                    "resource": scope,
                    "max_amount": None,
                    "revoked": False,
                }
                for role, op, scope in (
                    ("browser", "write", "browser-observations"),
                    ("research", "write", "research"),
                    ("research", "read", "research"),
                    ("finance", "read", "research"),
                    ("finance", "read", "browser-observations"),
                )
            ],
        }

    def observe_ens(self, agent_id):
        return {"observation": {"matches": self.matches, "chainId": 11155111}}

    def list_memories(self, *, memory_id):
        return {
            "memories": [
                {
                    "inference_status": "unverified",
                    "inference_reference": None,
                    "provenance": None,
                    "analysis": {
                        "evidence": {
                            "gateway_connection_attested": True,
                            "gateway_certificate_sha256": "a" * 64,
                        }
                    },
                }
            ]
        }


def test_live_memory_stage_validates_identities_and_uses_stable_ids():
    owner = OwnerClient()
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    ids = {name: name for name in ("browser", "research", "finance")}
    requests = {"claim": str(uuid4()), "research": str(uuid4())}
    report = run_memory_stage(
        owner,
        browser,
        research,
        ids,
        requests,
        {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
    )
    assert report["claim_id"] == "browser"
    assert report["finance_research_readable"] is True
    assert report["claim_withheld_from_finance"] is True
    assert report["origin_event_ids"]["claim"] == browser.attestations[0][1]["event_id"]
    assert report["inference_status"] == "unverified"
    assert browser.writes[0][3]["request_id"] == requests["claim"]
    assert research.writes[0][3]["request_id"] == requests["research"]
    with pytest.raises(ValueError, match="local finance transfer"):
        run_memory_stage(
            owner,
            browser,
            research,
            ids,
            requests,
            {"asset": "USDC", "max_amount": 200, "claim_amount": 5000},
        )
    report = run_memory_stage(
        owner,
        browser,
        research,
        ids,
        requests,
        {"asset": "USDC", "max_amount": "100", "claim_amount": "5000"},
    )
    assert report["local_finance_capability_id"] == "cap"
    assert browser.attestations[0][1]["event_id"] == browser.attestations[1][1]["event_id"]
    with pytest.raises(ValueError, match="base-unit limit"):
        run_memory_stage(
            owner,
            browser,
            research,
            ids,
            requests,
            {"asset": "USDC", "max_amount": 100.0, "claim_amount": 5000},
        )
    owner.matches = False
    with pytest.raises(ValueError, match="ENS address"):
        run_memory_stage(
            owner,
            browser,
            research,
            ids,
            requests,
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert len(browser.writes) == 2 and len(research.writes) == 2


def test_live_stage_requires_finance_identity_and_read_grants_before_writes():
    owner = OwnerClient()
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    ids = {name: name for name in ("browser", "research", "finance")}
    requests = {"claim": str(uuid4()), "research": str(uuid4())}
    transfer = {"asset": "USDC", "max_amount": 100, "claim_amount": 5000}
    finance = FinanceClient()
    finance.address = "wrong-finance"
    with pytest.raises(ValueError, match="finance key"):
        run_memory_stage(owner, browser, research, ids, requests, transfer, finance=finance)
    policy = owner.list_capabilities()
    policy["capabilities"] = [
        cap
        for cap in policy["capabilities"]
        if not (cap["agent_id"] == "finance" and cap["resource"] == "research")
    ]
    owner.list_capabilities = lambda: policy
    with pytest.raises(ValueError, match="finance read grant"):
        run_memory_stage(owner, browser, research, ids, requests, transfer)
    assert not browser.writes and not research.writes


def test_live_stage_stops_before_claim_if_finance_cannot_read_research():
    class NoResearch(FinanceClient):
        def read_memory(self, agent_id, namespace):
            return {"memories": []}

    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(RuntimeError, match="Finance agent cannot read"):
        run_memory_stage(
            OwnerClient(),
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
            finance=NoResearch(),
        )
    assert len(research.writes) == 1 and not browser.writes


def test_live_stage_stops_before_claim_when_research_scan_is_incomplete():
    class UnfinishedScan(FinanceClient):
        def read_memory_page(self, _agent, _namespace, *, offset, limit):
            return {"memories": [], "next_offset": offset + limit}

    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(ValueError, match="page limit"):
        run_memory_stage(
            OwnerClient(),
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
            finance=UnfinishedScan(),
        )
    assert len(research.writes) == 1 and not browser.writes


def test_live_memory_stage_rejects_bridge_before_any_writes():
    owner = OwnerClient()
    owner.integration_readiness = lambda: {
        "ens_sepolia_configured": True,
        "zero_g_router_configured": True,
        "zero_g_experimental_bridge": True,
    }
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(ValueError, match="Experimental 0G bridge"):
        run_memory_stage(
            owner,
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert not browser.writes and not research.writes


@pytest.mark.parametrize(
    "supported,unbound", [(False, False), (None, False), (True, True), (True, None)]
)
def test_live_stage_refuses_missing_binding_or_unsafe_override_before_writes(supported, unbound):
    owner = OwnerClient()
    readiness = owner.integration_readiness()
    readiness.update(
        request_binding_verification_supported=supported, unbound_inference_allowed=unbound
    )
    owner.integration_readiness = lambda: readiness
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(ValueError, match="request binding|unbound inference"):
        run_memory_stage(
            owner,
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert not browser.writes and not research.writes


@pytest.mark.parametrize("required,available", [(False, True), (True, False), (None, True)])
def test_live_memory_stage_requires_connection_gate_before_writes(required, available):
    owner = OwnerClient()
    owner.integration_readiness = lambda: {
        "ens_sepolia_configured": True,
        "zero_g_router_configured": True,
        "connection_attestation_required": required,
        "connection_attestation_available": available,
    }
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(ValueError, match="connection verification"):
        run_memory_stage(
            owner,
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert not browser.writes and not research.writes


def test_memory_stage_success_requires_accepted_research():
    result = {
        "local_policy_snapshot_matched": True,
        "request_binding_support_reported": True,
        "unbound_override_disabled_reported": True,
        "research_status": "accepted",
        "research_readable": True,
        "finance_research_readable": True,
        "claim_withheld_from_finance": True,
        "research_gateway_connection_reported": True,
        "claim_gateway_connection_reported": True,
        "claim_status": "quarantined",
        "inference_status": "router_verified",
    }
    assert memory_stage_succeeded(result)
    result["claim_withheld_from_finance"] = False
    assert not memory_stage_succeeded(result)
    result["claim_withheld_from_finance"] = True
    result["research_status"] = "quarantined"
    assert not memory_stage_succeeded(result)
    result["research_status"] = "accepted"
    result["research_readable"] = False
    assert not memory_stage_succeeded(result)
    result["research_readable"] = True
    result["claim_gateway_connection_reported"] = False
    assert not memory_stage_succeeded(result)


def test_memory_stage_stops_before_claim_without_research_connection_evidence():
    owner = OwnerClient()
    owner.list_memories = lambda **_: {"memories": [{"analysis": None}]}
    browser, research = AgentClient("browser", "quarantined"), AgentClient("research", "accepted")
    with pytest.raises(RuntimeError, match="connection check"):
        run_memory_stage(
            owner,
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert not browser.writes


@pytest.mark.parametrize("research_status,readable", [("quarantined", True), ("accepted", False)])
def test_memory_stage_stops_before_claim_if_research_is_unavailable(research_status, readable):
    owner = OwnerClient()
    browser = AgentClient("browser", "quarantined")
    research = AgentClient("research", research_status)
    if not readable:
        research.read_memory = lambda *_: {"memories": []}
    with pytest.raises(RuntimeError, match="Research"):
        run_memory_stage(
            owner,
            browser,
            research,
            {name: name for name in ("browser", "research", "finance")},
            {"claim": str(uuid4()), "research": str(uuid4())},
            {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
        )
    assert not browser.writes


def test_live_memory_stage_through_gateway_is_idempotent(tmp_path, monkeypatch, gateway_transport):
    import base64
    import os
    from contextlib import ExitStack
    from types import SimpleNamespace

    from eth_account import Account
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from memoryseal import auth
    from memoryseal.api import app
    from memoryseal.client import MemorySealClient
    from memoryseal.config import settings
    from memoryseal.db import Base, get_session
    from memoryseal.inference import InferenceResult, ThreatAnalysis

    engine = create_engine(f"sqlite:///{tmp_path / 'scenario.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "zero_g_model", "test")
    monkeypatch.setattr(settings, "require_connection_attestation", True)
    monkeypatch.setattr(settings, "allow_unbound_inference", True)  # mocked inference
    verifier = tmp_path / "mock-verifier"
    verifier.write_text("test placeholder")
    verifier.chmod(0o700)
    monkeypatch.setattr(settings, "connection_attestation_verifier", str(verifier))
    monkeypatch.setattr(settings, "connection_attestation_verifier_sha256", "a" * 64)
    monkeypatch.setattr(
        "memoryseal.memory_service.AttestedGatewayTransport",
        lambda *_, **__: SimpleNamespace(verified_fingerprint="a" * 64),
    )
    monkeypatch.setattr(settings, "ens_rpc_url", "https://rpc.example")
    monkeypatch.setattr(settings, "ens_network", "sepolia")
    monkeypatch.setattr(settings, "zero_g_provider_address", None)
    monkeypatch.setattr(settings, "zero_g_tee_signer", None)
    monkeypatch.setattr(settings, "zero_g_signature_base_url", None)
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)
    monkeypatch.setattr(settings, "require_onchain_memory", False)
    monkeypatch.setattr(settings, "arkiv_private_key", None)
    monkeypatch.setattr(settings, "onchain_rpc_url", None)
    monkeypatch.setattr(
        "memoryseal.ens_observer.observe",
        lambda name, address: {
            "name": name,
            "resolvedAddress": address,
            "matches": True,
            "chainId": 11155111,
            "blockNumber": "42",
            "blockHash": "0x" + "a" * 64,
        },
    )

    contexts = []

    class Classifier:
        def __init__(self, *args, **kwargs):
            pass

        def analyze(self, **kwargs):
            contexts.append(kwargs["policy_context"])
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
        with TestClient(app) as server, ExitStack() as stack:
            accounts = [Account.create() for _ in range(4)]
            owner, browser, research, finance = [
                stack.enter_context(
                    MemorySealClient(
                        "http://testserver",
                        account.key,
                        audience=settings.request_audience,
                        transport=gateway_transport(server),
                    )
                )
                for account in accounts
            ]
            owner._test_finance = finance
            ids = {
                name: owner.register_agent(account.address, f"{name}.example.eth")["id"]
                for name, account in zip(
                    ("browser", "research", "finance"), accounts[1:], strict=True
                )
            }
            owner.grant(ids["browser"], "write", "browser-observations")
            owner.grant(ids["research"], "write", "research")
            owner.grant(ids["research"], "read", "research")
            owner.grant(ids["finance"], "read", "research")
            owner.grant(ids["finance"], "read", "browser-observations")
            owner.grant(ids["finance"], "transfer", "USDC", max_amount=100)
            readiness = owner.integration_readiness()
            assert readiness["ens_sepolia_configured"] is True
            assert readiness["zero_g_router_configured"] is True
            assert readiness["arkiv_publisher_configured"] is False
            assert readiness["onchain_observer_configured"] is False
            request_ids = {"research": str(uuid4()), "claim": str(uuid4())}
            with pytest.raises(ValueError, match="request binding"):
                run_memory_stage(
                    owner,
                    browser,
                    research,
                    ids,
                    request_ids,
                    {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
                )
            assert owner.list_memories()["memories"] == []
            monkeypatch.setattr(settings, "zero_g_api_key", None)
            with pytest.raises(ValueError, match="inference configuration"):
                run_memory_stage(
                    owner,
                    browser,
                    research,
                    ids,
                    request_ids,
                    {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
                )
            assert owner.list_memories()["memories"] == []
            monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("test"))
            # This test exercises the later stages against mocked inference only;
            # the actual gateway reports binding unsupported and must fail preflight.
            gateway_readiness = owner.integration_readiness
            monkeypatch.setattr(
                owner,
                "integration_readiness",
                lambda: (
                    gateway_readiness()
                    | {
                        "request_binding_verification_supported": True,
                        "unbound_inference_allowed": False,
                    }
                ),
            )
            first = run_memory_stage(
                owner,
                browser,
                research,
                ids,
                request_ids,
                {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
            )
            again = run_memory_stage(
                owner,
                browser,
                research,
                ids,
                request_ids,
                {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
            )
            import json

            claim_context = json.loads(contexts[-1])
            assert any(
                cap["id"] == first["local_finance_capability_id"] and cap["max_amount"] == "100"
                for cap in claim_context["capabilities"]
            )
            assert first["claim_id"] == again["claim_id"]
            assert first["research_memory_id"] == again["research_memory_id"]
            assert first["origin_event_ids"] == again["origin_event_ids"]
            events = owner.memory_provenance_events(first["claim_id"])["events"]
            assert any(
                event["event_type"] == "memory_origin_attested"
                and event["event_id"] == first["origin_event_ids"]["claim"]
                for event in events
            )
            found = owner.list_memories(
                request_id=request_ids["research"], agent_id=ids["research"]
            )
            assert [item["id"] for item in found["memories"]] == [first["research_memory_id"]]
            assert (
                owner.list_memories(request_id=request_ids["research"], agent_id=ids["browser"])[
                    "memories"
                ]
                == []
            )
            with MemorySealClient(
                "http://testserver",
                Account.create().key,
                audience=settings.request_audience,
                transport=gateway_transport(server),
            ) as outsider:
                assert outsider.list_memories(request_id=request_ids["research"])["memories"] == []
            assert first["local_policy_snapshot_matched"] is True
            assert first["claim_status"] == "quarantined"
            assert first["inference_status"] == "router_verified"
            assert first["provenance"]["state"] == "pending"
            assert len(owner.list_memories()["memories"]) == 2

            original_analyze = Classifier.analyze

            def change_policy_on_claim(self, **kwargs):
                if kwargs["source_type"] == "external":
                    owner.grant(ids["finance"], "transfer", "USDC", max_amount=200)
                return original_analyze(self, **kwargs)

            monkeypatch.setattr(Classifier, "analyze", change_policy_on_claim)
            changed = run_memory_stage(
                owner,
                browser,
                research,
                ids,
                {"research": str(uuid4()), "claim": str(uuid4())},
                {"asset": "USDC", "max_amount": 100, "claim_amount": 5000},
            )
            assert changed["claim_status"] == "quarantined"
            assert changed["inference_status"] == "stale"
            assert changed["local_policy_snapshot_matched"] is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
