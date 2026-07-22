# Запуск PUBG Mobile Squad Finder v1.3.1 на Bothost

## 1. Подготовка GitHub

Распакуйте архив. В корне репозитория должны находиться:

- `main.py`;
- `requirements.txt`;
- `Dockerfile`;
- папка `app`.

Не помещайте папку проекта ещё в одну вложенную папку репозитория.

Не загружайте `.env`, базы, резервные копии и токены.

## 2. Создание приложения на Bothost

1. Создайте Telegram-бота из GitHub-репозитория.
2. Главный файл укажите `main.py`.
3. Включите использование домена.
4. В поле порта установите `8080`.
5. После получения домена выполните повторный деплой.

Приложение слушает `0.0.0.0` и читает реальный порт из переменной `PORT`.

## 3. Обязательные переменные

```env
ENVIRONMENT=production
OWNER_TELEGRAM_ID=ВАШ_TELEGRAM_ID
TELEGRAM_MODE=webhook
WEBHOOK_PATH=/telegram/webhook
WEBHOOK_SECRET=СЛУЧАЙНЫЙ_СЕКРЕТ
ALLOW_DEV_AUTH=false
DATABASE_URL=sqlite+aiosqlite:////app/data/squad_finder.db
BACKUP_ENABLED=true
BACKUP_DIR=/app/data/backups
BACKUP_INTERVAL_HOURS=24
BACKUP_KEEP_COUNT=14
PORT=8080
```

Bothost обычно передаёт автоматически:

- `BOT_TOKEN`;
- `DOMAIN`;
- `PORT`.

Если `DOMAIN` не появился, задайте:

```env
PUBLIC_BASE_URL=https://ваш-домен.bothost.tech
```

Секрет webhook:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Допустимы только латинские буквы, цифры, `_` и `-`.

## 4. Перенос базы v1.2.0

При наличии старой SQLite-базы:

1. остановите приложение;
2. через файловый менеджер Bothost загрузите её как `/app/data/squad_finder.db`;
3. задайте `DATABASE_URL=sqlite+aiosqlite:////app/data/squad_finder.db`;
4. запустите приложение.

Миграция создаёт новые production-таблицы, не удаляя старые данные.

## 5. Проверка запуска

Откройте:

```text
https://ВАШ-ДОМЕН/health
```

Ожидается:

```json
{"status":"ok","version":"1.3.1","environment":"production"}
```

Затем:

```text
https://ВАШ-ДОМЕН/ready
```

Должны быть:

- HTTP `200`;
- `database: true`;
- `bot: true`;
- `webhook: true`.

Если `/health` работает, а `/ready` возвращает `503`, смотрите конкретное поле и логи.

## 6. Подключение Mini App

В BotFather укажите HTTPS-адрес Mini App:

```text
https://ВАШ-ДОМЕН/
```

Кнопка `/start` использует тот же адрес. Открывайте приложение именно внутри Telegram — production API принимает только подписанные `initData`.

## 7. Проверка владельца

1. Откройте Mini App своим Telegram-аккаунтом.
2. Раздел «Владелец» должен появиться.
3. Внутри раздела «Система» проверьте базу, бота и webhook.
4. Нажмите «Создать резервную копию».
5. У другого аккаунта кнопки владельца быть не должно, а прямой API-запрос должен возвращать `404`.

## 8. Проверка Telegram Stars

После деплоя выполните тест минимального тарифа:

1. создать рекламную заявку;
2. получить официальный счёт XTR;
3. оплатить внутри Telegram;
4. проверить статус `pending_moderation`;
5. одобрить из панели владельца;
6. проверить показ и переход;
7. выполнить тестовый возврат владельцем.

Реальную оплату и возврат нельзя полностью проверить без живого бота и Telegram-клиента.

## 9. Резервные копии

SQLite-копии сохраняются в:

```text
/app/data/backups
```

Хранятся последние `BACKUP_KEEP_COUNT` файлов и JSON-манифесты. Для внешнего PostgreSQL Dockerfile устанавливает `pg_dump`; дополнительно включите резервное копирование у провайдера БД.

## 10. Частые ошибки

### 502 или 504

- порт Bothost не равен `8080`;
- приложение не читает `PORT`;
- домен включён до повторного деплоя;
- процесс упал из-за production-проверки переменных.

### `/ready` показывает `webhook: false`

- не задан `WEBHOOK_SECRET`;
- `DOMAIN`/`PUBLIC_BASE_URL` не является HTTPS;
- неверный `BOT_TOKEN`;
- Telegram не смог установить webhook.

### Панель владельца не появилась

- неверный `OWNER_TELEGRAM_ID`;
- Mini App открыта в обычном браузере, а не Telegram;
- Telegram использует старый кэш — полностью закройте и откройте Mini App.

### База пропала после обновления

База была не в `/app/data`. Используйте только путь:

```env
DATABASE_URL=sqlite+aiosqlite:////app/data/squad_finder.db
```

### `/start` отправляется, но бот не отвечает

В v1.3.1 в логах после команды должны появиться строки:

```text
Получен Telegram update: update_id=... type=message user_id=...
Обработка /start: user_id=... chat_id=... mini_app_url=https://.../
Ответ на /start отправлен: user_id=... chat_id=...
Telegram update обработан: update_id=... type=message handled=true
```

При запуске также сверяйте строку `Telegram-бот подключён: id=... username=@...` — username должен совпадать с ботом, которому вы отправляете `/start`. Если строк `Получен Telegram update` нет, смотрите `pending_updates` и `Telegram сообщает об ошибке webhook` в стартовых логах.
