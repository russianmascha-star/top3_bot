import requests
import json
import re
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

# Ключ ScrapingBee
SCRAPINGBEE_API_KEY = "3KG51UIRHKF5U0SS73Z3TQ30EZQYYD3ISHPW0BC6VFJJTPT7D3CRTGUKXDGOG9WR99ZTVC4BKRXRUAFK"

# Целевой API (не страница, а сам JSON-эндпоинт)
API_URL = "https://www.stoloto.ru/p/api/mobile/api/v35/service/draws/archive?game=top3&count=1&page=1"
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

# ==================== Получение JSON через ScrapingBee (минимальные заголовки) ====================
def fetch_json_via_scrapingbee():
    try:
        scrapingbee_url = "https://app.scrapingbee.com/api/v1/"
        params = {
            'api_key': SCRAPINGBEE_API_KEY,
            'url': API_URL,
            'render_js': 'false',
            'premium_proxy': 'true',
            'country_code': 'ru',
            'timeout': '20000',
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.10.0 Safari/537.36',
            'Referer': 'https://www.stoloto.ru/top3/archive',
        }
        logger.info(f"Запрос к ScrapingBee для API: {API_URL}")
        resp = requests.get(scrapingbee_url, params=params, headers=headers, timeout=30)
        logger.info(f"Статус ScrapingBee: {resp.status_code}")
        if resp.status_code != 200:
            logger.error(f"Ошибка ScrapingBee: {resp.status_code} - {resp.text[:200]}")
            return None
        # ScrapingBee возвращает ответ от целевого URL в теле
        # Проверим, что это JSON
        try:
            data = resp.json()
            logger.info(f"Получен JSON, первые ключи: {list(data.keys()) if isinstance(data, dict) else 'list'}")
            return data
        except json.JSONDecodeError:
            logger.warning("ScrapingBee вернул не JSON, первые 500 символов:")
            logger.warning(resp.text[:500])
            return None
    except Exception as e:
        logger.error(f"Ошибка при запросе ScrapingBee: {e}")
        return None

def parse_draw_from_api_response(data):
    """Извлекает номер и числа из JSON ответа API"""
    try:
        if isinstance(data, dict) and 'draws' in data:
            draws = data['draws']
            if draws and len(draws) > 0:
                draw = draws[0]
                draw_number = draw.get('drawNumber') or draw.get('number')
                numbers = []
                if 'results' in draw and len(draw['results']) > 0:
                    numbers = draw['results'][0].get('numbers', [])
                if draw_number and numbers:
                    logger.info(f"✅ Получен тираж №{draw_number}, числа: {numbers}")
                    return {'drawNumber': draw_number, 'numbers': numbers}
        elif isinstance(data, list) and len(data) > 0:
            draw = data[0]
            draw_number = draw.get('drawNumber') or draw.get('number')
            numbers = draw.get('numbers', [])
            if not numbers and 'results' in draw:
                numbers = draw['results'][0].get('numbers', [])
            if draw_number and numbers:
                logger.info(f"✅ Получен тираж №{draw_number}, числа: {numbers}")
                return {'drawNumber': draw_number, 'numbers': numbers}
        logger.warning(f"Неожиданная структура JSON: {data}")
        return None
    except Exception as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return None

def fetch_latest_draw():
    data = fetch_json_via_scrapingbee()
    if not data:
        return None
    return parse_draw_from_api_response(data)

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
