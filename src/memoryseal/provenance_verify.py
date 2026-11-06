"""Compare private memory material with one selected public Arkiv query result."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from uuid import UUID

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import is_address

from memoryseal.client import verify_memory_commitment
from memoryseal.signatures import request_message


def verify_quarantine_request(
    event: dict, expected_owner: str, *, schema: str | None = None
) -> bool:
    """Verify the historical request signature; this does not prove publication or time."""
    try:
        audience, nonce = event["request_audience"], event["request_nonce"]
        timestamp, signature = event["request_timestamp"], event["request_signature"]
        if (
            not isinstance(audience, str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", audience)
            or not isinstance(timestamp, str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]{0,15})", timestamp)
            or int(timestamp) > 2**53 - 1
            or not isinstance(signature, str)
            or not re.fullmatch(r"0x[0-9a-f]{130}", signature)
            or not isinstance(nonce, str)
            or not re.fullmatch(r"[0-9a-f]{32}", nonce)
        ):
            return False
        selected = schema or event.get("schema")
        versioned = selected in ("memoryseal.memory-event.v6", "memoryseal.memory-event.v7")
        if versioned:
            event_id, commitment, policy = (
                event["event_id"],
                event["commitment"],
                event["policy_version"],
            )
            if (
                not isinstance(event_id, str)
                or str(UUID(event_id)) != event_id
                or not isinstance(commitment, str)
                or not re.fullmatch(r"[0-9a-f]{64}", commitment)
                or isinstance(policy, bool)
                or not isinstance(policy, (str, int))
            ):
                return False
            policy = str(policy)
            if not re.fullmatch(r"(?:0|[1-9][0-9]{0,15})", policy) or int(policy) >= 2**53:
                return False
            body = json.dumps(
                {"event_id": event_id, "commitment": commitment, "policy_version": int(policy)},
                separators=(",", ":"),
            ).encode()
            if hashlib.sha256(body).hexdigest() != event["request_body_sha256"]:
                return False
        else:
            body_by_hash = {hashlib.sha256(body).hexdigest(): body for body in (b"", b"{}")}
            body = body_by_hash.get(event["request_body_sha256"])
        if body is None:
            return False
        message = request_message(
            audience=audience,
            method="POST",
            target=f"/memories/{event['memory_id']}/"
            + (
                "attest-origin"
                if selected == "memoryseal.memory-event.v7"
                else "quarantine-event"
                if versioned
                else "quarantine"
            ),
            body=body,
            timestamp=int(timestamp),
            nonce=nonce,
        )
        return (
            Account.recover_message(encode_defunct(text=message), signature=signature).lower()
            == expected_owner.lower()
        )
    except (ValueError, TypeError, KeyError, BadSignature):
        return False


def compare_event(
    report,
    *,
    publisher,
    memory_id,
    entity_key,
    content,
    salt_base64,
    event_type="memory_created",
    expected_owner=None,
    expected_agent=None,
):
    """Match content to a selected public record; the supplied report is not authenticated."""
    if not is_address(publisher) or int(publisher, 16) == 0:
        raise ValueError("Invalid expected publisher")
    canonical_id = str(UUID(memory_id))
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", entity_key):
        raise ValueError("Invalid entity key")
    schemas = {
        "memory_created": {
            "memoryseal.memory-event.v1",
            "memoryseal.memory-event.v2",
            "memoryseal.memory-event.v3",
        },
        "memory_quarantined": {
            "memoryseal.memory-event.v4",
            "memoryseal.memory-event.v5",
            "memoryseal.memory-event.v6",
        },
        "memory_origin_attested": {"memoryseal.memory-event.v7"},
    }
    if event_type not in schemas or report.get("schema") not in schemas[event_type]:
        raise ValueError("Unsupported provenance schema")
    if event_type == "memory_quarantined" and (
        not isinstance(expected_owner, str)
        or not is_address(expected_owner)
        or int(expected_owner, 16) == 0
    ):
        raise ValueError("Expected owner is required for a quarantine event")
    if event_type == "memory_origin_attested" and (
        not isinstance(expected_owner, str)
        or not is_address(expected_owner)
        or int(expected_owner, 16) == 0
        or not isinstance(expected_agent, str)
        or not is_address(expected_agent)
        or int(expected_agent, 16) == 0
    ):
        raise ValueError("Expected owner and agent are required for an origin event")
    if not isinstance(report.get("creator"), str) or report["creator"].lower() != publisher.lower():
        raise ValueError("Publisher does not match the expected address")
    records = report.get("records")
    if not isinstance(records, list) or len(records) > 100:
        raise ValueError("Invalid query page")
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("entity_key"), str)
        and record["entity_key"].lower() == entity_key.lower()
    ]
    if len(matches) != 1:
        raise ValueError("Selected entity is missing or duplicated in this page")
    event = matches[0]
    if event.get("memory_id") != canonical_id or event.get("event_type") != event_type:
        raise ValueError("Selected event does not match the expected memory")
    if event_type == "memory_quarantined" and (
        not isinstance(event.get("owner"), str)
        or not isinstance(event.get("actor_address"), str)
        or event["owner"].lower() != expected_owner.lower()
        or event["actor_address"].lower() != expected_owner.lower()
        or event.get("status") != "quarantined"
    ):
        raise ValueError("Quarantine owner, actor or status does not match")
    if event_type == "memory_origin_attested" and (
        not isinstance(event.get("owner"), str)
        or event["owner"].lower() != expected_owner.lower()
        or not isinstance(event.get("actor_address"), str)
        or event["actor_address"].lower() != expected_agent.lower()
        or not isinstance(event.get("agent_address"), str)
        or event["agent_address"].lower() != expected_agent.lower()
        or event.get("status") not in ("accepted", "quarantined")
    ):
        raise ValueError("Origin owner, agent or actor does not match")
    request_signature_valid = None
    if report["schema"] in ("memoryseal.memory-event.v5", "memoryseal.memory-event.v6"):
        request_signature_valid = verify_quarantine_request(
            event, expected_owner, schema=report["schema"]
        )
        if not request_signature_valid:
            raise ValueError("Quarantine request signature does not match")
    agent_signature_valid = None
    if report["schema"] == "memoryseal.memory-event.v7":
        agent_signature_valid = verify_quarantine_request(
            event, expected_agent, schema=report["schema"]
        )
        if not agent_signature_valid:
            raise ValueError("Origin request signature does not match")
    return {
        "matches": verify_memory_commitment(content, salt_base64, event.get("commitment")),
        "memory_id": canonical_id,
        "entity_key": entity_key.lower(),
        "publisher": publisher,
        "schema": report["schema"],
        "event_type": event_type,
        "owner_request_signature_valid": request_signature_valid,
        "agent_request_signature_valid": agent_signature_valid,
        "observed_block": report.get("block_number"),
        "scope": (
            "Compares private material to a supplied query page; the page, RPC, publication and truth are not authenticated. "
            + (
                "The request signature binds the event ID, commitment and policy version, not publication time or other event metadata."
                if report["schema"] in ("memoryseal.memory-event.v6", "memoryseal.memory-event.v7")
                else "The request signature does not bind the event ID, commitment, policy version, or publication time."
            )
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Privately compare memory content to an Arkiv query page"
    )
    parser.add_argument(
        "report", type=Path, help="Public JSON produced by integrations/arkiv/query.mjs"
    )
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--memory-id", required=True)
    parser.add_argument("--entity-key", required=True)
    parser.add_argument(
        "--event-type",
        choices=("memory_created", "memory_quarantined", "memory_origin_attested"),
        default="memory_created",
    )
    parser.add_argument("--expected-owner", help="required for quarantine and origin events")
    parser.add_argument("--expected-agent", help="required for an origin event")
    args = parser.parse_args()
    # Private content and salt are supplied through stdin, never command-line arguments.
    private_raw = sys.stdin.buffer.read(1_048_577)
    if len(private_raw) > 1_048_576:
        parser.error("Private input too large")
    private = json.loads(private_raw)
    result = compare_event(
        json.loads(args.report.read_text()),
        publisher=args.publisher,
        memory_id=args.memory_id,
        entity_key=args.entity_key,
        content=private["content"],
        salt_base64=private["commitment_salt"],
        event_type=args.event_type,
        expected_owner=args.expected_owner,
        expected_agent=args.expected_agent,
    )
    print(json.dumps(result, indent=2))
    if not result["matches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
