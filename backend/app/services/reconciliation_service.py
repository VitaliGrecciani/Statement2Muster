import logging
from typing import List, Dict, Tuple, Optional
from app.schemas.canonical import CanonicalTransaction, AccountSummary, StatementResult

logger = logging.getLogger("statement2muster.reconciliation")

def reconcile_account(
    account_id: str,
    bank_name: str,
    transactions: List[CanonicalTransaction],
    opening_balance_cents: Optional[int] = None,
    closing_balance_cents: Optional[int] = None,
    files: Optional[List[str]] = None,
    client_entity_id: str = "default"
) -> AccountSummary:
    """
    Performs Solldoppik balance check for an account:
    Startsaldo + sum(Umsätze) == Endsaldo
    """
    turnover_debit = 0
    turnover_credit = 0

    for tx in transactions:
        if tx.amount_cents < 0:
            turnover_debit += abs(tx.amount_cents)
        else:
            turnover_credit += tx.amount_cents

    net_delta = turnover_credit - turnover_debit
    summary = AccountSummary(
        account_id=account_id,
        bank_name=bank_name,
        client_entity_id=client_entity_id,
        opening_balance_cents=opening_balance_cents,
        closing_balance_cents=closing_balance_cents,
        turnover_debit_cents=turnover_debit,
        turnover_credit_cents=turnover_credit,
        transaction_count=len(transactions),
        files=files or []
    )

    currencies = {tx.currency for tx in transactions if tx.currency}
    if len(currencies) > 1:
        summary.reconciliation_status = "DISCREPANCY"
        logger.warning(
            f"Multiple currencies detected within account {account_id} ({currencies}). Marking as DISCREPANCY."
        )
        return summary

    if opening_balance_cents is not None and closing_balance_cents is not None:
        calc_closing = opening_balance_cents + net_delta
        summary.calculated_closing_cents = calc_closing
        discrepancy = calc_closing - closing_balance_cents
        summary.discrepancy_cents = discrepancy

        if discrepancy == 0:
            summary.reconciliation_status = "BALANCED"
        else:
            summary.reconciliation_status = "DISCREPANCY"
            logger.warning(
                "Balance discrepancy detected during reconciliation check (reconciliation_status=DISCREPANCY)."
            )
    else:
        summary.reconciliation_status = "UNVERIFIED"

    return summary

def build_statement_result(
    request_id: str,
    tenant_id: str,
    transactions: List[CanonicalTransaction],
    account_balances: Dict[str, Tuple[Optional[int], Optional[int], str]], # key -> (opening, closing, bank_name)
    file_count: int,
    successful_files: int,
    unparsed_lines: Optional[List[dict]] = None,
    warnings: Optional[List[str]] = None
) -> StatementResult:
    """
    Aggregates transactions by account, performs reconciliation on each,
    and returns a complete StatementResult.
    """
    # Group transactions by account key (account_id or client_entity + account_id)
    grouped: Dict[str, List[CanonicalTransaction]] = {}
    for tx in transactions:
        acc_key = f"{tx.client_entity_id}_{tx.account_id}" if tx.account_id else tx.client_entity_id
        grouped.setdefault(acc_key, []).append(tx)

    accounts_summary: Dict[str, AccountSummary] = {}
    statuses = []

    for acc_key, txs in grouped.items():
        bal_info = account_balances.get(acc_key, (None, None, txs[0].bank_name if txs else "Unknown"))
        opening, closing, bank_name = bal_info
        files = list({tx.source_file_id for tx in txs if tx.source_file_id})
        client_id = txs[0].client_entity_id if txs else "default"
        acc_id = txs[0].account_id if txs else acc_key

        summary = reconcile_account(
            account_id=acc_id,
            bank_name=bank_name,
            transactions=txs,
            opening_balance_cents=opening,
            closing_balance_cents=closing,
            files=files,
            client_entity_id=client_id
        )
        accounts_summary[acc_key] = summary
        statuses.append(summary.reconciliation_status)

    if any(s == "DISCREPANCY" for s in statuses):
        overall = "DISCREPANCY"
    elif all(s == "BALANCED" for s in statuses) and statuses:
        overall = "BALANCED"
    else:
        overall = "UNVERIFIED"

    final_warnings = list(warnings or [])
    if overall == "DISCREPANCY":
        final_warnings.append("Buchungsdifferenz festgestellt: Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein.")

    return StatementResult(
        request_id=request_id,
        tenant_id=tenant_id,
        transactions=transactions,
        accounts=accounts_summary,
        total_files=file_count,
        successful_files=successful_files,
        unparsed_lines=unparsed_lines or [],
        warnings=final_warnings,
        overall_reconciliation=overall
    )
