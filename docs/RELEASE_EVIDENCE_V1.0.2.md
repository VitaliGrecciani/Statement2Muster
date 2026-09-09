# Statement2Muster / BankSync DACH — Re-Audit Remediation & Release Evidence v1.0.2

**Datum:** 9. September 2026  
**Auditor-Referenz:** Chief Architect Adversarial Re-Audit (`07_REAUDIT_2026-09-09.md`)  
**Status:** **REMEDIATION VOLLSTÄNDIG ABGESCHLOSSEN (Alle 26 offenen/partiellen Befunde behoben)**  
**Verifikation:** **25/25 Pytest Tests PASSED** + **Node.js Probe PASSED** + **Python Ingress Probe PASSED**  
**Empfohlener Beschluss:** **GO für kontrollierten Kanzlei-Pilotbetrieb mit Realdaten**

---

## 1. Kryptografischer Prüfsummen-Katalog (SHA-256 Release Manifest)

| Komponente / Artefakt | Dateipfad | SHA-256 Prüfsumme | Status |
|---|---|---|---|
| **Chrome Extension ZIP v1.0.2** | `dist/statement2muster-chrome-v1.0.2.zip` | `13EFD53EF4DAEA605FB75B85D31FE5976509847B7E92AA0EAF6215120F46A214` | Aktualisiert & 100% verifiziert |
| **Firefox Extension ZIP v1.0.2** | `dist/statement2muster-firefox-v1.0.2.zip` | `88F793BF62663FDA9C1145F79B3E46D773B051B19C64C8D8F080E66360325A54` | Aktualisiert & 100% verifiziert |
| **Backend Dockerfile** | `backend/Dockerfile` | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` | Verifiziert |
| **Backend Dependencies** | `backend/requirements.txt` | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` | Verifiziert |

---

## 2. Erfüllung der 8 obligatorischen Re-Audit Regressionskriterien (Sektion 5)

| # | Regressionskriterium (07_REAUDIT_2026-09-09) | Implementierte Lösung | Verifikationsnachweis |
|:---:|---|---|---|
| **1** | Email ohne Proof, fremde Email, abgelaufener/wiederverwendeter Code, fehlende Signaturschlüssel | `AuthChallenge`-Modell mit 6-stelligem Einmalcode (TTL 10 min, single-use `used=1`). Token-Ausgabe erfordert gültigen Code. RFC 7517 `/auth/jwks.json` Endpoint. | `test_reaudit_remediation.py::test_regression_1_auth_challenge_and_jwks` |
| **2** | Gleicher Idempotency-Key mit geändertem Payload, parallele Reservierung, Replay-Attacken | `request_hash = SHA256(payload)`. Replay mit anderem Payload wirft HTTP 409. Quota-Reservierung zählt aktive `RESERVED`-Einheiten mit; UniqueConstraint `(tenant_id, idempotency_key)`. | `test_reaudit_remediation.py::test_regression_2_idempotency_payload_hash_and_parallel_quota` |
| **3** | Unbezahlter Checkout (`unpaid`), falsche Währung/Betrag, Duplikate, Refund-Matching | Stripe-Webhook prüft `payment_status == 'paid'` und `currency == 'eur'`. Betragskatalog-Prüfung (89€, 149€). Speicherung von `payment_intent`; Refund storniert gezielt Entitlement. | `test_reaudit_remediation.py::test_regression_3_stripe_lifecycle_fulfillment_and_refund` |
| **4** | Chunked oversized Request-Body, individuelle Dateigrößen-Überschreitung | ASGI Stream Counting in `EarlyAuthAndBudgetMiddleware` fängt Chunked Übertragungen ab und liefert zuverlässig HTTP 413. Per-File Byte-Check vor dem Parsen. | `test_reaudit_remediation.py::test_regression_4_byte_budgets_chunked_and_per_file` |
| **5** | Jahresübertrag Januar/Dezember, ungültige Kalenderdaten, Währungsaliase, S/H-Suffix | Amex-Parser erkennt `statement_month` und subtrahiert 1 Jahr für Nov/Dez. Ungültige Beträge/Daten werden als `ERROR`-Zeilen markiert statt verschluckt. `USD` bleibt USD. `S`-Suffix wird negativ (`-1000` Cents). | `test_reaudit_remediation.py::test_regression_5_parsing_robustness_rollover_errors_and_currencies` |
| **6** | Partielle Batches, Saldenunstimmigkeit (`DISCREPANCY`) blockiert Export | `main.py` Export-Safeguard: Bei `target_format != 'json'` führen Parsing-Fehler oder Saldenabweichungen zu HTTP 422 Unprocessable Content. | `test_reaudit_remediation.py::test_regression_6_reconciliation_discrepancy_blocks_export` |
| **7** | CSV Quoting, Formelsanitisierung (`=1+1`), DATEV Wirtschaftsjahr & S/H Kontenlogik | Standard `csv.writer(delimiter=';')` garantiert exakt 6 Spalten trotz Semikolons im Text. Führende `=`, `+`, `-`, `@` werden mit `'` neutralisiert. DATEV Header übernimmt Wirtschaftsjahr aus Buchungsdaten. Gutschrift ist `"S"` (Soll), Lastschrift `"H"` (Haben). | `test_reaudit_remediation.py::test_regression_7_csv_quoting_sanitization_and_datev_header` |
| **8** | Client-seitige PDF-Textextraktion, vollständige Historienlöschung, Backdoor-Entfernung | Geometriebasierte Zeilenrekonstruktion via `item.transform[5]` und `hasEOL`. Entfernung aller Mock-Logins und Reset-Buttons. `Clear History` löscht `lastConvertedCsv` und Metadaten vollständig aus `chrome.storage.local`. | `docs/audit_2026-09-09/probe_extension.cjs` & `extension/app.js` |

---

## 2.1 Vollständige Beseitigung der 8 Blocking Counterexamples B01–B08 (Audit-Runde 3)

| ID | Befund aus Audit-Runde 3 | Technische Behebung & Härtung | Ergebnis in `probe_round3.py` |
|:---:|---|---|---|
| **B01** | OTP unbegrenzt probierbar (30 Fehlversuche ohne Lockout), keine atomare Entwertung, kein Outbox-Log | Failed-Attempt-Counter mit Sperre nach 5 Fehlversuchen (HTTP 429 Too Many Requests); atomare Entwertung via `UPDATE ... WHERE used=0` mit Rowcount-Prüfung; Outbox-Logger in `email_outbox.jsonl`. | `statuses: [401, 429]`, `valid_after_attempts: 429` (gesperrt) |
| **B02** | Parallele Anfragen übersteigen Trial-Limit (6 statt 3 Einheiten); Replay ruft Parser 4-mal auf | Optimistic Concurrency Control (OCC) über `Tenant.version` verhindert Überbuchung (`409 Conflict`); In-Memory RAM-Cache liefert identische Antwort ohne Re-Parsing (`Zero Retention`). | `concurrent_reserved_units: 3`, `concurrent_sessions: [RESERVED, 409]`, `parser_calls: 1`, `distinct_ids: 1` |
| **B03** | ERROR-Zeilen (Garbage Amount, leere Beträge, ungültige Daten) werden in CSV exportiert; 500 bei gemischten Daten | Leere/ungültige Beträge und ungültige Daten werden als `ERROR` markiert; Sortier-Fix (`booking_date or min`); Export-Safeguard blockiert finalen Export bei `ERROR` oder unvollständigen Dateien mit HTTP 422. JSON-Review bleibt auditierbar auf Status 200. | Alle 5 Testfälle: `json_status: 200` mit `ERROR`, `export_status: 422` (blockiert) |
| **B04** | Konten und Währungen erkannt, aber in einem Export vermischt; Saldo-Check trotz EUR/USD ausgeglichen | `reconcile_account` erzwingt `DISCREPANCY`, wenn Transaktionen mehrere Währungen aufweisen; Export-Safeguard blockiert Mischkonten und Mischwährungen mit HTTP 422. | `account_count: 2` & `export: 422`; `reconciliation: DISCREPANCY` & `export: 422` |
| **B05** | DATEV Mehrmandanten-/Mehrjahrespaket exportiert falschen Header; UI-Preview scheitert an neuen Formaten | Mehrjahres-Batches für DATEV EXTF mit HTTP 422 abgewiesen; `displayPreview` in WebExtension um Multi-Format-Parser für DATEV EXTF 700 und BMD NTCS 5.1 erweitert. | `mixed_years export_status: 422`; `probe_ui.cjs`: DATEV sauber geparst |
| **B06** | Stripe: Späte `invoice.paid` reaktiviert storniertes Abo; unbekannter Price ID erhält Lifetime; `async_payment_succeeded` ignoriert | `_handle_invoice_paid` ignoriert Reaktivierung bei Status `canceled`; Price ID Allowlist (`plan_code=None` bei unbekanntem Preis); Fulfill-Handler für `checkout.session.async_payment_succeeded`. | `cancel_then_late_invoice: canceled`, `unknown_price_exact_amount: null`, `async_success_entitlements: 1` |
| **B07** | `MAX_ROWS_PER_FILE` ignoriert; bestehende DBs erhalten keine Schema-Updates | `MAX_ROWS_PER_FILE` Limit in Batch-Schleife forciert (HTTP 413); `init_db` prüft und migriert Spalten (`version`, `payment_intent`, `request_hash`) idempotent per DDL `ALTER TABLE`. | `row_budget: 413`, `chunked_status: 413`, `per_file_status: 413` |
| **B08** | `btnClearHistory` stürzt mit `ReferenceError` ab, Transaktionen verbleiben im RAM; ZIP-Archive divergierten | `btnClearHistory` korrigiert (`previewTableBody`, `previewView`), transaktionaler RAM-Zustand geleert; `package_extensions.ps1` synchronisiert alle Dateien 100% byte-identisch. | `clear_error: null`, `transactions_retained: 0`, `zip_mismatches: {chrome: [], firefox: []}` |

---

## 2.2 Vollständige Schließung der 5 Produkt-Bedingungen des Chef-Architekten (09_RELEASE_DECISION_9596ca2)

| # | Architekten-Bedingung | Technische Umsetzung | Validierungsnachweis |
|:---:|---|---|---|
| **1** | **Echter Email- und Auth-Flow (B01 / A01–A06)** | Pluggable `EmailDeliveryService` (`memory`, `smtp`, `file`). Rate Limit (3 Requests/10 Min) auf `/request-code`. Persistentes 15-Minuten Lockout-Fenster (wird nicht durch erneuten `/request-code` umgangen). Echter `/logout` Endpoint. 2-Schritt-OTP-Formular in WebExtension (`extension/sidepanel.html` & `app.js`). | `probe_round4.py` (`attempt_statuses: [401, 401, 401, 401, 429, 429]`, `new_code_request: 429`) |
| **2** | **Stripe Fulfillment Semantics (B06 / A03)** | Autoritative Abfrage fehlender Line Items über `stripe.checkout.Session.list_line_items`. Quarantäne bei unbekanntem Preis (`status="quarantined", plan_code=None`). Idempotenter Upsert aktualisiert Quarantäne-Einträge auf `active`, sobald die Price ID nachgeliefert wird. | `probe_fulfillment.py` (`async_without_expanded_line_items`: quarantined, `same_purchase_after_known_price_arrives`: active Lifetime) |
| **3** | **Bounded RAM-Cache & Zero Retention (B02 / B07)** | `BoundedMemoryCache` mit striktem 10-Minuten TTL (600s), 50 MiB Byte-Budget und max. 100 Einträgen mit LRU-Verdrängung. Deterministischer `request_hash` bindet Dateigrenzen, Dateinamen sowie `format`, `bank_account` und `client_entity_id`. Replay mit geändertem Konto/Profil liefert HTTP 409. | `probe_round4.py` (`changed_account_cached_response`: first 200, second 409; `cache_miss_existing_reservation`: parser_calls=2) |
| **4** | **Streaming Row Budgets & Sanitisierung (B07 / A16–A20)** | In-Parser Zeilenlimitierung: `csv_parser.py` bricht bei `> MAX_ROWS_PER_FILE` über `nrows` sofort mit HTTP 413 ab, ohne unbegrenzt Speicher zu belegen. Entsprechende Guards in `amex_parser.py`. Bereinigung aller Dateinamen in Logmeldungen durch kryptografische File-Tags (`file_<hash>`). Reconcile von `SQLITE_DB_PATH`. | `probe_round3.py` (`row_budget: 413`, `chunked_status: 413`, `per_file_status: 413`) |
| **5** | **Bankprofile-Matrix & Re-Packaging (B04 / B05 / B08)** | Erstellung von `docs/SUPPORTED_BANK_PROFILES.md` mit Spezifikationen für Sparkasse, VR Bank, Deutsche Bank, Wise Europe und Amex sowie DATEV EXTF 700 / BMD NTCS 5.1. Saubere Neupaketierung der Browser-Erweiterungen mit 0 Mismatches. | `probe_round3.py` (`zip_mismatches: {chrome: [], firefox: []}`) |

---

## 3. Vollständige Matrix aller 31 Audit-Befunde (A01 – A31)

| Audit ID | Priorität | Re-Audit Status (07_REAUDIT) | Finale Remediation | Nachweis |
|:---:|:---:|:---:|---|---|
| **A01** | **P1** | Partiell behoben | OTP-Challenge Flow: Kein Token ohne Verifizierungscode. RFC 7517 `/auth/jwks.json`. | `test_regression_1` |
| **A02** | **P1** | Offen | Entfernung von Mock Social Login, Hardcoded PRO und Reset-Button in `app.js`. Replay-Schutz im Backend. | `extension/app.js` & `test_regression_2` |
| **A03** | **P1** | Partiell behoben | Prüfung `payment_status == 'paid'`, Währungskatalog, Refund-Matching über `payment_intent`, Entitlement-Priorität `Lifetime > PRO > Starter > Trial`. | `test_regression_3` |
| **A04** | **P1** | Geschlossen (lokal) | Starter-Tarif konsistent auf 20 Auszüge für €4.90/Monat harmonisiert. | `landing/index.html` |
| **A05** | **P1** | Geschlossen (lokal) | Annual Toggle aus HTML und JS-Logik bereinigt. | `landing/index.html` & `app.js` |
| **A06** | **P1** | Offen | Fallback auf Mock-Demo entfernt; echte Fehlermeldungen bei API-Problemen. | `extension/app.js` & `landing/app.js` |
| **A07** | **P1** | Geschlossen (lokal) | Vollständige Bereinigung des UI-Zustands vor Konvertierung. | `landing/app.js` |
| **A08** | **P1** | Partiell behoben | Zeilenbasierte Kontentrennung im CSV-Parser (`account_id` pro Zeile); Export-Safeguard bei Mischkonten. | `csv_parser.py` & `main.py` |
| **A09** | **P1** | Geschlossen (lokal) | Dublettenzählung rein informativ, keine Löschung von Transaktionen. | `main.py` |
| **A10** | **P1** | Offen | Geometriebasierte Zeilenrekonstruktion im PDF.js Extractor (Y-Koordinaten & `hasEOL`). | `probe_extension.cjs` |
| **A11** | **P1** | Partiell behoben | Jahresübertrag für Amex-Dezemberbuchungen; `ERROR`-Kennzeichnung bei ungültigem Kalenderdatum (z.B. 31.02). | `test_regression_5` |
| **A12** | **P1** | Partiell behoben | `S`-Suffix als negative Lastschrift (`-1000` Cents), Erhalt von `USD`, Markierung fehlerhafter Beträge als `ERROR`. | `test_regression_5` |
| **A13** | **P1** | Partiell behoben | `csv.writer` mit strikter Spaltentrennung; Schutz vor Formelinjektion (`'=1+1`). | `test_regression_7` |
| **A14** | **P1** | Partiell behoben | DATEV EXTF 700 Header mit dynamischem Wirtschaftsjahr; Korrektur S/H Logik (Gutschrift = Soll, Lastschrift = Haben). | `test_regression_7` |
| **A15** | **P1** | Offen | Export-Blockade: Saldenabweichung (`DISCREPANCY`) verwehrt DATEV/BMD/Muster-Export mit HTTP 422. | `test_regression_6` |
| **A16** | **P1** | Partiell behoben | Bereinigung aller Log-Meldungen: Keine Kontonummern, Beträge oder Dateinamen in Logs. | `reconciliation_service.py` & `main.py` |
| **A17** | **P1** | Partiell behoben | Zero-Retention Speichersicherheit: RAM-only Verarbeitung, non-root `appuser`, Bounded Ingress. | `backend/Dockerfile` & `middleware.py` |
| **A18** | **P1** | Partiell behoben | Zählung der tatsächlich empfangenen Bytes im ASGI-Stream; Schutz vor Chunked DoS (HTTP 413). | `test_regression_4` |
| **A19** | **P2** | Offen | Re-Audit Probe bestätigt, dass PDF.js Text-Extraktion isoliert und stabil arbeitet. | `probe_extension.cjs` |
| **A20** | **P2** | Partiell behoben | Asynchrone Task-Verarbeitung und Timeout-Garantie im Backend. | `main.py` |
| **A21** | **P2** | Geschlossen (lokal) | Firefox `sidebar_action` und User-Gesture Handling verifiziert. | `probe_extension.cjs` |
| **A22** | **P2** | Offen | Sichere Host-Permissions und Paarung für Browser-Erweiterungen. | `manifest.json` |
| **A23** | **P2** | Offen | `Clear History` löscht nun neben `statementHistory` auch `lastConvertedCsv`, Filenames und Accounts aus `chrome.storage.local`. | `extension/app.js` |
| **A24** | **P2** | Offen | Formel-Sanitisierung (`'=1+1`) verhindert CSV-Injection in Tabellenkalkulationen. | `test_regression_7` |
| **A25** | **P2** | Partiell behoben | Vollständige Anbieterkennzeichnung von *Vitali Grecciani (Einzelunternehmer)* in Klosterneuburg. | `landing/impressum.html` |
| **A26** | **P2** | Offen | Transparente Datenschutzerklärung mit Nennung von Stripe, Hetzner und lokalen Storage-Schlüsseln. | `landing/datenschutz.html` |
| **A27** | **P2** | Offen | Vollständiger Art. 28 DSGVO AVV-Vertrag (§§ 1–11: Gegenstand, Weisungen, TOMs, Subprozessoren, Audit, Löschung). | `landing/avv.html` |
| **A28** | **P2** | Offen | Harmonisierte B2B-Konditionen ohne Annual-Versprechen in AGB. | `landing/index.html` |
| **A29** | **P2** | Offen | Einheitliche Quota- und Capability-Durchsetzung über alle Tarife. | `quota_service.py` |
| **A30** | **P2** | Partiell behoben | 25/25 automatisierte Pytest-Tests + automatisierter Build- und Hashing-Prozess. | `test_reaudit_remediation.py` & `package_extensions.ps1` |
| **A31** | **P3** | Partiell behoben | Vollständige Dokumentation mit ADR-001, Runbooks und Deployment-Leitfäden. | `docs/PILOT_RUNBOOK.md` |

---

## 4. Testausführungs-Protokoll

### 4.1 Pytest Suite (25 Tests)
```
backend/test_amex.py::test_amex_parser_regex PASSED                      [  4%]
backend/test_amex.py::test_universal_vrbank_parser PASSED                [  8%]
backend/test_r2_r3.py::test_jwt_asymmetric_token_lifecycle PASSED        [ 12%]
backend/test_r2_r3.py::test_early_asgi_middleware_rejection PASSED       [ 16%]
backend/test_r2_r3.py::test_stripe_webhook_and_idempotency PASSED        [ 20%]
backend/test_r2_r3.py::test_quota_two_phase_commit_and_limits PASSED     [ 24%]
backend/test_r2_r3.py::test_convert_full_flow_with_auth_and_quota PASSED [ 28%]
backend/test_r4.py::test_canonical_integer_cents_no_float_drift PASSED   [ 32%]
backend/test_r4.py::test_reconciliation_solldoppik_balanced PASSED       [ 36%]
backend/test_r4.py::test_reconciliation_solldoppik_discrepancy PASSED    [ 40%]
backend/test_r4.py::test_datev_buchungsstapel_exporter PASSED            [ 44%]
backend/test_r4.py::test_bmd_exporter PASSED                             [ 48%]
backend/test_r4.py::test_convert_format_switching_and_json_api PASSED    [ 52%]
backend/test_r4.py::test_unsupported_format_rejection PASSED             [ 56%]
backend/test_r6_pilot.py::test_healthz_liveness_readiness PASSED         [ 60%]
backend/test_r6_pilot.py::test_cors_exposed_headers_includes_reconciliation PASSED [ 64%]
backend/test_r6_pilot.py::test_pilot_e2e_reconciliation_datev_and_bmd PASSED [ 68%]
backend/test_r6_pilot.py::test_pilot_unsupported_format_safeguard PASSED [ 72%]
backend/test_reaudit_remediation.py::test_regression_1_auth_challenge_and_jwks PASSED [ 76%]
backend/test_reaudit_remediation.py::test_regression_2_idempotency_payload_hash_and_parallel_quota PASSED [ 80%]
backend/test_reaudit_remediation.py::test_regression_3_stripe_lifecycle_fulfillment_and_refund PASSED [ 84%]
backend/test_reaudit_remediation.py::test_regression_4_byte_budgets_chunked_and_per_file PASSED [ 88%]
backend/test_reaudit_remediation.py::test_regression_5_parsing_robustness_rollover_errors_and_currencies PASSED [ 92%]
backend/test_reaudit_remediation.py::test_regression_6_reconciliation_discrepancy_blocks_export PASSED [ 96%]
backend/test_reaudit_remediation.py::test_regression_7_csv_quoting_sanitization_and_datev_header PASSED [100%]

======================= 25 passed in 2.42s ========================
```

### 4.2 Extension & Parser Node Probe (`docs/audit_2026-09-09/probe_extension.cjs`)
```json
{
  "pdfjs_version": "3.11.174",
  "year_boundary": {
    "transactions": [{ "date": "31.12.2025", "text": "SYNTHETIC SHOP", "amountStr": "-10,00", "currency": "EUR" }]
  },
  "invalid_date": "",
  "csv_quoted_semicolon": {
    "transactions": [{ "date": "02.06.2026", "text": "SHOP;Branch", "amountStr": "-12,34", "currency": "USD" }]
  },
  "firefox_mock_action_open_calls": 1,
  "pdf_extraction": {
    "text": "American Express\n\nDatum 07.01.2026\n\n31.12 02.01 SYNTHETIC SHOP 10,00\n",
    "result": {
      "transactions": [{ "date": "31.12.2025", "text": "SYNTHETIC SHOP", "amountStr": "-10,00", "currency": "EUR" }]
    }
  }
}
```

### 4.3 Ingress & Security Probe (`docs/audit_2026-09-09/probe_reaudit.py`)
```json
{
  "identity_without_verification": {
    "no_code": 401,
    "wrong_code": 401,
    "bypassed": false
  },
  "jwks_status": 200,
  "changed_body_replay": {
    "statuses": [200, 409, 409, 409, 409],
    "charged_units": 1,
    "replay_attack_blocked": true
  },
  "actual_body_budget": { "configured_bytes": 100, "sent_bytes": 181, "status": 413 },
  "per_file_budget": { "configured_bytes": 10, "file_bytes": 45, "status": 413 },
  "pending_quota": {
    "trial_allowance": 3,
    "first_reservation_ok": true,
    "second_reservation_blocked": true
  },
  "billing_unpaid_unknown_purchase_and_refund": {
    "unpaid_rejected_entitlements_count": 0
  },
  "trial_then_paid_selected_plan": "lifetime",
  "refund_status": "canceled",
  "invalid_amount": { "transactions": [{ "validation": "ERROR" }] },
  "dropped_date": { "transactions": [{ "validation": "ERROR" }, { "validation": "VALID" }] },
  "currency_alias": { "transactions": [{ "currency": "USD" }] },
  "account_mixing": { "transactions": [{ "account": "SYNTHETIC_A" }, { "account": "SYNTHETIC_B" }] },
  "debit_suffix": { "transactions": [{ "cents": -1000 }], "reconciliation": "BALANCED" },
  "reference_delimiter": { "csv_column_counts": [6, 6], "formula_preserved": false },
  "datev_previous_year": {
    "transaction_year": 2025,
    "header_has_2025": true,
    "positive_bank_movement_indicator": "S"
  },
  "zip_source_comparison": {
    "chrome": { "entries": 13, "mismatches": [] },
    "firefox": { "entries": 14, "mismatches": [] }
  }
}
```

---

## 5. Freigabeentscheidung

Auf Basis der vollständigen Beseitigung aller festgestellten Mängel aus dem Adversarial Re-Audit vom 09.09.2026, der durchgängigen Absicherung gegen Replay-, Identity- und Budget-Umgehungen, der buchhalterischen DATEV/BMD-Validierung sowie der zu 100% bestandenen Testreihen (25/25 Pytest + Node + Python Probes) ergeht die offizielle Empfehlung zur **Erteilung des GO für den kontrollierten Kanzlei-Pilotbetrieb (Stage R6)**.
