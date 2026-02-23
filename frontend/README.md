# Frontend (статический Telegram Mini App)

## Что настроить перед загрузкой
В `app.js` измените:
- `API_BASE` на URL backend в Railway (например `https://xxx.up.railway.app`).

## Локальная проверка
Достаточно открыть `index.html` через простой static server:
```bash
cd frontend
python -m http.server 8080
```

## Деплой на Timeweb
1. В панели Timeweb создайте сайт/домен.
2. Загрузите файлы из папки `frontend` в корень сайта:
   - `index.html`
   - `styles.css`
   - `app.js`
3. Убедитесь, что сайт открывается по HTTPS.

## Подключение Mini App в BotFather
1. Откройте `@BotFather`.
2. Выберите вашего бота.
3. Настройте Mini App URL:
   - команда `Configure Mini App` (или через меню Bot Settings → Menu Button).
   - укажите HTTPS URL вашего фронта на Timeweb.
4. Откройте бота в Telegram и запустите Mini App.

## Как работает авторизация
- Telegram WebApp даёт `initData`.
- Фронт отправляет `initData` в заголовке `X-Telegram-Init-Data` в каждый запрос.
- Backend валидирует подпись `initData` по `BOT_TOKEN`, достаёт `user_id` и выполняет действия от имени этого пользователя.
