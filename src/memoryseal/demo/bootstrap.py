"""Register existing, ENS-resolved demo wallets and grant narrow local memory access."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from eth_account import Account

from memoryseal import ens_observer
from memoryseal.client import MemorySealClient
from memoryseal.demo.transfer_context import parse_local_transfer


def bootstrap(
    owner,
    addresses: dict[str, str],
    names: dict[str, str],
    request_ids: dict[str, str],
    *,
    local_transfer: dict | None = None,
    observe=ens_observer.observe,
):
    if local_transfer is not None:
        asset, limit, claim_amount = parse_local_transfer(local_transfer)
        local_transfer = {
            "asset": asset,
            "max_amount": str(limit),
            "claim_amount": str(claim_amount),
        }
    roles = {"browser", "research", "finance"}
    if (
        set(addresses) != roles
        or set(names) != roles
        or len({v.lower() for v in addresses.values()}) != 3
    ):
        raise ValueError("Three distinct agent addresses and names are required")
    if (
        set(request_ids) != {"research", "claim"}
        or len({str(UUID(v)) for v in request_ids.values()}) != 2
    ):
        raise ValueError("Two distinct stable request IDs are required")
    if owner.address.lower() in {value.lower() for value in addresses.values()}:
        raise ValueError("Owner and agent wallets must be distinct")
    observations = {}
    # Resolve all names before any registration or policy change.
    for role in sorted(roles):
        result = observe(names[role], addresses[role])
        if result.get("matches") is not True or result.get("chainId") != 11155111:
            raise ValueError(f"{role} ENS record does not match on Sepolia")
        observations[role] = result
    existing = {agent["signing_address"].lower(): agent for agent in owner.list_agents()["agents"]}
    for role in roles:
        prior = existing.get(addresses[role].lower())
        if prior and (prior["revoked"] or prior["ens_name"] != observations[role]["name"]):
            raise ValueError(f"{role} already has a revoked or differently named identity")
    grants = (
        ("browser", "write", "browser-observations"),
        ("research", "write", "research"),
        ("research", "read", "research"),
        ("finance", "read", "browser-observations"),
        ("finance", "read", "research"),
    )
    capabilities = owner.list_capabilities()["capabilities"]
    # Check all existing relevant grants before registering or granting anything.
    for role, operation, namespace in grants:
        prior = existing.get(addresses[role].lower())
        if not prior:
            continue
        current = [
            cap
            for cap in capabilities
            if cap["agent_id"] == prior["id"]
            and cap["operation"] == operation
            and cap["resource"] == namespace
            and not cap["revoked"]
        ]
        if current and current[0].get("expires_at"):
            parsed = datetime.fromisoformat(current[0]["expires_at"])
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed <= datetime.now(UTC):
                raise ValueError(f"{role} {operation} grant for {namespace} has expired")
    ids = {}
    for role in sorted(roles):
        prior = existing.get(addresses[role].lower())
        ids[role] = (
            prior["id"]
            if prior
            else owner.register_agent(addresses[role], observations[role]["name"])["id"]
        )
    for role, operation, namespace in grants:
        current = [
            cap
            for cap in capabilities
            if cap["agent_id"] == ids[role]
            and cap["operation"] == operation
            and cap["resource"] == namespace
            and not cap["revoked"]
        ]
        if current:
            # Preserve existing grants; report an expired scope instead of silently replacing it.
            expiry = current[0].get("expires_at")
            if expiry:
                parsed = datetime.fromisoformat(expiry)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                if parsed <= datetime.now(UTC):
                    raise ValueError(f"{role} {operation} grant for {namespace} has expired")
            continue
        owner.grant(ids[role], operation, namespace)
    return {
        "agents": ids,
        "request_ids": {key: str(UUID(value)) for key, value in request_ids.items()},
        "ens_observations": observations,
        **({"local_transfer": local_transfer} if local_transfer is not None else {}),
        "note": "Local memory grants only. Existing grants are left unchanged; ENS observations do not establish exclusive control or finality.",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Register pre-existing ENS-resolved Sepolia demo agents"
    )
    parser.add_argument("context", type=Path, help="JSON containing names and stable request_ids")
    args = parser.parse_args()
    keys = {
        name.lower(): os.environ.get(f"MEMORYSEAL_DEMO_{name}_KEY")
        for name in ("OWNER", "BROWSER", "RESEARCH", "FINANCE")
    }
    if not all(keys.values()):
        parser.error("Set all four dedicated demo keys in the process environment")
    addresses = {
        name: Account.from_key(keys[name]).address for name in ("browser", "research", "finance")
    }
    context = json.loads(args.context.read_text())
    with MemorySealClient(
        os.environ.get("MEMORYSEAL_GATEWAY_URL", "http://localhost:8000"),
        keys["owner"],
        audience=os.environ.get("MEMORYSEAL_REQUEST_AUDIENCE", "memoryseal-local"),
    ) as owner:
        result = bootstrap(
            owner,
            addresses,
            context["names"],
            context["request_ids"],
            local_transfer=context.get("local_transfer"),
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
