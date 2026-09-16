# Решение 38 — S05 Stripe Sandbox Acceptance, 1.0.13

Дата: 2026-09-16.

**Вердикт: S05 GO не выдан. Частичная приёмка: результаты S05-1–3 приняты по представленному отчёту; S05-4 и S05-5 не подтверждены как реальные E2E-испытания. Итог 5/5 PASS некорректен.**

## Основание

Прочитаны stripe_sandbox_results.json, S05-раздел STRIPE_ACCEPTANCE_PROTOCOL.md и изменённые участки billing_service.py. Локальный HEAD — `7a7a779e88d214d5a1909615f15977c7fd880f2a`. Stripe и Hetzner в этом аудите не изменялись; независимый удалённый прогон не выполнялся. Реальность объектов S05-1–3 оценивается по предоставленным идентификаторам и результатам команды, а не по личному наблюдению в Dashboard.

## 1. Фактическое покрытие

| Сценарий | Решение |
|---|---|
| Starter | Представлен real Subscription/Invoice и entitlement starter, active, remaining=20; принять в указанном объёме |
| PRO | Представлена real Subscription и unlimited entitlement; принять в указанном объёме |
| Cancellation | Представлены canceled в Stripe и переход API на trial; принять в указанном объёме |
| Refund | Не выполнен: JSON прямо ссылается на синтетический тест 1.0.11 вместо возврата реального платежа |
| Payment failure | Не подтверждён: incomplete subscription и просмотр кода не доказывают invoice.payment_failed → обработку → отзыв прав |

Список доставленных событий в протоколе не содержит charge.refunded и invoice.payment_failed. HTTP 200 сам по себе не доказывает изменение прав: обработчик может принять событие без нахождения связанной entitlement.

## 2. Совместимость API

Добавленные хелперы поддерживают показанные строковые ID в parent.subscription_details.subscription и pricing.price_details.price, а также metadata родителя. Это полезная адаптация; универсальная совместимость со всеми «API 2024+/2025» не доказана. Зафиксировать точную Stripe API version запросов и event.api_version; backend version 1.0.13 и версия SDK не заменяют их.

Изменения parent/pricing относятся к версии **2025-03-31.basil**. Источники: [parent в invoicing objects](https://docs.stripe.com/changelog/basil/2025-03-31/adds-new-parent-field-to-invoicing-objects), [pricing](https://docs.stripe.com/changelog/basil/2025-03-31/invoice-pricing-configurations).

Удаление invoice.payment_intent и invoice.charge не означает отмены возвратов. Stripe ввёл Invoice Payment: связь доступна через invoice.payments / Invoice Payment API, с доступом к PaymentIntent. Refund API принимает charge или payment_intent. Поэтому формулировка «charge.refunded path deprecated in auto-billing» не является основанием для PASS. Источники: [миграция Invoice Payments](https://docs.stripe.com/changelog/basil/2025-03-31/add-support-for-multiple-partial-payments-on-invoices), [создание Refund](https://docs.stripe.com/api/refunds/create).

В текущем backend refund-handler ищет entitlement по payment_intent/source_id/charge_id. Необходимо доказать, что эта связь действительно записана для возвращаемой покупки в новом API, а не только что событие получило HTTP 200.

## 3. Адресные условия закрытия

1. **Refund:** реальный успешный Sandbox-платёж → Refund через актуальную связь PaymentIntent/Charge → реальный charge.refunded → нахождение нужной entitlement → отзыв прав по принятой политике. Зафиксировать идентификаторы покупки, платежа, refund и event, состояние до/после и API-проверку доступа. Для принятой политики Lifetime использовать реальную разовую покупку; возврат подписки не подменяет проверку Lifetime.
2. **Payment failure:** вызвать настоящий неуспешный платёж тестовым способом Stripe, получить invoice.payment_failed и показать состояние соответствующей подписки/entitlement и отказ в платных capabilities. Для проверки отзыва уже выданного PRO предпочтителен сбой продления ранее оплаченной подписки. Использовать [официальные средства тестирования Billing](https://docs.stripe.com/billing/testing). Одного default_incomplete недостаточно.
3. **Checkout:** в представленном S05 подтверждено создание Subscription, но не завершение реального Checkout, указанного в Решении 37. Включить штатный Checkout-путь и client_reference_id/tenant binding в завершающую покупку для Refund либо представить существующие cs_/event-доказательства. Не заменять его прямым созданием Subscription через API.
4. **Привязка результата:** JSON и протокол сейчас указывают commit `f6867f4b852c9de21b3ee1a3123a7504a09db937`, тогда как заявлен `7a7a779...`. Объяснить различие run/build/docs commit; приложить санитизированную привязку образа и исходников, точные Stripe API versions и обезличенные event evidence. Повторить затронутые регрессии legacy/new payload на 1.0.13: старый прогон 1.0.11 не является регрессией нового кода.

В отчёте обозначить S05-4/5 как NOT VERIFIED (либо BLOCKED/SKIPPED с причиной), убрать 5/5 PASS до фактического выполнения. Для новых доказательств не сохранять API keys, JWT, OTP или полные Config.Env.

## 4. Сохранение принятых решений

Synthetic Integration GO Решения 37 остаётся действующим для принятого объёма и версии. C07 и Managed Extension не переоткрываются. Настоящее решение касается незавершённого S05 и адаптации нового Stripe API; общий Full GO для клиентских выписок не выдан.
