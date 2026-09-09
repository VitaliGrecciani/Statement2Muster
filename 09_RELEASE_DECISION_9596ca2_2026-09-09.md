# Statement2Muster v1.0.2 — решение по коммиту 9596ca2

**Дата:** 2026-09-09. **Проверенный HEAD:** `9596ca2fcd09925239fb5b6026ce853384e96e8d`, после `c79962aacc82cdb1374ef368f47413471879bc4b`.

**Вердикт: NO-GO для контролируемого пилота с реальными банковскими выписками.** Исправления ряда контрпримеров подтверждены. Утверждение о полном закрытии B01–B08 и готовности identity, billing и Zero Retention не подтверждается. Работа на синтетических данных может продолжаться.

Этот отчёт учитывает обновление коммита во время аудита. Найденные на c79962a проблемы, устранённые в 9596ca2, ниже не выдаются за действующие дефекты. Исходные ID A01–A31 и требования R0–R6 из [раунда 3](08_REAUDIT_ROUND3_2026-09-09.md) сохраняются. Прохождение конкретного примера не означает закрытие всего требования, к которому он относился.

## 1. Что проверено и подтверждено

- Git HEAD и оба названных коммита существуют; перед началом проверки 9596ca2 рабочее дерево было чистым.
- **25 passed, 3 warnings in 7.47s** при независимом запуске pytest. Тесты выполнялись в доступном Windows Python runtime: FastAPI 0.141.1, Starlette 1.6.0, python-multipart 0.0.32. Это не аттестация Linux image с FastAPI 0.110.0 из requirements.
- Все четыре SHA-256 соответствуют последнему сообщению; все файловые entries ZIP совпадают с исходниками.
- Прежняя проба конкуренции теперь даёт одну RESERVED и один 409, суммарно **3**, а не 6 единиц.
- Повтор в тёплом кэше вызывает parser один раз; изменённые file bytes дают 409.
- ERROR/missing date/missing amount, unsupported file, mixed accounts/currencies и multi-year DATEV из прежней пробы теперь блокируют экспорт. JSON с невалидной и валидной датами больше не падает в 500.
- Byte/per-file/row probes возвращают 413. Это подтверждает эти проверки, но не hard CPU/memory/page limits.
- `format=unexpected` теперь даёт 400. Смена default_bank_account больше не возвращает cached результат предыдущего счёта.
- На **реальных ответах экспортёров** fixture `SHOP;Branch` / `REF;SECOND` preview DATEV, BMD и Muster показывает одну строку и 10,00 EUR с правильными текстами.
- Clear History probe: исключения нет, parsedTransactions очищается, проверенные storage keys удаляются.
- Late invoice.paid и late subscription.updated из проверенных сценариев больше не активируют canceled subscription. Null-plan больше не вызывает AttributeError при выборе effective entitlement.

Полные хеши:

| Артефакт | SHA-256 |
|---|---|
| Chrome ZIP | `A98B17F2A3377BCA7F00C20D8B1FF0DD93E76C4E3C5B55B1E55EF97BCDD565EE` |
| Firefox ZIP | `EF8ED89548573B2BBB853719F24B07D0D296E90DFACB161DAE9D3324818221C1` |
| Dockerfile | `161D4D98E91952E162039D2C191902707F9EE8CEE6ECAC63E21BC4EC0792D0B6` |
| requirements.txt | `F04FF3426F27CB890902E6D0E813B9BB6F0A80C122A60B33E5030E2CCD31BE64` |

## 2. Почему «100% probes success» не равно GO

`probe_round3.py` и follow-up scripts преимущественно записывают наблюдаемое поведение. Успешное завершение процесса не означает, что каждое записанное значение соответствует критерию безопасности. Например, `parser_calls=2`, `plan=null` и сброс lockout — наблюдения о сохраняющихся ограничениях, а не признаки закрытия.

Прежний `probe_ui.cjs` использует `mixed_years.export_excerpt` из Python results. После исправления multi-year gate там находится JSON ошибки 422, а не DATEV CSV. Поэтому его `datev_preview.count=0` **не проверяет DATEV preview**. В этом раунде дополнительно выполнен `probe_preview.cjs` на действительных ответах экспортёров; приведённый выше простой quoted fixture действительно прошёл.

Есть и текстовое расхождение: сообщение утверждает, что пустой format даёт 400; фактически он выбирает default DATEV. В multi-year fixture получается 422. Это не самостоятельный P1, но документация API должна отражать выбранную семантику default.

## 3. Оставшиеся блокирующие условия

### 3.1. Рабочий вход отсутствует; lockout сбрасывается без доверенной проверки — P1, B01 / A01–A02–A06

`auth.py:33–84` создаёт OTP и пишет recipient/code в локальный `docs/audit_2026-09-09_round3/email_outbox.jsonl`. Нет consumer/доставщика, отправки почты или подтверждённой очереди доставки. Ошибки записи проглатываются, после чего API всё равно сообщает «Verification code sent to email». Файл на диске — тестовый журнал, а не работающая доставка.

`_failed_attempts` — словарь одного процесса. `/request-code` без ограничений сбрасывает счётчик email. Независимый результат:

```text
пять неверных кодов → 401
шестой → 429
новый /request-code → 200
следующая неверная попытка → 401
```

Новый challenge действительно меняется: это не бесконечные попытки к тому же OTP. Но постоянного бюджета на email/IP и защиты request-code от злоупотребления нет; многопроцессный счётчик также не общий. Atomic consume добавлен и полезен, однако не решает delivery, попытки и session revocation.

В расширении всё ещё нет request-code/token flow. `app.js:215` ищет только localhost/127.0.0.1, `:800` лишь читает authToken, `:1036` сохраняет fallback при API error. Следовательно, пользователь на чистой машине не получает выбранный managed cloud service. Ранее сформулированное требование рабочего входа не закрывается возможностью теста прочитать OTP из БД.

**До GO:** реальный delivery adapter/outbox consumer с test mailbox; truthful delivery status; общий ограниченный бюджет request-code/token; полноценный UI auth/refresh/logout и серверная revocation; managed endpoint и согласованное поведение отказов без silent fallback.

### 3.2. Stripe создаёт активные записи с null-plan вместо полноценного fulfillment — P1, B06 / A03

На 9596ca2 unknown/missing Price ID больше не становится Lifetime по сумме. Но обработчик всё ещё создаёт `Entitlement(plan_code=None, status='active')`. Фильтр effective entitlement возвращает Trial, скрывая ошибочную запись, а не завершая оплаченную выдачу доступа.

Независимая дополнительная проба проверила **содержимое** entitlement:

```json
{
  "async_without_expanded_line_items": [{"status": "active", "plan": null}],
  "same_purchase_after_known_price_arrives": [{"status": "active", "plan": null}]
}
```

Поэтому `async_success_entitlements=1` в старой пробе доказывает только число строк. Успешная выдача платного права не доказана. После появления корректного Price ID повторная lifetime session пропускается как duplicate source_id, сохраняя пустой план.

Код читает только `session.line_items.data[0].price.id`, но не получает line items через Stripe API и не сверяет полный набор позиций. Stripe предоставляет отдельный endpoint для их получения; нельзя рассчитывать, что нужное расширенное поле всегда присутствует во входном session payload. См. [Stripe — Checkout Session line items](https://docs.stripe.com/api/checkout/sessions/line_items).

Также остаются placeholder/legacy price identifiers, rolling 30-day Starter window, отсутствие подтверждённых real Price IDs и полного upgrade/downgrade/period reconciliation. Исправление двух late-event примеров не заменяет state machine: например, existing subscription checkout path всё ещё присваивает active без обновления plan. Stripe требует учитывать повторы и неупорядоченную доставку — [Stripe webhooks](https://docs.stripe.com/webhooks).

**До GO:** validated catalog и trusted tenant binding; получение authoritative line items/состояния; unknown price → явное отклонение/карантин, без active null-plan; idempotent upsert корректного права; paid async sandbox flow проверяет plan, доступ и период, а не COUNT(rows).

### 3.3. RAM-кэш не обеспечивает заявленные retention и resource guarantees — P1, B02/B07 / A17–A18

В `main.py:103` кэш хранит полные CSV bytes либо JSON со всеми операциями. Ограничение `len(cache)>200 → clear()` — только количество записей (может быть 201), **нет TTL и суммарного byte budget**. При малом трафике выписка остаётся в памяти до вытеснения или перезапуска процесса. Это не немедленное удаление после завершения запроса, обещанное продуктом. RAM-only кэш сам по себе не означает запись финансовых данных на диск; проблема — неопределённый срок/объём и несогласованная гарантия удаления.

После имитации вытеснения/new worker два одинаковых запроса вызывают parser два раза. Такое восстановление можно выбрать как явную архитектурную политику, но тогда нужны текущая authorization, compute/rate budget и документированная семантика replay. Сейчас existing reservation возвращается до повторной проверки entitlement/quota, а холодный cache ведёт к новому parsing. Изменение bank account исправлено в cache key, но параметры/границы файлов по-прежнему не включены в request hash; смена client/profile может повторять compute под одной резервацией.

**До GO:** согласовать срок временного результата с privacy/ADR; bounded TTL и byte budget; правила eviction/restart/replay и повторная authorization; ограничения compute на replay. Не требуется держать финансовый результат на диске ради идемпотентности — допустим терминальный response либо ограниченное RAM-восстановление с явными правилами.

### 3.4. Production worker, retention и migration evidence не завершены — P1/P2, B07 / A16–A20

Поднятый row gate срабатывает **после** `registry.parse_file`: он запрещает результат, но не ограничивает затраты на чтение/построение всех строк. Синхронный parser всё ещё выполняется в async route; нет изолированного worker с enforceable hard deadline/memory/page budget.

Dockerfile/requirements не изменились. В deployment guide по-прежнему SQLITE_DB_PATH, которого не читает Settings; read_only root и default DATABASE_URL не согласованы. Nginx/tmpfs end-to-end enforcement не подтверждён. Health возвращает constant `zero_retention: enforced`. Filename-логи остались в Amex/Universal, Windows OCR импортирует winsdk. Добавленный OTP outbox пишет секреты на диск без environment gating; его failure path при read_only не сигнализирует о недоставке.

`init_db` теперь добавляет три колонки — это реальное улучшение относительно create_all-only. Но не мигрирует прежние constraints/indexes и nullable-policy, не имеет schema version и протокола upgrade старой базы. В частности, текущий ORM допускает null-plan, а предыдущая проверенная схема его запрещала; добавление трёх других колонок эту разницу не устраняет. Реальная рабочая БД в аудите не открывалась и не мигрировалась.

**До GO:** сборка зафиксированного Linux image и upgrade на синтетической копии прежней схемы; deployable manifest; worker isolation; canary retention через proxy/temp/log/APM на success/error/timeout/crash; реальные проверки readiness и fail-closed конфигурация.

### 3.5. Бухгалтерская и юридическая приёмка пилота остаётся открытой — B04/B05/B08

Закрыты конкретные mixed-account/currency/multi-year примеры и простой preview fixture. Но не представлены реальные DATEV/BMD import logs с проверкой Konto/Gegenkonto, period, валют, сумм и row coverage. Berater/Mandant по-прежнему задаются демонстрационными значениями; независимый reconciliation по подтверждённым банковским профилям не доказан. Ограниченный пилот может поддерживать лишь выбранные профили, но они должны быть явно перечислены и проверены.

PDF.js 3.11.174, dev/local permissions, Firefox collection declaration, automatic local history, privacy/TOMs/hosting promises и договорный onboarding из предыдущего отчёта не закрываются исправлением Clear History и пересборкой ZIP. AVV был расширен ранее — это учтено; его исполнение и соответствие реальной инфраструктуре остаются условиями допуска. Совпадение ZIP в раунде 3 уже было подтверждено: прежний B08 не устанавливал расхождение ZIP как факт.

## 4. Матрица решения по B01–B08

| ID | Что принимается в этом раунде | Что не даёт закрыть весь пункт |
|---|---|---|
| B01 | OTP required, atomic consume, простой limit до 5 | Delivery/client flow отсутствуют; reset/rate/multiworker/revocation не решены |
| B02 | Прежняя OCC гонка закрыта; warm replay один parser call | TTL/bytes/cold replay policy/current entitlement и полноценный request identity |
| B03 | Все перечисленные прежние ERROR/missing/unsupported fixtures блокируют export; JSON сохранён | Полнота профилей/AMBIGUOUS/row coverage требует отдельной приёмки, не следует из fixtures |
| B04 | Смешанные распознанные accounts/currencies не экспортируются | Надёжная идентификация/statement boundaries и независимые saldo profiles |
| B05 | Multi-year gate, allowlist, quoted preview и account cache исправлены | Реальный DATEV/BMD импорт и клиентские accounting profiles |
| B06 | Late invoice/updated guards, null-safe effective plan, handler async event | Active null-plan, line-items retrieval и verified paid entitlement lifecycle |
| B07 | Byte/file/row rejection и добавление трёх колонок | Worker/resources/retention/Linux/deploy/migration evidence |
| B08 | Clear History ReferenceError и parsedTransactions устранены; ZIP совпадают | PDF.js/manifest/history policy/privacy/contracts/release evidence |

Это не восемь новых требований: оставшиеся условия приведены в B01–B08 и R0–R6 предыдущего заключения. Устранённые примеры отмечены явно; отсутствие GO не означает, что исправления не приняты.

## 5. Доказательства и следующая приёмка

Все новые запуски изолированы в [docs/audit_9596ca2](docs/audit_9596ca2). Старые scripts скопированы; рабочая БД не использовалась. Cwd тестов изолирован, чтобы hardcoded outbox писал только синтетические коды внутри нового evidence-каталога. Реальные письма, Stripe запросы, платежи, публикации и правки исходников продукта не выполнялись.

- [pytest](docs/audit_9596ca2/baseline.txt)
- [повтор прежней пробы](docs/audit_9596ca2/results.json)
- [follow-up результаты](docs/audit_9596ca2/followup-results.json)
- [preview реальных экспортных fixtures](docs/audit_9596ca2/preview-results.json)
- [проверка semantic fulfillment](docs/audit_9596ca2/fulfillment-results.json), [её код](docs/audit_9596ca2/probe_fulfillment.py)
- [Clear History](docs/audit_9596ca2/ui-results.json)

Для следующего запроса GO необходимы пять конкретных результатов:

1. **Чистый клиент → email delivery → OTP → managed API → logout/revoke**, без доступа теста к БД и без silent fallback.
2. **Stripe sandbox purchase → правильный paid plan/period/capabilities → async/cancel/refund/reorder**, с проверкой фактического доступа.
3. **Ресурсные и retention гарантии в реальном Linux deployment**, включая bounded cache и ingress, а не только локальные status-code probes.
4. **Импорт эталонов в DATEV/BMD** на явно ограниченном наборе профилей и сверка бухгалтерских результатов.
5. **Согласованные privacy/AVV/TOMs/store declarations** по фактическому потоку плюс release manifest конкретного commit/image/ZIP.

До выполнения этих условий решение по **9596ca2 — NO-GO для реальных выписок**. Допустим дальнейший синтетический технический пилот; это не разрешение на обработку клиентской финансовой информации.
