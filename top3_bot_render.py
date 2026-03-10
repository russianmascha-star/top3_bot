import requests
import json
from datetime import datetime
import time
import threading
import os
import sys
import re
import logging
from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode
import asyncio
from bs4 import BeautifulSoup  # обязательно установить через pip

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_SECONDS = 60  # можно увеличить до 300-600
# Используем только HTML, так как API заблокирован
HTML_URL = "https://www.stoloto.ru/top3/archive"
# ===================================================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!")

last_draw_number = None
app = Flask(__name__)

# Заголовки для имитации браузера
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.stoloto.ru/',
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

# ==================== Парсинг HTML ====================
def fetch_latest_draw():
    """
    Парсит страницу архива Топ-3 и возвращает данные последнего тиража
    в формате, аналогичном API: {'drawNumber': int, 'results': [{'numbers': [int, int, int]}]}
    """
    try:
        logger.info(f"Загружаем страницу: {HTML_URL}")
        response = session.get(HTML_URL, timeout=15)
        logger.info(f"Статус ответа: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки страницы: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Находим все тиражи (они в блоках с классом "draws-item")
        draws_items = soup.find_all('div', class_='draws-item')
        if not draws_items:
            logger.warning("Не найдены элементы с классом 'draws-item'")
            return None

        # Берём первый (последний) тираж
        first_item = draws_items[0]
        
        # Номер тиража – в элементе с классом "draws-item__number"
        number_elem = first_item.find('span', class_='draws-item__number')
        if not number_elem:
            logger.warning("Не найден номер тиража")
            return None
        draw_number_text = number_elem.get_text(strip=True)
        # Номер может быть в формате "№12345", извлекаем цифры
        draw_number = int(re.search(r'\d+', draw_number_text).group())

        # Числа – в элементах с классом "draws-item__number-ball" (обычно 3 штуки)
        balls = first_item.find_all('span', class_='draws-item__number-ball')
        if len(balls) < 3:
            logger.warning(f"Найдено только {len(balls)} шаров, ожидалось 3")
            numbers = []
        else:
            numbers = [int(ball.get_text(strip=True)) for ball in balls[:3]]

        logger.info(f"Найден тираж №{draw_number}, числа: {numbers}")
        return {
            'drawNumber': draw_number,
            'results': [{'numbers': numbers}]
        }

    except Exception as e:
        logger.error(f"Ошибка при парсинге HTML: {e}", exc_info=True)
        return None

def format_numbers_only(draw):
    numbers = draw.get('results', [{}])[0].get('numbers', [])
    if numbers:
        return f"🎲 {'-'.join(map(str, numbers))}"
    return "🎲 ?-?-?"

# ==================== Основная логика ====================
def check_new_draw():
    global last_draw_number
    now = datetime.now().strftime('%H:%M:%S')
    logger.info(f"=== Проверка в {now} ===")

    latest_draw = fetch_latest_draw()
    if not latest_draw:
        logger.warning("⚠️ Не удалось получить данные")
        return

    current_number = latest_draw.get('drawNumber')
    if current_number is None:
        logger.warning("Номер тиража отсутствует")
        return

    if last_draw_number is None:
        last_draw_number = current_number
        logger.info(f"ℹ️ Последний известный тираж: №{last_draw_number}")
    elif current_number > last_draw_number:
        logger.info(f"🎉 НОВЫЙ ТИРАЖ! №{current_number}")
        numbers_text = format_numbers_only(latest_draw)
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
