"""Optional integration against official ENSv2 deployment artifacts on local PyEVM."""

import json
import os
from pathlib import Path

import pytest
from eth_abi import decode, encode
from eth_tester import EthereumTester
from eth_utils import keccak


@pytest.mark.skipif(not os.getenv("MEMORYSEAL_ENS_ARTIFACTS"), reason="ENS artifacts not supplied")
def test_official_registry_registration_and_token_roles():
    artifacts = Path(os.environ["MEMORYSEAL_ENS_ARTIFACTS"])
    chain = EthereumTester()
    owner, recipient = chain.get_accounts()[:2]
    zero = "0x" + "0" * 40

    def data(signature, types, args):
        return "0x" + (keccak(text=signature)[:4] + encode(types, args)).hex()

    def deploy(name, types, args):
        artifact = json.loads((artifacts / f"{name}.json").read_text())
        tx = chain.send_transaction(
            {
                "from": owner,
                "gas": 12_000_000,
                "data": artifact["bytecode"] + encode(types, args).hex(),
            }
        )
        receipt = chain.get_transaction_receipt(tx)
        assert receipt["status"] == 1
        return receipt["contract_address"]

    def read(to, signature, types, args, outputs):
        result = chain.call(
            {"from": owner, "to": to, "gas": 1_000_000, "data": data(signature, types, args)}
        )
        return decode(outputs, bytes.fromhex(result[2:]))

    store = deploy("LabelStore", ["address"], [zero])
    registry = deploy("RootRegistry", ["address", "address", "uint256"], [store, owner, 1])
    label = "browser"
    label_id = int.from_bytes(keccak(text=label), "big")
    assert read(registry, "getStatus(uint256)", ["uint256"], [label_id], ["uint8"])[0] == 0
    assert read(registry, "getExpiry(uint256)", ["uint256"], [label_id], ["uint64"])[0] == 0
    roles = (1 << 16) | (1 << 20) | (1 << 24) | (1 << 156)
    expiry = chain.get_block_by_number("latest")["timestamp"] + 86400
    tx = chain.send_transaction(
        {
            "from": owner,
            "to": registry,
            "gas": 1_000_000,
            "data": data(
                "register(string,address,address,address,uint256,uint64)",
                ["string", "address", "address", "address", "uint256", "uint64"],
                [label, owner, zero, zero, roles, expiry],
            ),
        }
    )
    assert chain.get_transaction_receipt(tx)["status"] == 1
    assert (
        read(registry, "findOwner(string)", ["string"], [label], ["address"])[0].lower()
        == owner.lower()
    )
    assert read(registry, "getStatus(uint256)", ["uint256"], [label_id], ["uint8"])[0] == 2
    assert read(
        registry,
        "hasRoles(uint256,uint256,address)",
        ["uint256", "uint256", "address"],
        [label_id, roles, owner],
        ["bool"],
    )[0]
    # Resolver-setting permission belongs to the owner, not an arbitrary account.
    for sender, expected in [(recipient, 0), (owner, 1)]:
        tx = chain.send_transaction(
            {
                "from": sender,
                "to": registry,
                "gas": 1_000_000,
                "data": data(
                    "setResolver(uint256,address)", ["uint256", "address"], [label_id, recipient]
                ),
            }
        )
        assert chain.get_transaction_receipt(tx)["status"] == expected
    assert (
        read(registry, "getResolver(string)", ["string"], [label], ["address"])[0].lower()
        == recipient.lower()
    )
    token_id = read(registry, "findTokenId(string)", ["string"], [label], ["uint256"])[0]
    tx = chain.send_transaction(
        {
            "from": owner,
            "to": registry,
            "gas": 1_000_000,
            "data": data(
                "safeTransferFrom(address,address,uint256,uint256,bytes)",
                ["address", "address", "uint256", "uint256", "bytes"],
                [owner, recipient, token_id, 1, b""],
            ),
        }
    )
    assert chain.get_transaction_receipt(tx)["status"] == 1
    assert (
        read(registry, "findOwner(string)", ["string"], [label], ["address"])[0].lower()
        == recipient.lower()
    )


@pytest.mark.skipif(not os.getenv("MEMORYSEAL_ENS_ARTIFACTS"), reason="ENS artifacts not supplied")
def test_official_resolver_delegation_scope_and_revocation():
    artifacts = Path(os.environ["MEMORYSEAL_ENS_ARTIFACTS"])
    chain = EthereumTester()
    owner, agent = chain.get_accounts()[:2]

    def calldata(signature, types, args):
        return "0x" + (keccak(text=signature)[:4] + encode(types, args)).hex()

    def deploy(name, types, args):
        artifact = json.loads((artifacts / f"{name}.json").read_text())
        tx = chain.send_transaction(
            {
                "from": owner,
                "gas": 15_000_000,
                "data": artifact["bytecode"] + encode(types, args).hex(),
            }
        )
        receipt = chain.get_transaction_receipt(tx)
        assert receipt["status"] == 1
        return receipt["contract_address"]

    def read(to, signature, types, args, outputs):
        result = chain.call(
            {"from": owner, "to": to, "gas": 1_000_000, "data": calldata(signature, types, args)}
        )
        return decode(outputs, bytes.fromhex(result[2:]))

    def send(sender, to, signature, types, args):
        tx = chain.send_transaction(
            {"from": sender, "to": to, "gas": 2_000_000, "data": calldata(signature, types, args)}
        )
        return chain.get_transaction_receipt(tx)

    factory = deploy("VerifiableFactory", [], [])
    implementation = deploy("PermissionedResolverImpl", ["address"], [owner])
    all_roles = int("11" * 32, 16)
    init = bytes.fromhex(
        calldata(
            "initialize((address,uint256)[],bytes[])",
            ["(address,uint256)[]", "bytes[]"],
            [[(owner, all_roles)], []],
        )[2:]
    )
    # eth_call predicts the CREATE2 proxy for this sender/salt; the transaction
    # then deploys it and the factory verifies the actual implementation.
    deploy_args = [implementation, 42, init]
    from eth_utils import to_checksum_address

    proxy = to_checksum_address(
        read(
            factory,
            "deployProxy(address,uint256,bytes)",
            ["address", "uint256", "bytes"],
            deploy_args,
            ["address"],
        )[0]
    )
    assert (
        send(
            owner,
            factory,
            "deployProxy(address,uint256,bytes)",
            ["address", "uint256", "bytes"],
            deploy_args,
        )["status"]
        == 1
    )
    assert (
        read(factory, "verifyContract(address)", ["address"], [proxy], ["address"])[0].lower()
        == implementation.lower()
    )
    setter = bytes.fromhex(
        calldata(
            "setText(bytes,string,string)",
            ["bytes", "string", "string"],
            [b"\x00", "memoryseal.config", ""],
        )[2:]
    )
    assert (
        send(
            owner, proxy, "grantSetterRoles(bytes,address)", ["bytes", "address"], [setter, agent]
        )["status"]
        == 1
    )
    name = b"\x07browser\x07example\x03eth\x00"
    sibling = b"\x07finance\x07example\x03eth\x00"
    assert (
        send(
            agent,
            proxy,
            "setText(bytes,string,string)",
            ["bytes", "string", "string"],
            [name, "memoryseal.config", "v1"],
        )["status"]
        == 1
    )
    assert (
        send(
            agent,
            proxy,
            "setText(bytes,string,string)",
            ["bytes", "string", "string"],
            [name, "other", "v1"],
        )["status"]
        == 0
    )
    # ENS grants this key across the resolver, not just the chosen name.
    assert (
        send(
            agent,
            proxy,
            "setText(bytes,string,string)",
            ["bytes", "string", "string"],
            [sibling, "memoryseal.config", "v1"],
        )["status"]
        == 1
    )
    resource = int.from_bytes(keccak(text="memoryseal.config"), "big")
    assert (
        send(
            owner,
            proxy,
            "revokeRoles(uint256,uint256,address)",
            ["uint256", "uint256", "address"],
            [resource, 1 << 4, agent],
        )["status"]
        == 1
    )
    assert (
        send(
            agent,
            proxy,
            "setText(bytes,string,string)",
            ["bytes", "string", "string"],
            [name, "memoryseal.config", "v2"],
        )["status"]
        == 0
    )
