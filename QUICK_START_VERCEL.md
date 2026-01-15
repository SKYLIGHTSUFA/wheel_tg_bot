# Быстрый старт на Vercel

## 1. Деплой проекта

```bash
# Установите Vercel CLI
npm i -g vercel

# Войдите в аккаунт
vercel login

# Деплой
vercel --prod
```

Или через веб-интерфейс: [vercel.com/dashboard](https://vercel.com/dashboard)

## 2. Настройка переменных окружения

В Vercel Dashboard → Settings → Environment Variables:

- `BOT_TOKEN` - токен вашего Telegram бота
- `WEBAPP_URL` - URL вашего проекта (например: `https://your-project.vercel.app`)

## 3. Настройка Webhook

После деплоя выполните:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-project.vercel.app/api/webhook"
```

Или откройте в браузере:
```
https://your-project.vercel.app/api/set-webhook
```

## 4. Проверка

1. Откройте бота в Telegram
2. Отправьте `/start`
3. Проверьте работу WebApp

## Готово! 🎉

Подробная инструкция: [VERCEL_DEPLOY.md](./VERCEL_DEPLOY.md)
