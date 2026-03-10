import requests
import json
from datetime import datetime
import time
import threading
import sys
from telegram import Bot
from telegram.constants import ParseMode
import asyncio
import os
from flask import Flask

# ========== НАСТРОЙКИ ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GAME_NAME = "top3"
CHECK_INTERVAL_SECONDS = 60  # 1 минута для теста
API_URL = f"https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/archive?count=1&game={GAME_NAME}"
# ===============================

last_draw_number = None
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

async def send_telegram_message(text):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        print("✅ Сообщение отправлено:", text, flush=True)
    except Exception as e:
        print("❌ Ошибка отправки:", e, flush=True)

def fetch_latest_draw():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and 'draws' in data and len(data['draws']) > 0:
            return data['draws'][0]
    except Exception as e:
        print("❌ Ошибка парсинга:", e, flush=True)
    return None

def format_numbers_only(draw):
    results = draw.get('results', [])
    if results and 'numbers' in results[0]:
        return f"🎲{'-'.join(map(str, results[0]['numbers']))}"
    return "🎲?-?-?"

def check_new_draw():
    global last_draw_number
    now = datetime.now().strftime('%H:%M:%S')
    print(f"[{now}] Проверка...", flush=True)
    latest_draw = fetch_latest_draw()
    if not latest_draw:
        print("⚠️ Нет данных", flush=True)
        return
    current_number = latest_draw.get('drawNumber')
    if last_draw_number is None:
        last_draw_number = current_number
        print(f"ℹ️ Последний тираж: №{last_draw_number}", flush=True)
    elif current_number > last_draw_number:
        print(f"🎉 Новый тираж! №{current_number}", flush=True)
        asyncio.run(send_telegram_message(format_numbers_only(latest_draw)))
        last_draw_number = current_number
    else:
        print("➖ Новых нет", flush=True)

def background_loop():
    print("🚀 Фоновый поток запущен", flush=True)
    check_new_draw()
    while True:
        print(f"💤 Сон {CHECK_INTERVAL_SECONDS} сек...", flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)
        check_new_draw()

if __name__ == "__main__":
    bg = threading.Thread(target=background_loop)
    bg.daemon = True
    bg.start()
    print("✅ Flask запускается", flush=True)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
