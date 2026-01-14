#!/bin/bash

# Скрипт для запуска бота с Cloudflare Tunnel

echo "🚀 Запуск бота с Cloudflare Tunnel..."

# Проверяем, установлен ли cloudflared
if ! command -v cloudflared &> /dev/null; then
    echo "❌ cloudflared не установлен!"
    echo "Установите его:"
    echo "  macOS: brew install cloudflare/cloudflare/cloudflared"
    echo "  Linux: wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
    exit 1
fi

# Запускаем бота в фоне
echo "📦 Запуск бота на порту 8000..."
python3 bot.py &
BOT_PID=$!

# Ждем немного, чтобы бот запустился
sleep 3

# Запускаем Cloudflare Tunnel
echo "🌐 Запуск Cloudflare Tunnel..."
echo "📱 URL будет показан ниже. Скопируйте его и обновите WEBAPP_URL в bot.py"
echo ""

cloudflared tunnel --url http://localhost:8000

# При остановке скрипта убиваем бота
trap "kill $BOT_PID" EXIT
