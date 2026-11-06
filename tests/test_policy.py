from datetime import UTC, datetime, timedelta

from memoryseal.models import Agent, Capability
from memoryseal.policy import evaluate


def test_spending_requires_current_scoped_capability():
    agent = Agent(id="finance", owner_address="owner", signing_address="finance", revoked=False)
    cap = Capability(
        id="c",
        agent_id="finance",
        operation="transfer",
        resource="USDC",
        max_amount=100,
        revoked=False,
        policy_version=1,
    )

    def check(amount, resource="USDC"):
        return evaluate(
            agent, [cap], operation="transfer", resource=resource, amount=amount, policy_version=1
        ).allowed

    assert check(100)
    assert not check(2000)
    assert not check(1, "ETH")
    assert not check(-1)
    assert not evaluate(
        agent,
        [cap],
        operation="transfer",
        resource="USDC",
        amount=1,
        policy_version=2,
        expected_version=1,
    ).allowed
    cap.revoked = True
    assert not check(1)


def test_expired_capability_and_revoked_agent_are_denied():
    agent = Agent(id="browser", owner_address="owner", signing_address="browser", revoked=False)
    cap = Capability(
        id="c",
        agent_id="browser",
        operation="write",
        resource="observations",
        revoked=False,
        policy_version=1,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    def check():
        return evaluate(
            agent, [cap], operation="write", resource="observations", policy_version=1
        ).allowed

    assert not check()
    cap.expires_at = None
    assert check()
    agent.revoked = True
    assert not check()
