import base64
import json
import subprocess
import sys
from uuid import uuid4

import pytest

from memoryseal.encryption import content_commitment
from memoryseal.provenance_verify import compare_event


def test_private_commitment_matches_only_selected_public_event():
    content = "A private observation 🛡️"
    salt = b"a" * 32
    publisher, entity = "0x" + "1" * 40, "0x" + "2" * 64
    memory_id = str(uuid4())
    record = {
        "entity_key": entity,
        "memory_id": memory_id,
        "event_type": "memory_created",
        "commitment": content_commitment(content.encode(), salt),
    }
    report = {
        "schema": "memoryseal.memory-event.v3",
        "creator": publisher,
        "records": [record],
        "block_number": "123",
    }
    args = {
        "publisher": publisher,
        "memory_id": memory_id,
        "entity_key": entity,
        "content": content,
        "salt_base64": base64.b64encode(salt).decode(),
    }
    result = compare_event(report, **args)
    assert result["matches"] is True
    assert content not in str(result) and args["salt_base64"] not in str(result)
    assert compare_event(report, **(args | {"content": content + "!"}))["matches"] is False
    with pytest.raises(ValueError, match="Publisher"):
        compare_event(report, **(args | {"publisher": "0x" + "3" * 40}))
    with pytest.raises(ValueError, match="missing or duplicated"):
        compare_event(report | {"records": [record, record]}, **args)


def test_quarantine_comparison_requires_explicit_event_and_owner():
    content, salt = "confidential example 823", b"s" * 32
    owner, publisher, entity, memory_id = (
        "0x" + "a" * 40,
        "0x" + "b" * 40,
        "0x" + "c" * 64,
        str(uuid4()),
    )
    record = {
        "entity_key": entity,
        "memory_id": memory_id,
        "event_type": "memory_quarantined",
        "owner": owner,
        "actor_address": owner,
        "status": "quarantined",
        "commitment": content_commitment(content.encode(), salt),
    }
    report = {"schema": "memoryseal.memory-event.v4", "creator": publisher, "records": [record]}
    args = {
        "publisher": publisher,
        "memory_id": memory_id,
        "entity_key": entity,
        "content": content,
        "salt_base64": base64.b64encode(salt).decode(),
    }
    with pytest.raises(ValueError, match="Unsupported"):
        compare_event(report, **args)
    with pytest.raises(ValueError, match="owner"):
        compare_event(report, **args, event_type="memory_quarantined")
    result = compare_event(report, **args, event_type="memory_quarantined", expected_owner=owner)
    assert result["matches"] is True
    assert result["event_type"] == "memory_quarantined"
    assert content not in str(result) and args["salt_base64"] not in str(result)
    for field, value in (
        ("actor_address", "0x" + "d" * 40),
        ("owner", "0x" + "d" * 40),
        ("status", "accepted"),
    ):
        with pytest.raises(ValueError, match="owner, actor or status"):
            compare_event(
                report | {"records": [record | {field: value}]},
                **args,
                event_type="memory_quarantined",
                expected_owner=owner,
            )


def test_quarantine_cli_reads_private_input_from_stdin(tmp_path):
    content, salt = "secret text", b"s" * 32
    owner, publisher, entity, memory_id = (
        "0x" + "a" * 40,
        "0x" + "b" * 40,
        "0x" + "c" * 64,
        str(uuid4()),
    )
    report = {
        "schema": "memoryseal.memory-event.v4",
        "creator": publisher,
        "records": [
            {
                "entity_key": entity,
                "memory_id": memory_id,
                "event_type": "memory_quarantined",
                "owner": owner,
                "actor_address": owner,
                "status": "quarantined",
                "commitment": content_commitment(content.encode(), salt),
            }
        ],
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    private = {"content": content, "commitment_salt": base64.b64encode(salt).decode()}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "memoryseal.provenance_verify",
            str(path),
            "--publisher",
            publisher,
            "--memory-id",
            memory_id,
            "--entity-key",
            entity,
            "--event-type",
            "memory_quarantined",
            "--expected-owner",
            owner,
        ],
        input=json.dumps(private),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["matches"] is True
    assert content not in result.stdout + result.stderr
    assert private["commitment_salt"] not in result.stdout + result.stderr
