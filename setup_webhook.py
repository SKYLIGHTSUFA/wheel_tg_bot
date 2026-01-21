import requests

# 1. Ваш токен
BOT_TOKEN = "8576138519:AAES_lBttGBQ-cvJ_HvcDjTNzYyoGYBOneE"

# 2. Ваш белый IP и порт (например, 8443)
# HTTPS обязательно!
WEBHOOK_URL = "https://94.41.87.102:8443/webhook"

# 3. Путь к публичному сертификату, который мы создали
CERT_PATH = r"C:\Users\fatik\public.pem"


def set_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"

    # Параметры запроса
    data = {
        "url": WEBHOOK_URL
    }

    # Открываем файл сертификата и отправляем его
    with open(CERT_PATH, "rb") as cert_file:
        files = {
            "certificate": cert_file
        }

        response = requests.post(url, data=data, files=files)

    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")


if __name__ == "__main__":
    set_webhook()
