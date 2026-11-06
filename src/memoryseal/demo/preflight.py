"""Check live-demo configuration without printing secrets or contacting services."""

import base64
import binascii
import json
import os

from eth_account import Account
from eth_utils import is_address

from memoryseal.attested_transport import verifier_configured
from memoryseal.bridge_transport import bridge_configured
from memoryseal.config import settings
from memoryseal.zero_g_provider_verifier import provider_verifier_configured
from memoryseal.zero_g_verification import valid_pins


def key_valid(value):
    try:
        return bool(value) and bool(Account.from_key(value).address)
    except (ValueError, TypeError):
        return False


def checks(config, env):
    try:
        encryption_ok = len(base64.b64decode(config.encryption_key or "", validate=True)) == 32
    except (ValueError, binascii.Error):
        encryption_ok = False
    demo_names = ("OWNER", "BROWSER", "RESEARCH", "FINANCE")
    demo_keys = [env.get(f"MEMORYSEAL_DEMO_{name}_KEY") for name in demo_names]
    valid_demo_keys = all(key_valid(key) for key in demo_keys)
    distinct = valid_demo_keys and len({Account.from_key(key).address for key in demo_keys}) == 4
    arkiv_key = config.arkiv_private_key.get_secret_value() if config.arkiv_private_key else None
    pins = (
        config.zero_g_provider_address,
        config.zero_g_tee_signer,
        config.zero_g_signature_base_url,
    )
    return {
        "local_encryption_key": encryption_ok,
        "ens_sepolia_configuration": bool(config.ens_rpc_url and config.ens_network == "sepolia"),
        "arkiv_publisher_key": key_valid(arkiv_key),
        "zero_g_router_configuration": bool(config.zero_g_api_key and config.zero_g_model),
        "gateway_connection_check_required": config.require_connection_attestation,
        "request_binding_verification_supported": False,
        "inference_path_permitted": (
            not config.zero_g_experimental_bridge
            and (
                not config.require_connection_attestation
                or verifier_configured(
                    config.connection_attestation_verifier,
                    config.connection_attestation_verifier_sha256,
                )
            )
        )
        or (
            config.zero_g_experimental_bridge
            and not config.require_connection_attestation
            and bridge_configured(
                config.zero_g_bridge_executable, config.zero_g_bridge_sha256, pins
            )
            and (
                not config.zero_g_provider_verifier
                or (
                    provider_verifier_configured(
                        config.zero_g_provider_verifier, config.zero_g_provider_verifier_sha256
                    )
                    and bool(config.zero_g_registry_rpc_url)
                )
            )
        ),
        "zero_g_provider_pins": valid_pins(*pins),
        "demo_memory_path_supported": not config.zero_g_experimental_bridge,
        "zero_g_registry_rpc": bool(config.zero_g_registry_rpc_url),
        "sepolia_observer_configuration": bool(
            config.onchain_rpc_url
            and config.onchain_chain_id == 11155111
            and is_address(config.onchain_registry or "")
            and int(config.onchain_registry, 16) != 0
            and is_address(config.onchain_executor or "")
            and int(config.onchain_executor, 16) != 0
        ),
        "demo_action_rpc": bool(env.get("MEMORYSEAL_DEMO_RPC_URL")),
        "distinct_demo_wallet_keys": bool(distinct),
    }


def main():
    result = checks(settings, os.environ)
    print(
        json.dumps(
            {
                "checks": result,
                "scope": "Configuration syntax and presence only; no network, funding, ownership, deployment, attestation or permission checks were performed.",
            },
            indent=2,
        )
    )
    if not all(result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
