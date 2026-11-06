"""LangGraph-compatible nodes for gateway-enforced memory operations.

These synchronous callables bind the agent, namespace and source type outside
untrusted graph state. They do not enforce access to tools outside the gateway.
"""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from memoryseal.client import MemorySealClient


@dataclass(frozen=True)
class MemoryNodes:
    client: MemorySealClient
    agent_id: str
    namespace: str
    source_type: Literal["agent", "external"]

    def __post_init__(self):
        UUID(self.agent_id)
        if not self.namespace or len(self.namespace) > 128:
            raise ValueError("A namespace of 1–128 characters is required")
        if self.source_type not in ("agent", "external"):
            raise ValueError("Unsupported source type")

    def write(self, state: dict[str, Any]) -> dict[str, Any]:
        """Write state content using a caller-supplied stable UUID for safe retry."""
        content = state["memory_content"]
        request_id = str(UUID(state["memory_request_id"]))
        if not isinstance(content, str):
            raise TypeError("memory_content must be text")
        result = self.client.write_memory(
            self.agent_id,
            self.namespace,
            content,
            source_type=self.source_type,
            source_reference=state.get("memory_source_reference"),
            parent_id=state.get("memory_parent_id"),
            request_id=request_id,
        )
        return {"memory_write": result}

    def read(self, state: dict[str, Any]) -> dict[str, Any]:
        """Read one page; follow next_offset even when a page is empty."""
        result = self.client.read_memory_page(
            self.agent_id,
            self.namespace,
            offset=state.get("memory_offset", 0),
            limit=state.get("memory_limit", 100),
        )
        return {"memory_page": result}
