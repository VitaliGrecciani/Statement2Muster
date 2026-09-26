# Руководство по выполнению Builder E2E (Условие R54-1)

Для закрытия последнего условия Решения 54 (**R54-1**) требуется зафиксировать реальный вызов Action из интерфейса ChatGPT Builder / Preview.

---

### Шаг 1. Создание приватного тестового GPT
1. Откройте в браузере **ChatGPT** -> **Explore GPTs** -> **Create** (или перейдите по адресу `https://chatgpt.com/gpts/editor`).
2. Вкладка **Configure**:
   - **Name:** `Statement2Muster G07 Test`
   - **Description:** `DATEV EXTF & BMD Accounting Converter (Acceptance Test)`
   - **Instructions:**
     ```text
     You are Statement2Muster accounting assistant. When the user provides bank transactions or statement data, invoke the convertStatement action to generate DATEV EXTF (Windows-1252) or BMD NTCS 5.1 export. Always display the financial turnover summary (total debit, total credit, net balance) and present the temporary download link.
     ```

---

### Шаг 2. Добавление Action
1. Внизу раздела **Configure** нажмите **Create new action**.
2. **Authentication:**
   - Выберите **None** (для проверки штатного анонимного Demo-режима).
   - *Альтернативно:* выберите **API Key** -> Auth Type: **Bearer** и укажите токен тарифа Pro.
3. **Schema:**
   - Нажмите **Import from URL** и введите:
     `https://api.statement2muster.com/openapi.json`
   - *Или скопируйте JSON напрямую из файла `docs/chatgpt/openapi.json` (SHA-256: `f6097b0b98048a4bef7f55bfd3fb15f8438a0e5d21967a52690a48937c12ee15`).*
4. **Privacy Policy:**
   `https://statement2muster.com/datenschutz.html`

---

### Шаг 3. Запуск теста в Preview
1. В правой панели **Preview** отправьте тестовое сообщение:
   ```text
   Konvertiere bitte diesen Bankauszug in DATEV EXTF:
   15.03.2026, -189.50 EUR, AWS Cloud Services EMEA, Ref INV-2026-991
   18.03.2026, +3400.00 EUR, Kundenhonorar Softwareaudit, Ref RE-8821
   ```
2. При запросе подтверждения нажмите **Always allow** / **Allow**.
3. Нажмите на виджет вызова Action (пилюлю вызова `api.statement2muster.com`), раскройте детали запроса/ответа.

---

### Шаг 4. Фиксация артефактов для Архитектора
Скопируйте:
1. **Идентификатор тестового GPT** (из адресной строки редактора, например `g-p-XXXXXX` или ссылка `https://chatgpt.com/g/g-XXXXXX`).
2. **JSON запроса и ответа (Trace)** из окна вызова Action в чате.

Эти данные вносятся в протокол для получения финального вердикта **G07 Clearance (GO)**.
