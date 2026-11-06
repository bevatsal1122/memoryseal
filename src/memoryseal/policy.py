"""Deterministic capability checks; memory content is never an authority input."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from memoryseal.models import Agent, Capability


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    policy_version: int


def evaluate(
    agent: Agent,
    capabilities: Iterable[Capability],
    *,
    operation: str,
    resource: str,
    policy_version: int,
    expected_version: int | None = None,
    amount: int | None = None,
    at: datetime | None = None,
) -> Decision:
    """Evaluate an exact operation and resource against the owner's current policy.

    Amounts are integer base units. A spend limit applies per action; cumulative
    budgets require a separate atomic accounting mechanism.
    """
    if expected_version is not None and expected_version != policy_version:
        return Decision(False, "stale policy version", policy_version)
    if agent.revoked:
        return Decision(False, "agent revoked", policy_version)
    if operation == "transfer" and amount is None:
        return Decision(False, "transfer amount required", policy_version)
    if amount is not None and (type(amount) is not int or not 0 < amount < 2**256):
        return Decision(False, "amount must be a positive uint256", policy_version)
    instant = at or datetime.now(UTC)
    for capability in capabilities:
        if (
            capability.agent_id != agent.id
            or capability.revoked
            or capability.operation != operation
            or capability.resource != resource
        ):
            continue
        expiry = capability.expires_at
        if expiry is not None:
            # SQLite returns naive UTC datetimes despite timezone=True.
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= instant:
                continue
        if amount is not None and (capability.max_amount is None or amount > capability.max_amount):
            continue
        return Decision(True, "capability permits operation", policy_version)
    return Decision(False, "no valid capability permits operation", policy_version)
