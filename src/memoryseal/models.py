from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from memoryseal.db import Base


def now() -> datetime:
    return datetime.now(UTC)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("owner_address", "signing_address"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_address: Mapped[str] = mapped_column(String, index=True)
    signing_address: Mapped[str] = mapped_column(String, index=True)
    policy_chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    ens_name: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Uint256Text(TypeDecorator):
    """Store uint256 values as decimal text without SQLite numeric coercion."""

    impl = String(78)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**256:
            raise ValueError("invalid uint256 amount")
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        amount = int(value)
        if not 0 < amount < 2**256:
            raise ValueError("invalid stored uint256 amount")
        return amount


class Capability(Base):
    __tablename__ = "capabilities"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    operation: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    max_amount: Mapped[int | None] = mapped_column("max_amount_text", Uint256Text(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_version: Mapped[int] = mapped_column(Integer)


class PolicyState(Base):
    __tablename__ = "policy_state"
    owner_address: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)


class AcceptanceRule(Base):
    __tablename__ = "acceptance_rules"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    namespace: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String, default="strict")


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("uq_memory_agent_request_id", "agent_id", "request_id", unique=True),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_address: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    namespace: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    source_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    source_reference_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    category: Mapped[str] = mapped_column(String)
    trust_class: Mapped[str] = mapped_column(String, default="untrusted")
    status: Mapped[str] = mapped_column(String)
    inference_status: Mapped[str] = mapped_column(String, default="not_configured")
    inference_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    analysis_json: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    owner_review_commitment: Mapped[str | None] = mapped_column(String, nullable=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    encryption_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    commitment: Mapped[str] = mapped_column(String)
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id"), nullable=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Nonce(Base):
    __tablename__ = "nonces"
    __table_args__ = (UniqueConstraint("address", "nonce"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String)
    nonce: Mapped[str] = mapped_column(String)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_address: Mapped[str] = mapped_column(String, index=True)
    actor_address: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProvenanceOutbox(Base):
    __tablename__ = "provenance_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    event_type: Mapped[str] = mapped_column(String, default="memory_created")
    payload: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="pending")
    creator_address: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    publishing_started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_check_at: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    check_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    entity_key: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_address: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    address: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String)


class EncryptionIdentity(Base):
    __tablename__ = "encryption_identities"
    address: Mapped[str] = mapped_column(String, primary_key=True)
    public_key: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String)


class VaultNamespace(Base):
    __tablename__ = "vault_namespaces"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_address: Mapped[str] = mapped_column(String, index=True)
    namespace: Mapped[str] = mapped_column(String)
    __table_args__ = (UniqueConstraint("owner_address", "namespace"),)
    active_version: Mapped[int] = mapped_column(Integer, default=1)


class VaultEpoch(Base):
    __tablename__ = "vault_epochs"
    namespace_id: Mapped[str] = mapped_column(ForeignKey("vault_namespaces.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String)
    envelopes_json: Mapped[str] = mapped_column(String)
    manifest_json: Mapped[str] = mapped_column(String)
    signature: Mapped[str] = mapped_column(String)


class VaultRecord(Base):
    __tablename__ = "vault_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    namespace_id: Mapped[str] = mapped_column(ForeignKey("vault_namespaces.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    key_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    envelope_json: Mapped[str] = mapped_column(String)
    original_digest: Mapped[str] = mapped_column(String)
    commitment: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="quarantined")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class VaultOutbox(Base):
    __tablename__ = "vault_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("vault_records.id"), index=True)
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="pending")
    creator_address: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    publishing_started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_check_at: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    check_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    entity_key: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BrowserCredential(Base):
    __tablename__ = "browser_credentials"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    address: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String)
    audience: Mapped[str] = mapped_column(String)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)


class SetupReceipt(Base):
    __tablename__ = "setup_receipts"
    owner_address: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    digest: Mapped[str] = mapped_column(String)
    result_json: Mapped[str] = mapped_column(String)
