# Запрос на официальный аудит Главного Архитектора (Codex CLI)
## Проект: Statement2Muster — Custom GPT Action & OpenAPI 3.1 Integration
**Дата:** 26 сентября 2026 г.  
**Инженер-исполнитель:** Antigravity (Gemini)  
**Product Owner:** Vitali Grecciani (Vito)  
**Инстанция аудита:** Главный Архитектор (OpenAI Codex CLI `codex.exe`)

---

### 1. Контекст и цели реализации
Для захвата органического поискового трафика в экосистеме OpenAI GPT Store и привлечения предпринимателей, бухгалтеров и стартапов DACH-региона спроектирован и реализован официальный **Custom GPT / ChatGPT Action** для сервиса **Statement2Muster** («Statement2Muster • DATEV & BMD Auszugskonverter»).

Пользователь загружает выписку (PDF, CSV или текст от American Express, Wise, PayPal, Sparkasse и др.) прямо в окно ChatGPT. Ассистент извлекает данные и через OpenAPI Action обращается к бэкенду Statement2Muster. Бэкенд выполняет строгую бухгалтерскую валидацию, собирает канонический файл **DATEV EXTF 700** (Windows-1252, Soll/Haben, SKR03/SKR04) или **BMD NTCS 5.1** и возвращает его пользователю как в виде прямой временной ссылки на скачивание, так и в виде base64-пейлоуда для моментального скачивания прямо из чата.

---

### 2. Техническая реализация и архитектурные решения

1. **Эндпоинты в `backend/app/api/endpoints/gpt_action.py` (с проксированием в `gpt.py`):**
   - `POST /v1/gpt/convert` и `POST /api/v1/gpt/convert`:
     * Принимает структурированный массив `transactions: List[GptTransactionItem]`, `file_base64` (base64-encoded PDF/CSV) или `raw_content`.
     * При передаче бинарного файла или текста выполняет изоляционный прогон через `parser_supervisor.parse_file` в отдельном дочернем ОС-процессе (C07, OOM-guard 512 MiB, таймаут 30 секунд).
     * Конвертирует суммы в целочисленные центы (`amount_cents`) без потерь и float-дрейфа.
     * Автоматически расставляет бухгалтерские признаки Soll ('S' — приход/Gutschrift) и Haben ('H' — расход/Lastschrift) на активных счетах.
     * Генерирует байтовый поток в кодировке Windows-1252 с окончаниями строк CRLF.
     * Формирует финансовую сводку: количество проводок, сумма дебета, кредита, сальдо периода.
     * Возвращает как временную ссылку на скачивание `download_url`, так и `file_base64` для моментального встраивания файла в чат.
   - `GET /v1/gpt/download/{download_id}` и `GET /api/v1/gpt/download/{download_id}`:
     * Отдает файл прямо из RAM с заголовками:
       `Content-Disposition: attachment; filename="..."`
       `Content-Type: text/csv; charset=windows-1252`
       `Cache-Control: no-store, no-cache, must-revalidate, private`
       `X-Zero-Retention: enforced-in-memory-only`
   - `POST /v1/gpt/check-license` и `POST /api/v1/gpt/check-license`:
     * Позволяет боту мгновенно валидировать ключ или email пользователя прямо во время диалога.

2. **Соблюдение инварианта Zero Durable Storage (ADR-001):**
   - Файлы пользователей **не сохраняются на диск сервера ни на миллисекунду**.
   - Используется `BoundedMemoryCache` в оперативной памяти (`ttl_seconds=1800` / 30 минут, `max_bytes=30 MiB`, `max_entries=300`).
   - Активный сборщик мусора очищает истекшие записи, предотвращая утечки памяти.

3. **Схема монетизации и Free-Tier квоты (3 бесплатных выписки):**
   - Free Tier: ровно **3 бесплатные выписки** на сессию/email пользователя (`MAX_FREE_CONVERSIONS = 3`).
   - При исчерпании лимита бэкенд возвращает статус `status: "limit_reached"`, дружелюбное уведомление и проверенные ссылки Stripe:
     * Starter (€4.90 / месяц) — `https://buy.stripe.com/cNi6oH9vDcnL2v0dWTebu03`
     * Business PRO (€29.00 / месяц) — `https://buy.stripe.com/14AfZh6jr2NbedI6urebu04`
     * Lifetime (€89.00 разово) — `https://buy.stripe.com/14A00j6jrfzX2v0bOLebu05`
   - Параметр `license_key` или email с активной подпиской в базе данных снимает любые ограничения (`is_unlimited: true`).

4. **Артефакты интеграции:**
   - [docs/chatgpt/openapi.yaml](file:///C:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/chatgpt/openapi.yaml) — каноническая OpenAPI 3.1.0 спецификация.
   - [docs/chatgpt/openapi.json](file:///C:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/chatgpt/openapi.json) — JSON-эквивалент для импорта в OpenAI GPT Builder.
   - [docs/chatgpt/GPT_INSTRUCTIONS.md](file:///C:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/chatgpt/GPT_INSTRUCTIONS.md) — системный промпт, обработка квот, инструкция по импорту в DATEV и пошаговый гайд сборки Custom GPT.
   - [docs/chatgpt/icon_512.png](file:///C:/Users/zorik/Documents/Obsidian%20Vault/10_Projects/Statement2Muster/docs/chatgpt/icon_512.png) — аватарка 512x512 для профиля в GPT Store.

---

### 3. Результаты верификации и тестирования

1. **Автотесты (pytest):**
   - Специализированный тестовый сьют `backend/test_gpt_action.py` (8 тестов: DATEV EXTF Windows-1252, BMD NTCS 5.1, RAM-only download, 404 on expire, цикл исчерпания 3 бесплатных выписок, снятие лимитов по лицензионному ключу, валидация ключей в check-license, разбор base64 через `parser_supervisor`).
   - Полный регрессионный прогон всего бэкенда: **42 из 42 тестов пройдены успешно (100% PASS)**.

---

### 4. Вопросы Главному Архитектору для вердикта GO / NO-GO:
1. Является ли спроектированная архитектура (RAM-only download cache + OpenAPI 3.1 action + 3-statement free limit + C07 process supervisor) полностью соответствующей требованиям Zero Durable Storage, ADR-001 и GDPR?
2. Соответствует ли OpenAPI-спецификация стандартам OpenAI ChatGPT Actions (параметры, типы, description, обработка ошибок, отсутствие авторизации для Free Tier)?
3. Готово ли решение к публикации в OpenAI GPT Store и выдаче вердикта **GO**?
