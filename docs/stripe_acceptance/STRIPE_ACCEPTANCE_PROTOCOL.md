# Протокол приёмочных испытаний: Stripe Lifecycle & Entitlements (Synthetic Signed Webhook Integration)

**Основание:** Решения Главного Архитектора № 24 (`24_SMTP_STATUS_AND_FULL_GO_PLAN_2026-09-14.md`), № 25 (`25_NEXT_BLOCK_MANAGED_EXTENSION_ACCEPTANCE_2026-09-15.md`), № 31 (`31_MANAGED_EXTENSION_GO_2026-09-15.md`), № 32 (`32_STRIPE_LIFECYCLE_REVIEW_2026-09-16.md`) и № 33 (`33_STRIPE_SYNTHETIC_FOLLOWUP_2026-09-16.md`)  
**Дата проведения:** 2026-09-16  
**Статус:** **100% PASSED (24 из 24 сценариев успешно выполнены на живом бэкенде Hetzner)**  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Контролирующие лица:** Главный Архитектор (OpenAI Codex CLI `codex.exe`, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`), Product Owner (Vitali Grecciani / Vito)  

---

## 1. Provenance и параметры испытательного стенда

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Тестовый Git Commit** | `HEAD` (релиз 1.0.8) | Включает исправления замечаний Решений № 32 и № 33 (детерминированное согласование равных timestamp, устранение фиктивных 30-дневных рамок, переменные периоды, отложенный чекаут) |
| **Backend Docker Image** | `statement2muster-api:1.0.8` | Неизменяемый образ, собран `--no-cache` на Hetzner Host `46.225.95.36` |
| **Backend Image ID** | `sha256:1e1be37ad6e44ba05d8c8044d0ebf450f88be447beae2856c67309f3cd0521da` | Зафиксирован в Docker Daemon Hetzner |
| **Backend Container ID** | `5dd8e97322f4959dd93d89793a8f2fadd9d061a4854cd03035cbeb1399585bef` | Имя контейнера: `s2m-backend-api`, Status: `healthy` |
| **Docker Inspect Artifact** | `docs/stripe_acceptance/docker_inspect_108_sanitized.json` | Обезличенный JSON инспекции контейнера по строгому allowlist (`Config.Env` очищен от секретов) |
| **API URL** | `http://127.0.0.1:8000` | SSH-туннель к продуктивному контейнеру Hetzner (`127.0.0.1:8100`) |
| **Тип испытаний** | **Synthetic Signed Webhook Integration** | Автономная интеграционная проверка валидаторов, БД и квот с аутентичным HMAC-SHA256 (`Stripe-Signature`) |
| **Исполняемый раннер тестов** | `tests/acceptance/run_stripe_lifecycle.py` | 24 сценария, полностью закрывающих замечания Решений № 32 и № 33 |
| **Машинный результат** | `docs/stripe_acceptance/stripe_lifecycle_results.json` | 24/24 сценариев со статусом PASS |
| **Каталог цен и тарифов** | `docs/stripe_acceptance/STRIPE_CATALOG_ALIGNMENT.md` | Сверка производственных и тестовых Price IDs, валют, сумм и режимов |

---

## 2. Матрица устранения замечаний Решений № 32 и № 33

| Замечание | Суть дефекта / Требование Архитектора | Реализованное исправление в релизе 1.0.8 | Подтверждающий тест | Статус |
| :--- | :--- | :--- | :--- | :---: |
| **S01** | Валидация суммы и валюты: при 0, отрицательной или отсутствующей сумме, не-EUR валюте или несовпадении `mode`/плана права могли активироваться. | В `billing_service.py` внедрена строгая проверка:<br>1) `type(amount_total) is int and amount_total > 0 and amount_total == expected["amount_cents"]`;<br>2) `isinstance(currency, str) and currency.lower() == "eur"`;<br>3) режим `subscription` для `starter`/`pro`, `payment` для `lifetime`.<br>При любом нарушении статус переводится в `"quarantined"`, `plan_code = None`. | **Сценарий 14** (проверены 6 веток: 0 amount, omitted, negative, missing currency, wrong currency, mode mismatch). | **PASS** |
| **S02** | Поздний `checkout.session.completed` мог реанимировать отмененную подписку (`canceled`) с новым `event_id`. | В `_handle_checkout_completed` добавлена проверка статуса существующей подписки / разовой покупки. Если `existing.status == "canceled"`, воскрешение блокируется, права остаются аннулированными. | **Сценарий 15** (checkout → deleted → поздний checkout с тем же `subscription_id` → права отозваны). | **PASS** |
| **S03 (Part 1)** | Неупорядоченность событий: старое `invoice.payment_failed` после нового `invoice.paid` могло деградировать права; старое `invoice.paid` после неудачи активировать; `valid_until` мог откатиться назад. | В модель `Entitlement` добавлено поле `last_event_created_at`. Обработчики сверяют `event_created_ts`. События строго старше `last_event_created_at` отклоняются как устаревшие. Монотонность `valid_until` соблюдается для подтверждённых периодов. | **Сценарий 18** (защита от отката `valid_until` назад). | **PASS** |
| **S03 (Part 2: Equal created, Решение № 33)** | Равные timestamp (`created = 100`) давали результат, зависящий от порядка доставки: `paid -> failed` давал `past_due`, а `failed -> paid` давал `active`. | В модель `Entitlement` добавлены поля `last_invoice_id` и `last_invoice_status`. При `invoice.payment_failed`:<br>1) если `invoice_id == ent.last_invoice_id` и `ent.last_invoice_status == "paid"`, сбой игнорируется как устаревшая попытка для уже оплаченного счета;<br>2) если период сбоя `failed_period_end <= cur_valid` при `status == "active"`, сбой не ломает уже подтверждённый оплаченный период.<br>Обе перестановки детерминированно сохраняют статус `active`. | **Сценарии 16 и 17** (перестановка A: paid → failed при created=100 даёт active; перестановка B: failed → paid при created=100 даёт active). | **PASS** |
| **S04** | `subscription.updated` с неизвестным `price` сохранял старый `plan_code` и активировал его. Несовместимый `mode` создавал подписку с `valid_until = None`. | В `_handle_subscription_updated` при неизвестном price `plan_code` сбрасывается в `None`, статус в `"quarantined"`. При попытке включить в подписку разовый товар (mode mismatch) подписка изолируется в карантин. | **Сценарии 19, 20** (неизвестный price сбрасывает plan_code в None; не-рекуррентный товар переводит подписку в карантин). | **PASS** |
| **Раздел 3: Фиктивные рамки 30 дней (Решение № 33)** | Checkout создавал активную подписку с локально выдуманным `valid_until = now + 30 days`, из-за чего первый фактический период (например, 28 дней февраля или 7 дней prorated) игнорировался монотонностью. | В модель `Entitlement` добавлена колонка `has_authoritative_period` (0 = provisional, 1 = confirmed). При checkout без авторитетных дат подписка активна провизорно (`valid_until = None`, `has_authoritative_period = 0`). При получении `invoice.paid` фактические даты периода принимаются безусловно, даже если период короче 30 дней (7 дней, 28 дней). | **Сценарий 22** (7-дневный prorated первый период и 28-дневный период февраля приняты без искажений). | **PASS** |
| **Раздел 3: Отложенный чекаут (Решение № 33)** | Доставка `invoice.paid` ДО `checkout.session.completed` могла сбросить или не найти тенанта. | `_handle_invoice_paid` предварительно инициализирует право доступа с явным `tenant_id` и `has_authoritative_period = 1`. Запоздалый `checkout.session.completed` корректно связывает сессию и `payment_intent`, сохраняя авторитетные границы периода. | **Сценарий 23** (invoice.paid приходит первым, чекаут вторым; права и квота активны и не повреждены). | **PASS** |
| **Раздел 3: Повторные / корректирующие инвойсы (Решение № 33)** | Повторная оплата или корректировочный инвойс того же периода не должны сдвигать `current_period_start` и обнулять квоту. | В `_handle_invoice_paid`: если `new_valid_until == cur_valid`, граница `current_period_start` НЕ сдвигается, и уже израсходованная квота Starter НЕ обнуляется. | **Сценарий 24** (исчерпание квоты → повторный инвойс того же периода → остаток остаётся исчерпанным, 429 сохраняется). | **PASS** |

---

## 3. Результаты испытаний (24 сценария)

Все 24 сценария выполнены против живого бэкенда на Hetzner. Каждое событие вебхука подписывалось аутентичным HMAC-SHA256 заголовком `Stripe-Signature`. Проверялись HTTP-ответы эндпоинтов, состояние записей в БД, эндпоинт `/api/v1/me/entitlements` и реальное исполнение квоты в `/api/v1/convert`.

### Сводная таблица результатов:

| № | Сценарий | Событие Stripe / Входные данные | Ожидаемый результат | Фактический результат | Статус |
| :-: | :--- | :--- | :--- | :--- | :-: |
| **1** | **Starter Subscription** | `checkout.session.completed` (`price_starter_490`, €4.90, 490¢) | Выдача квоты 20 выписок в месяц. После конвертации выписки остаток уменьшается до 19. | Выдан план `starter`, `quota_limit = 20`. Конвертация выполнена штатно (200 OK), квота зафиксирована: `used = 1`, `remaining = 19`. | **PASS** |
| **2** | **Business PRO Subscription** | `checkout.session.completed` (`price_pro_2900`, €29.00, 2900¢) | Выдача безлимитного тарифа (`quota_limit = "unlimited"`), активация `multi_upload`. | Выдан план `pro`, статус `active`, `quota_limit = "unlimited"`. Пакетная конвертация нескольких файлов прошла успешно (200 OK). | **PASS** |
| **3** | **Lifetime License** | `checkout.session.completed` (`price_lifetime_8900`, €89.00, mode `payment`) | Разовый платёж (`source_type = "one_time"`), пожизненный безлимит, `valid_until = None`. | Выдан план `lifetime`, `source_type = "one_time"`, `quota_limit = "unlimited"`, доступ бессрочный. | **PASS** |
| **4** | **Subscription Renewal** | `invoice.paid` с будущим `period.end` | Продление подписки: обновление `valid_until` в соответствии с периодом инвойса. | `valid_until` продлён до конца расчетного периода (`2026-10-16`), статус сохранён `active`. | **PASS** |
| **5** | **Payment Failure** | `invoice.payment_failed` для активной подписки | Переход статуса в `past_due`, немедленный отзыв активных PRO-привилегий. | Статус подписки переведён в `past_due`. Эндпоинт `/api/v1/me/entitlements` более не возвращает PRO-доступ. | **PASS** |
| **6** | **Cancellation at Period End** | `customer.subscription.updated` (`cancel_at_period_end: true`) | Льготный период (Grace Period): доступ остаётся активным до наступления `valid_until`. | Статус остался `active`, `valid_until` зафиксирован. Конвертация в течение льготного периода разрешена (200 OK). | **PASS** |
| **7** | **Immediate Deletion** | `customer.subscription.deleted` | Немедленное прекращение доступа: статус `canceled`. | Статус переведён в `canceled`, доступ аннулирован мгновенно. | **PASS** |
| **8** | **Charge Refund** | `charge.refunded` по `payment_intent` Lifetime лицензии | Немедленный отзыв пожизненной лицензии (`canceled`). | Статус лицензии переведён в `canceled`, доступ аннулирован. | **PASS** |
| **9** | **Signature Security** | Запрос без заголовка и с поддельным HMAC `Stripe-Signature` | Немедленный отказ с кодом **HTTP 400 Bad Request**. | • Без заголовка: 400 (`Missing Stripe-Signature header`).<br>• Поддельный HMAC: 400 (`Invalid Stripe signature header`). | **PASS** |
| **10** | **Idempotency & Replay** | Повторная отправка идентичного `event_id` | Первый запрос: `status = "success"`. Повторный запрос: `status = "already_processed"`, 0 дубликатов в БД. | Дубликат распознан реестром `stripe_event_inbox`, возвращён статус `already_processed` (HTTP 200), таблица `entitlements` не затронута. | **PASS** |
| **11** | **Out-of-Order Resilience** | Запоздалое событие `subscription.updated` (`active`) после `subscription.deleted` | Защита от воскрешения: устаревшее событие игнорируется, статус остаётся `canceled`. | Событие проигнорировано (`stale subscription.updated`), подписка сохранила статус `canceled`. | **PASS** |
| **12** | **Anti-Tampering Protection** | Попытки манипуляции: неизвестный Price ID, валюта `USD`, сумма 100¢ вместо 2900¢ | Отказ в выдаче прав: статус `"quarantined"`, `plan_code = None`, платный доступ заблокирован. | Все 3 попытки взлома переведены в карантин (`quarantined`), платные полномочия не начислены, пользователь оставлен на Trial. | **PASS** |
| **13** | **Multi-Tenant Isolation** | Покупка тарифа пользователем А | Права начисляются строго пользователю А, пользователь Б остаётся на изолированной квоте. | Утечка прав между тенантами полностью исключена. Пользователь Б имеет `plan: "trial"`, `tenant_id` изолирован. | **PASS** |
| **14** | **S01 Amount, Currency & Mode** | Нулевая сумма, отрицательная сумма, пропущенная сумма, не-EUR валюта, несовпадение mode | Все аномальные платежи изолируются в карантин. Платные права не начисляются. | 6 тестовых аномалий проверены: все 6 переведены в `quarantined`, `plan_code = None`. | **PASS** |
| **15** | **S02 No Revive Canceled Sub** | Поздний `checkout.session.completed` для отмененной (`canceled`) подписки | Запрет реанимации: статус остаётся `canceled`, права не восстанавливаются. | Попытка активации отклонена: статус остался `canceled`, права не начислены. | **PASS** |
| **16** | **S03 Out-of-Order Permutation A (Equal Timestamps)** | Событие `invoice.paid`, затем `invoice.payment_failed` при равных timestamp (`created = 100`) | Сохранение актуального статуса `active`, сбой для уже оплаченного периода игнорируется. | Статус остался `active`, `valid_until` не поврежден, права подтверждены. | **PASS** |
| **17** | **S03 Out-of-Order Permutation B (Equal Timestamps)** | Событие `invoice.payment_failed`, затем `invoice.paid` при равных timestamp (`created = 100`) | Детерминированный переход в `active`, оплата успешно закрывает инвойс и активирует права. | Статус переведён в `active`, конвертация 200 OK. | **PASS** |
| **18** | **S03 valid_until Monotonicity** | Инвойс с более ранним `period.end`, чем текущий `valid_until` | Запрет отката `valid_until` назад: монотонное продвижение времени вперед для подтвержденных периодов. | `valid_until` сохранил более позднюю дату, откат заблокирован. | **PASS** |
| **19** | **S04 Unknown Price on Update** | `subscription.updated` с неизвестным `price_id` | Сброс `plan_code` в `None`, перевод в `quarantined` (ненаследование старых прав). | `plan_code` сброшен в `None`, статус `quarantined`, PRO-привилегии аннулированы. | **PASS** |
| **20** | **S04 Mode Mismatch on Update** | `subscription.updated` с нерекуррентным товаром (`price_lifetime_8900`) | Перевод подписки в `quarantined` из-за несовпадения типа продукта. | Подписка переведена в `quarantined`, права аннулированы. | **PASS** |
| **21** | **Section 3 Starter Quota Boundary** | Исчерпание 20 выписок Starter → `invoice.paid` с новым `period.start` | Мгновенный сброс счетчика квоты до 20 доступных выписок в новом периоде. | До продления: 429 Quota Exceeded. После `invoice.paid`: квота сброшена, конвертация 200 OK, `remaining = 19`. | **PASS** |
| **22** | **Section 3 Variable Period Lengths (7d / 28d)** | Чекаут без авторитетных рамок → короткий первый период (7 дней prorated) → 28 дней февраля | Устранение 30-дневной догадки: периоды фиксируются строго из инвойсов, квота сбрасывается на границе периода. | Короткий период 7 дней принят; последующий период февраля (28 дней) принят; квота корректно обнулена на границе. | **PASS** |
| **23** | **Section 3 Delayed Checkout Delivery** | Событие `invoice.paid` доставлено РАНЬШЕ, чем `checkout.session.completed` | Ранний инвойс предварительно создает право доступа с авторитетными датами; поздний чекаут не ломает период. | Право успешно создано по инвойсу; чекаут привязал сессию; доступ активен, период сохранен. | **PASS** |
| **24** | **Section 3 Duplicate / Adjustment Invoice** | Повторный инвойс или корректировка для того же периода (`new_valid_until == cur_valid`) | Сохранение текущего `current_period_start` и счетчика квоты: отсутствие произвольного обнуления использования. | Квота исчерпана (429); после повторного инвойса того же периода квота НЕ сбросилась, 429 сохранен. | **PASS** |

---

## 4. Архитектурное заключение

1. **Замечания Решений № 32 и № 33 закрыты в полном объёме:**
   - **Строгая валидация (S01)**: целочисленная сумма в центах, строгий EUR, совпадение mode (`payment` vs `subscription`). При любых расхождениях — изоляция в карантин (`quarantined`).
   - **Защита от воскрешения (S02)**: отмененная подписка (`canceled`) не может быть реанимирована последующим чекаутом с тем же идентификатором.
   - **Детерминированное упорядочивание при равных timestamp (S03)**: введение `last_invoice_id` и `last_invoice_status` устраняет недетерминированность порядка доставки при одинаковом `created`. Обе перестановки (`paid -> failed` и `failed -> paid`) приводят к стабильному и корректному состоянию `active`.
   - **Устранение фиктивных 30-дневных рамок (Раздел 3 Решения № 33)**: флаг `has_authoritative_period` исключает локальные догадки чекаута. Поддерживаются любые переменные биллинговые циклы: недельные прорации (7 дней), календарные месяцы любой длины (28 дней февраля, 30/31 день).
   - **Устойчивость к опережающей доставке инвойса (Раздел 3 Решения № 33)**: доставка `invoice.paid` до `checkout.session.completed` предварительно инициализирует подписку с авторитетными датами, а чекаут связывает платежную информацию без повреждения границ цикла.
   - **Идемпотентность повторных инвойсов одного периода (Раздел 3 Решения № 33)**: корректировочные инвойсы одного периода не сдвигают начало цикла и не обнуляют накопленный расход квот.
2. **Безопасность и чистота стенда:**
   - Образ `statement2muster-api:1.0.8` собран с `--no-cache` и зафиксирован в неизменяемом виде (`sha256:1e1be37ad6e44ba05d8c8044d0ebf450f88be447beae2856c67309f3cd0521da`).
   - Контейнер `5dd8e97322f4` находится в состоянии `healthy`. Обезличенный инспект зафиксирован в `docs/stripe_acceptance/docker_inspect_108_sanitized.json`.
   - Секреты не попали в репозиторий, инспекты и отчеты.
   - Все 24 интеграционных сценария успешно завершены со статусом PASS.
3. **Статус блока Приоритет A:**
   - Блок **Synthetic Signed Webhook Integration** полностью реализован, протестирован на живом бэкенде Hetzner и готов к вынесению официального вердикта Главного Архитектора.
   - Переход к этапу **S05 (Stripe Sandbox Acceptance)** подготовлен в соответствии с планом.
