#!/bin/bash

# Скрипт запуска приложения через Tuna туннель

echo "🚀 Запуск Telegram бота через Tuna туннель..."

# Проверяем наличие переменной окружения BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
    echo "⚠️  Внимание: BOT_TOKEN не установлен!"
    echo "Установите его командой: export BOT_TOKEN='ваш_токен'"
    exit 1
fi

# Проверяем, установлен ли Tuna CLI
if ! command -v tuna &> /dev/null; then
    echo "❌ Tuna CLI не установлен!"
    echo ""
    echo "Установите Tuna CLI:"
    echo "  curl -sSL https://tuna.am/install.sh | bash"
    echo ""
    echo "Или через Homebrew (macOS):"
    echo "  brew install tuna"
    echo ""
    echo "Или через pip:"
    echo "  pip install tuna-cli"
    echo ""
    echo "После установки перезапустите скрипт."
    exit 1
fi

# Проверяем наличие TUNA_TOKEN (опционально, но рекомендуется)
if [ -z "$TUNA_TOKEN" ]; then
    echo "⚠️  Внимание: TUNA_TOKEN не установлен!"
    echo "Получите токен на https://tuna.am после регистрации"
    echo "Установите его командой: export TUNA_TOKEN='tt_...'"
    echo ""
    read -p "Продолжить без токена? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Устанавливаем USE_WEBHOOK для использования webhook
export USE_WEBHOOK=true

# Определяем порт
PORT="${PORT:-7070}"

# Запускаем приложение в фоне
echo "📦 Запускаем приложение на порту $PORT..."
echo "   USE_WEBHOOK=true (webhook будет установлен после запуска Tuna туннеля)"
export PORT=$PORT
python bot.py &
APP_PID=$!

# Ждем немного, чтобы приложение запустилось
sleep 3

# Запускаем Tuna HTTP туннель
echo "🌐 Запускаем Tuna HTTP туннель на порту $PORT..."
echo ""
echo "📋 Инструкции:"
echo "1. Tuna выдаст публичный URL (например: https://xxxxx.tuna.am)"
echo "2. Скопируйте этот URL"
echo "3. В другом терминале установите WEBAPP_URL:"
echo "   export WEBAPP_URL='https://xxxxx.tuna.am'"
echo "4. Установите webhook командой:"
echo "   curl -X POST \"http://localhost:$PORT/api/set-webhook?webhook_url=https://xxxxx.tuna.am/api/webhook\""
echo ""
echo "Или остановите приложение (Ctrl+C в этом терминале) и перезапустите с WEBAPP_URL:"
echo "   export USE_WEBHOOK=true"
echo "   export WEBAPP_URL='https://xxxxx.tuna.am'"
echo "   export PORT=$PORT"
echo "   python bot.py"
echo ""
echo "Для остановки нажмите Ctrl+C"
echo ""

# Запускаем Tuna туннель
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

# После завершения туннеля останавливаем приложение
echo ""
echo "🛑 Останавливаем приложение..."
kill $APP_PID 2>/dev/null
wait $APP_PID 2>/dev/null
echo "✅ Приложение остановлено"
