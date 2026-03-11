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
from bs4 import BeautifulSoup

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
CHECK_INTERVAL_SECONDS = 60

# Ключ ScrapingBee
SCRAPINGBEE_API_KEY = "3KG51UIRHKF5U0SS73Z3TQ30EZQYYD3ISHPW0BC6VFJJTPT7D3CRTGUKXDGOG9WR99ZTVC4BKRXRUAFK"

# Целевая страница
TARGET_URL = "https://www.stoloto.ru/top3/archive"
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

# ==================== Получение HTML через ScrapingBee (упрощённый вариант) ====================
def fetch_html_via_scrapingbee():
    try:
        scrapingbee_url = "https://app.scrapingbee.com/api/v1/"
        params = {
            'api_key': SCRAPINGBEE_API_KEY,
            'url': TARGET_URL,
            'render_js': 'true',
            'premium_proxy': 'true',
            'country_code': 'ru',
            'wait': '5000',
            'wait_for': '.draws-item',
            'timeout': '20000',
            'block_resources': 'false',
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 YaBrowser/24.10.0 Safari/537.36',
            'Referer': 'https://www.stoloto.ru/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru,en;q=0.9',
        }
        logger.info(f"Запрос к ScrapingBee для {TARGET_URL}")
        resp = requests.get(scrapingbee_url, params=params, headers=headers, timeout=30)
        logger.info(f"Статус ScrapingBee: {resp.status_code}")
        if resp.status_code != 200:
            logger.error(f"Ошибка ScrapingBee: {resp.status_code} - {resp.text[:200]}")
            return None
        logger.info(f"ScrapingBee вернул {len(resp.text)} символов")
        return resp.text
    except Exception as e:
        logger.error(f"Ошибка при запросе ScrapingBee: {e}")
        return None

def parse_draw_from_html(html):
    """Парсит HTML и извлекает последний тираж"""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Ищем JSON внутри скриптов
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and ('__INITIAL_STATE__' in script.string or 'draws' in script.string):
                match = re.search(r'({.*"draws".*})', script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        draws = None
                        if 'draws' in data:
                            draws = data['draws']
                        elif 'props' in data and 'pageProps' in data['props'] and 'draws' in data['props']['pageProps']:
                            draws = data['props']['pageProps']['draws']
                        elif isinstance(data, list) and len(data) > 0 and 'number' in data[0]:
                            draws = data
                        if draws and len(draws) > 0:
                            draw = draws[0]
                            draw_number = draw.get('number') or draw.get('drawNumber')
                            numbers = draw.get('numbers', [])
                            if not numbers and 'results' in draw:
                                numbers = draw['results'][0].get('numbers', [])
                            if draw_number and numbers:
                                logger.info(f"✅ Из JSON получен тираж №{draw_number}, числа: {numbers}")
                                return {'drawNumber': draw_number, 'numbers': numbers}
                    except:
                        continue
        
        # Если JSON не найден, парсим HTML-элементы
        draw_items = soup.find_all('div', class_='draws-item')
        if not draw_items:
            logger.warning("Не найдены элементы с классом 'draws-item' в HTML")
            # Выведем фрагмент для отладки
            logger.info(f"HTML фрагмент (первые 3000 символов): {html[:3000]}")
            return None
        
        first = draw_items[0]
        number_elem = first.find('span', class_='draws-item__number') or first.find('span', class_='number')
        if not number_elem:
            logger.warning("Не найден номер тиража")
            return None
        number_text = number_elem.get_text(strip=True)
        match = re.search(r'\d+', number_text)
        if not match:
            logger.warning(f"Не удалось извлечь номер из: {number_text}")
            return None
        draw_number = int(match.group())
        
        ball_elems = first.find_all('span', class_='draws-item__number-ball') or first.find_all('span', class_='ball')
        numbers = []
        for ball in ball_elems[:3]:
            text = ball.get_text(strip=True)
            if text.isdigit():
                numbers.append(int(text))
        
        if len(numbers) != 3:
            logger.warning(f"Найдено только {len(numbers)} чисел: {numbers}")
            return None
        
        logger.info(f"✅ Из HTML получен тираж №{draw_number}, числа: {numbers}")
        return {'drawNumber': draw_number, 'numbers': numbers}
    except Exception as e:
        logger.error(f"Ошибка парсинга HTML: {e}")
        return None

def fetch_latest_draw():
    html = fetch_html_via_scrapingbee()
    if not html:
        return None
    return parse_draw_from_html(html)

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
