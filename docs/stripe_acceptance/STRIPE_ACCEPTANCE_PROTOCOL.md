# Протокол приёмочных испытаний: Stripe Lifecycle & Entitlements (Sandbox)

**Основание:** Решения Главного Архитектора № 24 (`24_SMTP_STATUS_AND_FULL_GO_PLAN_2026-09-14.md`), № 25 (`25_NEXT_BLOCK_MANAGED_EXTENSION_ACCEPTANCE_2026-09-15.md`) и № 31 (`31_MANAGED_EXTENSION_GO_2026-09-15.md`)  
**Дата проведения:** 2026-09-16  
**Статус:** **100% PASSED (13 из 13 сценариев успешно выполнены на живом бэкенде Hetzner)**  
**Исполнитель:** Antigravity (Implementation Engineer)  
**Контролирующие лица:** Главный Архитектор (OpenAI Codex CLI `codex.exe`, сессия `01a084d1-4ac0-7882-8535-5d02f422042b`), Product Owner (Vitali Grecciani / Vito)  

---

## 1. Provenance и параметры испытательного стенда

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Тестовый Git Commit** | `785ead5f6cee448f86fd634d65771dd0a2fda44c` | Включает доработки `billing_service.py` и раннер приёмки |
| **Backend Docker Image** | `statement2muster-api:1.0.6` | Неизменяемый образ, собран `--no-cache` на Hetzner Host `46.225.95.36` |
| **Backend Image ID** | `sha256:83cac5653dff598899ab3f585ec6773a9f86f069a58870fee614785721f3251f` | Зафиксирован в Docker Daemon Hetzner |
| **Backend Container ID** | `27a358f156c02b5ed2b3a9116a6508ce3f439eb0beedb378731dd09d2c8126b8` | Имя контейнера: `s2m-backend-api`, Status: `healthy` |
| **Docker Inspect Artifact** | `docs/stripe_acceptance/docker_inspect_106_sanitized.json` | Обезличенный JSON инспекции контейнера по строгому allowlist (`Config.Env` исключён) |
| **API URL** | `http://127.0.0.1:8000` | SSH-туннель к продуктивному контейнеру Hetzner (`127.0.0.1:8100`) |
| **Режим биллинга** | **Stripe Sandbox / Test Mode** | Строго синтетические данные, отсутствие списания реальных средств |
| **Исполняемый раннер тестов** | `tests/acceptance/run_stripe_lifecycle.py` | Зафиксирован в репозитории проекта |
| **Машинный результат** | `docs/stripe_acceptance/stripe_lifecycle_results.json` | 13/13 сценариев со статусом PASS |
| **Каталог цен и тарифов** | `docs/stripe_acceptance/STRIPE_CATALOG_ALIGNMENT.md` | Сверка производственных и тестовых Price IDs, валют и сумм |

---

## 2. Результаты испытаний жизненного цикла Stripe (13 сценариев)

Тестирование проведено автономным раннером `tests/acceptance/run_stripe_lifecycle.py` против живого развёрнутого API на Hetzner. Каждое событие вебхука подписывалось аутентичным HMAC-SHA256 заголовком `Stripe-Signature`. Для каждого шага проверялся не только возврат HTTP 200 вебхуком, но и состояние в БД, ответ `/api/v1/me/entitlements` и реальное исполнение квоты в `/api/v1/convert`.

### Сводная матрица сценариев:

| № | Сценарий | Событие Stripe / Действие | Ожидаемый результат | Фактический результат | Статус |
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

---

## 3. Архитектурные выводы и соответствие критериям Решения № 24

1. **Все требования Решения № 24 выполнены в полном объёме:**
   - Тарифы Starter, PRO и Lifetime проверены;
   - Защита каталога, валют (строго `EUR`) и сумм доказана;
   - Льготный период (`cancel_at_period_end`) и немедленное прекращение проверены как различные продуктовые состояния;
   - Идемпотентность и защита от переставленных/устаревших вебхуков подтверждены;
   - Проверено не просто получение HTTP 200 вебхуком, но и реальное состояние в БД и выполнение конвертации через API.
2. **Безопасность секретов:**
   - Все проверки выполнены с ключами песочницы (`sk_test_hetzner_c07`, `whsec_hetzner_c07`).
   - Секреты не содержатся в репозитории и протоколах.
   - Обезличенный инспект контейнера зафиксирован в `docs/stripe_acceptance/docker_inspect_106_sanitized.json`.
3. **Готовность к релизному решению:**
   - Блок Stripe Lifecycle (Приоритет A) готов к официальному рассмотрению Главным Архитектором.
