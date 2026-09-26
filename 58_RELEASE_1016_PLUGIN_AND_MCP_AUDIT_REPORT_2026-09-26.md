# Отчет Инженера-исполнителя Главному Архитектору: Релиз 1.0.16 (OpenAI Plugin Manifest & Model Context Protocol MCP Server)

**Дата:** 26 сентября 2026 г.  
**Контекст аудита:** Внеочередной архитектурный аудит релиза 1.0.16 и переход на стандарт Plugins/MCP  
**Git HEAD:** `5bcfe4a` (ветка `main`, синхронизировано с `origin/main`)  
**Окружение:** Hetzner Cloud (46.225.95.36 / Frankfurt am Main), Docker контейнер `s2m-backend-api`  
**Статус контейнера:** `healthy` (image `statement2muster-api:1.0.16`)  
**Product Owner:** Vitali Grecciani (Vito)  
**Implementation Engineer:** Antigravity (Gemini)  
**Главный Архитектор:** Внешняя аудиторская инстанция на базе OpenAI Codex CLI  

---

## 1. Основания релиза и нормативный контекст

В рамках подготовки к выводу из эксплуатации устаревающего формата Custom GPTs (официальный дедлайн OpenAI — 11 декабря 2026 г., прекращение публичного магазина GPT для личных аккаунтов с августа 2026 г.) и согласно распоряжению Product Owner выполнен переход Statement2Muster на открытую архитектуру **OpenAI Plugins** и **Model Context Protocol (MCP)**.

---

## 2. Ключевые изменения в релизе 1.0.16

### 2.1. Официальный манифест плагина OpenAI (`/.well-known/ai-plugin.json`)
- Развернут эндпоинт `GET /.well-known/ai-plugin.json` (а также алиасы `/ai-plugin.json` и `/api/v1/plugin-manifest.json`).
- Манифест содержит:
  - `schema_version`: `"v1"`
  - `name_for_model`: `"statement2muster"`
  - `api`: `{"type": "openapi", "url": "https://api.statement2muster.com/openapi.json"}`
  - `logo_url`: `"https://statement2muster.com/logo.png"`
  - `legal_info_url`: `"https://statement2muster.com/datenschutz.html"`
  - Заголовки CORS: `Access-Control-Allow-Origin: *`.

### 2.2. Сервер Model Context Protocol (MCP JSON-RPC 2.0)
- Реализован шлюз `POST /api/v1/mcp` и `POST /mcp` по спецификации `protocolVersion: 2024-11-05`.
- Поддерживаемые методы:
  - `ping` -> пустой результат `{}`.
  - `initialize` -> рукопожатие, объявление серверных возможностей (`tools: {"listChanged": false}`) и `serverInfo`.
  - `notifications/initialized` -> `204 No Content`.
  - `tools/list` -> регистрация инструмента `convert_statement` со строгой JSON-схемой параметров (банк, формат DATEV/BMD, счет, сессия, массив транзакций).
  - `tools/call` -> исполнение вызова `convert_statement` через канонический сервис `app.api.endpoints.gpt_action.gpt_convert_statement`:
    * Сквозное соблюдение Zero Durable Storage (хранение только в ОЗУ с TTL 1800s);
    * Идемпотентность по SHA-256 хэшу и защита от повторных списаний квот;
    * Форматирование ответа в человеко- и машиночитаемый Markdown с финансовой сводкой и защищенным URL скачивания;
    * Обработка превышения демо-лимита (`limit_reached`) с выдачей ссылок на тарифы Stripe.

### 2.3. Исправление дефекта UX браузерного расширения
- **Проблема:** При разворачивании расширения во весь экран создавалась новая вкладка, но боковая панель (Side Panel) оставалась открытой, создавая на экране две одновременные копии приложения.
- **Решение:**
  - Внедрен вызов `window.close()` в контексте боковой панели при вызове полноэкранной вкладки.
  - Добавлена плавная анимация раскрытия контейнера (`transition: max-width 0.28s, animation: fadeInTab`).
  - Реализован двухсторонний переключатель: в полноэкранном режиме кнопка трансформируется в `[⇥] In Seitenleiste andocken`, позволяя вернуть боковую панель и закрыть вкладку.

### 2.4. Фирменный анимированный векторный брендинг (Quiver SVG)
- На сайт (`landing/logo_s2m.svg`) и в расширение (`extension/logo.svg`) внедрен оригинальный векторный анимированный SVG (SMIL), поочередно пульсирующий буквами S-2-M и запускающий неоновый луч по финансовой направляющей.
- Внедрен механизм сброса кэша `logo_s2m.svg?v=quiver` в `landing/index.html`.

---

## 3. Результаты верификации и доказательная база

### 3.1. Автоматизированные тесты
- Запущен полный регрессионный сьют: **28 из 28 тестов пройдены успешно (100% PASS)**:
  - `backend/test_plugin_and_mcp.py`: 5/5 PASS (манифест, GET-статус, `initialize`, `tools/list`, `tools/call`).
  - `backend/test_gpt_action.py`: 23/23 PASS (квоты, изолированность тенантов, Windows-1252 ANSI, защита от дрифта плавающей точки, валидация дат).

### 3.2. Сквозные пробы по боевому HTTPS (`https://api.statement2muster.com`)
1. **Healthcheck:**
   ```json
   GET /api/v1/health -> 200 OK {"status": "ok", "message": "Statement2Muster API is running", "version": "1.0.16"}
   ```
2. **Plugin Manifest:**
   ```json
   GET /.well-known/ai-plugin.json -> 200 OK (schema_version: "v1", name_for_model: "statement2muster")
   ```
3. **MCP Initialize:**
   ```json
   POST /api/v1/mcp {"method": "initialize"} -> 200 OK (protocolVersion: "2024-11-05", tools available)
   ```
4. **MCP Tools List:**
   ```json
   POST /api/v1/mcp {"method": "tools/list"} -> 200 OK (tool: convert_statement)
   ```
5. **MCP Tool Live Execution:**
   ```json
   POST /api/v1/mcp {"method": "tools/call", "params": {"name": "convert_statement", ...}}
   -> 200 OK, isError: false
   -> Generated URL: https://api.statement2muster.com/v1/gpt/download/s2m_gpt_593a3c9f4d8848369f396c0e91e45f3d
   ```

---

## 4. Запрос к Главному Архитектору

Просим Главного Архитектора провести системный аудит релиза **1.0.16** и вынести официальное решение касательно:
1. Соответствия реализации стандарту OpenAI Plugin Manifest и Model Context Protocol (MCP JSON-RPC 2.0).
2. Соблюдения требований Zero Durable Storage и архитектурных инвариантов ADR-001.
3. Фиксации Решения 58 в аудиторском реестре проекта Statement2Muster.
