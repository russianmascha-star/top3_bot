import requests
import json
from datetime import datetime
import time
import threading
import os
import sys
import logging
from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode
import asyncio

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_SECONDS = 60

# Расширенный список потенциальных API для Топ-3
API_URLS = [
    # Пробуем разные варианты (первые два уже давали 200)
    "https://www.stoloto.ru/top3/archive/draws",
    "https://www.stoloto.ru/top3/archive/last",
    "https://www.stoloto.ru/top3/archive?format=json",
    "https://www.stoloto.ru/top3/archive/data",
    "https://www.stoloto.ru/api/v1/top3/archive?limit=1",
    "https://www.stoloto.ru/api/v1/games/top3/draws/latest",
    "https://www.stoloto.ru/api/v2/top3/draws/last",
    "https://www.stoloto.ru/top3/result/last?json=1",
    "https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/archive?count=1&game=top3",
    "https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/last?game=top3",
    "https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/archive?count=1&game=top3-1",
    "https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/last?game=top3-1",
]
# ===================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы! Сообщения не будут отправляться.")

last_draw_number = None
app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.stoloto.ru/top3/archive',
    'Connection': 'keep-alive',
}

session = requests.Session()
session.headers.update(HEADERS)

# ==================== Telegram ====================
async def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        logger.info(f"✅ Сообщение отправлено: {text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")

def send_telegram_sync(text):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_telegram_message(text))
    finally:
        loop.close()

# ==================== Поиск работающего API ====================
def try_api(url):
    """Пробует один URL, возвращает (успех, данные)"""
    try:
        logger.info(f"Пробуем API: {url}")
        resp = session.get(url, timeout=10)
        logger.info(f"Статус: {resp.status_code}")
        
        # Если статус 200, но не JSON, выведем начало ответа для анализа
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                logger.warning(f"Content-Type: {content_type}, первые 500 символов ответа:")
                logger.warning(resp.text[:500])
            
            try:
                data = resp.json()
                logger.info(f"JSON получен, ключи: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                # Попытаемся извлечь номер тиража и числа
                draw_number = None
                numbers = []
                if isinstance(data, dict):
                    if 'draws' in data and len(data['draws']) > 0:
                        draw = data['draws'][0]
                        draw_number = draw.get('drawNumber') or draw.get('number')
                        if 'results' in draw and len(draw['results']) > 0:
                            numbers = draw['results'][0].get('numbers', [])
                    elif 'draw' in data:
                        draw = data['draw']
                        draw_number = draw.get('drawNumber') or draw.get('number')
                        if 'results' in draw and len(draw['results']) > 0:
                            numbers = draw['results'][0].get('numbers', [])
                    elif 'drawNumber' in data:
                        draw_number = data['drawNumber']
                        if 'results' in data and len(data['results']) > 0:
                            numbers = data['results'][0].get('numbers', [])
                elif isinstance(data, list) and len(data) > 0:
                    draw = data[0]
                    draw_number = draw.get('drawNumber') or draw.get('number')
                    if 'results' in draw and len(draw['results']) > 0:
                        numbers = draw['results'][0].get('numbers', [])
                
                if draw_number is not None:
                    logger.info(f"✅ Найден тираж №{draw_number}, числа: {numbers}")
                    return True, {'drawNumber': draw_number, 'numbers': numbers}
                else:
                    logger.warning("Не удалось извлечь номер тиража из JSON")
            except json.JSONDecodeError:
                logger.warning("Ответ не является JSON")
        return False, None
    except Exception as e:
        logger.error(f"Ошибка при запросе к {url}: {e}")
        return False, None

def fetch_latest_draw():
    """Перебирает API_URLS и возвращает данные первого успешного"""
    for url in API_URLS:
        success, data = try_api(url)
        if success:
            return data
    logger.error("Ни один API не сработал")
    return None

def format_numbers_only(draw):
    numbers = draw.get('numbers', [])
    if numbers:
        return f"🎲 {'-'.join(map(str, numbers))}"
    return "🎲 ?-?-?"

# ==================== Основная логика ====================
def check_new_draw():
    global last_draw_number
    now = datetime.now().strftime('%H:%M:%S')
    logger.info(f"=== Проверка в {now} ===")

    draw_data = fetch_latest_draw()
    if not draw_data:
        logger.warning("⚠️ Не удалось получить данные")
        return

    current_number = draw_data.get('drawNumber')
    if current_number is None:
        logger.warning("Номер тиража отсутствует")
        return

    if last_draw_number is None:
        last_draw_number = current_number
        logger.info(f"ℹ️ Последний известный тираж: №{last_draw_number}")
        # При первом запуске отправим сообщение о последнем тираже
        numbers_text = format_numbers_only(draw_data)
        send_telegram_sync(f"Бот запущен. Последний тираж: №{current_number} {numbers_text}")
    elif current_number > last_draw_number:
        logger.info(f"🎉 НОВЫЙ ТИРАЖ! №{current_number}")
        numbers_text = format_numbers_only(draw_data)
        send_telegram_sync(numbers_text)
        last_draw_number = current_number
    else:
        logger.info("➖ Новых тиражей нет")

def background_loop():
    logger.info("🚀 Фоновый поток запущен")
    check_new_draw()
    while True:
        logger.info(f"💤 Сон {CHECK_INTERVAL_SECONDS} сек...")
        time.sleep(CHECK_INTERVAL_SECONDS)
        check_new_draw()

# ==================== Flask ====================
@app.route('/')
def health():
    return "Bot is running", 200

@app.route('/status')
def status():
    return {
        'status': 'ok',
        'last_draw': last_draw_number,
        'interval': CHECK_INTERVAL_SECONDS
    }

# ==================== Запуск ====================
if __name__ == "__main__":
    bg = threading.Thread(target=background_loop, daemon=True)
    bg.start()
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"✅ Flask запускается на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
