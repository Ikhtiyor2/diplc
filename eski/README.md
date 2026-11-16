# DiplomacyLC

Платформа языкового центра: домашние задания, упражнения, тесты, посещаемость, прогресс учеников и Telegram-уведомления.

Интерфейс на русском. Бэкенд — Django, страницы отдаются сервером (HTML + HTMX), без Node.js и без SPA на React. За счёт этого кабинет открывается сразу, без гидратации.

## Стек

- Django 5.1, Django REST Framework, JWT, Swagger (`/api/docs/`)
- PostgreSQL в Docker, SQLite для локального быстрого старта
- Prisma не используется: схема и миграции — Django ORM / Prisma-уровень модели описан в приложениях `apps/*`
- Tailwind-сборка не нужна: свой CSS design system в `static/css/app.css`
- Chart.js для графиков, Lucide-иконки как SVG
- Supabase Storage — опционально через S3-совместимый endpoint
- Telegram Bot API

## Роли

| Роль | Возможности |
| --- | --- |
| Администратор | Пользователи и пароли, группы, вся статистика, тесты, упражнения, Telegram, журнал действий |
| Преподаватель | Свои группы, посещаемость, ДЗ, проверка, тесты, аналитика ученика, журнал |
| Ученик | Дашборд, сдача ДЗ, тесты, упражнения, прогресс, привязка Telegram |

## Запуск через Docker

```bash
copy .env.example .env
docker compose up --build
```

Откройте http://localhost:8000

## Локальный запуск без Docker

Нужен Python 3.10+.

```bash
py -3 -m pip install -r requirements.txt
py -3 manage.py migrate
py -3 manage.py seed
py -3 manage.py runserver
```

Логин в кабинет выдаёт администратор центра. Пароли в репозитории и на публичных страницах не хранятся.

## API

- Swagger UI и схема доступны только после входа: `/api/docs/`, `/api/schema/`
- Логин JWT: `POST /api/v1/auth/login/` с полями `login` и `password`
- Заголовок: `Authorization: Bearer <access>`

Основные ресурсы: `users`, `groups`, `attendance`, `assignments`, `submissions`, `tests`, `questions`, `test-results`, `exercises`, `audit`, `notifications`, `dashboard`.

Экспорт Excel: `GET /api/v1/groups/{id}/export/attendance/` и `/export/grades/` (также кнопки в журнале группы).

## Telegram

1. Создайте бота у [@BotFather](https://t.me/BotFather) и запишите токен в `TELEGRAM_BOT_TOKEN`.
2. Укажите `TELEGRAM_BOT_USERNAME`.
3. Запустите `python manage.py run_telegram_bot` или сервис `bot` в Compose.
4. В профиле сгенерируйте код и отправьте его боту.

Уведомления ученика: новое ДЗ, новый тест, дедлайн завтра, оценка, комментарий.
Уведомления преподавателя: новая сдача, напоминание о проверке (`python manage.py notify_reminders`).

## Supabase Storage

В `.env`:

```
USE_SUPABASE_STORAGE=1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_ENDPOINT_URL=https://<project>.supabase.co/storage/v1/s3
```

## Структура

```
apps/accounts        пользователи, роли, Telegram-привязка
apps/groups          языки, группы, зачисления
apps/attendance      посещаемость и автопересчёт %
apps/homework        задания, файлы, сдачи, проверка
apps/assessments     тесты 5 типов и результаты
apps/practice        онлайн-упражнения 7 типов
apps/notifications   in-app + Telegram
apps/audit           история действий
apps/api             REST + JWT + RBAC
apps/web             HTML-кабинет
```
