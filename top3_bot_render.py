import requests
import json
from datetime import datetime
import time
import threading
from telegram import Bot
from telegram.constants import ParseMode
import asyncio
import os
from flask import Flask

# ========== НАСТРОЙКИ ==========
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GAME_NAME = "top3"
CHECK_INTERVAL_SECONDS = 300  # 5 минут для теста, потом замените на 900
API_URL = f"https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/archive?count=1&game={GAME_NAME}"
# ===============================

last_draw_number = None

# --- Flask для health checks ---
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

# --- Функции бота ---
async def send_telegram_message(text):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        print(f"✅ Сообщение отправлено: {text}")
    except Exception as e:
        print(f"❌ Ошибка при отправке в Telegram: {e}")

def fetch_latest_draw():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and 'draws' in data and len(data['draws']) > 0:
            return data['draws'][0]
        return None
    except Exception as e:
        print(f"❌ Ошибка при парсинге: {e}")
        return None

def format_numbers_only(draw):
    results = draw.get('results', [])
    if results and 'numbers' in results[0]:
        winning_numbers = results[0]['numbers']
        numbers_str = '-'.join(map(str, winning_numbers))
    else:
        numbers_str = '?-?-?'
    return f"🎲{numbers_str}"

def check_new_draw():
    global last_draw_number
    now = datetime.now().strftime('%H:%M:%S')
    print(f"[{now}] Проверка...")
    latest_draw = fetch_latest_draw()
    if not latest_draw:
        print("⚠️ Нет данных от API")
        return
    current_number = latest_draw.get('drawNumber')
    if last_draw_number is None:
        last_draw_number = current_number
        print(f"ℹ️ Бот запущен. Последний тираж: №{last_draw_number} (не отправлен)")
    elif current_number > last_draw_number:
        print(f"🎉 Новый тираж! №{current_number}")
        short_message = format_numbers_only(latest_draw)
        asyncio.run(send_telegram_message(short_message))
        last_draw_number = current_number
    else:
        print("➖ Новых тиражей нет")

def background_check():
    """Функция, работающая в фоновом потоке: делает проверки и спит."""
    print("🚀 Запуск фонового потока с проверками")
    # Первая проверка сразу
    check_new_draw()
    # Затем цикл
    while True:
        print(f"💤 Фоновый поток спит {CHECK_INTERVAL_SECONDS} сек...")
        time.sleep(CHECK_INTERVAL_SECONDS)
        check_new_draw()

if __name__ == "__main__":
    # Запускаем фоновый поток для проверок
    bg_thread = threading.Thread(target=background_check)
    bg_thread.daemon = True
    bg_thread.start()
    print("✅ Фоновый поток запущен, теперь запускаем Flask в главном потоке")
    # Запускаем Flask (блокирует главный поток)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
