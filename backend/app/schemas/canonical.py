import datetime
import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, computed_field

class CanonicalTransaction(BaseModel):
    """
    Canonical Transaction Model (ADR-001 Section 7 & Audit Section 6.4).
    Enforces strict typing, integer cents to prevent float drift,
    and ISO currency isolation.
    """
    transaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    client_entity_id: str = "default"
    account_id: str = ""
    bank_name: str = "Unknown"
    source_file_id: str = ""
    source_row_page: str = ""
    booking_date: Optional[datetime.date] = None
    value_date: Optional[datetime.date] = None
    amount_cents: int  # Negative for debit/expense, positive for credit/revenue
    currency: str = "EUR"
    description: str = ""
    reference: str = ""
    contra_account: Optional[str] = None
    validation_status: Literal["VALID", "AMBIGUOUS", "ERROR"] = "VALID"
    warnings: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def signed_amount(self) -> str:
        """String representation with decimal comma, e.g. -12,34 or 12,34"""
        sign = "-" if self.amount_cents < 0 else ""
        abs_cents = abs(self.amount_cents)
        euros = abs_cents // 100
        cents = abs_cents % 100
        return f"{sign}{euros},{cents:02d}"

    @computed_field
    @property
    def signed_amount_dot(self) -> str:
        """Standard decimal dot string representation, e.g. -12.34"""
        sign = "-" if self.amount_cents < 0 else ""
        abs_cents = abs(self.amount_cents)
        euros = abs_cents // 100
        cents = abs_cents % 100
        return f"{sign}{euros}.{cents:02d}"

    @computed_field
    @property
    def decimal_amount(self) -> Decimal:
        return Decimal(self.amount_cents) / Decimal(100)

    @computed_field
    @property
    def soll_haben_kennzeichen(self) -> str:
        """
        DATEV Standard for active bank account (e.g. SKR03/SKR04 Konto 1200/1800):
        Incoming money (Gutschrift / positive amount >= 0) increases the bank balance: 'S' (Soll).
        Outgoing money (Lastschrift / negative amount < 0) decreases the bank balance: 'H' (Haben).
        Ref: DATEV Hilfe-Center Dok.-Nr. 1070387 / Dok.-Nr. 1035899.
        """
        return "S" if self.amount_cents >= 0 else "H"

    @computed_field
    @property
    def abs_amount_str(self) -> str:
        """Absolute amount with comma for DATEV Umsatz field, e.g. 12,34"""
        abs_cents = abs(self.amount_cents)
        euros = abs_cents // 100
        cents = abs_cents % 100
        return f"{euros},{cents:02d}"

class AccountSummary(BaseModel):
    """Account level reconciliation summary."""
    account_id: str
    bank_name: str
    client_entity_id: str = "default"
    opening_balance_cents: Optional[int] = None
    closing_balance_cents: Optional[int] = None
    calculated_closing_cents: Optional[int] = None
    turnover_debit_cents: int = 0
    turnover_credit_cents: int = 0
    reconciliation_status: Literal["BALANCED", "UNVERIFIED", "DISCREPANCY"] = "UNVERIFIED"
    discrepancy_cents: Optional[int] = None
    transaction_count: int = 0
    files: List[str] = Field(default_factory=list)

class StatementResult(BaseModel):
    """
    Validated conversion result across all processed statements.
    """
    request_id: str
    tenant_id: str
    transactions: List[CanonicalTransaction] = Field(default_factory=list)
    accounts: Dict[str, AccountSummary] = Field(default_factory=dict)
    total_files: int = 0
    successful_files: int = 0
    unparsed_lines: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    overall_reconciliation: Literal["BALANCED", "UNVERIFIED", "DISCREPANCY"] = "UNVERIFIED"
