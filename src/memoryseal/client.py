"""Python client for signed MemorySeal gateway requests."""

import base64
import binascii
import hmac
import json
import math
import re
import time
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
from eth_account import Account

from memoryseal.encryption import content_commitment
from memoryseal.http_limits import ResponseTooLarge, read_json_limited
from memoryseal.signatures import sign_request


def verify_memory_commitment(content: str, salt_base64: str, commitment: str) -> bool:
    """Check exact UTF-8 content against a private salt and public v1 commitment."""
    try:
        if (
            not isinstance(content, str)
            or not isinstance(salt_base64, str)
            or not isinstance(commitment, str)
        ):
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", commitment):
            return False
        salt = base64.b64decode(salt_base64, validate=True)
        return hmac.compare_digest(content_commitment(content.encode("utf-8"), salt), commitment)
    except (ValueError, UnicodeError, binascii.Error):
        return False


class MemoryWriteOutcomeUnknown(RuntimeError):
    """The gateway might have committed a write whose response was not received."""

    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__("Memory write may have committed; retry the same write using request_id.")


class MemorySealClient:
    def __init__(
        self, base_url: str, private_key: str, *, audience: str, transport=None, write_timeout=180.0
    ):
        if not math.isfinite(write_timeout) or write_timeout <= 0:
            raise ValueError("write timeout must be a finite positive number")
        try:
            url = urlsplit(base_url)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                raise ValueError("invalid gateway URL")
            # Accessing port also rejects malformed port syntax.
            _ = url.port
            if (
                url.scheme == "http"
                and url.hostname.lower() not in ("localhost", "127.0.0.1", "::1")
                and transport is None
            ):
                raise ValueError("remote gateway requires HTTPS")
        except (TypeError, AttributeError) as exc:
            raise ValueError("invalid gateway URL") from exc
        self._key = private_key
        self.address = Account.from_key(private_key).address
        self.audience = audience
        self.write_timeout = write_timeout
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=15.0)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _request(self, method: str, path: str, data: dict | None = None, *, timeout=15.0) -> dict:
        # Sign exactly the bytes transmitted; never retry a signed request automatically.
        body = (
            json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
            if data is not None
            else b""
        )
        fields = {
            "audience": self.audience,
            "method": method,
            "target": path,
            "body": body,
            "timestamp": int(time.time()),
            "nonce": uuid4().hex,
        }
        headers = {
            "content-type": "application/json",
            "x-memoryseal-address": self.address,
            "x-memoryseal-timestamp": str(fields["timestamp"]),
            "x-memoryseal-nonce": fields["nonce"],
            "x-memoryseal-signature": sign_request(self._key, **fields),
        }
        with self._http.stream(
            method, path, content=body, headers=headers, timeout=timeout
        ) as response:
            if not response.is_success:
                # Preserve useful gateway errors without buffering arbitrary bodies.
                error_body = bytearray()
                try:
                    for chunk in response.iter_bytes(chunk_size=16_384):
                        if len(error_body) + len(chunk) > 65_536:
                            error_body.clear()
                            break
                        error_body.extend(chunk)
                except httpx.HTTPError:
                    error_body.clear()
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in ("content-encoding", "content-length")
                }
                httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=bytes(error_body),
                    request=response.request,
                ).raise_for_status()
            return read_json_limited(response, max_bytes=24 * 1024 * 1024)

    def _post(self, path: str, data: dict, *, timeout=15.0) -> dict:
        return self._request("POST", path, data, timeout=timeout)

    def integration_readiness(self) -> dict:
        return self._request("GET", "/integrations/readiness")

    def list_agents(self) -> dict:
        return self._request("GET", "/agents")

    def agent_access(self) -> dict:
        return self._request("GET", "/agent-access")

    def list_capabilities(self) -> dict:
        return self._request("GET", "/capabilities")

    def list_memories(
        self,
        *,
        agent_id=None,
        namespace=None,
        status=None,
        memory_id=None,
        request_id=None,
        parent_id=None,
        offset=0,
        limit=100,
    ) -> dict:
        params = {"offset": offset, "limit": limit}
        params.update(
            {
                key: value
                for key, value in {
                    "agent_id": agent_id,
                    "namespace": namespace,
                    "status": status,
                    "memory_id": memory_id,
                    "request_id": str(UUID(request_id)) if request_id is not None else None,
                    "parent_id": parent_id,
                }.items()
                if value is not None
            }
        )
        return self._request("GET", "/memories?" + urlencode(params))

    def inspect_memory(self, memory_id: str) -> dict:
        return self._request("GET", f"/memories/{UUID(memory_id)}")

    def review_memory(
        self, memory_id: str, *, event_id: str, commitment: str, policy_version: int
    ) -> dict:
        """Explicitly approve a low-risk observation for sharing, not for taking actions."""
        return self._post(
            f"/memories/{UUID(memory_id)}/review-event",
            {
                "event_id": str(UUID(event_id)),
                "commitment": commitment,
                "policy_version": policy_version,
            },
        )

    def quarantine_memory(self, memory_id: str) -> dict:
        return self._post(f"/memories/{UUID(memory_id)}/quarantine", {})

    def quarantine_memory_signed(
        self, memory_id: str, *, event_id: str, commitment: str, policy_version: int
    ) -> dict:
        """Sign a quarantine event ID, current commitment and policy version."""
        if (
            not isinstance(commitment, str)
            or not re.fullmatch(r"[0-9a-f]{64}", commitment)
            or isinstance(policy_version, bool)
            or not isinstance(policy_version, int)
            or not 0 <= policy_version < 2**53
        ):
            raise ValueError("invalid quarantine event fields")
        return self._post(
            f"/memories/{UUID(memory_id)}/quarantine-event",
            {
                "event_id": str(UUID(event_id)),
                "commitment": commitment,
                "policy_version": policy_version,
            },
        )

    def author_commitment_salt(self, memory_id: str) -> dict:
        """Privately retrieve the commitment opening for a memory this agent wrote."""
        return self._post(f"/memories/{UUID(memory_id)}/author-commitment-salt", {})

    def attest_memory_origin_verified(
        self, memory_id: str, *, event_id: str, commitment: str, policy_version: int, content: str
    ) -> dict:
        """Check locally supplied content before signing the commitment acknowledgement."""
        opening = self.author_commitment_salt(memory_id)
        if (
            opening.get("id") != str(UUID(memory_id))
            or opening.get("commitment") != commitment
            or not verify_memory_commitment(content, opening.get("commitment_salt"), commitment)
        ):
            raise ValueError("memory commitment does not match the submitted content")
        return self.attest_memory_origin(
            memory_id, event_id=event_id, commitment=commitment, policy_version=policy_version
        )

    def attest_memory_origin(
        self, memory_id: str, *, event_id: str, commitment: str, policy_version: int
    ) -> dict:
        """Sign a public acknowledgement of a commitment supplied by the gateway."""
        if (
            not isinstance(commitment, str)
            or not re.fullmatch(r"[0-9a-f]{64}", commitment)
            or isinstance(policy_version, bool)
            or not isinstance(policy_version, int)
            or not 0 <= policy_version < 2**53
        ):
            raise ValueError("invalid origin attestation fields")
        return self._post(
            f"/memories/{UUID(memory_id)}/attest-origin",
            {
                "event_id": str(UUID(event_id)),
                "commitment": commitment,
                "policy_version": policy_version,
            },
        )

    def memory_provenance_events(self, memory_id: str) -> dict:
        return self._request("GET", f"/memories/{UUID(memory_id)}/provenance-events")

    def publish_memory_event(self, memory_id: str, event_id: str) -> dict:
        return self._request(
            "POST",
            f"/memories/{UUID(memory_id)}/provenance-events/{UUID(event_id)}/publish",
            {},
            timeout=90,
        )

    def reconcile_memory_event(self, memory_id: str, event_id: str) -> dict:
        return self._request(
            "POST",
            f"/memories/{UUID(memory_id)}/provenance-events/{UUID(event_id)}/reconcile",
            {},
            timeout=90,
        )

    def observe_memory_provenance_event(self, memory_id: str, event_id: str) -> dict:
        return self._request(
            "POST",
            f"/memories/{UUID(memory_id)}/provenance-events/{UUID(event_id)}/observe",
            {},
            timeout=70.0,
        )

    def observe_provenance(self, memory_id: str) -> dict:
        return self._request(
            "POST", f"/memories/{UUID(memory_id)}/observe-provenance", {}, timeout=70.0
        )

    def list_events(self) -> dict:
        return self._request("GET", "/events")

    def register_agent(self, signing_address: str, ens_name: str | None = None) -> dict:
        return self._post(
            "/agents/register", {"signing_address": signing_address, "ens_name": ens_name}
        )

    def revoke_agent(self, agent_id: str) -> dict:
        return self._post(f"/agents/{UUID(agent_id)}/revoke", {})

    def observe_ens(self, agent_id: str) -> dict:
        return self._post(f"/agents/{UUID(agent_id)}/observe-ens", {}, timeout=40.0)

    def grant(
        self,
        agent_id: str,
        operation: str,
        resource: str,
        *,
        max_amount: int | None = None,
        expires_at: str | None = None,
    ) -> dict:
        return self._post(
            "/capabilities/grant",
            {
                "agent_id": agent_id,
                "operation": operation,
                "resource": resource,
                "max_amount": str(max_amount) if max_amount is not None else None,
                "expires_at": expires_at,
            },
        )

    def revoke(self, capability_id: str) -> dict:
        return self._post(f"/capabilities/{UUID(capability_id)}/revoke", {})

    def write_memory(
        self,
        agent_id: str,
        namespace: str,
        content: str,
        *,
        source_type: str,
        source_reference: str | None = None,
        parent_id: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        request_id = str(UUID(request_id)) if request_id is not None else str(uuid4())
        try:
            result = self._post(
                "/memory/write",
                {
                    "agent_id": agent_id,
                    "namespace": namespace,
                    "content": content,
                    "source_type": source_type,
                    "source_reference": source_reference,
                    "parent_id": parent_id,
                    "request_id": request_id,
                },
                timeout=self.write_timeout,
            )
            if (
                not isinstance(result, dict)
                or result.get("request_id") != request_id
                or result.get("status") not in ("accepted", "quarantined")
                or not isinstance(result.get("lineage_eligible"), bool)
                or not isinstance(result.get("id"), str)
            ):
                raise MemoryWriteOutcomeUnknown(request_id)
            try:
                UUID(result["id"])
            except ValueError as exc:
                raise MemoryWriteOutcomeUnknown(request_id) from exc
            return result
        except (
            httpx.RequestError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ResponseTooLarge,
        ) as exc:
            raise MemoryWriteOutcomeUnknown(request_id) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 408 or exc.response.status_code >= 500:
                raise MemoryWriteOutcomeUnknown(request_id) from exc
            raise

    def read_memory_page(
        self, agent_id: str, namespace: str, *, offset: int = 0, limit: int = 100
    ) -> dict:
        """Read a bounded page; an empty page can still have a next offset."""
        if (
            type(offset) is not int
            or type(limit) is not int
            or offset < 0
            or offset > 2**63 - 101
            or not 1 <= limit <= 100
        ):
            raise ValueError("Invalid memory page request")
        page = self._post(
            "/memory/read",
            {"agent_id": agent_id, "namespace": namespace, "offset": offset, "limit": limit},
            timeout=45.0,
        )
        if not isinstance(page, dict):
            raise ValueError("Invalid memory page response")  # noqa: TRY004 - one protocol error
        records, next_offset = page.get("memories"), page.get("next_offset", ...)
        if (
            not isinstance(records, list)
            or len(records) > limit
            or any(not isinstance(record, dict) for record in records)
            or (
                next_offset is not None
                and (type(next_offset) is not int or next_offset != offset + limit)
            )
        ):
            raise ValueError("Invalid memory page response")
        return page

    def read_memory(self, agent_id: str, namespace: str) -> dict:
        """Read all pages for compatibility; use read_memory_page for bounded client memory."""
        memories = []
        offset = 0
        while True:
            page = self.read_memory_page(agent_id, namespace, offset=offset)
            memories.extend(page["memories"])
            next_offset = page["next_offset"]
            if next_offset is None:
                return {"memories": memories}
            offset = next_offset

    def simulate_transfer(
        self, agent_id: str, asset: str, amount: int, policy_version: int
    ) -> dict:
        return self._post(
            "/actions/simulate-transfer",
            {
                "agent_id": agent_id,
                "asset": asset,
                "amount": str(amount),
                "policy_version": policy_version,
            },
        )

    def observe_onchain_deployment(self) -> dict:
        return self._request("GET", "/onchain/observe-deployment", timeout=70.0)

    def observe_token_balance(self, *, token: str, recipient: str, block_number: int) -> dict:
        return self._post(
            "/actions/observe-token-balance",
            {"token": token, "recipient": recipient, "block_number": block_number},
            timeout=90.0,
        )

    def observe_onchain_grant(
        self,
        *,
        agent_id: str,
        transaction_hash: str,
        token: str,
        max_amount: int,
        expires_at: int,
        policy_version: int,
    ) -> dict:
        return self._post(
            "/actions/observe-onchain-grant",
            {
                "agent_id": agent_id,
                "transaction_hash": transaction_hash,
                "token": token,
                "max_amount": str(max_amount),
                "expires_at": expires_at,
                "policy_version": policy_version,
            },
            timeout=180.0,
        )

    def observe_onchain_transfer(
        self,
        *,
        agent_id: str,
        transaction_hash: str,
        token: str,
        recipient: str,
        amount: int,
        policy_version: int,
    ) -> dict:
        return self._post(
            "/actions/observe-onchain",
            {
                "agent_id": agent_id,
                "transaction_hash": transaction_hash,
                "token": token,
                "recipient": recipient,
                "amount": str(amount),
                "policy_version": policy_version,
            },
            timeout=180.0,
        )
