# Отладка ошибок на Vercel

## Ошибка: FUNCTION_INVOCATION_FAILED

### Шаг 1: Проверьте логи

1. Зайдите в [Vercel Dashboard](https://vercel.com/dashboard)
2. Выберите ваш проект
3. Перейдите в **Deployments** → выберите последний деплой
4. Откройте вкладку **Logs** → **Runtime Logs**
5. Найдите ошибку в логах

### Шаг 2: Проверьте переменные окружения

Убедитесь, что установлены:
- `BOT_TOKEN` - токен Telegram бота
- `WEBAPP_URL` - URL вашего проекта (опционально)

### Шаг 3: Проверьте health endpoint

Откройте в браузере:
```
https://your-project.vercel.app/api/health
```

Должен вернуться JSON:
```json
{
  "status": "ok",
  "vercel": true,
  "db_path": "/tmp/db.sqlite3"
}
```

### Шаг 4: Частые проблемы

#### Проблема: Ошибка импорта

**Решение:**
- Проверьте, что все зависимости в `requirements.txt`
- Убедитесь, что версии пакетов совместимы
- Проверьте логи на наличие ошибок импорта

#### Проблема: Ошибка с базой данных

**Решение:**
- На Vercel БД должна быть в `/tmp`
- Проверьте, что переменная `VERCEL=1` установлена (устанавливается автоматически)
- Убедитесь, что путь к БД: `/tmp/db.sqlite3`

#### Проблема: Ошибка с Bot Token

**Решение:**
- Проверьте, что `BOT_TOKEN` установлен в Environment Variables
- Убедитесь, что токен корректный (можно проверить через Telegram Bot API)

### Шаг 5: Локальная отладка

Установите Vercel CLI и запустите локально:

```bash
npm i -g vercel
vercel dev
```

Это запустит локальный сервер, который имитирует Vercel окружение.

### Шаг 6: Проверка зависимостей

Убедитесь, что в `requirements.txt` есть все необходимые пакеты:

```
aiogram>=3.0.0
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
aiosqlite>=0.19.0
pydantic>=2.0.0
python-multipart>=0.0.6
mangum>=0.17.0
```

### Шаг 7: Пересборка проекта

Иногда помогает полная пересборка:

1. В Vercel Dashboard → Settings → General
2. Нажмите "Redeploy" → "Redeploy with existing Build Cache" → выберите "Use existing Build Cache: No"
3. Дождитесь завершения деплоя

## Получение подробных логов

Если ошибка не очевидна, добавьте больше логирования:

1. Проверьте логи в Vercel Dashboard
2. Добавьте `print()` statements в код для отладки
3. Проверьте, что все исключения обрабатываются

## Контакты для поддержки

Если проблема не решается:
1. Проверьте [документацию Vercel](https://vercel.com/docs)
2. Проверьте [GitHub Issues](https://github.com/vercel/vercel/issues)
3. Обратитесь в [Vercel Community](https://github.com/vercel/community)
