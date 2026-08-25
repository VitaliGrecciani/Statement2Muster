# Statement2Muster (BankSync)

Автоматическая конвертация банковских выписок (PDF/CSV) в стандартизированный формат Muster для импорта в бухгалтерские системы (BMD, DATEV).

## Документы проекта

- [[01_PRD_MVP|01. PRD — MVP v1.0]] — цель, платформа, user journey, монетизация
- [[02_Технический_стек|02. Технический стек и архитектура]] — Chrome Extension, FastAPI backend, Next.js лендинг
- [[03_Структура_репозитория|03. Структура монорепозитория]] — дерево файлов проекта

## Ключевые решения

| Компонент | Технология | Деплой |
|---|---|---|
| Chrome Extension | HTML/CSS/JS + Manifest V3 | Chrome Web Store |
| Backend API | Python + FastAPI | Docker на Hetzner |
| Лендинг + Auth | Next.js + TailwindCSS | Vercel |
| База данных | PostgreSQL (Supabase/Docker) | — |
| Биллинг | Stripe Checkout | — |

## Монетизация MVP

3 бесплатные конвертации (localStorage) → редирект на лендинг → Stripe подписка.

---

*Проект создан: 2026-08-23*
