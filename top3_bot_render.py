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
from bs4 import BeautifulSoup

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_SECONDS = 60  # можно увеличить до 300-600
# Пробуем разные URL
HTML_URL = "https://www.stoloto.ru/top3/archive"  # исходный
# HTML_URL = "https://www.stoloto.ru/top3/result/last"  # закомментировано, но можно переключить
# ===================================================

# Настройка логирования
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
    Загружает страницу и пытается извлечь данные о последнем тираже.
    Выводит весь HTML в логи для анализа.
    """
    try:
        logger.info(f"Загружаем страницу: {HTML_URL}")
        response = session.get(HTML_URL, timeout=15)
        logger.info(f"Статус ответа: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Ошибка загрузки страницы: {response.status_code}")
            return None

        # Выводим весь HTML в логи (осторожно: может быть очень много)
        logger.info("===== НАЧАЛО HTML =====")
        logger.info(response.text)  # Весь HTML
        logger.info("===== КОНЕЦ HTML =====")

        # Пробуем найти JSON внутри тегов <script>
        soup = BeautifulSoup(response.text, 'html.parser')
        scripts = soup.find_all('script', type='application/json')
        for i, script in enumerate(scripts):
            logger.info(f"Найден script #{i} с JSON: {script.string[:500]}...")  # первые 500 символов

        # Также ищем любые скрипты с данными
        all_scripts = soup.find_all('script')
        for i, script in enumerate(all_scripts):
            if script.string and ('draw' in script.string or 'tirage' in script.string or 'numbers' in script.string):
                logger.info(f"Скрипт #{i} содержит ключевые слова: {script.string[:500]}...")

        # Если дошли до сюда, но ничего не нашли, возвращаем None
        logger.warning("Не удалось извлечь данные из HTML")
        return None

    except Exception as e:
        logger.error(f"Ошибка при парсинге HTML: {e}", exc_info=True)
        return None

def format_numbers_only(draw):
    # Пока заглушка, если данные будут найдены
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

    # Здесь будет обработка, когда данные появятся
    # current_number = latest_draw.get('drawNumber')
    # ... остальная логика

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
