#!/bin/bash

# Скрипт для исправления проблем с webhook

WEBAPP_URL="${WEBAPP_URL:-https://k5n9n5-94-41-87-102.ru.tuna.am}"
BOT_TOKEN="${BOT_TOKEN:-8576138519:AAES_lBttGBQ-cvJ_HvcDjTNzYyoGYBOneE}"

echo "🔧 Исправление проблем с webhook..."
echo ""

# 1. Проверяем pending updates
echo "1. Проверка pending updates через Telegram API:"
WEBHOOK_INFO=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo")
PENDING=$(echo "$WEBHOOK_INFO" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('result', {}).get('pending_update_count', 0))" 2>/dev/null)

if [ "$PENDING" -gt 0 ]; then
    echo "   ⚠️  Обнаружено $PENDING необработанных обновлений"
    echo "   Переустанавливаем webhook для очистки..."
    
    # Переустанавливаем webhook через API приложения
    curl -s -X POST "http://localhost:8000/api/set-webhook?webhook_url=${WEBAPP_URL}/api/webhook" | python3 -m json.tool 2>/dev/null
    
    echo "   ✅ Webhook переустановлен, pending updates должны быть очищены"
else
    echo "   ✅ Pending updates: $PENDING"
fi
echo ""

# 2. Проверяем доступность webhook URL
echo "2. Проверка доступности webhook URL:"
if curl -s "${WEBAPP_URL}/api/health" > /dev/null 2>&1; then
    echo "   ✅ Webhook URL доступен"
else
    echo "   ❌ Webhook URL недоступен!"
    echo "   Убедитесь, что Tuna туннель запущен: tuna http 8000"
    exit 1
fi
echo ""

# 3. Проверяем информацию о webhook
echo "3. Текущая информация о webhook:"
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | python3 -m json.tool 2>/dev/null
echo ""

# 4. Рекомендации
echo "💡 Рекомендации:"
echo "   - Если pending_update_count > 0, отправьте команду /start в боте еще раз"
echo "   - Проверьте логи приложения на наличие ошибок"
echo "   - Убедитесь, что Tuna туннель активен: tuna http 8000"
echo ""
