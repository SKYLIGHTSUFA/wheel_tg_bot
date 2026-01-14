# Настройка Cloudflare Tunnel

## 1. Установка cloudflared

### macOS:
```bash
brew install cloudflare/cloudflare/cloudflared
```

### Linux:
```bash
# Скачайте бинарник с официального сайта
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

### Windows:
Скачайте с https://github.com/cloudflare/cloudflared/releases

## 2. Быстрый запуск (без регистрации)

```bash
cloudflared tunnel --url http://localhost:8000
```

Это даст вам временный URL вида: `https://random-name.trycloudflare.com`

## 3. Постоянный туннель (рекомендуется)

### Шаг 1: Войдите в Cloudflare
```bash
cloudflared tunnel login
```

### Шаг 2: Создайте туннель
```bash
cloudflared tunnel create wheel_tg_bot
```

### Шаг 3: Создайте конфигурационный файл
Создайте файл `~/.cloudflared/config.yml`:

```yaml
tunnel: <tunnel-id-из-шага-2>
credentials-file: /Users/ilnaz/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: wheel-tg-bot.yourdomain.com  # Ваш домен в Cloudflare
    service: http://localhost:8000
  - service: http_status:404
```

### Шаг 4: Запустите туннель
```bash
cloudflared tunnel run wheel_tg_bot
```

## 4. Автозапуск (опционально)

### macOS (через launchd):
Создайте файл `~/Library/LaunchAgents/com.cloudflare.tunnel.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cloudflare.tunnel</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/cloudflared</string>
        <string>tunnel</string>
        <string>run</string>
        <string>wheel_tg_bot</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Загрузите:
```bash
launchctl load ~/Library/LaunchAgents/com.cloudflare.tunnel.plist
```
