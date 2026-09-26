# G07: Отчёт о промышленном развёртывании и Live Acceptance приёмке Custom GPT Action

**Дата:** 2026-09-26  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Инстанция аудита:** Главный Архитектор (OpenAI Codex CLI, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`)  
**Основание:** Решение 53 («Custom GPT Action: Production Deployment Clearance для G07»)  
**Целевой хост:** Hetzner Cloud (`46.225.95.36` / `100.83.117.115`)  
**Публичный endpoint:** `https://api.statement2muster.com`

---

## 1. Идентификация артефактов и целостность сборки (Gate G07.1)

| Параметр | Значение | Примечание |
|---|---|---|
| **Build Source Commit** | `271d9ed3e6b90968bc1a9bb56ce8c7522e397603` | Базовый коммит реализации R52-1–R52-3 |
| **Audit HEAD Commit** | `8533cd3d08257078015372eaee2214d172314258` | HEAD аудита Решения 53 (дерево `backend` идентично) |
| **Release Tag / Version** | `1.0.15` | Инкремент с `1.0.14` |
| **Docker Image Name** | `statement2muster-api:1.0.15` | Собрано локально на хосте Hetzner |
| **Docker Image ID** | `sha256:cbdd33f0cfdb6c70d2b4e3d024b8399183c6e937f550193d1d695f3c20178b75` | Неизменяемый хэш контейнерного образа |
| **Container ID** | `8abaec76a4a74644d4e51ab5c4acf8171820e78fcf210e2f41a8edccc25b1511` | Имя контейнера: `s2m-backend-api` |
| **Container Status** | `Up / healthy` | Healthcheck опрашивает `/healthz` каждые 30s |
| **Source Manifest Match** | **33 / 33 файлов (100% совпадение)** | Пофайловое SHA-256 сравнение дерева `/app/app` с Git HEAD |

Доказательные файлы:
- `docs/gpt_action_acceptance/repo_source_manifest.json`
- `docs/gpt_action_acceptance/container_source_manifest.json`
- `docs/gpt_action_acceptance/source_comparison.json`
- `docs/gpt_action_acceptance/docker_inspect_1015_sanitized.json` (все секреты маскированы `[REDACTED_SECRET]`)

---

## 2. Результаты E2E Live Acceptance тестирования на синтетических данных (Gate G07.2–G07.4)

Все тесты выполнены через внешний публичный HTTPS-шлюз `https://api.statement2muster.com` с валидными криптографическими JWT RS256 (`iss: statement2muster.com`, `aud: statement2muster-api`).

### Сводная таблица тестов

| # | Сценарий / Тест | Метод и путь | Ожидаемый результат | Фактический результат | Статус |
|---|---|---|---|---|---|
| **6.1** | Проверка жизнеспособности сервиса | `GET /healthz` | HTTP 200, status: healthy, version: 1.0.15, zero_retention: enforced | HTTP 200, `version: "1.0.15"`, `zero_retention: "enforced"`, `database: "connected"` | **PASS** |
| **6.2** | Спецификация OpenAPI для GPT Action | `GET /openapi.json` | HTTP 200, регистрация `/v1/gpt/convert` и `/v1/gpt/download/{download_id}` | HTTP 200, оба маршрута строго зарегистрированы и доступны | **PASS** |
| **6.3** | Конвертация выписки (DATEV EXTF) | `POST /v1/gpt/convert` (Tenant A) | HTTP 200, status: success, net_balance: €3210.50, download_id | HTTP 200, `download_id: s2m_gpt_933bf540...`, `net_balance: 3210.50`, `count: 2` | **PASS** |
| **6.4** | Скачивание из RAM-кэша (Zero-Retention) | `GET /v1/gpt/download/{download_id}` | HTTP 200, `Content-Type: text/csv; charset=windows-1252`, `X-Zero-Retention: enforced-in-memory-only`, валидный DATEV EXTF | HTTP 200, заголовок `X-Zero-Retention: enforced-in-memory-only` присутствует, 4 строки, кодировка Windows-1252, заголовок `"EXTF";700;21;"Buchungsstapel";12;`, SHA256: `05a8d7cb17c50ee60cfe3d5196a8802d9d5feb8e397bfd0e1fb3595e132b98e8` | **PASS** |
| **6.5** | Идемпотентный повтор (Replay) | `POST /v1/gpt/convert` (Tenant A, повтор) | HTTP 200, идентичный download_id, побайтно идентичный ответ, без списания квоты | HTTP 200, тело ответа побайтно совпадает, тот же `download_id`, парсер повторно не вызывался | **PASS** |
| **6.6** | Изоляция владельца кэша (R52-1) | `POST /v1/gpt/convert` (Tenant B, исчерпан) | HTTP 429 Too Many Requests, утечка чужого результата и download_id заблокирована | HTTP 429: *"Starter plan monthly quota of 20 statements reached. Upgrade to Business PRO for unlimited conversions."* Чужой кэш недоступен. | **PASS** |
| **6.7** | Анонимный Demo Tier (4 шага) | `POST /v1/gpt/convert` (Anon Session) | Шаги 1–3: HTTP 200 success; Шаг 4: HTTP 200 limit_reached | Шаг 1: `success`<br>Шаг 2: `success`<br>Шаг 3: `success`<br>Шаг 4: `limit_reached` (конвертация заблокирована, лимит 3 выписок исчерпан) | **PASS** |
| **6.8** | Усечение ошибок валидации (F03) | `POST /v1/gpt/convert` (600 невалидных строк) | HTTP 422 Unprocessable Entity, длина тела < 2000 символов, ошибка `too_many_errors` | HTTP 422, длина ответа 1316 символов (< 2000), 6 структурных ошибок, последняя: `too_many_errors` | **PASS** |
| **6.9** | Большой пакет (Large Batch) | `POST /v1/gpt/convert` (Tenant C, 150 строк) | HTTP 200, inline base64 исключён (`file_base64: null`), выдана ссылка на скачивание | HTTP 200, `file_base64: null`, `download_url` присутствует, `transaction_count: 150` | **PASS** |
| **6.10**| Аудит биллинга в БД (Ledger Audit) | Проверка таблицы `usage_reservations` в SQLite | Tenant A: 1 unit COMMITTED; Tenant B: 20 units COMMITTED (предопределено); Tenant C: 1 unit COMMITTED | Все резервации строго соответствуют фактическому потреблению: лишних или потерянных единиц нет. | **PASS** |

Доказательный JSON с полными телами ответов и замерами:
- `docs/gpt_action_acceptance/g07_live_acceptance_results.json`

---

## 3. Подтверждение способа доставки файлов (Gate G07.4)

- В полном соответствии с директивой Решения 53 (п. 4), доставка файлов документируется как **Link-only**:
  * Файлы генерируются на лету и сохраняются **исключительно в оперативной памяти (RAM)** с TTL 1800 секунд (30 минут).
  * На диск сервера Hetzner не записывается ни одного байта выписок клиентов (`zero-retention: enforced`).
  * Скачивание осуществляется по строгому одноразовому токенизированному URL `/v1/gpt/download/{download_id}` с возвратом заголовка `X-Zero-Retention: enforced-in-memory-only`.
  * Никаких неподдерживаемых нативных файловых протоколов GPT Actions не заявляется.

---

## 4. Резюме для Главного Архитектора

1. Все требования, выдвинутые в **Решении 53 (Раздел 4)** для прохождения шлюза G07, **выполнены в полном объёме**.
2. Образ `statement2muster-api:1.0.15` успешно собран, развёрнут и верифицирован на проде Hetzner.
3. Пофайловое совпадение с исходным деревом Git — **100% (33/33)**.
4. Все 10 сценариев Live Acceptance тестирования завершились со статусом **PASS**.
5. Запрашивается официальный вердикт Главного Архитектора: **G07 Acceptance Clearance (GO)**.
