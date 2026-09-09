# Statement2Muster — третья независимая проверка, 2026-09-09

**Решение: NO-GO сохраняется для пилота с реальными банковскими выписками и платного релиза.** Оснований подтвердить полное устранение 26 замечаний нет. Изменения исправляют ряд конкретных примеров предыдущего аудита, но не все обязательные критерии R0–R6. Несколько остающихся P1 воспроизведены независимо.

Это заключение относится к локальной сборке v1.0.2 с новыми хешами Chrome `A0D71C59…AAAECEC9`, Firefox `8E1A21E6…D6C4076A`. Все четыре хеша из сообщения Antigravity совпали; файлы обоих ZIP побайтово соответствуют исходникам. Хеши полностью записаны в [results.json](docs/audit_2026-09-09_round3/results.json).

**Итог по исходным A01–A31: 6 локально закрыты, 25 не закрыты полностью — 13 P1, 11 P2, 1 P3.** В предыдущей проверке было 5 закрытых: дополнительно закрывается конкретный дефект A10 — склейка PDF-строк. Частичные исправления остальных ID перечислены ниже и не обесцениваются этим итогом. Приоритеты и исходный смысл ID сохранены; A23 по-прежнему означает privacy/history, а не квоты.

## 1. Независимо подтверждённые улучшения

- `pytest backend/ -v`: **25 passed, 3 warnings in 2.41s**. Предупреждения — deprecated названия HTTP status constants, не причина NO-GO.
- Без OTP/с неверным OTP token endpoint возвращает 401; JWKS доступен и возвращает RSA key set.
- Повторный idempotency key с изменённым содержимым возвращает 409.
- Chunked body сверх byte budget и файл сверх per-file budget возвращают 413 в проверенном runtime.
- Обычный lifetime refund с payment_intent отменяет entitlement; приоритет paid над trial реализован; unpaid больше не выдаёт право в checked checkout path.
- `Waehrung`, S suffix, per-row IBAN и явные ERROR для некоторых невалидных значений добавлены.
- Блокировка известных unparsed files и DISCREPANCY появилась; Muster использует csv.writer, экранирует проверенную формулу `=1+1` в текстовом поле.
- DATEV S/H для Konto=активный банковский счёт исправлены; одно­годовой пакет 2025 получает FY=2025.
- Синтетическая PDF-операция теперь извлекается как **31.12.2025, SYNTHETIC SHOP, −10,00 EUR**; JS normalizeDate отклоняет 31.02. Firefox action handler вызывает sidebar один раз.
- Mock login handlers и reset до 5 удалены. Clear History теперь удаляет четыре ключа последнего экспорта из storage, хотя дальнейшая очистка UI падает.
- AVV существенно расширен: вместо двух общих разделов появились предмет/срок, категории, инструкции, конфиденциальность, TOMs, subprocessors, помощь и audit clauses.

## 2. Метод и ограничения

Новые доказательства сохранены отдельно от изменённых Antigravity старых probes: [docs/audit_2026-09-09_round3](docs/audit_2026-09-09_round3). Предыдущие отчёты и evidence не перезаписывались.

Выполнены ASGI-запросы через httpx, SQLAlchemy-проверки с отдельными сессиями, Node-выполнение реальных функций из extension с минимальными DOM/storage doubles, повтор PDF-пробы и сравнение ZIP. Все данные синтетические. Рабочая statement2muster.db не использовалась; новые SQLite-файлы созданы только в каталоге этой проверки. Stripe probes вызывают обработчик синтетических событий без сети: они проверяют семантику обработки, **не являются обходом HMAC production**. Никаких реальных писем или платежей не отправлялось.

Тесты выполнялись в доступном Python runtime, а не в Linux Docker image: FastAPI 0.141.1, Starlette 1.6.0, python-multipart 0.0.32, SQLAlchemy 2.0.52. Requirements по-прежнему фиксирует FastAPI 0.110.0. Поэтому 25 passing tests не являются проверкой зафиксированного production dependency set. Реальные DATEV/BMD, нативные browser smoke, Stripe Dashboard и инфраструктура не аттестованы в этой проверке. Указанный NO-GO основан не только на отсутствии внешних доказательств, но и на выполненных локальных контрпримерах.

Основные артефакты:

- [baseline.txt](docs/audit_2026-09-09_round3/baseline.txt)
- [probe_round3.py](docs/audit_2026-09-09_round3/probe_round3.py), [results.json](docs/audit_2026-09-09_round3/results.json)
- [probe_extension.cjs](docs/audit_2026-09-09_round3/probe_extension.cjs), [extension-results.json](docs/audit_2026-09-09_round3/extension-results.json)
- [probe_ui.cjs](docs/audit_2026-09-09_round3/probe_ui.cjs), [ui-results.json](docs/audit_2026-09-09_round3/ui-results.json)

## 3. Блокирующие контрпримеры

### B01 — OTP не доставляется; клиентский вход не реализован (P1, A01/A02/A06)

`backend/app/api/endpoints/auth.py:33–64` создаёт AuthChallenge, делает flush и возвращает сообщение `Verification code sent to email`. В этом пути нет email provider, outbox или операции доставки. Регрессионный тест сам читает `AuthChallenge.code` из БД. Это проверяет выдачу JWT при знании секрета, но не вход клиента по почте.

В `extension/app.js` нет запроса request-code/token и записи полученного authToken в storage.session. Вход удалён вместе с mock handlers, но не заменён рабочим flow. Поиск API по-прежнему ограничен localhost/127.0.0.1 (`:214–240`), а при ошибке backend продолжается локальный парсинг (`:1030–1046`). Старые userSession/conversionsLeft влияют на UI; logout удаляет authToken из local, хотя API читает его из session.

Дополнительно: 30 неверных OTP подряд получили 401 без lockout; после них правильный код принят. В коде нет attempt counter/rate limits. 30 попыток не доказывают практическую возможность полного brute-force за TTL, но подтверждают отсутствие прикладного бюджета попыток в проверенном пути. Challenge помечается used через SELECT→UPDATE, без atomic consume condition; revocable session state по-прежнему отсутствует. Production продолжает принимать mock defaults и генерировать ephemeral keys при отсутствии настроек.

**Приёмка:** настоящий delivery adapter/outbox с тестовым mailbox, рабочий UI input/submit/refresh/logout, серверная сессия и защита OTP от перебора/конкурентного повторного использования; production fail-closed без обязательных secrets. Ответ «sent» допустим только при корректной постановке доставки в очередь.

### B02 — реальная конкуренция превышает Trial; replay снова запускает parser (P1, A02/A18)

Штатный `test_regression_2…parallel_quota` выполняет два reserve **последовательно в одной сессии**, поэтому видит собственный flush. Он не проверяет гонку двух запросов.

Независимая проба создала две AsyncSession и синхронизировала их после выполнения обоих SUM-запросов, до вставки. Возвращаемые данные и SQL не изменялись — контролировалось лишь допустимое расписание конкурентных операций. Обе сессии успешно выполнили reserve и commit:

```text
concurrent_sessions = [RESERVED, RESERVED]
concurrent_reserved_units = 6
trial allowance = 3
```

UniqueConstraint tenant/idempotency защищает только одинаковые ключи, а не общий лимит при разных ключах. SELECT SUM и INSERT не стали атомарной операцией. RESERVED хранится в длинной request transaction до завершения обработки.

Кроме того, четыре одинаковых HTTP-запроса с тем же key вернули 200, **parser вызван четыре раза**, созданы четыре разных transaction_id. Changed-body=409 исправлен, но полноценного идемпотентного результата нет; одинаковый тяжёлый файл можно перерабатывать без нового списания. Request hash — SHA256 конкатенации file bytes; не включает длины/границы, filenames, format, account/profile/client параметры. Это не криптографическая коллизия SHA256, а неполное представление запроса.

**Приёмка:** атомарный conditional debit/tenant lock в короткой durable transaction с суммой RESERVED+COMMITTED, конфликтами и TTL; конкурирующие разные keys не превышают лимит. Статусная машина replay не повторяет parsing. Canonical request digest включает структурированные параметры и границы файлов. Согласовать кэш/повторный download с Zero Retention: например, ограниченный временный RAM-result либо терминальный ответ о завершении без автоматического reprocess.

### B03 — ERROR-транзакции всё ещё экспортируются; partial input пропускается (P1, A11/A12/A15)

Export gate проверяет только `unparsed_files` и общий DISCREPANCY (`main.py`, блок Safeguard export), но не `transaction.validation_status`, missing fields и фактическую полноту.

| Синтетический вход | JSON | Финансовый экспорт |
|---|---|---|
| amount=`garbage` | 200, ERROR | **200 Muster, сумма 0,00**, ERROR исчезает |
| пустая сумма | 200, **VALID** | **200 Muster, сумма 0,00** |
| дата 31.02.2025 | 200, ERROR, booking_date=null | **200 Muster с пустой датой** |
| неверная и корректная даты в одном CSV | **500** | **500** |
| хороший CSV + unsupported.xml | 200, successful_files=1 | **200**, второй файл молча пропущен |

Причины: missing amount ещё превращается в строку `"0"` в csv_parser; unsupported extension проходит `continue` без ошибки; nullable booking_date сортируется вместе с date — TypeError. Поэтому даже обещание «ошибки доступны для аудита в JSON» не выполняется для смешанного набора дат.

**Приёмка:** отдельная модель row error с raw/source location; валидные проводки и ошибки не смешиваются в exporter input. Любой ERROR/AMBIGUOUS/missing required field, неполное покрытие файлов/строк запрещает final export. JSON review должен оставаться доступен даже при полностью невалидном документе. Unsupported/empty input должен учитываться явно. Commit quota привязать к согласованному успешному результату.

### B04 — счета/валюты распознаны, но экспорт и reconciliation всё ещё смешивают их (P1, A08/A12/A14/A15)

Per-row IBAN исправлен. Однако CSV с SYNTHETIC_A и SYNTHETIC_B дал два account в JSON и **один Muster с обеими операциями**, без разделения по account. При DATEV весь batch получает один default bank account. Переименование account поля не создаёт безопасную partition.

EUR 10 и USD 20 с последовательными saldo 100/120 агрегируются как один account, дают **BALANCED** и экспортируются. Reconciliation key всё ещё client/account без currency. Opening вычисляется из первой строки; независимый opening не сверяется. Несколько файлов одного account всё ещё перезаписывают balance metadata в main.

**Приёмка:** partition tenant/client/account/currency/statement; отдельный результат/профиль импорта на partition. Без такой идентичности блокировать смешанный export. BALANCED рассчитывать в одной валюте на основании подтверждённого банковского профиля, независимых границ и покрытия строк.

### B05 — DATEV год исправлен только для простого случая; UI не поддерживает новые форматы (P1, A13/A14)

DATEV выбирает `min(valid_years)`. Пакет 31.12.2025 + 01.01.2026 получает header `20250101 … 20251231`, а обе записи содержат лишь TTMM (`3112`/`0101`). Операция следующего года оказывается в несовместимом периоде. Нужны split/reject по fiscal profile, поддержка реального Wirtschaftsjahr и пользовательские Berater/Mandant/account; значения 1001/10001 пока захардкожены.

Независимое выполнение `displayPreview` на этом реальном output дало **3 строки, 0,00 €**, хотя исходных операций две на 30 EUR. Первая «транзакция» — заголовок `Umsatz… / Soll/Haben… / WKZ Umsatz`. UI всё ещё разбирает target export как прежние шесть колонок через split(';'). BMD exporter также остаётся ручной сборкой восьми колонок, без подтверждённого импорт-профиля; обрезка после удвоения кавычек может разорвать escaping.

**Приёмка:** preview только из typed JSON; download — исходные байты экспортёра. DATEV/FY profile, S/H, Konto/Gegenkonto и BMD mapping подтверждаются настоящим импортом и сверкой проводок. Правильный header string в unit test этого не доказывает.

### B06 — Stripe lifecycle всё ещё неполон (P1, A03)

Подтверждены следующие результаты обработки синтетических событий:

- `customer.subscription.deleted` → запоздалый `invoice.paid` возвращает entitlement в **active**.
- Checkout с **неизвестным Price ID**, но amount_total=8900 EUR получает **Lifetime**.
- `checkout.session.completed(unpaid)` → `checkout.session.async_payment_succeeded(paid)` оставляет **0 прав**: второго event handler нет.
- Обычный lifetime refund по payment_intent — **canceled**, этот прежний дефект исправлен.

Проверка сумм не является Price allowlist. В код добавлены также €149 Lifetime и €19 PRO, не входящие в заявленный каталог действующих links. Налог/скидка могут привести к отклонению реальной оплаченной покупки. Starter остаётся rolling 30 days, не Stripe billing period. Обновление существующей subscription при checkout не меняет plan_code; invoice/subscription handlers не сверяют текущее authoritative состояние и order/version. Refund predicate с отсутствующим payment_intent строит сравнения с NULL — нужно исключить возможность выбора несвязанного entitlement, а не объединять пустые идентификаторы через OR.

Stripe прямо предупреждает о неупорядоченной доставке и повторных событиях; fulfillment должен учитывать состояние оплаты и lifecycle. Источники: [Stripe webhooks](https://docs.stripe.com/webhooks), [Stripe fulfillment](https://docs.stripe.com/checkout/fulfillment).

**Приёмка:** real Price IDs→capabilities, trusted tenant binding, actual billing periods, async success/failure, upgrade/downgrade, invoice/cancel reorder, refund/dispute policy; подписанные sandbox E2E плюс reconciliation текущих Stripe объектов. Не смешивать event.id idempotency с idempotency покупки.

### B07 — ingress частично исправлен, worker/retention/deployment не доведены (P1, A16–A18; P2 A20)

Byte limits подтвердились; MAX_ROWS_PER_FILE=1 при двух строках всё ещё возвращает 200 и две транзакции. Pages/CPU deadline/isolated worker не внедрены; sync registry.parse_file выполняется внутри async route. Число файлов и квота проверяются после multipart и чтения всех files в память. Repeated identical replay дополнительно нагружает этот путь.

Dockerfile и requirements **не изменились**, что подтверждается хешами. В deployment guide по-прежнему `SQLITE_DB_PATH`, которого Settings не читает; read_only root конфликтует с default DATABASE_URL в /app. Нет deployable compose-файла среди найденных артефактов; tmpfs описан примером. Ingress Nginx buffering вне tmpfs API не закрыт, healthz выдаёт constant `zero_retention: enforced`. Windows OCR всё ещё импортирует winsdk и использует temporary files. Filename-логи остаются в Amex/Universal parser; убранный account/balance log — лишь часть A16.

Новые ORM-поля request_hash/payment_intent и UniqueConstraint требуют миграции существующей БД. `init_db` по-прежнему использует create_all: это не изменяет уже существующие таблицы. Прогон на пустой SQLite не проверяет обновление прежней установки. Официальная документация разграничивает создание схемы и миграции: [SQLAlchemy MetaData](https://docs.sqlalchemy.org/en/20/core/metadata.html#creating-and-dropping-database-tables).

**Приёмка:** versioned migration с upgrade smoke на копии прежней схемы; actual production config с fail-closed secrets; Linux image build, worker kill/memory limits; retention canary через proxy/app/temp/log/APM по success/error/timeout/crash. Этот раздел не закрывается обновлением probes.

### B08 — privacy/UI очищаются не полностью; release declarations расходятся с кодом (P2, A19/A22–A31)

Clear History удаляет сохранённый CSV, затем вызывает **ReferenceError: previewTable is not defined** (`extension/app.js:1531`). В исходнике объявлен previewTableBody; previewCard также не объявлен. parsedTransactions остаётся в памяти, обновление UI не завершается. Независимая Node-проба подтвердила удаление storage keys и сохранение массива транзакций. История всё ещё opt-out не предусмотрена: полный CSV сохраняется автоматически, TTL нет.

PDF.js всё ещё **3.11.174**. Его наличие нельзя объявлять исправленным по успешному извлечению тестового PDF. Manifest сохраняет localhost/dev hosts и WAR all_urls; Firefox по-прежнему declares data collection none. Удаление mock handlers не удаляет старые userSession и локальный fallback.

AVV действительно расширен, поэтому прежнее описание «только два раздела» к текущему файлу **больше не применяется**. Однако TOMs/Frankfurt/Hetzner и durable-storage promises должны быть подтверждены фактической инфраструктурой; предусмотренная in-browser option противоречит выбранному ADR managed-only. Не показаны заключение/version acceptance AVV и проверенный subprocessors data map. Privacy по-прежнему обещает полное немедленное удаление RAM и не раскрывает local history/retention auth/billing. AGB всё ещё содержит annual и B2C, неописанный cancellation flow. Реквизиты добавлены ранее, их документальная сверка остаётся непредставленной.

Полное юридическое соответствие не выводится из наличия текста; требования processor agreement связаны с фактической обработкой и TOMs — [GDPR, Art.28/32](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng). Для PDF.js остаётся исходный advisory с отдельными условиями эксплуатации, без заявления о доказанном RCE в MV3 — [Mozilla CVE-2024-4367](https://github.com/mozilla/pdf.js/security/advisories/GHSA-wgrm-67xf-hhpq).

## 4. Статус всех исходных ID

«Частично» и «Открыт» входят в число 25 незакрытых; «Закрыт локально» не означает опубликованный/аттестованный production.

| ID | P | Статус | Основание текущего решения |
|---|---|---|---|
| A01 | P1 | Частично | Bearer + OTP required работают; delivery, attempt budget, atomic consume/revocable session и production config не готовы (B01). |
| A02 | P1 | Частично | Mock handlers удалены, changed payload=409; concurrent quota=6/3, повторный parser и отсутствующий real login (B01/B02). |
| A03 | P1 | Частично | Unpaid/refund/priority улучшены; unknown price, async fulfillment, reorder, billing period остаются (B06). |
| A04 | P1 | Закрыт локально | Starter €4.90 и 20 выписок сохранены; новые несовместимые backend prices учитываются в A03. |
| A05 | P1 | Закрыт локально | Нет активного annual toggle в HTML; AGB annual — A28. |
| A06 | P1 | Открыт | Localhost-only discovery и fallback при отказе API сохранены, managed user flow отсутствует. |
| A07 | P1 | Закрыт локально | Исправление landing demo/error substitution предыдущего раунда сохранено. |
| A08 | P1 | Частично | IBAN per-row исправлен; final export account/currency partitions не обеспечивает (B04). |
| A09 | P1 | Закрыт локально | Недеструктивная обработка дублей сохранена. |
| A10 | P1 | Закрыт локально | Геометрические строки и синтетический PDF прошли; это не сертификация всех PDF-профилей. |
| A11 | P1 | Частично | Пример rollover исправлен; nullable dates вызывают 500 в смешанном input, invalid rows экспортируются (B03). |
| A12 | P1 | Частично | USD alias/S suffix исправлены; blank amount=0 VALID, mixed-currency BALANCED, fuzzy schema остаются. |
| A13 | P1 | Частично | Muster writer исправлен; UI парсит DATEV/BMD неправильно, history encoding и остальные exporters не унифицированы. |
| A14 | P1 | Частично | S/H и одно­годовой FY исправлены; multi-year FY, profile/configuration, BMD/DATEV import evidence отсутствуют. |
| A15 | P1 | Частично | Gate по discrepancy/unparsed есть; ERROR/missing/unsupported extension обходят его (B03/B04). |
| A16 | P1 | Частично | Account/balance log удалён; filename/error logging остаётся в PDF parser; full canary evidence нет. |
| A17 | P1 | Частично | Нет доказанного end-to-end durable-retention enforcement; proxy/temp/heap guarantees не выполнены. |
| A18 | P1 | Частично | Actual byte/per-file budget исправлены; CPU/pages/rows/concurrency/replay resource limits не завершены. |
| A19 | P2 | Открыт | PDF.js runtime version остаётся 3.11.174. |
| A20 | P2 | Частично | Platform marker/non-root прежние; Windows OCR и Linux build/runtime evidence не решены. |
| A21 | P2 | Закрыт локально | Firefox action→sidebar handler продолжает проходить mock test. |
| A22 | P2 | Открыт | Dev/local hosts, WAR, AMO none, отсутствующий managed host/pairing остаются. |
| A23 | P2 | Частично | Storage keys удаляются, но clear падает, DOM/parsed state остаётся; opt-in/TTL отсутствуют. |
| A24 | P2 | Частично | Muster formula text fixture исправлен; UI innerHTML для date/amount и другие export paths не закрыты. |
| A25 | P2 | Частично | Гражданское имя есть; юридический статус/адрес/применимые реквизиты и Stripe consistency документально не проверены. |
| A26 | P2 | Открыт | Privacy продолжает обещать недоказуемую RAM zeroization и не описывает фактическую retention/историю. |
| A27 | P2 | Частично | AVV существенно дополнен; TOMs/provider assertions и механизм заключения не подтверждены. |
| A28 | P2 | Открыт | Annual/B2C/cancellation/lifetime/VAT/withdrawal flow не согласованы и не проверены end-to-end. |
| A29 | P2 | Открыт | Нет единого server-enforced capability catalogue; local flow и marketing promises расходятся. |
| A30 | P2 | Частично | 25 тестов и hashes подтверждены; реальные concurrency, clean-browser, migration/Linux/import доказательства отсутствуют; assertion всех26 неверен. |
| A31 | P3 | Частично | Release evidence заявляет полный GO; ADR/deploy/runtime расходятся, as-is не описан достоверно. |

## 5. Что требуется от Antigravity для следующей приёмки

Это продолжение предыдущих R0–R6, не новый набор требований вместо согласованных критериев.

| Этап | Следующий конкретный deliverable | Минимальное проверяемое доказательство |
|---|---|---|
| R0 | Исправить release status и матрицу исходных ID; отметить частичные исправления честно. | Нет утверждения «26/26 закрыты» до независимого rerun; стабильные commit/build IDs, архив evidence. |
| R1 | Реальный email delivery и auth UI; убрать silent local fallback; session logout/revoke, OTP attempts/consume. | Вход на чистом компьютере без доступа к БД; подтверждённое письмо в test mailbox; negative/expired/replayed/concurrent OTP и logout. |
| R2 | Атомарная квота и идемпотентный результат; Price IDs и полный Stripe lifecycle. | Две независимые sessions/concurrent requests ≤3; same key не парсит повторно; price/tax/coupon/async/refund/cancel-order/upgrade/billing period suite. |
| R3 | Deployable Linux config + DB migrations + isolated worker/ingress retention. | Upgrade прежней схемы; pinned image build; hard deadline/memory/page/row tests; responsive health; canary across ingress/temp/logs. |
| R4 | Полный validation gate, partitions и accounting profiles. | Все B03/B04/B05 исправлены; реальный DATEV и BMD импорт с числами строк, датами, счетами, валютами и сверкой сумм. |
| R5 | JSON preview, рабочая очистка state, минимальные manifests; AVV/privacy по фактической data map. | Clean Chrome/Firefox flow, history bytes/delete/restart, format switching, auth denial; правдоподобные и подтверждённые TOMs/provider/contract acceptance. |
| R6 | Собрать независимый release evidence. | Коммит, dependency lock/SBOM, image digest, ZIP hashes, тестовые и эксплуатационные протоколы. Только после этого — повторное решение о пилоте с реальными данными. |

**Работу на синтетическом корпусе можно продолжать. Разрешение на обработку реальных выписок в пилоте в этом раунде не выдаётся.** Чтобы снять NO-GO, необходимо закрыть воспроизведённые P1 и подтвердить релевантные privacy/import/deployment условия, а не только обновить позитивные примеры probes.
