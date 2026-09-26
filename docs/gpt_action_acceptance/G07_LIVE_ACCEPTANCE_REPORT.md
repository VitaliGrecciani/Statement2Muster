# G07: Отчёт об устранении замечаний Решения 54 и Live Acceptance приёмке Custom GPT Action

**Дата:** 2026-09-26  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Инстанция аудита:** Главный Архитектор (OpenAI Codex CLI, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`)  
**Основание:** Решение 53 и Решение 54 («Custom GPT Action: аудит G07 на версии 1.0.15»)  
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
| **Container ID** | `5cb4872ffdf07ddecbe77cf117c17ef5f340a35e80d8b7b8298ba003673ad81b` | Имя контейнера: `s2m-backend-api` |
| **Container Status** | `Up / healthy` | Healthcheck опрашивает `/healthz` каждые 15s |
| **Source Manifest Match** | **33 / 33 файлов (100% совпадение)** | Пофайловое SHA-256 сравнение дерева `/app/app` с Git HEAD |

Доказательные файлы:
- `docs/gpt_action_acceptance/repo_source_manifest.json`
- `docs/gpt_action_acceptance/container_source_manifest.json`
- `docs/gpt_action_acceptance/source_comparison.json`
- `docs/gpt_action_acceptance/docker_inspect_1015_sanitized.json` (все секреты маскированы `[REDACTED_SECRET]`)

---

## 2. Закрытие замечаний Решения 54

### 2.1. Закрытие R54-3: Восстановление 10-минутной политики JWT и лимита 10 MiB
- В `docker-compose.prod.yml` и runtime контейнера на проде Hetzner установлены:
  * `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10` (ранее было 43200 — 30 суток).
  * `MAX_FILE_SIZE_BYTES=10485760` (10 MiB, согласовано с описанием в Actions OpenAPI).
- Контейнер пересоздан, inspect зафиксирован в `docker_inspect_1015_sanitized.json`.
- Проверена штатная выдача JWT через серверную функцию `create_access_token`:
  * `exp - iat = 600` секунд (строго 10 минут).
  * Истекший токен (`exp < now`) возвращает **HTTP 401 Unauthorized** (`"Token expired. Please re-authenticate."`).

### 2.2. Закрытие R54-2: Детальная сверка CSV, CRLF, Windows-1252, восстановление и вытеснение
- Тестовый HTTP-раннер размещён в `tests/acceptance/run_g07_live_acceptance.py`.
- **Исключено извлечение private RSA ключа через SSH:** токены генерируются исключительно штатным серверным вызовом `create_access_token` внутри контейнера без передачи секретов клиенту.
- **Сверка содержимого скачанного CSV (`downloaded_statement_sample.csv`):**
  * Кодировка: строго `windows-1252`.
  * Переносы строк: строго `CRLF` (`\r\n`), одиночные байты `\n` или `\r` отсутствуют.
  * SHA-256 скачанного файла: `cc0861fc934c562a953acb0ea9c728d504a628ec33e11f81ee3232553ae70357`.
  * Заголовок 1: `"EXTF";700;21;"Buchungsstapel";12;...`
  * Заголовок 2: `"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";...`
  * Строка 1: `189,50` Haben (`H`, Lastschrift/Abgang Bank 1200), Konto `1200`, Belegdatum `1503`, Belegfeld 1 `INV-2026-991`, Buchungstext `AWS Cloud Services EMEA`.
  * Строка 2: `3400,00` Soll (`S`, Gutschrift/Zugang Bank 1200), Konto `1200`, Belegdatum `1803`, Belegfeld 1 `RE-8821`, Buchungstext `Kundenhonorar Softwareaudit`.
  * Сальдо и обороты: дебет `-189.50 EUR`, кредит `3400.00 EUR`, сальдо `+3210.50 EUR`.
- **Сценарий Error & Recovery:**
  * Запрос с невалидной датой (`2026-13-45`) возвращает **HTTP 422 Unprocessable Entity**.
  * Последующий валидный запрос в рамках той же сессии успешно обрабатывается (**HTTP 200 OK**).
- **Сценарий File Eviction & 410 Replay:**
  * Операция успешно конвертируется (**HTTP 200 OK**).
  * Выполняется сброс оперативной памяти контейнера (Zero Durable Retention).
  * Попытка скачивания по ссылке возвращает **HTTP 404 Not Found**.
  * Повторный идемпотентный запрос той же операции возвращает **HTTP 410 Gone** (`"Das Ergebnis für diesen Vorgang ist im flüchtigen RAM-Zwischenspeicher abgelaufen..."`).
  * Проверка SQLite ledger подтверждает: в `usage_reservations` осталась ровно **1 запись COMMITTED**, повторного списания квоты не произошло.

### 2.3. Исправление формулировок и параметров (Раздел 4 Решения 54)
- URL скачивания задокументирован как **временный токенизированный bearer-link, не одноразовый**: чтение из памяти не удаляет запись, срок жизни ограничен TTL 1800s или перезапуском.
- Интервал проверки здоровья контейнера (Healthcheck interval) зафиксирован как **15 секунд**.
- Результаты сохранены в сводном JSON `docs/gpt_action_acceptance/g07_live_acceptance_results.json`.

---

## 3. Сводная таблица результатов Live Acceptance (13 сценариев)

| # | Сценарий / Тест | Метод и путь | Ожидаемый результат | Фактический результат | Статус |
|---|---|---|---|---|---|
| **5.1** | Проверка жизнеспособности сервиса | `GET /healthz` | HTTP 200, healthy, version: 1.0.15, zero_retention: enforced | HTTP 200, `version: "1.0.15"`, `zero_retention: "enforced"`, `database: "connected"` | **PASS** |
| **5.2** | Спецификация OpenAPI для GPT Action | `GET /openapi.json` | HTTP 200, регистрация `/v1/gpt/convert` и `/v1/gpt/download/{download_id}` | HTTP 200, оба маршрута строго зарегистрированы и доступны | **PASS** |
| **5.3** | Политика срока жизни JWT (R54-3) | Проверка полей `iat`/`exp` и отказ expired | Срок 600 секунд (10 мин), отказ просроченного 401 | `exp - iat = 600s`, просроченный токен возвращает HTTP 401 Unauthorized | **PASS** |
| **5.4** | Конвертация выписки (DATEV EXTF) | `POST /v1/gpt/convert` (Tenant A) | HTTP 200, status: success, net_balance: €3210.50, download_id | HTTP 200, `download_id: s2m_gpt_f954...`, `net_balance: 3210.50`, `count: 2` | **PASS** |
| **5.5** | Скачивание и поколоночный аудит CSV | `GET /v1/gpt/download/{download_id}` | HTTP 200, Windows-1252, CRLF, точные проводки, суммы и счета | HTTP 200, CRLF подтверждён, Windows-1252, 189,50 H и 3400,00 S на счёте 1200, SHA256: `cc0861fc...` | **PASS** |
| **5.6** | Идемпотентный повтор (Replay) | `POST /v1/gpt/convert` (Tenant A, повтор) | HTTP 200, идентичный download_id, побайтно идентичный ответ, без списания квоты | HTTP 200, тело ответа побайтно совпадает, тот же `download_id`, без повторного списания | **PASS** |
| **5.7** | Ошибка и восстановление (R54-2) | `POST /v1/gpt/convert` (невалидный -> валидный) | HTTP 422 на невалидную дату, затем HTTP 200 на валидную дату | HTTP 422 -> HTTP 200 success | **PASS** |
| **5.8** | Вытеснение файла и 410 Replay (R54-2) | Конвертация -> RAM purge -> Download / Replay | Download: 404; Replay: 410 Gone, без нового списания | Download: HTTP 404; Replay: HTTP 410 Gone (`abgelaufen`), в ledger строго 1 COMMITTED | **PASS** |
| **5.9** | Изоляция владельца кэша (R52-1) | `POST /v1/gpt/convert` (Tenant B, исчерпан) | HTTP 429 Too Many Requests, утечка чужого результата и download_id заблокирована | HTTP 429: Starter quota reached. Чужой кэш недоступен. | **PASS** |
| **5.10**| Анонимный Demo Tier (4 шага) | `POST /v1/gpt/convert` (Anon Session) | Шаги 1–3: HTTP 200 success; Шаг 4: HTTP 200 limit_reached | Шаги 1–3: `success`; Шаг 4: `limit_reached` (лимит 3 выписок исчерпан) | **PASS** |
| **5.11**| Усечение ошибок валидации (F03) | `POST /v1/gpt/convert` (600 невалидных строк) | HTTP 422 Unprocessable Entity, длина тела < 2000 символов, ошибка `too_many_errors` | HTTP 422, длина ответа 1316 символов (< 2000), 6 структурных ошибок, последняя: `too_many_errors` | **PASS** |
| **5.12**| Большой пакет (Large Batch) | `POST /v1/gpt/convert` (Tenant C, 150 строк) | HTTP 200, inline base64 исключён (`file_base64: null`), выдана ссылка на скачивание | HTTP 200, `file_base64: null`, `download_url` присутствует, `transaction_count: 150` | **PASS** |
| **5.13**| Аудит биллинга в SQLite | Проверка таблицы `usage_reservations` в SQLite | Точные COMMITTED записи для каждого тестового арендатора без дублирования | Все записи соответствуют ожиданиям: Tenant A: 1; Tenant B: 20; Tenant C: 2; Tenant Exp: 1. | **PASS** |

---

## 4. Результаты фактического выполнения Builder E2E (Условие R54-1 — ЗАКРЫТО)

Тестирование проведено непосредственно в интерфейсе **ChatGPT Custom GPT Builder / Preview** против промышленного шлюза `https://api.statement2muster.com`:

1. **Идентификатор тестового GPT:**
   - Редактор: `https://chatgpt.com/gpts/editor/g-6ab7b524949881919d6f3ac8d6945deb`
   - ID GPT: `g-6ab7b524949881919d6f3ac8d6945deb`
   - Action ID: `g-b3708005d7e27157dcec71bad2832e4c8a6cd25c`
2. **Импортированная спецификация OpenAPI:**
   - Источник: `https://api.statement2muster.com/gpt-openapi.json`
   - SHA-256: `f6097b0b98048a4bef7f55bfd3fb15f8438a0e5d21967a52690a48937c12ee15`
   - Операции зарегистрированы: `convertStatement` (POST `/v1/gpt/convert`), `downloadConvertedFile` (GET `/v1/gpt/download/{download_id}`).
3. **Режим аутентификации:** `None` (штатный анонимный Demo Tier, отслеживание лимитов в оперативной памяти).
4. **Трассировка живых вызовов (зафиксирована в `BUILDER_E2E_TRACE.json` и логах Nginx):**
   - **Первая попытка (12:30:50 UTC):** ChatGPT передал невалидное имя поля (`"date"` вместо `"booking_date"`). Бэкенд строго отверг запрос с кодом **HTTP 422 Unprocessable Entity** (`"booking_date": Field required`).
   - **Автоматическое исправление (12:30:52 UTC):** ChatGPT скорректировал схему и отправил валидный запрос. Бэкенд вернул **HTTP 200 OK** (2906 байт). ChatGPT отобразил финансовую сводку:
     * *Erfolgreich in DATEV EXTF 700 konvertiert.*
     * *Soll -189,50 EUR · Haben 3.400,00 EUR · Saldo +3.210,50 EUR.*
     * Ссылка на скачивание: *DATEV-EXTF-Datei herunterladen* (TTL 30 минут).
   - **Проверка Replay (12:37:02 UTC):** По команде *«Wiederhole bitte dieselbe Konvertierung»* отправлен повторный запрос. Бэкенд вернул **HTTP 200 OK** (побайтно идентичные 2906 байт) из кэша. ChatGPT отобразил:
     * *Erneut erfolgreich in DATEV EXTF 700 konvertiert.*
     * Те же самые суммы и ссылки, без сбоев и без повторного списания квоты.
5. **Записи в логах Nginx (`/var/log/nginx/access.log`):**
   ```text
   172.199.137.82 - [26/Sep/2026:12:27:39 +0000] "GET /gpt-openapi.json HTTP/1.1" 200 13265 "-" "Mozilla/5.0... ChatGPT-User/1.0; +https://openai.com/bot"
   172.199.137.87 - [26/Sep/2026:12:30:50 +0000] "POST /v1/gpt/convert HTTP/1.1" 422 390 "-" "Mozilla/5.0... ChatGPT-User/1.0; +https://openai.com/bot"
   172.199.137.92 - [26/Sep/2026:12:30:52 +0000] "POST /v1/gpt/convert HTTP/1.1" 200 2906 "-" "Mozilla/5.0... ChatGPT-User/1.0; +https://openai.com/bot"
   172.199.137.92 - [26/Sep/2026:12:37:02 +0000] "POST /v1/gpt/convert HTTP/1.1" 200 2906 "-" "Mozilla/5.0... ChatGPT-User/1.0; +https://openai.com/bot"
   ```
6. **Графические доказательства сохранены:**
   - `docs/gpt_action_acceptance/chatgpt_builder_preview_overview.png`
   - `docs/gpt_action_acceptance/chatgpt_builder_preview_trace.png`
   - `docs/gpt_action_acceptance/chatgpt_builder_replay_trace.png`

---

## 5. Итоговое резюме для Главного Архитектора

1. Все три условия **Решения 54** закрыты в полном объёме:
   - **R54-1 (Builder E2E):** Выполнен реальный запуск в ChatGPT Builder Preview (ID: `g-6ab7b524949881919d6f3ac8d6945deb`), зафиксированы трассы 422, 200 и Replay 200 от бота `ChatGPT-User/1.0`.
   - **R54-2 (Файл, вытеснение, восстановление):** Все 13 сценариев в `tests/acceptance/run_g07_live_acceptance.py` пройдены со статусом PASS. Сверка CSV (Windows-1252, CRLF, проводки, суммы), Error & Recovery и 410 Replay при вытеснении подтверждены.
   - **R54-3 (Политика JWT и лимиты файлов):** Лимит 10 минут (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10`) и 10 MiB восстановлены и проверены на живом контейнере на Hetzner.
2. Все формулировки и параметры приведены в строгое соответствие с требованиями раздела 4 Решения 54.
3. Запрашивается официальное утверждение Главным Архитектором: **Окончательный вердикт G07 Acceptance Clearance (GO)**.
