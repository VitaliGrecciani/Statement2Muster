# Протокол приёмочных испытаний: Установленное расширение и Managed Auth
**Основание:** Решения Главного Архитектора № 25 (`25_NEXT_BLOCK_MANAGED_EXTENSION_ACCEPTANCE_2026-09-15.md`), № 26 (`26_MANAGED_EXTENSION_REVIEW_2026-09-15.md`), № 27 (`27_MANAGED_EXTENSION_FOLLOWUP_2026-09-15.md`), № 28 (`28_MANAGED_EXTENSION_REVIEW_2026-09-15.md`) и № 29 (`29_MANAGED_EXTENSION_REVIEW_2026-09-15.md`)  
**Дата проведения:** 2026-09-15  
**Статус:** **100% PASSED (Все требования Решений 26, 27, 28 и 29 полностью выполнены и подтверждены воспроизводимыми доказательствами)**  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Контролирующие лица:** Главный Архитектор (OpenAI Codex CLI `codex.exe`, независимый локальный аудит кода и артефактов), Product Owner (Vitali Grecciani / Vito)  

---

## 1. Provenance, область пилота и фиксация артефактов (Traceability)

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Тестовый Git Commit** | Динамический `HEAD` ветки `main` | Включает все исправления по Решениям 27, 28 и 29 |
| **Backend Docker Image** | `statement2muster-api:1.0.5` | Неизменяемый образ, собран `--no-cache` на Hetzner Host `46.225.95.36:8100` |
| **Backend Image ID** | `sha256:039d44e6c728192b56a29bf025abfcbfff0158d71debb662dd16fac3c86b7b9c` | Зафиксирован в Docker Daemon Hetzner |
| **Backend Container ID** | `bf53f26bd990b8c1e471c3e5e94f528a4dc0e05796c62febb8fb7ed831c4895d` | Имя контейнера: `s2m-backend-api`, Health: `healthy` |
| **Docker Inspect Artifact** | `docs/managed_extension_acceptance/docker_inspect_sanitized.json` | Обезличенный JSON инспекции контейнера по строгому allowlist (секреты и `Config.Env` исключены) |
| **API URL** | `http://127.0.0.1:8000` | SSH-туннель к продуктивному контейнеру Hetzner (`127.0.0.1:8100`) |
| **Chrome Extension ZIP** | `dist/statement2muster-chrome-v1.0.2.zip` | Релизный архив расширения для Chrome (включает охват deadline на тело ответа и `window.__lastDownloadId`) |
| **Chrome ZIP SHA-256** | `AC771E0D538A5C1AEE747C39AF89A6DE7889125462CC6A1309C164B7DFDF09EB` | Актуальный хэш релизного архива |
| **Firefox Extension ZIP** | `dist/statement2muster-firefox-v1.0.2.zip` | Релизный архив расширения для Firefox |
| **Firefox ZIP SHA-256** | `3FFEC60A357FC240850AFCA5A3158C5FA7AFF0E2B90D92208B7A5BCA131D103E` | Хэш независимо верифицирован Архитектором |
| **Область пилота (Pilot Scope)** | **Chrome-only Pilot (Phase 1)** | Расширение Side Panel (MV3) для Chrome 123+. Firefox собран и хэширован, исключен из активной фазы браузерного тестирования согласно Решению 26/27/28/29. |
| **Тестовый браузер** | Playwright Chromium (v1234) / System Chrome 152 | Чистый изолированный профиль пользователя |
| **Тестовый аккаунт** | `vitogr24@gmail.com` | Tenant ID: `3af0965f-8ce1-429f-b896-24d4d1af6505` (PRO) |
| **Исполняемые раннеры тестов** | `tests/acceptance/run_chain1_chrome.py`<br>`tests/acceptance/run_chain2_hardening.py` | Зафиксированы непосредственно в репозитории проекта |

### Побитовая сверка файлов (Repo vs Hetzner Container `bf53f26bd990...`):
| Модуль бэкенда | SHA256 в локальном репозитории | SHA256 внутри живого Docker-контейнера | Статус |
| :--- | :--- | :--- | :---: |
| `backend/app/core/security.py` | `8dbaff1c946772df3edc38c8cbbd0d45b156450fbc372354d224030bd015a320` | `8dbaff1c946772df3edc38c8cbbd0d45b156450fbc372354d224030bd015a320` | **100% MATCH** |
| `backend/app/main.py` | `69a6e527720b278b4c59aef3eda721f4283fcab3d27778e7ef786a5fa9eae91f` | `69a6e527720b278b4c59aef3eda721f4283fcab3d27778e7ef786a5fa9eae91f` | **100% MATCH** |
| `backend/app/api/endpoints/auth.py` | `308d914dcfafc8d5a80f4feb9da67024b36f7f18345ef87b49a3d01a842407ad` | `308d914dcfafc8d5a80f4feb9da67024b36f7f18345ef87b49a3d01a842407ad` | **100% MATCH** |

---

## 2. Результаты Цепочки 1: Пользовательский путь и обработка отказов в установленном Chrome Extension

Тестирование выполнено раннером `tests/acceptance/run_chain1_chrome.py` в реальном браузере Chromium с загрузкой распакованного ZIP-дистрибутива в чистый изолированный профиль. Машинно-читаемые результаты зафиксированы в `chain1_chrome_results.json`.

### Сводная матрица шагов:

| № | Проверяемый шаг | Ожидаемый результат | Фактический результат | Скриншот / Артефакт | Статус |
| :-: | :--- | :--- | :--- | :--- | :-: |
| **1** | **Инициализация Sidepanel** | Панель открывается, статус-бейдж показывает «Server Engine aktiv», кнопка входа «Anmelden». | Бейдж: «Server Engine aktiv», кнопка «Anmelden» активна. Managed API доступен (v1.0.5). | `screenshots/01_sidepanel_initial.png` | **PASS** |
| **2** | **OTP Аутентификация из реального письма (Resend API)** | Запрос OTP, чтение кода из реального доставленного письма через Resend API без хардкода секретов в коде, ввод в UI, маскирование секрета в логах. | Запрос для `vitogr24@gmail.com`. Ключ Resend прочитан из `os.environ` / `.env`. Код извлечен из письма Resend (`17e1546d...`), секрет замаскирован (`23**53`). БД не опрашивалась. Сессия PRO сохранена. | `screenshots/02_login_modal_email.png`<br>`screenshots/03_login_modal_code_step.png`<br>`screenshots/04_authenticated_state.png` | **PASS** |
| **3** | **Неподменённое нативное скачивание Chromium и сверка проводок (Decision 28)** | Клик по кнопке скачивания без monkeypatching `chrome.downloads.download`, ожидание завершения через `chrome.downloads.search`, считывание файла с диска, проверка Windows-1252 и сверка 10 проводок. | Вызван штатный нативный `chrome.downloads.download({ saveAs: false })`. Chromium записал файл на диск (`playwright-artifacts-94GS11\828464b6...`). Считано 1489 байт. Кодировка: Windows-1252. Заголовок: `"EXTF"`. 10 из 10 проводок сверены по датам, суммам и назначениям с `Sparkasse_Kontoauszug_Januar2026.csv`. Soll = 4 465,00 €, Haben = 1 765,00 €, Net = +2 700,00 €. | `downloads/EXTF_Buchungsstapel.csv`<br>`screenshots/05_file_selected.png`<br>`screenshots/06_preview_rendered.png` | **PASS** |
| **4** | **Обработка ошибок UI, Дедлайн чтения тела и Восстановление следующего запроса (Decision 29)** | Корректное отображение ошибок 422, 401, 402, 429, сетевого сбоя, **таймаута до заголовков (4F)**, **таймаута зависшего тела ответа (4G)** и **успешного восстановления следующего запроса (4H)**. | • **422:** `Server-Fehler: Keine Buchungssätze in den bereitgestellten Dateien gefunden...`<br>• **401:** `Server-Fehler: Session abgelaufen. Bitte erneut anmelden.`<br>• **402:** `Server-Fehler: Kontingent erschöpft. Bitte upgraden Sie Ihren Plan.`<br>• **429:** `Server-Fehler: Zu viele Anfragen. Bitte warten Sie 60 Sekunden.`<br>• **Network immediate:** `Server-Fehler: Failed to fetch`.<br>• **4F Pre-Headers Timeout:** Сервер удерживает ответ 8 сек без заголовков. Прерывание клиентом через 3 сек, локальный парсер заблокирован, кнопка восстановлена.<br>• **4G Post-Headers Body Stream Timeout (Decision 29):** Сервер вернул HTTP 200 OK headers сразу, но удерживает chunked body stream открытым 8 сек. Клиентский `AbortController` прервал `response.arrayBuffer()` по дедлайну 3 сек. UI отобразил `Server-Fehler: Zeitüberschreitung: Der Server hat nicht innerhalb von 3s geantwortet.`, парсер заблокирован, кнопка восстановлена.<br>• **4H Subsequent Request Recovery (Decision 29):** Снят мок, повторно нажат `#convert-btn` — запрос штатно обработан живым бэкендом, в preview отрендерено 10 строк. | `screenshots/07_error_corrupted_file.png` | **PASS** |
| **5** | **Logout, Серверный Revocation, Cold Browser Restart и явный Re-Login** | Очистка storage, серверный отзыв токена (401), холодный перезапуск браузера, явное подтверждение повторного входа через UI. | Нажатие «Abmelden», токен удален из storage. Сервер отклонил старый токен (HTTP 401: `Token has been revoked. Please re-authenticate.`). Браузер закрыт и открыт с тем же профилем: сессия осталась завершенной («Anmelden»). **Шаг 5.2:** Выполнен повторный UI-вход с получением нового OTP из Resend API (`d282a0d9...`, `11**27`), сессия успешно восстановлена (`vitogr24`). | `screenshots/08_logged_out_state.png`<br>`screenshots/11_relogin_after_restart.png` | **PASS** |
| **6** | **Очистка истории и Storage Purge** | Удаление записей в UI и полная очистка финансовых данных из `chrome.storage.local`. | Записи сократились с 2 до 0. Хранилище проверено: `historyCount = 0`, `hasLastCsv = False`, `hasAccounts = False`. Все финансовые данные удалены. | `screenshots/09_history_view.png`<br>`screenshots/10_history_cleared.png` | **PASS** |

---

## 3. Результаты Цепочки 2: Отказоустойчивость, Fail-Closed Revocation и Мульти-процессорная изоляция

Тестирование проведено раннером `tests/acceptance/run_chain2_hardening.py` на изолированном стенде с синтетическими базами данных. Машинно-читаемый отчет зафиксирован в `chain2_fault_tolerance_results.json`.

### Сценарий 1: Fail-closed проверка отзыва токена
1. **Сбой/блокировка SQLite БД при пустом RAM-кэше:**
   - Выполнен сброс in-memory кэша (`_revoked_tokens.clear()`).
   - При инъекции `sqlite3.OperationalError` функция `is_token_revoked()` немедленно выбрасывает `HTTPException(status_code=503, detail="Revocation registry unavailable. Operation rejected for security.")`.
   - Вызов `/api/v1/convert` во время сбоя базы возвращает клиенту **HTTP 503 Service Unavailable**.
2. **Восстановление БД:**
   - После восстановления БД подтвержденный отозванный токен возвращает **HTTP 401 Unauthorized**.
3. **Истечение записи в RAM-кэше (`exp <= now`):**
   - В RAM-кэш помещена истёкшая запись (`exp = now - 10`).
   - При инъекции `OperationalError` в SQLite функция `is_token_revoked()` удаляет истёкшую запись и **продолжает проверку реестра SQLite**, получая ошибку и выбрасывая **HTTPException(503)** (обход проверки полностью устранен).
   - При доступной БД истёкшая запись RAM-кэша проваливается в SQLite и подтверждает статус отзыва токена (**True / 401**).
4. **Статус:** **PASS**.

### Сценарий 2: Реальная изоляция независимого OS-процесса
1. Токен отозван через эндпоинт `/api/v1/auth/logout` и персистентно сохранен в таблице `revoked_tokens`.
2. Запущен **настоящий независимый OS-подпроцесс Python** (`subprocess.run`) с абсолютно изолированным адресным пространством и пустой памятью.
3. Подпроцесс выполнил проверку токена через SQLite и подтвердил статус отзыва: `SUBPROCESS_REVOKED:True` (код возврата `0`).
4. **Статус:** **PASS**.

### Сценарий 3: Идемпотентность миграций и последующие операции
1. Создана легаси-схема v1 без колонок `tenants.version`, `entitlements.payment_intent`, `usage_reservations.request_hash` с предзаполненными данными.
2. Выполнен 1-й запуск миграции `init_db()`: колонки добавлены динамически, целостность сохранена.
3. Выполнены 2-й и 3-й запуски `init_db()`: подтверждена 100% идемпотентность (no-op, 0 ошибок).
4. **Последующие операции на мигрированной БД:**
   - OTP-вход выполнен успешно, выдан PRO JWT.
   - Конвертация в JSON выверила 10 транзакций.
   - DATEV EXTF экспорт сгенерировал валидный файл Windows-1252 (12 строк, 10 проводок).
5. **Статус:** **PASS**.

### Сценарий 4: Ошибки воркера и изоляция границы безопасности
1. Поврежденный бинарный файл обработан с кодом **HTTP 422**.
2. Последующий валидный запрос обработан в штатном режиме (**HTTP 200**).
3. Отозванный токен отсекается middleware на границе (**HTTP 401**), не допуская нагрузку на воркеры.
4. **Статус:** **PASS**.

---

## 4. Дефекты и внесенные исправления по Решению 29

1. **Обезличивание Docker Inspect по строгому Allowlist:**
   - *Было:* В `docker_inspect_105.json` попал блок `Config.Env`.
   - *Стало:* Файл удален. Создан `docs/managed_extension_acceptance/docker_inspect_sanitized.json`, содержащий строго разрешенные метаданные (`Id`, `Image`, `Created`, `State`, `Mounts`, `HostConfig.Binds`, `PortBindings`, `Ports`, `Labels`). `Config.Env` исключен полностью (`"Env_Policy": "SANITIZED: Environment variables excluded per Decision 29 security policy"`).
   - *Верификация:* Проверен локально — 0 секретов.

2. **Распространение Deadline таймаута на чтение тела ответа (`extension/app.js`):**
   - *Было:* `clearTimeout(timeoutId)` вызывался в блоке `finally` вокруг `await fetch()`, оставляя `response.arrayBuffer()` и `response.json()` без таймера.
   - *Стало:* Весь цикл чтения (получение заголовков + `response.arrayBuffer()` / `response.json()`) объединен в единый `try/catch/finally` блок под защитой `AbortController`. Таймер очищается в общем финальном блоке.
   - *Верификация:* Добавлена проба 4G (сервер отправляет заголовки 200 OK и удерживает body stream). Подтверждено, что клиент прерывает чтение тела ровно по истечении 3с, выводит сообщение об ошибке, не допускает скрытого фоллбэка и восстанавливает кнопку.

3. **Проверка восстановления следующего запроса (Проба 4H):**
   - *Было:* После сбоя по таймауту не проверялась возможность немедленного выполнения следующего запроса.
   - *Стало:* В раннер добавлен шаг 4H: после таймаута тело разблокируется, и отправляется валидная выписка. Запрос успешно обрабатывается бэкендом, в UI рендерится 10 строк предпросмотра.

---

## 5. Итоговая матрица соответствия Решениям 25, 26, 27, 28 и 29

| Пункт требования | Статус | Доказательство |
| :--- | :---: | :--- |
| **P1: Обезличивание Docker inspect и безопасность секретов** | **ВЫПОЛНЕНО** | `docker_inspect_105.json` удален. `docker_inspect_sanitized.json` по строгому allowlist без `Config.Env`. Репозиторий проверен — 0 ключей/секретов. |
| **Распространение Deadline на тело ответа** | **ВЫПОЛНЕНО** | `extension/app.js`: общий `try/catch/finally` охватывает `fetch` + `arrayBuffer` + `json`. Проба 4G PASS (3с аборт зависшего потока тела). |
| **Восстановление следующего запроса** | **ВЫПОЛНЕНО** | Проба 4H PASS: следующий запрос после таймаута успешно отрендерил 10 строк в preview. |
| **Неподменённый нативный download** | **УТВЕРЖДЕНО АРХИТЕКТОРОМ (Р29)** | `chrome.downloads.download({ saveAs: false })`, статус `complete` через `downloads.search`, считывание файла с диска, 10/10 проводок сверены. |
| **Fail-closed revocation и мульти-процессорность** | **УТВЕРЖДЕНО АРХИТЕКТОРОМ (Р28/29)** | Unit-тесты 6/6 PASS, Chain 2 4/4 PASS: 503 при сбое SQLite, независимый OS-подпроцесс, идемпотентность миграций. |
| **Оставшиеся открытые замечания** | **0** | Все замечания Решения 29 закрыты в полном объёме с предоставлением воспроизводимых доказательств. |

**Заключение:** Все технические, архитектурные требования и критерии безопасности Решений 25, 26, 27, 28 и 29 Главного Архитектора выполнены в полном объёме. Продукт готов к выпуску официального вердикта **Full GO**.
