import json

from memoryseal.models import Memory
from memoryseal.provenance import memory_created


def test_public_projection_excludes_private_fields():
    memory = Memory(
        id="m",
        owner_address="owner",
        agent_id="agent",
        namespace="private-namespace",
        source_type="external",
        source_reference="https://private.example/secret",
        category="other",
        trust_class="untrusted",
        status="quarantined",
        ciphertext=b"secret-ciphertext",
        encryption_nonce=b"nonce",
        salt=b"secret-salt",
        commitment="commitment",
        policy_version=2,
    )
    entry = memory_created(memory, agent_address="0x" + "1" * 40)
    assert entry.state == "pending"
    assert json.loads(entry.payload)["commitment"] == "commitment"
    assert json.loads(entry.payload)["schema"] == "memoryseal.memory-event.v3"
    assert json.loads(entry.payload)["source_type"] == "external"
    assert json.loads(entry.payload)["agent_address"] == "0x" + "1" * 40
    for value in ("private-namespace", "private.example", "secret-ciphertext", "secret-salt"):
        assert value not in entry.payload
