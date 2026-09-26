"""
Backward compatibility proxy module re-exporting the canonical implementation from gpt_action.py.
"""
from app.api.endpoints.gpt_action import (
    router,
    gpt_download_cache,
    gpt_free_tier_tracker,
    STRIPE_LINKS,
    MAX_FREE_CONVERSIONS,
    parse_strict_date,
    normalize_currency,
    parse_amount_to_cents,
    GptTransactionItem,
    GptConvertRequest,
    FinancialSummary,
    FreeTierStatus,
    GptConvertResponse,
    resolve_verified_tenant,
    gpt_convert_statement,
    gpt_download_file
)

__all__ = [
    "router",
    "gpt_download_cache",
    "gpt_free_tier_tracker",
    "STRIPE_LINKS",
    "MAX_FREE_CONVERSIONS",
    "parse_strict_date",
    "normalize_currency",
    "parse_amount_to_cents",
    "GptTransactionItem",
    "GptConvertRequest",
    "FinancialSummary",
    "FreeTierStatus",
    "GptConvertResponse",
    "resolve_verified_tenant",
    "gpt_convert_statement",
    "gpt_download_file"
]
