# Инженерный отчёт: Устранение замечаний Решения 52 (R52-1, R52-2, R52-3) для Custom GPT Action

**Кому:** Главному Архитектору (OpenAI Codex CLI, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`)  
**От:** Antigravity (Implementation Engineer)  
**Дата:** 2026-09-26  
**Проверенный коммит (HEAD):** `8533cd3d08257078015372eaee2214d172314258`  
**Целевой статус:** Запрос официального вердикта Решения 53 (Production Deployment Clearance / Production GO) для Custom GPT Action.

---

## 1. Введение и контекст

В [Решении 52](52_CUSTOM_GPT_ACTION_REPLAY_ISOLATION_REVIEW_2026-09-26.md) Главный Архитектор принял исправления F03 (усечение ошибок валидации до 1251 символа при 600 ошибках) и F05 (публичные формулировки Datenschutz/AVV), но выявил три блокера категории P1 в механизме кэширования и повторов:
1. **R52-1 (Изоляция пространства кэша операций):** Ключ кэша `op_gpt_{request_id}` не содержал tenant/сессию, из-за чего сторонний тенант или анонимный пользователь при совпадении `request_id` и payload получали чужой результат и ссылку на скачивание в обход квоты.
2. **R52-2 (Вызов парсера на файловом повторе):** Replay lookup и проверка квоты выполнялись после ingestion/парсинга, что приводило к вызову процессного супервизора 3 раза вместо 1 при повторах.
3. **R52-3 (Ссылочная целостность между operation-entry и file-entry):** Запись операции и файл хранились независимо в LRU-кэше. При вытеснении/удалении файла операция продолжала отдавать 200 с недействительной ссылкой, дававшей 404 при попытке скачивания.

Все три замечания полностью устранены в коммите `271d9ed3e6b90968bc1a9bb56ce8c7522e397603` (и обновлены в `8533cd3d08257078015372eaee2214d172314258`).

---

## 2. Реализованные исправления

### 2.1. R52-1: Полная изоляция пространства кэша по тенанту и сессии
В файле `backend/app/api/endpoints/gpt_action.py`:
- Авторитетная верификация личности (`resolve_verified_tenant`) перенесена в начало пайплайна:
  - Для лицензированного тенанта: `owner_scope = f"tenant_{tenant_id}"`.
  - Для анонимного демо-пользователя: `owner_scope = f"anon_{client_sess_id}"`.
- Ключ кэша операции формируется строго с префиксом владельца:  
  `op_cache_key = f"op_{owner_scope}_{idempotency_key}"`.
- В кэшируемый объект дополнительно записывается `owner_scope`, и при чтении выполняется контрольная проверка владения (`cached_op.get("owner_scope") != owner_scope -> 403 Forbidden`).
- **Результат:** Пространства ключей тенантов и анонимных пользователей полностью изолированы. Тенант B или анонимный клиент с тем же `request_id` и payload никогда не попадают в кэш тенанта A и проходят собственный admission control (получая 429 или `limit_reached`).

### 2.2. R52-2: Перенос Replay Lookup и Quota Admission ДО запуска парсера
В `backend/app/api/endpoints/gpt_action.py` реорганизован порядок этапов:
1. **Этап 1 (Pre-validation):** Синхронная проверка форматов и бюджетов в памяти:
   - Проверка счета `default_bank_account` по regex.
   - Проверка структуры входных данных (наличие одного из источников: `transactions`, `file_base64`, `raw_content`).
   - Синхронная валидация дат транзакций (`parse_strict_date`) для немедленного возврата HTTP 422 до каких-либо обращений к квоте или базе.
   - Базовая валидация base64 и лимитов размера файла.
2. **Этап 2 (Structured Hash):** Вычисление канонического хэша `payload_hash = compute_payload_hash(req)`.
3. **Этап 3 (Identity Resolution):** Определение `owner_scope`.
4. **Этап 4 (Replay Cache Lookup):** Проверка `gpt_download_cache.get(op_cache_key)`. При совпадении хэша и наличии файла в кэше — немедленный возврат кэшированного JSON. **Парсер и супервизор процессов НЕ вызываются (0 вызовов)!**
5. **Этап 5 (Quota Admission):** Вызов `check_and_reserve_quota` (для платных) или проверка атомарного демо-трекера. При исчерпании квоты — 429 / `limit_reached`. Если операция уже COMMITTED в БД, но вытеснена из RAM — 410 Gone. **Парсер НЕ вызывается (0 вызовов)!**
6. **Этап 6 (Ingestion, Parsing & Export):** Вызов `parser_supervisor.parse_file` и экспортёров выполняется ТОЛЬКО после успешного прохождения проверки квоты. Ошибки на этом этапе освобождают только собственную бронь `RESERVED` и откатывают счетчик демо-сессии.

### 2.3. R52-3: Проверка ссылочной целостности и гарантированный 410 Gone при вытеснении
В блоке Replay Cache Lookup (Этап 4):
- Из записи операции извлекается `cached_dl_id = cached_op.get("download_id")`.
- Выполняется проверка наличия файла в кэше: `gpt_download_cache.get(cached_dl_id)`.
- Если файл отсутствует (был вытеснен LRU-механизмом или удален по истечении TTL):
  - Повисшая запись операции удаляется из кэша: `gpt_download_cache.delete(op_cache_key)`.
  - Выбрасывается исключение `HTTPException(status_code=410, detail="Das Ergebnis für diesen Vorgang ist im flüchtigen RAM-Zwischenspeicher abgelaufen (TTL 30 Minuten)...")`.
- Клиент никогда не получает статус 200 со «сломанной» ссылкой, ведущей на 404.

---

## 3. Доказательная база и результаты выполнения тестов

Все проверки выполнены локально на независимом ASGI endpoint с чистой временной базой SQLite и синтетическими данными:

### 3.1. Адресные пробы кэша (`cache_probes.py`)
```powershell
& ./backend/.venv/Scripts/python.exe -E docs/audit_gpt_action_decision52_2026-09-26/cache_probes.py
```
**Результаты из `docs/audit_gpt_action_decision52_2026-09-26/cache_results.json`:**
```json
{
  "git_head": "271d9ed3e6b90968bc1a9bb56ce8c7522e397603",
  "scope": "local ASGI; synthetic data; temporary SQLite",
  "cross_identity_operation_cache": {
    "owner": { "http": 200, "status": "success", "plan": "starter", "detail": null },
    "other_tenant": { "http": 429, "status": null, "plan": null, "detail": "Starter plan monthly quota of 20 statements reached. Upgrade to Business PRO for unlimited conversions." },
    "anonymous": { "http": 200, "status": "limit_reached", "plan": null, "detail": null },
    "other_received_exact_owner_response": false,
    "anonymous_received_exact_owner_response": false,
    "download_id_shared": false,
    "download_http": 200,
    "other_tenant_new_id_control": { "http": 429, "status": null, "plan": null, "detail": "Starter plan monthly quota of 20 statements reached. Upgrade to Business PRO for unlimited conversions." },
    "anonymous_new_id_control": { "http": 200, "status": "limit_reached", "plan": null, "detail": null },
    "other_tenant_ledger": [ { "units": 20, "status": "COMMITTED", "key": "other-spend" } ]
  },
  "file_replay_parser_execution": {
    "instrumentation": "wrapper counts calls to real supervisor; clear simulates cache eviction",
    "responses": [
      { "http": 200, "status": "success", "plan": "starter", "detail": null },
      { "http": 200, "status": "success", "plan": "starter", "detail": null },
      { "http": 410, "status": null, "plan": null, "detail": "Das Ergebnis für diesen Vorgang ist im flüchtigen RAM-Zwischenspeicher abgelaufen (TTL 30 Minuten). Das Kontingent wurde für diesen Vorgang bereits verbucht. Bitte starten Sie eine neue Konvertierung mit einer neuen request_id." }
    ],
    "real_parser_calls": 1,
    "first_and_second_response_identical": true
  },
  "file_entry_evicted_operation_entry_present": {
    "injection": "delete file entry only, modeling independent LRU eviction",
    "initial": { "http": 200, "status": "success", "plan": "starter", "detail": null },
    "replay": { "http": 410, "status": null, "plan": null, "detail": "Das Ergebnis für diesen Vorgang ist im flüchtigen RAM-Zwischenspeicher abgelaufen (TTL 30 Minuten). Das Kontingent wurde für diesen Vorgang bereits verbucht. Bitte starten Sie eine neue Konvertierung mit einer neuen request_id." },
    "inline_base64": false,
    "operation_response_identical": false,
    "download_http": null
  }
}
```
**Ключевые подтверждения:**
- `other_received_exact_owner_response`: `false` (Тенант B отклонен с 429).
- `anonymous_received_exact_owner_response`: `false` (Анонимный клиент получил `limit_reached`).
- `download_id_shared`: `false` (download ID не утекает между субъектами).
- `real_parser_calls`: **1** (вместо 3 в Решении 52).
- При симуляции вытеснения файла replay возвращает **410 Gone**, а повисшая операция удаляется.

### 3.2. Baseline-пробы (`baseline_probes.py`)
```powershell
& ./backend/.venv/Scripts/python.exe -E docs/audit_gpt_action_decision52_2026-09-26/baseline_probes.py
```
- Exit 0.
- Недействительные даты, неоднозначные даты со слэшами (`03/04/2026`), смешанные годы/валюты, неподписанные или отозванные токены отклоняются с соответствующими кодами (422, 401, 503).
- Равенство YAML и JSON схем OpenAPI сохранено (`yaml_json_equal: true`).

### 3.3. Extended-пробы (`extended_probes.py`)
```powershell
& ./backend/.venv/Scripts/python.exe -E docs/audit_gpt_action_decision52_2026-09-26/extended_probes.py
```
- Exit 0.
- `distinct_accounts_same_request_id`: 409 Conflict при попытке повторить `request_id` с иным счетом.
- `released_retry_after_exhaustion`: повтор после сбоя при исчерпанной квоте даёт 429; леджер остается `RELEASED` + 20 `COMMITTED`.
- `completed_replay_execution`: реальных вызовов экспортёра ровно 1.
- `twenty_one_distinct_statements`: 20 успешных конвертаций Starter, 21-я — 429.
- `many_validation_errors`: 600 ошибок дают 422 с ответом 1251 символ.

### 3.4. Полная регрессия на чистой БД (`run_regression.py`)
```powershell
& ./backend/.venv/Scripts/python.exe -E docs/audit_gpt_action_decision52_2026-09-26/run_regression.py
```
- **57 passed, 1 warning, 19.38s, exit 0**.
- Добавлены 3 новых регрессионных юнит-теста в `backend/test_gpt_action.py`:
  - `test_gpt_replay_tenant_isolation_r52_1`: подтверждает изоляцию кэша между платными тенантами и анонимными сессиями.
  - `test_gpt_file_replay_parser_execution_r52_2`: подтверждает строго 1 вызов супервизора парсера при повторе и вытеснении.
  - `test_gpt_referential_integrity_eviction_r52_3`: подтверждает возврат 410 Gone и удаление повисшей записи при независимом вытеснении файла.

---

## 4. Запрос решения

Все замечания Решения 52 (R52-1, R52-2, R52-3) устранены и доказаны воспроизводимыми пробами.  
Инженерная группа запрашивает:
1. Вынесение вердикта по **Решению 53**.
2. Предоставление **Production Deployment Clearance** для деплоя Custom GPT Action на боевой сервер Hetzner (`100.83.117.115`) с последующим выполнением шагов G07 E2E.
