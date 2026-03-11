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

# Ключ ScrapingBee (ваш)
SCRAPINGBEE_API_KEY = "3KG51UIRHKF5U0SS73Z3TQ30EZQYYD3ISHPW0BC6VFJJTPT7D3CRTGUKXDGOG9WR99ZTVC4BKRXRUAFK"

# Целевой API Столото
TARGET_URL = "https://www.stoloto.ru/p/api/mobile/api/v35/service/draws/archive?game=top3&count=1&page=1"

# Если хотите использовать прокси напрямую (без ScrapingBee), раскомментируйте и укажите
# PROXY = "http://user:pass@ip:port"
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

# Сессия (может не понадобиться для ScrapingBee, но оставим)
session = requests.Session()

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

# ==================== Получение данных через ScrapingBee ====================
def fetch_latest_draw():
    try:
        # Формируем запрос к ScrapingBee
        scrapingbee_url = "https://app.scrapingbee.com/api/v1/"
        params = {
            'api_key': SCRAPINGBEE_API_KEY,
            'url': TARGET_URL,
            'render_js': 'false',          # API не требует JS
            'premium_proxy': 'true'         # использовать премиум прокси для обхода блокировок
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.10.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru,en;q=0.9',
            'Referer': 'https://www.stoloto.ru/top3/archive',
            'Origin': 'https://www.stoloto.ru',
            'Device-Platform': 'WEB_MOBILE_WINDOWS',
            'Device-Type': 'MOBILE',
            'Gosloto-Partner': 'bXMjXFRXZ3coWXh6R3s1NTdUX3dnWIBMLUxmdg',
            'Gosloto-Token': '1e86f2a700-566331-41b406-b68f85-13836177b21027',
        }
        # Куки не передаём через заголовки, ScrapingBee сама их сохранит? Лучше передать как часть запроса?
        # Можно добавить куки в параметр 'cookies' или в заголовок. Попробуем добавить в headers.
        # В ScrapingBee можно передать заголовки через параметр 'headers' (JSON string)
        # Для простоты пока без кук, возможно, они не нужны, если запрос идёт через прокси.
        # Если без кук не работает, можно передать их в параметре 'cookies'.

        logger.info(f"Запрос к ScrapingBee для URL: {TARGET_URL}")
        resp = requests.get(scrapingbee_url, params=params, headers=headers, timeout=30)
        logger.info(f"Статус от ScrapingBee: {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"Ошибка ScrapingBee: {resp.status_code} - {resp.text[:200]}")
            return None

        # Проверяем, что вернулось (может быть JSON или HTML)
        content_type = resp.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            data = resp.json()
        else:
            # Если вернулся HTML, попробуем найти JSON внутри (но вряд ли)
            logger.warning("ScrapingBee вернул не JSON, пробуем распарсить как HTML?")
            # Здесь можно добавить парсинг HTML, но пока просто вернём None
            return None

        # Парсим ответ (ожидаем ту же структуру, что и у прямого API)
        if isinstance(data, dict) and 'draws' in data:
            draws = data['draws']
            if draws and len(draws) > 0:
                draw = draws[0]
                draw_number = draw.get('drawNumber') or draw.get('number')
                numbers = []
                if 'results' in draw and len(draw['results']) > 0:
                    numbers = draw['results'][0].get('numbers', [])
                logger.info(f"✅ Получен тираж №{draw_number}, числа: {numbers}")
                return {'drawNumber': draw_number, 'numbers': numbers}
        logger.warning(f"Неожиданная структура JSON: {data}")
        return None

    except Exception as e:
        logger.error(f"Ошибка при запросе через ScrapingBee: {e}", exc_info=True)
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
