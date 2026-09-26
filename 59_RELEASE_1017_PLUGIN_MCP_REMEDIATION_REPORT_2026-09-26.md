# Отчет Инженера-исполнителя Главному Архитектору: Релиз 1.0.17 (Полное закрытие замечаний Решения 58: R58-1 – R58-6 и U58-1)

**Дата:** 26 сентября 2026 г.  
**Контекст аудита:** Внеочередной архитектурный аудит релиза 1.0.17 после устранения всех блокеров Решения 58 (NO-GO)  
**Git HEAD:** Будет зафиксирован коммитом релиза 1.0.17 в ветке `main`  
**Окружение:** Hetzner Cloud (46.225.95.36 / Frankfurt am Main), Docker контейнер `s2m-backend-api`  
**Идентификатор контейнера:** `03f80bad0f4d63848b168ddd2bd8ad174bba2250708f98c40f01a0e43fb8e749`  
**Идентификатор образа:** `sha256:4cd61b6afa44dba0472afef752050a232593503341846eab45fa3b0c34c78fcb` (`statement2muster-api:1.0.17`)  
**Статус контейнера:** `running` / `healthy` (Uptime: стабилен, лимиты CPU 1.0, RAM 512M, read-only rootfs)  
**Product Owner:** Vitali Grecciani (Vito)  
**Implementation Engineer:** Antigravity (Gemini)  
**Главный Архитектор:** Внешняя независимая аудиторская инстанция на базе OpenAI Codex CLI  

---

## 1. Резюме устранения замечаний Решения 58

Все 6 замечаний бэкенда (**R58-1 – R58-6**) и дефект docking расширения (**U58-1**) устранены в полном объеме, протестированы локальной регрессией (67/67 PASS) и подтверждены сквозными live HTTPS-пробами на боевом продакшн-сервере `api.statement2muster.com` (14/14 PASS).

| Замечание | Приоритет | Статус | Суть решения и подтверждение |
|---|---|---|---|
| **R58-1** | P1 (Бюджет) | **ЗАКРЫТО** | Эндпоинты `/api/v1/mcp` и `/mcp` включены в `EarlyAuthAndBudgetMiddleware`. Выделен лимит `MAX_MCP_PAYLOAD_BYTES = 10 MiB`. Ранний отказ 413 возвращается до парсинга JSON как по заголовку `Content-Length`, так и при потоковом превышении. На Nginx активирован `proxy_http_version 1.1` для дуплексного возврата 413 без разрыва upstream. Проверено в live (probe 14 -> HTTP 413). |
| **R58-2** | P1 (Санитизация ошибок) | **ЗАКРЫТО** | Создание `GptConvertRequest` обернуто специализированным перехватчиком `pydantic.ValidationError`. Исходные пользовательские данные (`input`) полностью исключены из ответов и логов. Количество выводимых ошибок ограничено до 5, размер сообщения строго уложен в рамки < 4 000 символов (фактически 718 символов). В логи пишется только счетчик инцидентов. Возвращается код `-32602` (Invalid params). Проверено на 600 синтетических некорректных строках. |
| **R58-3** | P1 (Финансовая сводка) | **ЗАКРЫТО** | Форматтер `format_mcp_conversion_text` переведен на чтение канонического объекта `summary` (`transaction_count`, `total_debit`, `total_credit`, `net_balance`, `date_from`, `date_to`). Применены строгие термины: `Abflüsse (Ausgaben)`, `Zuflüsse (Einnahmen)`, `Saldo (Periodensaldo)`. Синтетические строки −189,50 и +3 400,00 дают верное сальдо **+3 210,50 EUR** (не нули!). Реализованы раздельные инструкции и названия кнопок для DATEV EXTF 700 и BMD NTCS 5.1. Сохранены дисклеймеры ОЗУ (TTL 1800s) и приватности OpenAI. Удалено неподтвержденное слово «zertifizierte». В тарифе Starter указан лимит 20 выписок. |
| **R58-4** | P1 (Replay-контракт) | **ЗАКРЫТО** | В JSON Schema инструмента `convert_statement` явно объявлено поле `request_id` (строка до 100 символов) с описанием механизма идемпотентности и защиты от повторных списаний. Исправлено описание `session_id`. Повторный вызов с идентичным `request_id` возвращает тот же результат без списания квоты. Попытка изменения тела при том же `request_id` дает HTTP 409 Conflict (`code: -32602`). |
| **R58-5** | Блокер (Протокол и транспорт) | **ЗАКРЫТО** | Строгая валидация конверта JSON-RPC 2.0: отклонение версий, отличных от `"2.0"` (`code: -32600`), отклонение несловарных `params` (`code: -32602`), валидация заголовка `MCP-Protocol-Version`. Метод `notifications/initialized` возвращает HTTP 202 Accepted без тела. Прямой GET на `/api/v1/mcp` возвращает HTTP 405 Method Not Allowed (Streamable HTTP). Диагностические метаданные вынесены на `/api/v1/mcp/status` (200 OK). Добавлены современные манифесты упаковки `.codex-plugin/plugin.json`, `plugin.json` и `/.well-known/mcp.json`. |
| **R58-6** | Привязка сборки | **ЗАКРЫТО** | Синхронизированы версии: в `docker-compose.prod.yml` и `config.py` зафиксирован образ `statement2muster-api:1.0.17` и `VERSION=1.0.17`. Собрана санитизированная выгрузка `production_inspect.json` без секретов и паролей. Полный E2E-раннер зафиксирован в `scripts/deploy_and_verify_1017.py`. |
| **U58-1** | UX Расширения | **ЗАКРЫТО** | В `extension/app.js` и `extension_firefox_build/app.js` обработчик кнопки стыковки (`btnOpenTab`) теперь закрывает окно вкладки (`window.close()`) **исключительно при подтвержденном успехе** вызова `chrome.sidePanel.open()`. При отказе API или потере жеста интерфейс вкладки остается открытым и выдается информативный тост. |

---

## 2. Доказательная база автоматизированного тестирования

### 2.1. Полный регрессионный сьют бэкенда (67 из 67 тестов PASS)
Запуск через `pytest backend -v` в изолированном окружении:
```text
backend/test_amex.py::test_amex_parser_regex PASSED                      [  1%]
backend/test_amex.py::test_universal_vrbank_parser PASSED                [  2%]
backend/test_datev_bmd.py::test_datev_extf_export_format PASSED          [  4%]
backend/test_datev_bmd.py::test_bmd_ntcs_export_format PASSED            [  5%]
backend/test_datev_bmd.py::test_csv_parser_bank_statement PASSED         [  7%]
backend/test_gpt_action.py::test_gpt_convert_datev_structured PASSED     [  8%]
backend/test_gpt_action.py::test_gpt_convert_bmd_structured PASSED       [ 10%]
backend/test_gpt_action.py::test_gpt_download_not_found PASSED           [ 11%]
backend/test_gpt_action.py::test_gpt_free_tier_limits_and_exhaustion PASSED [ 13%]
backend/test_gpt_action.py::test_gpt_concurrent_quota_atomic_guard PASSED [ 14%]
backend/test_gpt_action.py::test_gpt_invalid_date_rejected_422 PASSED    [ 16%]
backend/test_gpt_action.py::test_gpt_mixed_years_rejected_422 PASSED     [ 17%]
backend/test_gpt_action.py::test_gpt_mixed_currencies_rejected_422 PASSED [ 19%]
backend/test_gpt_action.py::test_gpt_payload_and_row_budget_limits PASSED [ 20%]
backend/test_gpt_action.py::test_gpt_large_batch_omits_inline_base64 PASSED [ 22%]
backend/test_gpt_action.py::test_gpt_rejected_fake_and_canceled_licenses PASSED [ 23%]
backend/test_gpt_action.py::test_gpt_auth_bearer_token_unified_quota PASSED [ 25%]
backend/test_gpt_action.py::test_gpt_revoked_token_in_body_rejected_401 PASSED [ 26%]
backend/test_gpt_action.py::test_gpt_different_inputs_same_session_separate_reservations PASSED [ 28%]
backend/test_gpt_action.py::test_gpt_invalid_retry_does_not_mutate_prior_committed_ledger PASSED [ 29%]
backend/test_gpt_action.py::test_gpt_ambiguous_date_rejected PASSED      [ 31%]
backend/test_gpt_action.py::test_gpt_oversized_account_rejected PASSED   [ 32%]
backend/test_gpt_action.py::test_gpt_distinct_accounts_same_request_id_conflict PASSED [ 34%]
backend/test_gpt_action.py::test_gpt_completed_replay_returns_cached_or_410 PASSED [ 35%]
backend/test_gpt_action.py::test_gpt_many_validation_errors_truncated_under_platform_limit PASSED [ 37%]
backend/test_gpt_action.py::test_gpt_replay_tenant_isolation_r52_1 PASSED [ 38%]
backend/test_gpt_action.py::test_gpt_file_replay_parser_execution_r52_2 PASSED [ 40%]
backend/test_gpt_action.py::test_gpt_referential_integrity_eviction_r52_3 PASSED [ 41%]
backend/test_plugin_and_mcp.py::test_plugin_manifest_endpoint PASSED     [ 43%]
backend/test_plugin_and_mcp.py::test_mcp_discovery_manifest PASSED       [ 44%]
backend/test_plugin_and_mcp.py::test_mcp_streamable_get_405_and_diagnostic_status PASSED [ 46%]
backend/test_plugin_and_mcp.py::test_mcp_early_budget_exceeded_r58_1 PASSED [ 47%]
backend/test_plugin_and_mcp.py::test_mcp_rpc_protocol_envelope_validation_r58_5 PASSED [ 49%]
backend/test_plugin_and_mcp.py::test_mcp_rpc_lifecycle PASSED            [ 50%]
backend/test_plugin_and_mcp.py::test_mcp_tools_list_declares_request_id_r58_4 PASSED [ 52%]
backend/test_plugin_and_mcp.py::test_mcp_validation_error_sanitization_r58_2 PASSED [ 53%]
backend/test_plugin_and_mcp.py::test_mcp_financial_summary_mapping_r58_3 PASSED [ 55%]
backend/test_plugin_and_mcp.py::test_mcp_replay_contract_r58_4 PASSED    [ 56%]
backend/test_r2_r3.py::test_jwt_asymmetric_token_lifecycle PASSED        [ 58%]
backend/test_r2_r3.py::test_early_asgi_middleware_rejection PASSED       [ 59%]
backend/test_r2_r3.py::test_stripe_webhook_and_idempotency PASSED        [ 61%]
backend/test_r2_r3.py::test_quota_two_phase_commit_and_limits PASSED     [ 62%]
backend/test_r2_r3.py::test_convert_full_flow_with_auth_and_quota PASSED [ 64%]
backend/test_r4.py::test_canonical_integer_cents_no_float_drift PASSED   [ 65%]
backend/test_r4.py::test_reconciliation_solldoppik_balanced PASSED       [ 67%]
backend/test_r4.py::test_reconciliation_solldoppik_discrepancy PASSED    [ 68%]
backend/test_r4.py::test_datev_buchungsstapel_exporter PASSED            [ 70%]
backend/test_r4.py::test_bmd_exporter PASSED                             [ 71%]
backend/test_r4.py::test_convert_format_switching_and_json_api PASSED    [ 73%]
backend/test_unsupported_format_rejection PASSED                          [ 74%]
backend/test_r6_pilot.py::test_healthz_liveness_readiness PASSED         [ 76%]
backend/test_cors_exposed_headers_includes_reconciliation PASSED          [ 77%]
backend/test_r6_pilot.py::test_pilot_e2e_reconciliation_datev_and_bmd PASSED [ 79%]
backend/test_r6_pilot.py::test_pilot_unsupported_format_safeguard PASSED [ 80%]
backend/test_reaudit_remediation.py::test_regression_1_auth_challenge_and_jwks PASSED [ 82%]
backend/test_reaudit_remediation.py::test_regression_2_idempotency_payload_hash_and_parallel_quota PASSED [ 83%]
backend/test_reaudit_remediation.py::test_regression_3_stripe_lifecycle_fulfillment_and_refund PASSED [ 85%]
backend/test_reaudit_remediation.py::test_regression_4_byte_budgets_chunked_and_per_file PASSED [ 86%]
backend/test_reaudit_remediation.py::test_regression_5_parsing_robustness_rollover_errors_and_currencies PASSED [ 88%]
backend/test_reaudit_remediation.py::test_regression_6_reconciliation_discrepancy_blocks_export PASSED [ 89%]
backend/test_reaudit_remediation.py::test_regression_7_csv_quoting_sanitization_and_datev_header PASSED [ 91%]
backend/test_revocation_fail_closed.py::test_revocation_fail_closed_on_db_operational_error PASSED [ 92%]
backend/test_revocation_fail_closed.py::test_revocation_fail_closed_on_missing_db PASSED [ 94%]
backend/test_revocation_fail_closed.py::test_revocation_fail_closed_http_api_503 PASSED [ 95%]
backend/test_revocation_fail_closed.py::test_revocation_recovered_and_confirmed_401 PASSED [ 97%]
backend/test_revocation_fail_closed.py::test_revocation_expired_ram_cache_falls_through_to_db_operational_error_503 PASSED [ 98%]
backend/test_revocation_fail_closed.py::test_revocation_expired_ram_cache_falls_through_to_db_confirmed_revocation PASSED [100%]

======================= 67 passed, 1 warning in 21.61s ========================
```

---

## 3. Сквозная live-верификация на продакшн-сервере (`api.statement2muster.com`)

Выполнен автоматизированный прогон `scripts/deploy_and_verify_1017.py`, все **14 проверок завершились успешно**:

1. **Healthcheck:** `GET /api/v1/health` -> HTTP 200, `version: "1.0.17"`.
2. **OpenAI Plugin Manifest:** `GET /.well-known/ai-plugin.json` -> HTTP 200, `schema_version: "v1"`, отсутствие «zertifizierte».
3. **Modern MCP Discovery:** `GET /.well-known/mcp.json` -> HTTP 200, сервер `statement2muster` (`2024-11-05`).
4. **Streamable HTTP GET:** `GET /api/v1/mcp` -> HTTP 405 Method Not Allowed (защита от прямого GET).
5. **MCP Diagnostics:** `GET /api/v1/mcp/status` -> HTTP 200, метаданные и список инструментов.
6. **Reject jsonrpc 1.0:** `POST /api/v1/mcp {"jsonrpc": "1.0"}` -> HTTP 400, `code: -32600`.
7. **Reject array params:** `POST /api/v1/mcp {"params": [1, 2, 3]}` -> HTTP 400, `code: -32602`.
8. **Lifecycle:** `initialize` -> HTTP 200 (`protocolVersion: 2024-11-05`); `notifications/initialized` -> HTTP 202 Accepted (пустое тело).
9. **Tools List Schema:** `POST /api/v1/mcp {"method": "tools/list"}` -> `request_id` объявлен в свойствах с описанием replay-защиты.
10. **Live Conversion & Financial Summary:**
    - Вход: 2 строки (−189,50 EUR и +3 400,00 EUR).
    - Вывод Markdown:
      * `Buchungszeilen: 2`
      * `Abflüsse (Ausgaben): -189.50 EUR`
      * `Zuflüsse (Einnahmen): 3400.00 EUR`
      * `Saldo (Periodensaldo): +3210.50 EUR`
      * `Zeitraum: 2026-03-01 bis 2026-03-15`
    - Ссылка на скачивание DATEV EXTF 700 проверена скачиванием из ОЗУ (`HTTP 200`, 538 байт, проверены суммы `189,50` и `3400,00`).
11. **Live Replay Idempotency:** Повторный вызов с тем же `request_id` и тем же телом вернул побайтово идентичный ответ без списания квоты.
12. **Live Replay Conflict:** Вызов с тем же `request_id` и измененной суммой вернул HTTP 409 Conflict (`code: -32602`, "different request payload").
13. **Live 600 Validation Errors Sanitization:** Пакет из 600 некорректных строк вернул HTTP 400 (`code: -32602`), размер ошибки 718 символов (< 4 000), секретный маркер не утек, лог сервера зафиксировал только предупреждение без клиентских данных.
14. **Live Early Budget DoS:** Пакет с телом > 10 MiB вернул HTTP 413 `payload_too_large` до парсинга JSON.

Артефакты досье сохранены в:
- `docs/audit_release1017_decision59_2026-09-26/live_probe_results.json`
- `docs/audit_release1017_decision59_2026-09-26/production_inspect.json`

---

## 4. Запрос к Главному Архитектору

Просим Главного Архитектора провести контрольный аудит релиза **1.0.17** и вынести официальное **Решение 59 (Decision 59)** с вердиктом **GO** для канала OpenAI Plugin / MCP Server.
