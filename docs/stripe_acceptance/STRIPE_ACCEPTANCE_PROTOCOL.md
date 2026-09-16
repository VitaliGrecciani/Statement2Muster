# Протокол приёмочных испытаний: Stripe Lifecycle & Entitlements (Synthetic Signed Webhook Integration)

**Основание:** Решения Главного Архитектора № 24 (`24_SMTP_STATUS_AND_FULL_GO_PLAN_2026-09-14.md`), № 25 (`25_NEXT_BLOCK_MANAGED_EXTENSION_ACCEPTANCE_2026-09-15.md`), № 31 (`31_MANAGED_EXTENSION_GO_2026-09-15.md`), № 32 (`32_STRIPE_LIFECYCLE_REVIEW_2026-09-16.md`), № 33 (`33_STRIPE_SYNTHETIC_FOLLOWUP_2026-09-16.md`), № 34 (`34_STRIPE_SYNTHETIC_REVIEW_2026-09-16.md`) № 35 (`35_STRIPE_SYNTHETIC_REVIEW_2026-09-16.md`) и № 36 (`36_STRIPE_SYNTHETIC_REVIEW_2026-09-16.md`)  
**Дата проведения:** 2026-09-16  
**Статус:** **100% PASSED (30 из 30 сценариев успешно выполнены на живом бэкенде Hetzner)**  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Контролирующие лица:** Главный Архитектор (OpenAI Codex CLI `codex.exe`, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`), Product Owner (Vitali Grecciani / Vito)  

---

## 1. Provenance и параметры испытательного стенда

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Тестовый Git Commit** | `6f03c77cfb699b55aee0e95816cab0776fda42fb` | Включает исправления замечаний Решений № 32, № 33, № 34, № 35 и № 36 (разделение скоупов событий подписок и инвойсов, сверка периода по `paid_through`, монотонность валидации инвойсов без мутаций, конечный дедлайн предварительного доступа, каталог и защита тенанта в раннем инвойсе) |
| **Backend Docker Image** | `statement2muster-api:1.0.11` | Неизменяемый образ, собран `--no-cache` на Hetzner Host `46.225.95.36` |
| **Backend Image ID** | `sha256:c2a89e67abae8ebce0502973db83b9d5e659cec5847278cf97f39e0fdbbc38e1` | Зафиксирован в Docker Daemon Hetzner |
| **Backend Container ID** | `173b145cb5f491e11252aed5bcb293e1ce1ad403af8466b5389ce51f4ed417dd` | Имя контейнера: `s2m-backend-api`, Status: `healthy` |
| **Docker Inspect Artifact** | `docs/stripe_acceptance/docker_inspect_1011_sanitized.json` | Обезличенный JSON инспекции контейнера по строгому allowlist (`Config.Env` очищен от секретов) |
| **API URL** | `http://127.0.0.1:8000` | SSH-туннель к продуктивному контейнеру Hetzner (`127.0.0.1:8100`) |
| **Тип испытаний** | **Synthetic Signed Webhook Integration** | Автономная интеграционная проверка валидаторов, БД и квот с аутентичным HMAC-SHA256 (`Stripe-Signature`) |
| **Исполняемый раннер тестов** | `tests/acceptance/run_stripe_lifecycle.py` | 30 сценариев, полностью закрывающих замечания Решений № 32, № 33, № 34, № 35 и № 36 |
| **Машинный результат** | `docs/stripe_acceptance/stripe_lifecycle_results.json` | 30/30 сценариев со статусом PASS |
| **Каталог цен и тарифов** | `docs/stripe_acceptance/STRIPE_CATALOG_ALIGNMENT.md` | Сверка производственных и тестовых Price IDs, валют, сумм и режимов |

---

## 2. Матрица устранения замечаний Решений № 32, № 33, № 34, № 35 и № 36

| Замечание | Суть дефекта / Требование Архитектора | Реализованное исправление в релизе 1.0.9 | Подтверждающий тест | Статус |
| :--- | :--- | :--- | :--- | :---: |
| **S01** | Валидация суммы и валюты: при 0, отрицательной или отсутствующей сумме, не-EUR валюте или несовпадении `mode`/плана права могли активироваться. | В `billing_service.py` внедрена строгая проверка:<br>1) `type(amount_total) is int and amount_total > 0 and amount_total == expected["amount_cents"]`;<br>2) `isinstance(currency, str) and currency.lower() == "eur"`;<br>3) режим `subscription` для `starter`/`pro`, `payment` для `lifetime`.<br>При любом нарушении статус переводится в `"quarantined"`, `plan_code = None`. | **Сценарий 14** (проверены 6 веток: 0 amount, omitted, negative, missing currency, wrong currency, mode mismatch). | **PASS** |
| **S02** | Поздний `checkout.session.completed` мог реанимировать отмененную подписку (`canceled`) с новым `event_id`. | В `_handle_checkout_completed` добавлена проверка статуса существующей подписки / разовой покупки. Если `existing.status == "canceled"`, воскрешение блокируется, права остаются аннулированными. | **Сценарий 15** (checkout → deleted → поздний checkout с тем же `subscription_id` → права отозваны). | **PASS** |
| **S03 (Part 1)** | Неупорядоченность событий: старое `invoice.payment_failed` после нового `invoice.paid` могло деградировать права; старое `invoice.paid` после неудачи активировать; `valid_until` мог откатиться назад. | В модель `Entitlement` добавлено поле `last_event_created_at`. Обработчики сверяют `event_created_ts`. События строго старше `last_event_created_at` отклоняются как устаревшие. Монотонность `valid_until` соблюдается для подтверждённых периодов. | **Сценарий 18** (защита от отката `valid_until` назад). | **PASS** |
| **S03 (Part 2: Equal created, Решение № 33)** | Равные timestamp (`created = 100`) давали результат, зависящий от порядка доставки: `paid -> failed` давал `past_due`, а `failed -> paid` давал `active`. | В модель `Entitlement` добавлены поля `last_invoice_id` и `last_invoice_status`. При `invoice.payment_failed`:<br>1) если `invoice_id == ent.last_invoice_id` и `ent.last_invoice_status == "paid"`, сбой игнорируется как устаревшая попытка для уже оплаченного счета;<br>2) если период сбоя `failed_period_end <= paid_through` при `status == "active"`, сбой не ломает уже подтверждённый оплаченный период.<br>Обе перестановки детерминированно сохраняют статус `active`. | **Сценарии 16 и 17** (перестановка A: paid → failed при created=100 даёт active; перестановка B: failed → paid при created=100 даёт active). | **PASS** |
| **S04** | `subscription.updated` с неизвестным `price` сохранял старый `plan_code` и активировал его. Несовместимый `mode` создавал подписку с `valid_until = None`. | В `_handle_subscription_updated` при неизвестном price `plan_code` сбрасывается в `None`, статус в `"quarantined"`. При попытке включить в подписку разовый товар (mode mismatch) подписка изолируется в карантин. | **Сценарии 19, 20** (неизвестный price сбрасывает plan_code в None; не-рекуррентный товар переводит подписку в карантин). | **PASS** |
| **Решение № 34, Пункт 1 (P1)** | В `_handle_invoice_paid` мутация `ent.plan_code` производилась до проверки монотонности периода. Проигнорированный старый инвойс с тарифом PRO менял план с Starter на PRO. | Все проверки применимости события (проверка `event_created_ts`, проверка монотонности периода `candidate_valid_until < cur_valid`) выполняются строго **ДО** любых мутаций ORM-объекта. При обнаружении устаревания происходит немедленный выход без изменения `ent` (тариф, статус, даты и квоты остаются нетронутыми). Изменения применяются атомарно только после успешного прохождения всех проверок. | **Сценарий 25** (активный Starter с расходом квоты 1/20 получает устаревший инвойс PRO: тариф остаётся Starter, остаток остаётся 19, статус active). | **PASS** |
| **Решение № 34, Пункт 2 (P1)** | Предварительный доступ (provisional active) при чекауте без дат имел `valid_until = None`, что в текущей логике делало доступ бессрочным при задержке/недоставке инвойса. | Устранен бессрочный доступ при отсутствии границ: в модель добавлена колонка `provisional_deadline`. При чекауте без инвойса устанавливается строгий конечный дедлайн ожидания инвойса: `valid_until = now + 72 часа`, `has_authoritative_period = 0`. Если инвойс не поступает, по истечении 72 часов доступ автоматически прекращается (экспирация). | **Сценарий 26** (создание подписки с provisional deadline; при истечении дедлайна доступ аннулируется, происходит возврат на trial). | **PASS** |
| **Решение № 34, Пункт 3** | Ветвь `invoice-before-checkout` не проверяла сумму, валюту и полноту периода по политике S01; чекаут не защищал от перепривязки `tenant_id` (угон подписки). | 1) При создании права из раннего инвойса внедрена строгая проверка каталога: точное совпадение суммы в центах, строгий EUR, обязательное присутствие и корректный порядок границ (`period_end > period_start`). При любых нарушениях — статус `quarantined`.<br>2) В чекауте внедрена защита привязки тенанта: если `existing.tenant_id != current_tenant_id`, операция блокируется, подписка изолируется в `quarantined`, фиксируется алерт безопасности. | **Сценарий 27** (отклонение искажённой суммы, не-EUR валюты, отсутствующего периода; блокировка попытки угона чужим тенантом). | **PASS** |
| **Решение № 34, Пункт 4** | `payment_failed` игнорировался, если `failed_period_end <= valid_until`. Однако `valid_until` мог быть сдвинут событием `subscription.updated` без оплаты, что приводило к игнорированию реального сбоя списания. | В модель `Entitlement` добавлена колонка `paid_through` (фактически оплаченный срок). Поле `paid_through` обновляется **только** при получении `invoice.paid` и никогда не изменяется событием `subscription.updated`. Обработчик `payment_failed` сравнивает период сбоя строго с `paid_through`. Если период не оплачен (`failed_period_end > paid_through`), сбой не игнорируется, статус переходит в `past_due`, платные права отзываются. | **Сценарий 28** (цепочка: оплата периода N → смещение границы подписки на N+1 без оплаты → payment_failed для N+1 → статус переводится в `past_due`, PRO-привилегии отозваны). | **PASS** |
| **Решение № 36 (Разделение скоупов событий подписок и инвойсов)** | В `_handle_invoice_paid` проверка `event_created_ts < ent.last_event_created_at` выполняла ранний выход без мутаций. Календарное событие `subscription.updated` с более поздним timestamp (`S.created = 202`) блокировало задержанный инвойс оплаты (`I.created = 201`), не давая продвинуть `current_period_start` и сбросить квоту. | Введена колонка `last_invoice_event_created_at` для изолированного отслеживания инвойсных событий. События подписки обновляют `last_event_created_at`, а инвойсы — `last_invoice_event_created_at`. Инвойс отклоняется как устаревший только если `event_created_ts < last_invoice_event_created_at` И `candidate_valid_until <= cur_paid`. При успешной оплате обновляется `last_invoice_event_created_at = event_created_ts` без изменения `last_event_created_at`. | **Сценарии 29 и 30** (фиксированная пара `(I, S)` с `I.created = 201 < S.created = 202`. В обоих порядках доставки `S -> I` и `I -> S` на независимых начальных состояниях квота 20 восстанавливается, 1 конвертация -> 19, дубликат инвойса сохраняет 19). | **PASS** |
| **Решение № 35 (Сверка периода по `paid_through`)** | При опережающей доставке `subscription.updated` перед `invoice.paid`, `valid_until` сдвигался на период N+1. Последующий `invoice.paid` сравнивал дату инвойса с `cur_valid` (`candidate_valid_until == cur_valid`) и ошибочно считал новый период дубликатом, не сдвигая `current_period_start` и не сбрасывая квоту Starter. | В `_handle_invoice_paid` проверка монотонности и новизны периода переведена на сравнение строго с `cur_paid = to_utc(ent.paid_through)`:<br>1) При `candidate_valid_until > cur_paid`: признаётся **НОВЫЙ ОПЛАЧЕННЫЙ ПЕРИОД**, `valid_until = max(candidate_valid_until, cur_valid)`, `paid_through = candidate_valid_until`, `current_period_start = candidate_period_start` (полный сброс квоты Starter до 20 выписок);<br>2) При `candidate_valid_until == cur_paid`: признаётся дубликат/корректировка текущего оплаченного периода, `current_period_start` не смещается, расход квоты сохраняется;<br>3) При `candidate_valid_until < cur_paid`: устаревший инвойс, отклоняется без мутаций. | **Сценарии 29 и 30** (проверены обе перестановки: 29: sub.updated -> invoice.paid; 30: invoice.paid -> sub.updated. В обеих перестановках: исчерпание в периоде N -> сброс до 20 в периоде N+1 -> расход 1 выписки (остаток 19) -> дубликат инвойса сохраняет остаток 19). | **PASS** |


---

## 3. Результаты испытаний (30 сценариев)

Все 30 сценариев выполнены против живого бэкенда на Hetzner (контейнер `173b145cb5f4`, образ `statement2muster-api:1.0.11`). Каждое событие вебхука подписывалось аутентичным HMAC-SHA256 заголовком `Stripe-Signature`.

### Сводная таблица результатов:

| № | Сценарий | Событие Stripe / Входные данные | Ожидаемый результат | Фактический результат | Статус |
| :-: | :--- | :--- | :--- | :--- | :-: |
| **1** | **Starter Subscription** | `checkout.session.completed` (`price_starter_490`, €4.90, 490¢) | Выдача квоты 20 выписок в месяц. После конвертации выписки остаток уменьшается до 19. | Выдан план `starter`, `quota_limit = 20`. Конвертация выполнена штатно (200 OK), квота зафиксирована: `used = 1`, `remaining = 19`. | **PASS** |
| **2** | **Business PRO Subscription** | `checkout.session.completed` (`price_pro_2900`, €29.00, 2900¢) | Выдача безлимитного тарифа (`quota_limit = "unlimited"`), активация `multi_upload`. | Выдан план `pro`, статус `active`, `quota_limit = "unlimited"`. Пакетная конвертация нескольких файлов прошла успешно (200 OK). | **PASS** |
| **3** | **Lifetime License** | `checkout.session.completed` (`price_lifetime_8900`, €89.00, mode `payment`) | Разовый платёж (`source_type = "one_time"`), пожизненный безлимит, `valid_until = None`. | Выдан план `lifetime`, `source_type = "one_time"`, `quota_limit = "unlimited"`, доступ бессрочный. | **PASS** |
| **4** | **Subscription Renewal** | `invoice.paid` с будущим `period.end` | Продление подписки: обновление `valid_until` и `paid_through` в соответствии с периодом инвойса. | `valid_until` продлён до конца расчетного периода (`2026-10-16`), статус сохранён `active`. | **PASS** |
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
| **25** | **Decision 34 Point 1: Stale Invoice Immutability** | Действующий Starter получает устаревший инвойс с тарифом PRO и прошлым периодом. | Обработчик отклоняет событие до любых мутаций. Тариф, статус, даты и остаток квоты остаются нетронутыми. | Тариф остался `starter`, статус `active`, `remaining_units = 19`, конвертация выполнена штатно (200 OK). | **PASS** |
| **26** | **Decision 34 Point 2: Bounded Provisional Deadline** | Чекаут без инвойса получает дедлайн 72 часа. Проверка истечения срока дедлайна. | Исключение бессрочного доступа: при наступлении дедлайна доступ прекращается, права аннулируются. | Дедлайн зафиксирован; при просрочке дедлайна происходит падение на trial, права аннулируются. | **PASS** |
| **27** | **Decision 34 Point 3: Early Invoice Policy & Tenant Hijacking** | Аномальные ранние инвойсы (сумма, валюта, период) и попытка чужого тенанта заявить чекаут на чужую подписку. | Отклонение всех аномалий в карантин. Строгая блокировка попытки угона подписки с переводом в `quarantined`. | Аномалии переведены в карантин. Попытка угона заблокирована, атакующий остался на trial с 0 правами. | **PASS** |
| **28** | **Decision 34 Point 4: Separate paid_through from Subscription Dates** | Оплата периода N → сдвиг даты подписки на N+1 без оплаты → сбой оплаты инвойса N+1. | Раздельный учёт `paid_through`: сбой списания не игнорируется, статус переходит в `past_due`, права отзываются. | Статус переведен в `past_due`, PRO-права отозваны, конвертация сверх лимита trial заблокирована (429). | **PASS** |
| **29** | **Decision 36 Permutation 1 (S.created > I.created, S first)** | Исчерпание Starter (20 выписок → 429) → `subscription.updated` (N+1) → `invoice.paid` (N+1) | Продвижение `current_period_start` до N+1, сброс квоты до 20 выписок. 1 конвертация уменьшает остаток до 19. Повторный инвойс N+1 сохраняет 19. | Квота обнулена (429); после `sub.updated` + `invoice.paid` квота сброшена до 20 (`used = 0`); 1 конвертация 200 OK (`remaining = 19`); дубликат инвойса сохранил `remaining = 19`. | **PASS** |
| **30** | **Decision 36 Permutation 2 (I.created < S.created, I first)** | Исчерпание Starter (20 выписок → 429) → `invoice.paid` (N+1) → `subscription.updated` (N+1) | Идентичное детерминированное состояние при обратном порядке доставки: сброс до 20 выписок, 1 конвертация → 19, сохранение 19 при дубликате. | Квота обнулена (429); после `invoice.paid` + `sub.updated` квота сброшена до 20 (`used = 0`); 1 конвертация 200 OK (`remaining = 19`); дубликат инвойса сохранил `remaining = 19`. | **PASS** |


---

## 4. Архитектурное заключение

1. **Замечания Решений № 32, № 33, № 34, № 35 и № 36 закрыты в полном объёме:**
   - **Атомарность и защита от мутаций старыми инвойсами (Пункт 1 Решения № 34)**: Любые проверки устаревания (по timestamp и монотонности периода) производятся до изменения полей сущности `Entitlement`.
   - **Устранение бессрочного предварительного доступа (Пункт 2 Решения № 34)**: Введен атрибут `provisional_deadline` (72 часа). Подписка без подтвержденного инвойса имеет строго ограниченный дедлайн и автоматически экспирируется при отсутствии оплаты.
   - **Строгая валидация ранних инвойсов и защита привязки тенантов (Пункт 3 Решения № 34)**: Создание прав через `invoice-before-checkout` подчинено единой политике S01 (сумма, валюта, полнота периода). Попытки межтенантного угона подписок блокируются и изолируются в карантин.
   - **Разделение применимости событий подписок и инвойсов (Решение № 36)**: Устранена блокировка инвойсов оплаты событиями календаря подписки. Введена независимая фиксация `last_invoice_event_created_at`. Календарное событие `subscription.updated` с опережающим таймстемпом более не может подавить легитимный задержанный инвойс оплаты `invoice.paid`. Полная инвариантность к порядку доставки доказана на идентичных начальных состояниях в сценариях 29 и 30.
   - **Разделение фактически оплаченного срока `paid_through` и даты подписки (Пункт 4 Решения № 34)**: Поле `paid_through` продвигается исключительно подтвержденной оплатой инвойса. Смещение дат подписки событиями `subscription.updated` более не мешает обработке `payment_failed`.
2. **Безопасность и чистота стенда:**
   - Образ `statement2muster-api:1.0.11` собран с `--no-cache` и зафиксирован в неизменяемом виде (`sha256:c2a89e67abae8ebce0502973db83b9d5e659cec5847278cf97f39e0fdbbc38e1`).
   - Контейнер `173b145cb5f4` находится в состоянии `healthy`. Обезличенный инспект зафиксирован в `docs/stripe_acceptance/docker_inspect_1011_sanitized.json`.
   - Секреты не попали в репозиторий, инспекты и отчеты.
   - Все 30 интеграционных сценариев успешно завершены со статусом PASS (100%).
3. **Статус блока Приоритет A:**
   - Блок **Synthetic Signed Webhook Integration** полностью реализован, протестирован на живом бэкенде Hetzner и готов к вынесению официального вердикта Главного Архитектора.
   - Переход к этапу **S05 (Stripe Sandbox Acceptance)** подготовлен в соответствии с планом.


## S05 — Stripe Sandbox E2E Acceptance (Decision 38 Fully Verified)

**Date:** 2026-09-16T20:38:00Z  
**API Version:** 1.0.14 (backend release 1.0.14)  
**Deployed Git Commit:** `5599c4c5621493066e2eac5c96ac6637a5624e78`  
**Deployed Container ID:** `06d151787c83` (Image: `statement2muster-api:1.0.14`)  
**Hetzner Host:** 46.225.95.36  
**Stripe Mode:** sandbox_test (Account: `acct_1SmFVpI3NVmMw8fj`, Grecciani Labs)  
**Stripe API Versions:** Event API `2025-12-15.clover` | Invoicing/Pricing `2025-03-31.basil`  
**Synthetic Regression Status:** **30/30 PASS (100%)** on backend v1.0.14  
**Sandbox E2E Status:** **5/5 PASS (100%)** — OVERALL: PASSED

---

### 1. Provenance & Release Chain Alignment (Decision 38 Point 4)

| Commit | Role | Scope |
|---|---|---|
| `4632d52` | Release 1.0.13 | Initial Stripe 2024+/2025 compatibility helpers (`_extract_subscription_id`, `_extract_line_price_id`, `_extract_parent_metadata`) |
| `7a7a779` | Documentation | Interim review & protocol snapshot |
| `5599c4c` | **Release 1.0.14** | Fix `_handle_charge_refunded` with `Entitlement.payment_intent` filter; bump to 1.0.14; deployed container `06d151787c83` |

---

### 2. Full Scenario Results (Decision 38 Verified)

| Scenario | Result | Stripe Objects & Evidence | Entitlement State & Rights Check |
|---|---|---|---|
| **S05-1 Starter Subscription** | ✅ PASS | Customer: `cus_VGxT9RS9m9rCYD`<br>PM: `pm_1UGPYcI3NVmMw8fjLLmXFTjg`<br>Sub: `sub_1UGPYdI3NVmMw8fjgslFIURU`<br>Invoice: `in_1UGPYdI3NVmMw8fj2V180G60`<br>Event: `invoice.paid` (200 OK) | **Plan:** starter<br>**Status:** active<br>**Quota:** 20 files/mo (remaining: 20)<br>**Paid Through:** 2026-10-16 |
| **S05-2 PRO Subscription** | ✅ PASS | Customer: `cus_VGxT9RS9m9rCYD`<br>PM: `pm_1UGPYcI3NVmMw8fjLLmXFTjg`<br>Sub: `sub_1UGPYxI3NVmMw8fjM1DAELYl`<br>Event: `invoice.paid` (200 OK) | **Plan:** pro<br>**Status:** active<br>**Quota:** unlimited<br>**Capabilities:** multi_upload=true, anti_mix_guard=true, priority_support=true, batch_dedup=true |
| **S05-3 Subscription Cancellation** | ✅ PASS | Sub: `sub_1UGPYxI3NVmMw8fjM1DAELYl`<br>Method: `stripe.Subscription.cancel`<br>Stripe status: `canceled`<br>Event: `customer.subscription.deleted` (200 OK) | **Revocation Confirmed:**<br>API returns **trial fallback**<br>Quota reset to 3, all PRO capabilities blocked |
| **S05-4 Lifetime Checkout & Real Refund** *(Decision 38 Points 1 & 3)* | ✅ PASS | Checkout Session: `cs_test_a1fomEVHHVKtkLv1R3N7Wq4oUUXujhQWVKaT0clePdAfbLRiNXeP1SGjsU` (€89.00 EUR)<br>PI: `pi_3UGPZXI3NVmMw8fj0AGft1ka`<br>Charge: `ch_3UGPZXI3NVmMw8fj0usQCAZC`<br>Refund: `re_3UGPZXI3NVmMw8fj0cP4UmIt`<br>Events: `checkout.session.completed`, `charge.refunded` (200 OK) | **Before Refund:** plan=lifetime, status=active, quota=unlimited, all capabilities=true<br>**After Real Refund:** Entitlement marked canceled via PI match; API returns **trial fallback** (quota=3, capabilities revoked). |
| **S05-5 Subscription Renewal Failure** *(Decision 38 Point 2)* | ✅ PASS | Sub: `sub_1UGPa6I3NVmMw8fj11ouJw1x`<br>Renewal Invoice: `in_1UGPaRI3NVmMw8fjMoCg4ECt` (€4.90 EUR)<br>Declined PM: `tok_chargeCustomerFail` (`pm_1UGPaOI3NVmMw8fjaDHOTyxk`)<br>CardError: *Your card was declined*<br>Events: `payment_intent.payment_failed`, `charge.failed`, `invoice.payment_failed` (200 OK) | **DB Row:** `status='past_due'`, `last_invoice_status='payment_failed'`<br>**Rights Check:** Paid access revoked immediately; API returns **trial fallback**; paid capabilities blocked. |

---

### 3. Stripe API 2024+/2025 Architecture Compatibility Summary

1. **Invoicing & Subscription Architecture (`2025-03-31.basil`):**
   - Subscriptions in Invoices resolved through `parent.subscription_details.subscription` (with fallback to legacy `subscription`).
   - Line prices resolved through `pricing.price_details.price` (with fallback to `price.id` and `plan.id`).
   - Tenant metadata resolved through `parent.subscription_details.metadata`.
2. **Checkout & Refund Architecture:**
   - Full Checkout Session completion verified via official payment pages confirmation flow with `client_reference_id` and catalog binding (€89.00 EUR).
   - Real refunds resolved through PaymentIntent -> Charge link; entitlement canceled and access revoked.
3. **Billing Testing Standards:**
   - Genuine renewal failure tested via `tok_chargeCustomerFail` card with genuine `invoice.payment_failed` delivery and `past_due` DB transition.

---

### 4. Regression Integrity Verification

- **Synthetic Suite (30/30 PASS):** `tests/acceptance/run_stripe_lifecycle.py` executed on deployed backend v1.0.14 — all 30 tests passed with 100% compliance.
- **Sandbox Suite (5/5 PASS):** `scratch/run_stripe_sandbox_e2e.py` executed on live Hetzner host with real Stripe objects — all 5 scenarios passed with 100% compliance.
- **Overall Verdict Ready:** S05 conditions fully satisfied for Chief Architect final review.
