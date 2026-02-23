# Backend (FastAPI + SQLite) для Telegram Mini App

## Что делает
- Авторизация на каждом запросе через `initData` из Telegram WebApp (без JWT/сессий).
- CRUD задач для пользователя (`user_id` берётся из валидного `initData`).
- Фильтры задач: `active`, `today`, `completed`.
- Лидерборд по количеству завершённых задач.
- Фоновая проверка дедлайнов каждую минуту + уведомления в Telegram.

> Фильтр `today` работает по **UTC**.

## ENV переменные (Railway)
- `BOT_TOKEN` — токен вашего Telegram-бота.
- `FRONTEND_ORIGIN` — домен фронта на Timeweb (например `https://myapp.ru`).
- `TIMEZONE` — сейчас для документации (проект использует UTC), можно оставить `UTC`.
- `DATABASE_PATH` — путь к sqlite-файлу (по умолчанию `tasks.db`).

## Локальный запуск
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Деплой на Railway
1. Создайте новый проект Railway → `Deploy from GitHub`.
2. Выберите репозиторий и папку `backend` как root (или настройте Start Command).
3. Укажите Start Command:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
4. Добавьте ENV в Railway:
   - `BOT_TOKEN`
   - `FRONTEND_ORIGIN`
   - `TIMEZONE=UTC`
5. Задеплойте, получите URL вида `https://xxx.up.railway.app`.

## Проверка уведомлений
1. Создайте задачу с дедлайном через 1–2 минуты.
2. Дождитесь срабатывания минутного цикла.
3. Убедитесь, что:
   - пришло сообщение о дедлайне,
   - задача автоматически перешла в `completed`.
