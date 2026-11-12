import re
import datetime
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from fastapi import HTTPException, status

from app.schemas.canonical import CanonicalTransaction, StatementResult
from app.exporters.datev import export_to_datev_csv
from app.exporters.bmd import export_to_bmd_csv
from app.exporters.bmd_bankauszug import export_to_bmd_bankauszug_csv
from app.exporters.muster_csv import export_to_muster_csv

ACCOUNT_CODE_PATTERN = re.compile(r"^[0-9]{3,9}$")


def validate_account_code(
    raw_value: Optional[str],
    field_name: str = "default_bank_account",
    default: Optional[str] = None,
) -> str:
    """Validates DACH SKR03/SKR04/BMD numeric account code (R62-7)."""
    if raw_value is None or not str(raw_value).strip():
        if default is not None:
            return default
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Fehlender Kontocode in '{field_name}'.",
        )
    cleaned = str(raw_value).strip()
    if not ACCOUNT_CODE_PATTERN.fullmatch(cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ungültiges Kontofeld '{field_name}': Erwartet wird eine 3- bis 9-stellige Ziffernfolge (z.B. 1200 oder 2800).",
        )
    return cleaned


@dataclass(frozen=True)
class ExportFormatSpec:
    canonical_id: str
    ui_label: str
    media_type: str
    encoding: str
    filename: str
    requires_single_year: bool = False
    requires_eur_only: bool = False


FORMAT_SPECS: Dict[str, ExportFormatSpec] = {
    "json": ExportFormatSpec(
        canonical_id="json",
        ui_label="JSON Canonical",
        media_type="application/json",
        encoding="utf-8",
        filename="Statement2Muster.json",
    ),
    "datev": ExportFormatSpec(
        canonical_id="datev",
        ui_label="DATEV — EXTF Buchungsstapel",
        media_type="text/plain; charset=windows-1252",
        encoding="windows-1252",
        filename="EXTF_Buchungsstapel.csv",
        requires_single_year=True,
    ),
    "bmd_bankauszug": ExportFormatSpec(
        canonical_id="bmd_bankauszug",
        ui_label="BMD — Bankauszug CSV, 22 Spalten",
        media_type="text/csv; charset=utf-8",
        encoding="utf-8-sig",
        filename="BMD_Bankauszug_22.csv",
        requires_eur_only=True,
    ),
    "bmd": ExportFormatSpec(
        canonical_id="bmd",
        ui_label="BMD NTCS — bisheriges 8-Spalten-Profil",
        media_type="text/csv; charset=windows-1252",
        encoding="windows-1252",
        filename="BMD_Bankauszug.csv",
    ),
    "muster_csv": ExportFormatSpec(
        canonical_id="muster_csv",
        ui_label="Muster CSV (6 Spalten)",
        media_type="text/csv; charset=windows-1252",
        encoding="windows-1252",
        filename="Muster_Kontoauszug.csv",
    ),
}

FORMAT_ALIASES: Dict[str, str] = {
    "bmd_ntcs": "bmd",
}

ALLOWED_API_FORMATS = sorted(set(FORMAT_SPECS.keys()) | set(FORMAT_ALIASES.keys()))


def normalize_format_key(raw_format: Optional[str], default: str = "datev") -> str:
    """Normalizes format key & aliases before request hashing and cache lookup."""
    cleaned = (raw_format or "").lower().strip()
    if not cleaned:
        return default
    canonical = FORMAT_ALIASES.get(cleaned, cleaned)
    if canonical not in FORMAT_SPECS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{cleaned}'. Allowed formats: {ALLOWED_API_FORMATS}",
        )
    return canonical


def get_format_spec(canonical_format: str) -> ExportFormatSpec:
    if canonical_format not in FORMAT_SPECS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{canonical_format}'. Allowed formats: {ALLOWED_API_FORMATS}",
        )
    return FORMAT_SPECS[canonical_format]


def compute_export_blocks(
    result: StatementResult,
    canonical_format: Optional[str] = None,
) -> List[str]:
    """
    Computes blocking reasons preventing accounting export (shared across backend & export replay).
    Returns empty list if export is eligible.
    """
    blocks: List[str] = []
    txs = result.transactions or []

    if not txs:
        blocks.append("Keine Buchungssätze vorhanden.")
        return blocks

    if result.unparsed_lines:
        unparsed_names = [str(f.get("file", "unbekannt")) for f in result.unparsed_lines]
        blocks.append(
            f"Batch enthält nicht erkannte oder unvollständige Dateien: {unparsed_names}."
        )

    if result.overall_reconciliation == "DISCREPANCY":
        blocks.append(
            "Saldenabweichung (DISCREPANCY) festgestellt: Anfangssaldo + Umsätze stimmt nicht mit Endsaldo überein."
        )

    has_tx_errors = any(t.validation_status == "ERROR" for t in txs)
    if has_tx_errors:
        blocks.append("Mindestens eine Buchung enthält einen Validierungsfehler.")

    missing_booking_dates = any(t.booking_date is None for t in txs)
    if missing_booking_dates:
        blocks.append(
            "Fehlendes Buchungsdatum (nur Valutadatum vorhanden). Bitte Modus 'Valutadatum als Buchungsdatum' ausdrücklich aktivieren, falls zulässig."
        )

    distinct_accounts = {t.account_id for t in txs if t.account_id}
    if len(distinct_accounts) > 1:
        blocks.append(
            f"Gemischte Bankkonten erkannt ({sorted(distinct_accounts)}). Buchhaltungsexport erfordert genau ein Konto."
        )

    distinct_currencies = {t.currency for t in txs if t.currency}
    if len(distinct_currencies) > 1:
        blocks.append(
            f"Gemischte Währungen erkannt ({sorted(distinct_currencies)}). Buchhaltungsexport erfordert genau eine Währung."
        )

    invalid_contra = [
        str(t.contra_account)
        for t in txs
        if t.contra_account and not ACCOUNT_CODE_PATTERN.fullmatch(str(t.contra_account).strip())
    ]
    if invalid_contra:
        blocks.append(
            "Ungültiges Gegenkonto (contra_account): Erwartet wird eine 3- bis 9-stellige Ziffernfolge."
        )

    if canonical_format:
        spec = get_format_spec(canonical_format)
        if spec.requires_eur_only and any((t.currency or "").upper() != "EUR" for t in txs):
            non_eur = sorted({(t.currency or "?") for t in txs if (t.currency or "").upper() != "EUR"})
            blocks.append(
                f"Format 'bmd_bankauszug' unterstützt im aktuellen Stand nur EUR-Kontowährung (gefunden: {non_eur})."
            )
        if spec.requires_single_year:
            distinct_years = {t.booking_date.year for t in txs if t.booking_date}
            if len(distinct_years) > 1:
                blocks.append(
                    f"Mehrere Geschäftsjahre erkannt ({sorted(distinct_years)}). DATEV EXTF erfordert ein einzelnes Wirtschaftsjahr."
                )

    return blocks


def validate_accounting_export(result: StatementResult, canonical_format: str) -> None:
    """Enforces accounting export gates cleanly (raises HTTP 422 on any block)."""
    if canonical_format == "json":
        return
    blocks = compute_export_blocks(result, canonical_format=canonical_format)
    if blocks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Export blocked: {' '.join(blocks)} Use format=json to inspect details.",
        )


def render_export_bytes(
    transactions: List[CanonicalTransaction],
    canonical_format: str,
    default_bank_account: str = "1200",
    export_timestamp: Optional[datetime.datetime] = None,
) -> bytes:
    """Serializes CanonicalTransactions into the requested canonical export bytes."""
    validated_bank_account = validate_account_code(default_bank_account, "default_bank_account", default="1200")
    for tx in transactions:
        if tx.contra_account:
            validate_account_code(tx.contra_account, "contra_account")

    if canonical_format == "bmd_bankauszug":
        return export_to_bmd_bankauszug_csv(transactions)
    elif canonical_format == "bmd":
        bmd_account = validated_bank_account if validated_bank_account != "1200" else "2800"
        return export_to_bmd_csv(transactions, default_bank_account=bmd_account)
    elif canonical_format == "muster_csv":
        return export_to_muster_csv(transactions)
    elif canonical_format == "datev":
        return export_to_datev_csv(
            transactions,
            default_bank_account=validated_bank_account,
            export_timestamp=export_timestamp,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported export format '{canonical_format}'.",
        )
