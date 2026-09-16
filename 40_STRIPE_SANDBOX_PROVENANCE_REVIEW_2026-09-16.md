# Решение 40 — адресная сверка S05

Дата: 2026-09-16. Проверенный локальный HEAD: `e78a32202035d48fb18b03fc1decb7d576dc493a`.

**Вердикт: функциональная приёмка S05 сохраняется. Окончательный GO ожидает только подтверждения связи образа с release commit, уже запрошенной Решением 39.** Новых функциональных условий нет.

## Закрытые замечания

- В stripe_lifecycle_results.json исправлен backend_image на statement2muster-api:1.0.14; image ID и полный container ID совпадают с hetzner_container_inspect_1014.json. Отчёт содержит 30/30 PASS.
- Санитизированный inspect присутствует: container `06d151787c832a4bcc732266ef88fe8bb92ebb6b5f20e374690bd4106fe974b4` → image `sha256:b90fefef75a84ff36a3861b3f32ce126e70a53186f0c0bc7ffb519efc2477edb`, тег 1.0.14, healthy. Manifest digest указан отдельно.
- Раннер tests/acceptance/run_stripe_sandbox_e2e.py присутствует; в нём есть Checkout, Refund.create и Invoice.pay. В этом аудите он не запускался, внешние объекты не создавались.
- Проверенные Starter Invoice ID и PRO Customer/Subscription IDs согласованы между JSON и Markdown.
- Diff backend между release commit 5599c4c и текущим HEAD пуст.

Точность отчётности: доступный JSON регрессии указывает run commit `8949dd5531f444a186d3e2f587fb4c2e9bad1e8a`, а не e78a322. Это допустимо как сохранённый предыдущий прогон при неизменённом backend; не выдавать его за новый прогон на HEAD.

## Единственная оставшаяся связь

Представленный inspect подтверждает container → image, но не image → исходники release commit `5599c4c5621493066e2eac5c96ac6637a5624e78`. В labels нет org.opencontainers.image.revision; в каталоге stripe_acceptance не найдено source manifest/binding. Тег 1.0.14, VERSION и image manifest digest не содержат доказательства соответствия Git-дереву. Пустой локальный diff также не проверяет содержимое удалённого образа.

**Достаточный способ закрытия:** сохранить SHA-256 манифест Python-исходников из /app/app работающего контейнера и независимо построенный манифест backend/app из Git blobs commit 5599c4c; приложить сравнение путей и хэшей (0 diff/missing/extra) с полными container/image ID. Если применяется LF-нормализация, описать её. Не включать .env, ключи, базы данных и пользовательские данные. Альтернатива — существующая проверяемая сборочная аттестация, связывающая этот digest с commit.

Пересборка, новые платежи и повтор пяти E2E-сценариев для этой сверки не требуются. После подтверждения связи остаётся вынести S05 GO в ранее принятом пятисценарном объёме.

Проверка выполнена локально по предоставленным артефактам; состояние Hetzner/Stripe независимо не опрашивалось. C07, Managed Extension и Synthetic GO сохраняются. Полнота аудита секретов этим документом не удостоверяется.
