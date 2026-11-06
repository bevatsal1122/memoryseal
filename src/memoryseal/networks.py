"""Explicit per-request chain routing; never mutate process-wide network settings."""

from urllib.parse import urlsplit

from eth_utils import is_address
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator


class ChainConfig(BaseModel):
    chain_id: int = Field(gt=0, le=2**53 - 1, strict=True)
    name: str = Field(min_length=1, max_length=80)
    rpc_url: str
    registry: str
    executor: str

    @model_validator(mode="after")
    def valid(self):
        url = urlsplit(self.rpc_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))
        ):
            raise ValueError("chain RPC requires HTTPS or loopback HTTP")
        if not all(is_address(a) and int(a, 16) != 0 for a in (self.registry, self.executor)):
            raise ValueError("nonzero registry and executor required")
        return self


def configured_chains():
    from memoryseal.config import settings

    chains = {c.chain_id: c for c in settings.chains}
    if len(chains) != len(settings.chains):
        raise ValueError("duplicate configured chain ID")
    return chains


def network(chain_id=None):
    from types import SimpleNamespace

    from memoryseal.config import settings

    chains = configured_chains()
    if chain_id is not None and chain_id in chains:
        c = chains[chain_id]
        return SimpleNamespace(
            onchain_rpc_url=c.rpc_url,
            onchain_chain_id=c.chain_id,
            onchain_registry=c.registry,
            onchain_executor=c.executor,
        )
    if chain_id is not None and chain_id != settings.onchain_chain_id:
        raise HTTPException(404, "chain is not configured")
    return SimpleNamespace(
        **{
            k: getattr(settings, k)
            for k in ("onchain_rpc_url", "onchain_chain_id", "onchain_registry", "onchain_executor")
        }
    )


def public_networks():
    from memoryseal.config import settings

    rows = {
        c.chain_id: {
            "chain_id": c.chain_id,
            "name": c.name,
            "registry": c.registry,
            "executor": c.executor,
        }
        for c in configured_chains().values()
    }
    if settings.onchain_chain_id and settings.onchain_chain_id not in rows:
        rows[settings.onchain_chain_id] = {
            "chain_id": settings.onchain_chain_id,
            "name": "Default deployment",
            "registry": settings.onchain_registry,
            "executor": settings.onchain_executor,
        }
    return list(rows.values())
