#!/bin/bash

# Скрипт для тестирования webhook

WEBAPP_URL="${WEBAPP_URL:-https://k5n9n5-94-41-87-102.ru.tuna.am}"

echo "🧪 Тестирование webhook..."
echo ""

# 1. Проверка доступности локального сервера
echo "1. Проверка локального сервера:"
if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "   ✅ Локальный сервер работает"
    curl -s http://localhost:8000/api/health | python3 -m json.tool 2>/dev/null
else
    echo "   ❌ Локальный сервер не доступен"
    exit 1
fi
echo ""

# 2. Проверка доступности через Tuna
echo "2. Проверка доступности через Tuna:"
if curl -s "${WEBAPP_URL}/api/health" > /dev/null 2>&1; then
    echo "   ✅ Tuna туннель активен"
    curl -s "${WEBAPP_URL}/api/health" | python3 -m json.tool 2>/dev/null
else
    echo "   ❌ Tuna туннель не доступен"
    echo "   Убедитесь, что туннель запущен: tuna http 8000"
    exit 1
fi
echo ""

# 3. Проверка информации о webhook
echo "3. Информация о webhook:"
curl -s http://localhost:8000/api/webhook-info | python3 -m json.tool 2>/dev/null
echo ""

# 4. Тест отправки обновления (симуляция)
echo "4. Тест обработки обновления:"
TEST_UPDATE='{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": {
      "id": 123456789,
      "is_bot": false,
      "first_name": "Test",
      "username": "testuser"
    },
    "chat": {
      "id": 123456789,
      "first_name": "Test",
      "username": "testuser",
      "type": "private"
    },
    "date": 1640000000,
    "text": "/start"
  }
}'

echo "   Отправка тестового обновления на ${WEBAPP_URL}/api/webhook..."
RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "${WEBAPP_URL}/api/webhook" \
  -H "Content-Type: application/json" \
  -d "$TEST_UPDATE" \
  --max-time 10)

HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_CODE/d')

if [ "$HTTP_CODE" = "200" ]; then
    echo "   ✅ Запрос успешен (HTTP $HTTP_CODE)"
    echo "   Ответ: $BODY"
else
    echo "   ⚠️  HTTP код: $HTTP_CODE"
    echo "   Ответ: $BODY"
fi
echo ""

# 5. Проверка логов
echo "5. Проверьте логи приложения на наличие:"
echo "   - '📥 Получен запрос на /api/webhook'"
echo "   - '📨 Обновление получено'"
echo "   - '🎯 Получена команда /start'"
echo ""
