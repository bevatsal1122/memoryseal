"""Small deterministic reference agents that use the public SDK."""

from dataclasses import dataclass

from memoryseal.client import MemorySealClient


@dataclass
class BrowserAgent:
    client: MemorySealClient
    agent_id: str

    def observe(self, text: str, source: str) -> dict:
        return self.client.write_memory(
            self.agent_id,
            "browser-observations",
            text,
            source_type="external",
            source_reference=source,
        )


@dataclass
class ResearchAgent:
    client: MemorySealClient
    agent_id: str

    def record(self, text: str) -> dict:
        return self.client.write_memory(self.agent_id, "research", text, source_type="agent")

    def recall(self) -> dict:
        return self.client.read_memory(self.agent_id, "research")


@dataclass
class FinanceAgent:
    client: MemorySealClient
    agent_id: str

    def transfer(self, amount: int, policy_version: int) -> dict:
        return self.client.simulate_transfer(self.agent_id, "USDC", amount, policy_version)
