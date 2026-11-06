"""Collect bounded, owner-authorized observations for an existing P0 scenario.

This does not submit a transaction or prove TEE attestation, finality, or why a
transaction reverted. ENS and chain observations may add gateway audit events.
"""

import argparse
import json
import os
import re
from contextlib import ExitStack
from pathlib import Path

import httpx

from memoryseal.client import MemorySealClient
from memoryseal.demo.live_memory import DEMO_RESEARCH, demo_claim
from memoryseal.demo.memory_scan import find_readable_memory
from memoryseal.demo.transfer_context import parse_uint256


def collect_evidence(
    client: MemorySealClient,
    context: dict,
    research_client: MemorySealClient,
    finance_client: MemorySealClient,
) -> dict:
    agents = context["agents"]
    if set(agents) != {"browser", "research", "finance"} or len(set(agents.values())) != 3:
        raise ValueError("Three distinct browser, research and finance agent IDs are required")
    denied = dict(context["denied"])
    allowed = dict(context["allowed"])
    initial = context["initial_grant"]
    local_transfer = context["local_transfer"]
    amount = parse_uint256(context["amount"])
    initial_amount = parse_uint256(initial["max_amount"])
    local_limit = parse_uint256(local_transfer["max_amount"])
    claim_amount = parse_uint256(local_transfer["claim_amount"])
    initial_expiry = parse_uint256(initial["expires_at"], allow_zero=True)
    grant_expiry = parse_uint256(context["grant_expires_at"], allow_zero=True)
    local_policy_version = parse_uint256(context["local_policy_version"], allow_zero=True)
    if initial_expiry >= 2**64 or grant_expiry >= 2**64:
        raise ValueError("Grant expiry is outside the uint64 range")
    denied["policy_version"] = parse_uint256(denied["policy_version"], allow_zero=True)
    allowed["policy_version"] = parse_uint256(allowed["policy_version"], allow_zero=True)
    if initial_amount >= amount:
        raise ValueError("Initial grant must be positive and below the requested amount")
    if denied["policy_version"] >= allowed["policy_version"]:
        raise ValueError("Allowed action must use a later policy version")
    if denied["transaction_hash"].lower() == allowed["transaction_hash"].lower():
        raise ValueError("Action transactions must be distinct")
    registered = {item["id"]: item for item in client.list_agents()["agents"]}
    for role, agent_client in (("research", research_client), ("finance", finance_client)):
        agent = registered.get(agents[role])
        if not agent or agent["signing_address"].lower() != agent_client.address.lower():
            raise ValueError(f"{role} key does not match the registered agent")
    research_matches = find_readable_memory(
        research_client, agents["research"], "research", context["research_memory_id"]
    )
    research_visible = (
        len(research_matches) == 1 and research_matches[0]["content"] == DEMO_RESEARCH
    )
    finance_research_matches = find_readable_memory(
        finance_client, agents["finance"], "research", context["research_memory_id"]
    )
    finance_research_visible = (
        len(finance_research_matches) == 1
        and finance_research_matches[0]["content"] == DEMO_RESEARCH
    )
    claim_withheld = not find_readable_memory(
        finance_client, agents["finance"], "browser-observations", context["claim_id"]
    )
    deployment = client.observe_onchain_deployment()["observation"]
    identities = {
        name: client.observe_ens(agent_id)["observation"] for name, agent_id in agents.items()
    }
    page = client.list_memories(memory_id=context["claim_id"])["memories"]
    if len(page) != 1 or page[0]["agent_id"] != agents["browser"]:
        raise ValueError("Claim is missing or belongs to a different agent")
    claim = page[0]
    claim_content = client.inspect_memory(claim["id"])
    provenance = client.observe_provenance(claim["id"])["observation"]

    def action(transaction):
        return client.observe_onchain_transfer(
            agent_id=agents["finance"],
            token=context["token"],
            recipient=context["recipient"],
            amount=amount,
            **transaction,
        )

    initial_grant = client.observe_onchain_grant(
        agent_id=agents["finance"],
        transaction_hash=initial["transaction_hash"],
        token=context["token"],
        max_amount=initial_amount,
        expires_at=initial_expiry,
        policy_version=denied["policy_version"],
    )
    grant = client.observe_onchain_grant(
        agent_id=agents["finance"],
        transaction_hash=context["grant_transaction_hash"],
        token=context["token"],
        max_amount=amount,
        expires_at=grant_expiry,
        policy_version=allowed["policy_version"],
    )
    denied_result, allowed_result = action(denied), action(allowed)
    denied_observation, allowed_observation = (
        denied_result["observation"],
        allowed_result["observation"],
    )
    balance = None
    balance_error = None
    if allowed_observation.get("transfer_verified") is True:
        try:
            balance = client.observe_token_balance(
                token=context["token"],
                recipient=context["recipient"],
                block_number=allowed_observation["block_number"],
            )
        except httpx.HTTPError:
            # Preserve the other observations, without exposing response bodies or RPC URLs.
            balance_error = "Balance observation unavailable; inspect gateway configuration and RPC"
    analysis = claim.get("analysis") or {}
    inference = analysis.get("evidence") or {}
    return {
        "scope": "Observation checks only; this report does not establish complete P0 acceptance.",
        "p0_acceptance_verified": False,
        "unverified_acceptance_requirements": [
            "independent provider TEE attestation and request/response binding",
            "ENS exclusive identity control",
            "transaction finality and cause of the reverted action",
        ],
        "deployment": deployment,
        "agents": {
            name: {"id": agents[name], "ens": observation}
            for name, observation in identities.items()
        },
        "claim": {
            "id": claim["id"],
            "status": claim["status"],
            "inference_status": claim["inference_status"],
            "inference_reference": claim["inference_reference"],
            "inference_evidence": {
                key: value
                for key, value in inference.items()
                if key not in ("policy_snapshot_capability_ids", "policy_snapshot_transfer_limits")
            },
            "provenance": claim.get("provenance"),
            "arkiv_observation": provenance,
        },
        "initial_grant": initial_grant,
        "grant": grant,
        "recipient_balance_observation": balance,
        "recipient_balance_error": balance_error,
        "denied": {
            "transaction_hash": denied["transaction_hash"],
            "policy_version": denied["policy_version"],
            "observation": denied_observation,
        },
        "allowed": {
            "transaction_hash": allowed["transaction_hash"],
            "policy_version": allowed["policy_version"],
            "observation": allowed_observation,
        },
        "checks": {
            "ens_addresses_match": all(
                value.get("matches") is True and value.get("chainId") == 11155111
                for value in identities.values()
            ),
            "research_memory_readable": research_visible,
            "research_memory_readable_by_finance": finance_research_visible,
            "claim_withheld_from_finance": claim_withheld,
            "claim_quarantined": claim["status"] == "quarantined",
            "demo_claim_matched": claim.get("source_type") == "external"
            and claim_content.get("content") == demo_claim(local_transfer["asset"], claim_amount)
            and claim_content.get("commitment") == claim.get("commitment")
            and claim.get("commitment") is not None,
            "claim_covers_attempted_amount": claim_amount >= amount,
            "local_and_initial_limits_match": local_transfer["asset"].lower()
            == context["token"].lower()
            and local_limit == initial_amount
            and claim_amount > local_limit,
            "gateway_snapshot_finance_limit_matched": any(
                cap.get("id") == context["local_finance_capability_id"]
                and cap.get("agent_id") == agents["finance"]
                and cap.get("resource", "").lower() == context["token"].lower()
                and cap.get("max_amount") == str(initial_amount)
                for cap in inference.get("policy_snapshot_transfer_limits", [])
                if isinstance(cap, dict)
            ),
            "gateway_policy_snapshot_matched": (
                inference.get("policy_snapshot_version") == local_policy_version
                and claim.get("policy_version") == local_policy_version
                and context["local_finance_capability_id"]
                in inference.get("policy_snapshot_capability_ids", [])
            ),
            "model_reported_authorization_claim": analysis.get("category") == "authorization_claim",
            "model_reported_finance_capability_conflict": isinstance(
                analysis.get("conflicts_with"), list
            )
            and context["local_finance_capability_id"] in analysis["conflicts_with"],
            "gateway_reported_connection_attestation": (
                inference.get("gateway_connection_attested") is True
                and isinstance(inference.get("gateway_certificate_sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", inference["gateway_certificate_sha256"])
                is not None
                and inference["gateway_certificate_sha256"] != "0" * 64
            ),
            "router_reported_verification": inference.get("router_verified") is True
            and bool(claim["inference_reference"])
            and claim["inference_status"] in ("router_verified", "pinned_signature_verified"),
            "arkiv_record_matched": provenance == "matched",
            "consecutive_policy_versions": allowed["policy_version"]
            == denied["policy_version"] + 1,
            "initial_owner_grant_matched": initial_grant["observation"].get("grant_verified")
            is True
            and initial_grant.get("chain_id") == 11155111
            and bool(deployment.get("registry"))
            and initial_grant.get("registry", "").lower() == deployment["registry"].lower(),
            "initial_grant_before_denied": isinstance(
                initial_grant["observation"].get("block_number"), int
            )
            and isinstance(denied_observation.get("block_number"), int)
            and initial_grant["observation"]["block_number"] < denied_observation["block_number"],
            "owner_grant_matched": grant["observation"].get("grant_verified") is True
            and grant.get("chain_id") == 11155111
            and bool(deployment.get("registry"))
            and grant.get("registry", "").lower() == deployment["registry"].lower(),
            "grant_between_actions": isinstance(grant["observation"].get("block_number"), int)
            and isinstance(denied_observation.get("block_number"), int)
            and isinstance(allowed_observation.get("block_number"), int)
            and denied_observation["block_number"]
            < grant["observation"]["block_number"]
            < allowed_observation["block_number"],
            "denied_call_reverted": denied_observation.get("reverted_call_verified") is True,
            "allowed_transfer_event_matched": allowed_observation.get("transfer_verified") is True,
            "recipient_block_balance_delta_matched": balance is not None
            and balance.get("chain_id") == 11155111
            and balance["observation"].get("block_hash", "").lower()
            == allowed_observation.get("block_hash", "").lower()
            and bool(allowed_observation.get("block_hash"))
            and int(balance["observation"]["delta"]) == amount,
            "token_transfer_event_matched": allowed_observation.get("token_transfer_event_matched")
            is True,
            "actions_on_sepolia": denied_result.get("chain_id")
            == allowed_result.get("chain_id")
            == 11155111,
            "deployment_registry_matched": deployment.get("matches") is True
            and deployment.get("chain_id") == 11155111
            and deployment.get("executor", "").lower() == denied_result.get("executor", "").lower(),
            "runtime_matches_local_build": deployment.get("registry_code_matches_local") is True
            and deployment.get("executor_code_matches_local") is True,
            "same_executor": bool(denied_result.get("executor"))
            and denied_result.get("executor", "").lower()
            == allowed_result.get("executor", "").lower(),
            "denied_before_allowed": isinstance(denied_observation.get("block_number"), int)
            and isinstance(allowed_observation.get("block_number"), int)
            and denied_observation["block_number"] < allowed_observation["block_number"],
        },
        "limitations": [
            "RPC observations are not finality proofs.",
            "Memory reads are point-in-time observations, not proof of future access decisions.",
            "A reverted call does not prove its cause.",
            "Token events and balanceOf responses are contract assertions; block-level balance changes can include other transactions.",
            "Gateway connection verification is gateway-reported and trusts its configured verifier; provider execution and request/response binding remain unverified.",
            "Model-reported conflicts are advisory and are not independently tied to onchain policy.",
            "ENS address resolution does not establish exclusive resolver control.",
            "Runtime comparison trusts local build artifacts and the RPC; it is not a security audit.",
            "Version sequencing depends on the observed registry runtime remaining unchanged and a truthful RPC; it does not prove why the call reverted.",
            "Transaction order is only established when the observed blocks differ.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Collect public evidence for an existing MemorySeal scenario"
    )
    parser.add_argument("context", type=Path, help="JSON file with public scenario identifiers")
    args = parser.parse_args()
    keys = [
        os.environ.get(f"MEMORYSEAL_DEMO_{role}_KEY") for role in ("OWNER", "RESEARCH", "FINANCE")
    ]
    if not all(keys):
        parser.error("Set the demo OWNER, RESEARCH and FINANCE keys in the process environment")
    url = os.environ.get("MEMORYSEAL_GATEWAY_URL", "http://localhost:8000")
    audience = os.environ.get("MEMORYSEAL_REQUEST_AUDIENCE", "memoryseal-local")
    with ExitStack() as stack:
        owner, research, finance = [
            stack.enter_context(MemorySealClient(url, key, audience=audience)) for key in keys
        ]
        report = collect_evidence(owner, json.loads(args.context.read_text()), research, finance)
    print(json.dumps(report, indent=2))
    if not all(report["checks"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
