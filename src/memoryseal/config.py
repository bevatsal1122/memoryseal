from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from memoryseal.networks import ChainConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORYSEAL_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    chains: list[ChainConfig] = Field(default_factory=list)

    @field_validator("chains")
    @classmethod
    def unique_chains(cls, value):
        if len({c.chain_id for c in value}) != len(value):
            raise ValueError("duplicate chain IDs")
        return value

    database_url: str = "sqlite:///./memoryseal.db"
    encryption_key: str | None = None
    max_clock_skew_seconds: int = 300
    request_audience: str = "memoryseal-local"
    dashboard_origins: str = "http://localhost:3000"
    zero_g_api_key: SecretStr | None = None
    zero_g_model: str | None = None
    zero_g_network: Literal["testnet", "mainnet"] = "testnet"
    zero_g_trust_mode: Literal["private", "router_default"] = "private"
    zero_g_experimental_bridge: bool = False
    zero_g_bridge_executable: str | None = None
    zero_g_bridge_sha256: str | None = None
    zero_g_provider_verifier: str | None = None
    zero_g_provider_verifier_sha256: str | None = None
    require_connection_attestation: bool = True
    allow_unbound_inference: bool = False
    connection_attestation_verifier: str | None = None
    connection_attestation_verifier_sha256: str | None = None
    zero_g_provider_address: str | None = None
    zero_g_tee_signer: str | None = None
    zero_g_signature_base_url: str | None = None
    zero_g_registry_rpc_url: str | None = None
    onchain_rpc_url: str | None = None
    onchain_chain_id: int | None = None
    onchain_executor: str | None = None
    onchain_registry: str | None = None
    require_onchain_memory: bool = False
    arkiv_private_key: SecretStr | None = None
    arkiv_creator_address: str | None = None
    arkiv_access_key: SecretStr | None = None
    ens_rpc_url: str | None = None
    ens_network: str | None = None


settings = Settings()
