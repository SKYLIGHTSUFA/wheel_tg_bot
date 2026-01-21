#!/bin/bash

# Скрипт для быстрой настройки webhook с новым URL

WEBAPP_URL="${WEBAPP_URL:-https://mo5gx7-94-41-87-102.ru.tuna.am}"
PORT="${PORT:-7070}"

echo "🔧 Настройка webhook..."
echo ""

# 1. Проверяем доступность сервера
echo "1. Проверка локального сервера на порту $PORT..."
if curl -s "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
    echo "   ✅ Сервер работает"
else
    echo "   ❌ Сервер не доступен на порту $PORT"
    echo "   Убедитесь, что приложение запущено: python bot.py"
    exit 1
fi
echo ""

# 2. Проверяем доступность через Tuna
echo "2. Проверка доступности через Tuna..."
if curl -s "${WEBAPP_URL}/api/health" > /dev/null 2>&1; then
    echo "   ✅ Tuna туннель активен"
else
    echo "   ⚠️  Tuna туннель не доступен"
    echo "   Убедитесь, что туннель запущен: tuna http $PORT"
    read -p "Продолжить? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# 3. Устанавливаем webhook
echo "3. Установка webhook..."
WEBHOOK_URL="${WEBAPP_URL}/api/webhook"
RESPONSE=$(curl -s -X POST "http://localhost:${PORT}/api/set-webhook?webhook_url=${WEBHOOK_URL}")

if echo "$RESPONSE" | grep -q "ok"; then
    echo "   ✅ Webhook установлен: $WEBHOOK_URL"
else
    echo "   ❌ Ошибка установки webhook: $RESPONSE"
    exit 1
fi
echo ""

# 4. Проверяем информацию о webhook
echo "4. Информация о webhook:"
curl -s "http://localhost:${PORT}/api/webhook-info" | python3 -m json.tool 2>/dev/null
echo ""

# 5. Проверяем через Telegram API
echo "5. Проверка через Telegram API:"
BOT_TOKEN="${BOT_TOKEN:-8576138519:AAES_lBttGBQ-cvJ_HvcDjTNzYyoGYBOneE}"
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool 2>/dev/null
echo ""

echo "✅ Готово! Теперь отправьте /start в боте для проверки."
