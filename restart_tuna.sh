#!/bin/bash

# Скрипт для перезапуска Tuna туннеля

echo "🔄 Перезапуск Tuna туннеля..."
echo ""

# Проверяем наличие переменных
TUNA_TOKEN="${TUNA_TOKEN:-tt_dzlsgcyntgvbpv0uregz8jw9d88rhxq9}"
TUNA_LOCATION="${TUNA_LOCATION:-ru}"
PORT="${PORT:-7070}"

# Останавливаем старые процессы tuna
echo "1. Остановка старых процессов Tuna..."
pkill -f "tuna http" 2>/dev/null
sleep 2
echo "   ✅ Старые процессы остановлены"
echo ""

# Проверяем, что приложение запущено
echo "2. Проверка приложения на порту $PORT..."
if curl -s "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
    echo "   ✅ Приложение работает на порту $PORT"
else
    echo "   ⚠️  Приложение не доступно на порту $PORT"
    echo "   Убедитесь, что приложение запущено: python bot.py"
    read -p "Продолжить? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Запускаем новый Tuna туннель
echo "3. Запуск нового Tuna туннеля..."
echo "   Токен: ${TUNA_TOKEN:0:10}..."
echo "   Регион: $TUNA_LOCATION"
echo "   Порт: $PORT"
echo ""
echo "   После запуска вы получите новый URL"
echo "   Не закрывайте этот терминал!"
echo ""

if [ -n "$TUNA_TOKEN" ]; then
    if [ -n "$TUNA_LOCATION" ]; then
        tuna http "$PORT" --token="$TUNA_TOKEN" --location="$TUNA_LOCATION"
    else
        tuna http "$PORT" --token="$TUNA_TOKEN"
    fi
else
    if [ -n "$TUNA_LOCATION" ]; then
        tuna http "$PORT" --location="$TUNA_LOCATION"
    else
        tuna http "$PORT"
    fi
fi
