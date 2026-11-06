import base64

from eth_account import Account
from pydantic import SecretStr

from memoryseal.config import Settings
from memoryseal.demo.preflight import checks


def test_preflight_checks_are_boolean_and_do_not_expose_keys():
    config = Settings(
        _env_file=None,
        encryption_key=base64.b64encode(b"x" * 32).decode(),
        arkiv_private_key=SecretStr("invalid"),
        ens_rpc_url="https://rpc.example",
        ens_network="sepolia",
        onchain_rpc_url="https://rpc.example",
        onchain_chain_id=11155111,
        onchain_registry="0x" + "0" * 40,
        onchain_executor="0x" + "1" * 40,
    )
    key = Account.create().key.hex()
    env = {
        f"MEMORYSEAL_DEMO_{name}_KEY": key for name in ("OWNER", "BROWSER", "RESEARCH", "FINANCE")
    }
    result = checks(config, env)
    assert result["local_encryption_key"] is True
    assert result["ens_sepolia_configuration"] is True
    assert result["arkiv_publisher_key"] is False
    assert result["sepolia_observer_configuration"] is False
    assert result["distinct_demo_wallet_keys"] is False
    assert result["request_binding_verification_supported"] is False
    assert all(isinstance(value, bool) for value in result.values())
    assert key not in str(result)


def test_preflight_fails_closed_for_experimental_bridge_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr("memoryseal.bridge_transport.importlib.util.find_spec", lambda _: object())
    binary = tmp_path / "bridge"
    binary.write_text("placeholder")
    binary.chmod(0o700)
    config = Settings(
        _env_file=None,
        zero_g_experimental_bridge=True,
        require_connection_attestation=False,
        zero_g_bridge_executable=str(binary),
        zero_g_bridge_sha256="a" * 64,
        zero_g_provider_address="0x" + "1" * 40,
        zero_g_tee_signer="0x" + "2" * 40,
        zero_g_signature_base_url="https://provider.example",
    )
    assert checks(config, {})["inference_path_permitted"] is True
    assert checks(config, {})["gateway_connection_check_required"] is False
    assert checks(config, {})["demo_memory_path_supported"] is False
    monkeypatch.setattr("memoryseal.bridge_transport.importlib.util.find_spec", lambda _: None)
    assert checks(config, {})["inference_path_permitted"] is False
    monkeypatch.setattr("memoryseal.bridge_transport.importlib.util.find_spec", lambda _: object())
    config.zero_g_bridge_sha256 = None
    assert checks(config, {})["inference_path_permitted"] is False
    config.zero_g_bridge_sha256 = "a" * 64
    config.require_connection_attestation = True
    assert checks(config, {})["inference_path_permitted"] is False
    assert checks(config, {})["gateway_connection_check_required"] is True
