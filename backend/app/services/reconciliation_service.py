import datetime
import hashlib
import logging
from typing import List, Dict, Tuple, Optional, Any
from app.schemas.canonical import CanonicalTransaction, AccountSummary, StatementResult

logger = logging.getLogger("statement2muster.reconciliation")

def reconcile_account(
    account_id: str,
    bank_name: str,
    transactions: List[CanonicalTransaction],
    opening_balance_cents: Optional[int] = None,
    closing_balance_cents: Optional[int] = None,
    files: Optional[List[str]] = None,
    client_entity_id: str = "default",
    warnings: Optional[List[str]] = None,
    force_discrepancy: bool = False,
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
        files=files or [],
        warnings=list(warnings or []),
    )

    currencies = {tx.currency for tx in transactions if tx.currency}
    if len(currencies) > 1:
        summary.reconciliation_status = "DISCREPANCY"
        logger.warning(
            f"Multiple currencies detected within account {account_id} ({currencies}). Marking as DISCREPANCY."
        )
        return summary

    if force_discrepancy:
        summary.reconciliation_status = "DISCREPANCY"
        if opening_balance_cents is not None:
            summary.calculated_closing_cents = opening_balance_cents + net_delta
            if closing_balance_cents is not None:
                summary.discrepancy_cents = summary.calculated_closing_cents - closing_balance_cents
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

def _segment_identity_signature(seg: Dict[str, Any]) -> str:
    if seg.get("segment_fingerprint"):
        return str(seg["segment_fingerprint"])
    tx_sigs = sorted(
        (
            t.booking_date.isoformat() if t.booking_date else "",
            t.value_date.isoformat() if t.value_date else "",
            int(t.amount_cents),
            (t.currency or "EUR").upper(),
            (t.description or "").strip(),
            (t.partner or "").strip(),
        )
        for t in (seg.get("txs") or [])
    )
    stmt_nums = sorted(tuple(x) for x in (seg.get("statement_numbers") or []))
    raw = repr((seg.get("opening_cents"), seg.get("closing_cents"), stmt_nums, tx_sigs))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _segment_date_bounds(seg: Dict[str, Any]) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
    dates = [
        (t.booking_date or t.value_date)
        for t in (seg.get("txs") or [])
        if (t.booking_date or t.value_date) is not None
    ]
    if not dates:
        return None, None
    return min(dates), max(dates)


def _find_valid_balance_chains(
    segments: List[Dict[str, Any]],
    max_solutions: int = 2,
    max_steps: int = 25000,
) -> Tuple[List[List[Dict[str, Any]]], bool]:
    """
    Finds valid chronological balance chains [s_0 -> s_1 -> ...] independent of upload order (R62-5 / R63-2).
    Uses O(N) undirected connectivity + directed Eulerian degree pruning before memoized DFS bounded by
    `max_steps`, guaranteeing bounded latency even on disconnected or adversarial 12+ segment batches.
    Returns (solutions, budget_exhausted).
    """
    n = len(segments)
    if n == 0:
        return [], False

    # O(N) graph construction, connectivity check & Eulerian degree check
    adj_undirected: Dict[int, set] = {}
    in_deg: Dict[int, int] = {}
    out_deg: Dict[int, int] = {}
    edges_from: Dict[int, List[int]] = {}
    nodes: set = set()

    for i, s in enumerate(segments):
        u = int(s["opening_cents"])
        v = int(s["closing_cents"])
        nodes.add(u)
        nodes.add(v)
        adj_undirected.setdefault(u, set()).add(v)
        adj_undirected.setdefault(v, set()).add(u)
        out_deg[u] = out_deg.get(u, 0) + 1
        in_deg[v] = in_deg.get(v, 0) + 1
        edges_from.setdefault(u, []).append(i)

    # Disconnected components -> Eulerian chain across all segments is impossible
    start_v = next(iter(nodes))
    visited_nodes = {start_v}
    q = [start_v]
    qi = 0
    while qi < len(q):
        cur = q[qi]
        qi += 1
        for nxt in adj_undirected.get(cur, ()):
            if nxt not in visited_nodes:
                visited_nodes.add(nxt)
                q.append(nxt)
    if len(visited_nodes) < len(nodes):
        return [], False

    # Eulerian path degree condition: every node has out==in, OR one start (out-in==1) & one end (in-out==1)
    start_nodes: List[int] = []
    end_nodes: List[int] = []
    for node in nodes:
        diff = out_deg.get(node, 0) - in_deg.get(node, 0)
        if diff == 1:
            start_nodes.append(node)
        elif diff == -1:
            end_nodes.append(node)
        elif diff != 0:
            return [], False
    if not ((len(start_nodes) == 1 and len(end_nodes) == 1) or (len(start_nodes) == 0 and len(end_nodes) == 0)):
        return [], False

    bounds = [_segment_date_bounds(s) for s in segments]
    candidate_starts = edges_from.get(start_nodes[0], []) if start_nodes else list(range(n))

    solutions: List[List[Dict[str, Any]]] = []
    dead_states: set = set()
    full_mask = (1 << n) - 1
    path: List[int] = []
    steps = 0
    budget_exhausted = False
    use_memo = n <= 30

    def dfs(used_mask: int, last_idx: int) -> bool:
        nonlocal steps, budget_exhausted
        if len(solutions) >= max_solutions or budget_exhausted:
            return False
        if used_mask == full_mask:
            solutions.append([segments[idx] for idx in path])
            return True
        if steps >= max_steps:
            budget_exhausted = True
            return False
        steps += 1
        state = (used_mask, last_idx)
        if use_memo and state in dead_states:
            return False

        prev_close = int(segments[last_idx]["closing_cents"])
        _, prev_max_d = bounds[last_idx]
        any_found = False
        for nxt in edges_from.get(prev_close, ()):
            bit = 1 << nxt
            if used_mask & bit:
                continue
            curr_min_d, _ = bounds[nxt]
            if prev_max_d is not None and curr_min_d is not None and prev_max_d > curr_min_d:
                continue
            path.append(nxt)
            if dfs(used_mask | bit, nxt):
                any_found = True
            path.pop()
            if len(solutions) >= max_solutions or budget_exhausted:
                break

        if not any_found and not budget_exhausted and len(solutions) < max_solutions and use_memo:
            dead_states.add(state)
        return any_found

    for s_idx in candidate_starts:
        if len(solutions) >= max_solutions or budget_exhausted:
            break
        path.append(s_idx)
        dfs(1 << s_idx, s_idx)
        path.pop()

    return solutions, budget_exhausted


def _chain_file_segments(
    segments: List[Dict[str, Any]],
) -> Tuple[Optional[int], Optional[int], Optional[str], bool, List[str]]:
    """
    Aggregates multiple file summaries for the same account instead of overwriting balances.
    Verifies internal balance, detects duplicate statements / gaps, and resolves chain order
    deterministically independent of upload order (R62-5).
    Returns (opening_cents, closing_cents, bank_name, has_discrepancy, extra_warnings).
    """
    bank_name = next((s.get("bank_name") for s in segments if s.get("bank_name")), "Unknown")
    warnings: List[str] = []

    if not segments:
        return None, None, bank_name, False, warnings

    if len(segments) == 1:
        seg = segments[0]
        return seg.get("opening_cents"), seg.get("closing_cents"), bank_name, False, warnings

    has_discrepancy = False

    # 1. Validate each individual file segment internal Solldoppik balance
    for seg in segments:
        o_c = seg.get("opening_cents")
        c_c = seg.get("closing_cents")
        seg_txs = seg.get("txs") or []
        fname = seg.get("file", "unbekannt")
        if o_c is not None and c_c is not None and seg_txs:
            seg_sum = sum(t.amount_cents for t in seg_txs)
            if o_c + seg_sum != c_c:
                has_discrepancy = True
                warnings.append(
                    f"Saldendifferenz in Datei '{fname}': Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein."
                )

    # 2. Detect duplicate statement numbers or identical duplicate statement payloads across files
    seen_stmt_nums = set()
    seen_fps = set()
    for seg in segments:
        fname = seg.get("file", "unbekannt")
        for y, num in (seg.get("statement_numbers") or []):
            key = (int(y), int(num))
            if key in seen_stmt_nums:
                has_discrepancy = True
                warnings.append(
                    f"Doppelter Auszug Nr. {int(num):03d}/{int(y)} in Multi-Datei-Batch ('{fname}')."
                )
            seen_stmt_nums.add(key)

        fp = _segment_identity_signature(seg)
        if fp in seen_fps:
            has_discrepancy = True
            warnings.append(
                f"Doppelte oder überlappende Auszugsdatei im Batch erkannt ('{fname}')."
            )
        seen_fps.add(fp)

    # 3. Require balances on either all segments or none
    any_missing_bal = any(
        seg.get("opening_cents") is None or seg.get("closing_cents") is None
        for seg in segments
    )
    any_present_bal = any(
        seg.get("opening_cents") is not None or seg.get("closing_cents") is not None
        for seg in segments
    )
    if any_missing_bal:
        if any_present_bal:
            has_discrepancy = True
            warnings.append(
                "Unvollständige Saldenkette im Multi-Datei-Batch: Mindestens eine Datei enthält keine Kontostände."
            )
        return None, None, bank_name, has_discrepancy, warnings

    # 4. Resolve chain order independent of upload order
    all_have_stmt_nums = all(bool(seg.get("statement_numbers")) for seg in segments)
    if all_have_stmt_nums:
        ordered = sorted(segments, key=lambda s: min(tuple(x) for x in s["statement_numbers"]))
        for idx in range(1, len(ordered)):
            prev_seg = ordered[idx - 1]
            curr_seg = ordered[idx]
            prev_max_key = max(tuple(x) for x in prev_seg["statement_numbers"])
            curr_min_key = min(tuple(x) for x in curr_seg["statement_numbers"])
            if prev_max_key[0] == curr_min_key[0] and prev_max_key[1] + 1 != curr_min_key[1]:
                has_discrepancy = True
                warnings.append(
                    f"Fehlende Auszugsnummer zwischen Nr. {prev_max_key[1]:03d}/{prev_max_key[0]} "
                    f"und Nr. {curr_min_key[1]:03d}/{curr_min_key[0]}."
                )
            if prev_seg["closing_cents"] != curr_seg["opening_cents"]:
                has_discrepancy = True
                warnings.append(
                    f"Saldensprung im Multi-Datei-Batch zwischen '{prev_seg.get('file')}' "
                    f"und '{curr_seg.get('file')}' (fehlender oder überlappender Auszug)."
                )
            _, prev_max_d = _segment_date_bounds(prev_seg)
            curr_min_d, _ = _segment_date_bounds(curr_seg)
            if prev_max_d is not None and curr_min_d is not None and prev_max_d > curr_min_d:
                has_discrepancy = True
                warnings.append(
                    f"Zeitliche Überlappung im Multi-Datei-Batch zwischen '{prev_seg.get('file')}' "
                    f"und '{curr_seg.get('file')}'."
                )
        return ordered[0]["opening_cents"], ordered[-1]["closing_cents"], bank_name, has_discrepancy, warnings

    chains, budget_exhausted = _find_valid_balance_chains(segments, max_solutions=2)
    if not budget_exhausted and len(chains) == 1:
        ordered = chains[0]
        return ordered[0]["opening_cents"], ordered[-1]["closing_cents"], bank_name, has_discrepancy, warnings

    has_discrepancy = True
    if budget_exhausted:
        warnings.append(
            "Saldenkette zu komplex oder mehrdeutig für automatische Rekonstruktion (Suchbudget erschöpft; bitte Auszüge mit Auszugsnummern hochladen)."
        )
    elif len(chains) > 1:
        warnings.append(
            "Mehrdeutige Auszugsreihenfolge im Multi-Datei-Batch: mehrere Saldenketten möglich."
        )
    else:
        warnings.append(
            "Saldensprung oder zeitliche Lücke im Multi-Datei-Batch (fehlender, vertauschter oder überlappender Auszug)."
        )
    return None, None, bank_name, has_discrepancy, warnings


def build_statement_result(
    request_id: str,
    tenant_id: str,
    transactions: List[CanonicalTransaction],
    account_balances: Dict[str, Any], # key -> (opening, closing, bank_name) OR list of segment dicts
    file_count: int,
    successful_files: int,
    unparsed_lines: Optional[List[dict]] = None,
    warnings: Optional[List[str]] = None,
    account_warnings: Optional[Dict[str, List[str]]] = None,
) -> StatementResult:
    """
    Aggregates transactions by account, performs reconciliation on each,
    and returns a complete StatementResult.
    """
    grouped: Dict[str, List[CanonicalTransaction]] = {}
    for tx in transactions:
        acc_key = f"{tx.client_entity_id}_{tx.account_id}" if tx.account_id else tx.client_entity_id
        grouped.setdefault(acc_key, []).append(tx)

    accounts_summary: Dict[str, AccountSummary] = {}
    statuses = []
    final_warnings: List[str] = list(warnings or [])

    for acc_key, txs in grouped.items():
        raw_bal = account_balances.get(acc_key)
        acc_warn = list((account_warnings or {}).get(acc_key, []))
        force_discrepancy = False

        if isinstance(raw_bal, list):
            opening, closing, bank_name, seg_disc, seg_warns = _chain_file_segments(raw_bal)
            force_discrepancy = seg_disc
            for w in seg_warns:
                if w not in acc_warn:
                    acc_warn.append(w)
        elif isinstance(raw_bal, tuple) and len(raw_bal) >= 3:
            opening, closing, bank_name = raw_bal[0], raw_bal[1], raw_bal[2]
        else:
            opening, closing, bank_name = (None, None, txs[0].bank_name if txs else "Unknown")

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
            client_entity_id=client_id,
            warnings=acc_warn,
            force_discrepancy=force_discrepancy,
        )
        accounts_summary[acc_key] = summary
        statuses.append(summary.reconciliation_status)
        for w in acc_warn:
            if w not in final_warnings:
                final_warnings.append(w)

    if any(s == "DISCREPANCY" for s in statuses):
        overall = "DISCREPANCY"
    elif all(s == "BALANCED" for s in statuses) and statuses:
        overall = "BALANCED"
    else:
        overall = "UNVERIFIED"

    if overall == "DISCREPANCY":
        disc_msg = "Buchungsdifferenz festgestellt: Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein."
        if disc_msg not in final_warnings:
            final_warnings.append(disc_msg)

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
