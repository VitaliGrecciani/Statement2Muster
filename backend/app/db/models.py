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
