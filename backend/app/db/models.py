import datetime
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.session import Base

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

class AuthChallenge(Base):
    """Secure one-time verification code / challenge for identity verification (A01)."""
    __tablename__ = "auth_challenges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), index=True, nullable=False)
    code = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0, nullable=False) # 0 = false, 1 = true
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    version = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    entitlements = relationship("Entitlement", back_populates="tenant", cascade="all, delete-orphan")
    usage_reservations = relationship("UsageReservation", back_populates="tenant", cascade="all, delete-orphan")


class CustomerMapping(Base):
    __tablename__ = "customer_mappings"

    tenant_id = Column(String(36), ForeignKey("tenants.id"), primary_key=True)
    stripe_customer_id = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PlanCatalog(Base):
    __tablename__ = "plan_catalog"

    plan_code = Column(String(50), primary_key=True) # trial, starter, pro, lifetime
    stripe_price_id = Column(String(255), nullable=True)
    name = Column(String(100), nullable=False)
    quota_files_per_period = Column(Integer, nullable=True) # None = unlimited


class Entitlement(Base):
    __tablename__ = "entitlements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True, nullable=False)
    plan_code = Column(String(50), nullable=True)
    status = Column(String(50), default="active", nullable=False) # active, past_due, canceled
    source_type = Column(String(50), nullable=False) # subscription, one_time, trial
    source_id = Column(String(255), nullable=True) # stripe subscription ID or checkout session ID
    payment_intent = Column(String(255), nullable=True, index=True) # stripe payment_intent ID
    valid_until = Column(DateTime, nullable=True) # Null for Lifetime or active auto-renew
    current_period_start = Column(DateTime, nullable=True) # Start of authoritative billing cycle (Section 3)
    has_authoritative_period = Column(Integer, default=0, nullable=False) # 1 if bounds verified from invoice/subscription, 0 if provisional
    last_event_created_at = Column(Integer, default=0, nullable=True) # Unix timestamp of latest processed Stripe subscription event (S03)
    last_invoice_event_created_at = Column(Integer, default=0, nullable=True) # Unix timestamp of latest processed Stripe invoice event (Decision 36)
    last_invoice_id = Column(String(255), nullable=True) # Stripe invoice ID for authoritative reconciliation
    last_invoice_status = Column(String(50), nullable=True) # paid, payment_failed
    paid_through = Column(DateTime, nullable=True) # Actual paid-through timestamp from invoice.paid (Decision 34 Point 4)
    provisional_deadline = Column(DateTime, nullable=True) # Expiration deadline for unconfirmed provisional access (Decision 34 Point 2)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="entitlements")


class StripeEventInbox(Base):
    """Guarantees webhook idempotency (ADR-001)."""
    __tablename__ = "stripe_event_inbox"

    event_id = Column(String(255), primary_key=True)
    event_type = Column(String(100), nullable=False)
    status = Column(String(50), default="processed", nullable=False)
    processed_at = Column(DateTime, default=utcnow, nullable=False)


class UsageReservation(Base):
    """Atomic two-phase commit ledger for statement conversion quota."""
    __tablename__ = "usage_reservations"

    reservation_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True, nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=True) # SHA-256 of request payload
    units = Column(Integer, nullable=False) # Number of files
    status = Column(String(50), default="RESERVED", nullable=False) # RESERVED, COMMITTED, RELEASED
    created_at = Column(DateTime, default=utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="usage_reservations")

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_idempotency"),
        Index("idx_tenant_idempotency", "tenant_id", "idempotency_key"),
    )


class RevokedToken(Base):
    """Stores revoked RS256 Bearer JWTs (C02 / ADR-001)."""
    __tablename__ = "revoked_tokens"

    token_hash = Column(String(64), primary_key=True) # SHA-256 of the token
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, default=utcnow, nullable=False)


class AuthRateLimit(Base):
    """Persistent rate limiting and lockout state across workers and restarts (C04)."""
    __tablename__ = "auth_rate_limits"

    email = Column(String(255), primary_key=True)
    failed_attempts = Column(Integer, default=0, nullable=False)
    lockout_until = Column(DateTime, nullable=True)
    request_count = Column(Integer, default=0, nullable=False)
    window_start = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, nullable=False)



class SocialIdentity(Base):
    """Provider subject bound to a locally verified tenant."""
    __tablename__ = "social_identities"
    provider = Column(String(32), primary_key=True)
    subject = Column(String(255), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PendingSocialLink(Base):
    """Short-lived first-login challenge; email OTP is required before linking."""
    __tablename__ = "pending_social_links"
    token_hash = Column(String(64), primary_key=True)
    provider = Column(String(32), nullable=False)
    subject = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class KanzleiInvite(Base):
    """Single-use invitation bound to an email address."""
    __tablename__ = "kanzlei_invites"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    redeemed_at = Column(DateTime, nullable=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
