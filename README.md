# PUBG Mobile Squad Finder v1.3.1

Telegram Mini App для поиска тимейтов, комнат и кланов PUBG Mobile с закрытой панелью владельца и рекламой за Telegram Stars.

## Состояние проекта

Завершены все **7 из 7** этапов. Сборка готова для загрузки в GitHub и запуска на Bothost после заполнения production-переменных.

1. базовая архитектура;
2. игровой поиск;
3. кланы и команды;
4. закрытая панель владельца;
5. Telegram Stars и реклама;
6. production-подготовка для GitHub/Bothost;
7. премиум-графика и адаптивный мобильный интерфейс.

## Что исправлено в v1.3.1

- команда `/start` теперь обрабатывается внутри webhook до возврата HTTP 200;
- Telegram сможет повторить доставку update при временной ошибке обработки;
- устранён риск потери короткой фоновой задачи на хостинге;
- добавлены подробные логи получения update, обработки `/start` и отправки ответа;
- при запуске выводятся ID и username подключённого бота — можно сразу заметить неверный `BOT_TOKEN`;
- выводятся количество ожидающих update и последняя ошибка webhook;
- журнал дедупликации привязан к конкретному Telegram-боту; при первой фиксации или смене токена старые update очищаются, поэтому команда нового бота не будет ошибочно принята за дубль;
- `.env.example` дополнен русскими пояснениями по каждой переменной;
- вся графика, адаптивная вёрстка и production-функции v1.3.0 сохранены без изменений.

## Быстрый локальный запуск

Требуется Python 3.11–3.12.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Для локальной разработки в `.env`:

```env
ENVIRONMENT=development
TELEGRAM_MODE=disabled
ALLOW_DEV_AUTH=true
DEV_TELEGRAM_ID=100001
OWNER_TELEGRAM_ID=100001
DATABASE_URL=sqlite+aiosqlite:///./data/squad_finder.db
BACKUP_DIR=./data/backups
```

Запуск:

```bash
python main.py
```

Открыть `http://127.0.0.1:8080`.

## Production-проверка перед деплоем

После заполнения production-переменных:

```bash
python scripts/preflight.py
```

Успешная проверка завершается кодом `0` и показывает:

- пустой список `configuration_errors`;
- `database: true`;
- итоговый URL webhook.

## База данных

### SQLite на Bothost

```env
DATABASE_URL=sqlite+aiosqlite:////app/data/squad_finder.db
BACKUP_DIR=/app/data/backups
```

Папка `data` сохраняется между обновлениями. Старую базу v1.1.0 можно загрузить как `/app/data/squad_finder.db`; при запуске структура обновится без удаления пользователей, кланов, платежей и рекламы.

### PostgreSQL

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
```

Поддерживаются также входящие адреса `postgres://` и `postgresql://`: приложение преобразует их в async-драйвер автоматически.

## Резервные копии

Автоматически создаются каждые `BACKUP_INTERVAL_HOURS` и хранятся в `BACKUP_DIR`.

Ручной запуск:

```bash
python scripts/backup_db.py
```

Восстановление SQLite выполняется только при остановленном приложении:

```bash
python scripts/restore_sqlite.py data/backups/squad_finder_YYYYMMDDTHHMMSSZ.db data/squad_finder.db
```

Перед заменой текущая база сохраняется как `*.before_restore`.

## Безопасность панели владельца

Панель:

- скрыта в интерфейсе от всех, кроме владельца;
- недоступна обычным пользователям, модераторам и администраторам;
- проверяется сервером по точному `OWNER_TELEGRAM_ID`;
- при чужом запросе `/api/owner/*` возвращает `404`;
- не доверяет произвольному Telegram ID в production;
- использует подписанные Telegram Mini App `initData`.

## Основные маршруты

- `/` — Mini App;
- `/health` — процесс работает;
- `/ready` — база, бот и webhook готовы;
- `/telegram/webhook` — Telegram webhook;
- `/api/*` — API Mini App;
- `/api/owner/*` — скрытый API владельца.

## Структура

```text
app/
  routers/              API-разделы
  static/               Mini App и оптимизированные WebP-изображения
  auth.py               Telegram initData и права
  backup_service.py     резервные копии
  maintenance_service.py фоновые задачи
  middleware.py         лимиты и защитные заголовки
  telegram_service.py   webhook и защита от дублей
bot.py                   обработчики Telegram
main.py                  главный production-запуск
scripts/                 preflight, backup, restore
Dockerfile               контейнерный запуск
```

Подробная инструкция Bothost: `BOTHOST_DEPLOY_RU.md`.
