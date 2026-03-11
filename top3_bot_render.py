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
CHECK_INTERVAL_SECONDS = 60

# URL архива (там могут быть данные внутри скриптов)
ARCHIVE_URL = "https://www.stoloto.ru/top3/archive"
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

# ==================== Парсинг архива ====================
def extract_json_from_scripts(soup):
    """Ищет в скриптах JSON с данными о тиражах"""
    scripts = soup.find_all('script')
    for script in scripts:
        if not script.string:
            continue
        # Ищем ключевые слова
        if 'draws' in script.string or 'tirage' in script.string or 'results' in script.string:
            logger.info(f"Найден скрипт, похожий на данные: {script.string[:200]}...")
            # Пытаемся извлечь JSON из строки (иногда он внутри __NEXT_DATA__ или подобного)
            # Сначала ищем объект, начинающийся с { и заканчивающийся }
            # Но проще попробовать распарсить весь текст как JSON
            try:
                # Очистим от возможных присваиваний: var data = {...}
                text = script.string.strip()
                # Если начинается с window.__INITIAL_STATE__ = 
                if 'window.__INITIAL_STATE__' in text:
                    # Извлекаем JSON после =
                    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', text, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                        return data
                # Если просто JSON объект
                if text.startswith('{') and text.endswith('}'):
                    data = json.loads(text)
                    return data
                # Если это массив
                if text.startswith('[') and text.endswith(']'):
                    data = json.loads(text)
                    return data
            except json.JSONDecodeError:
                continue
    return None

def fetch_latest_draw():
    try:
        logger.info(f"Загружаем страницу архива: {ARCHIVE_URL}")
        resp = session.get(ARCHIVE_URL, timeout=15)
        logger.info(f"Статус: {resp.status_code}")
        if resp.status_code != 200:
            logger.error(f"Ошибка загрузки: {resp.status_code}")
            # Выведем начало страницы для понимания
            logger.warning(f"Тело ответа: {resp.text[:500]}")
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Сначала ищем JSON в скриптах
        json_data = extract_json_from_scripts(soup)
        if json_data:
            logger.info("Найден JSON в скриптах, пытаемся извлечь тираж")
            # Теперь нужно найти номер и числа. Структура может быть разной.
            # Обычно данные лежат в json_data['draws'] или json_data['props']['pageProps']['draws']
            # Пробуем несколько вариантов
            draws = None
            # Ищем по ключам
            if isinstance(json_data, dict):
                # Рекурсивно ищем ключ 'draws'
                def find_draws(obj):
                    if isinstance(obj, dict):
                        if 'draws' in obj:
                            return obj['draws']
                        for v in obj.values():
                            res = find_draws(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_draws(item)
                            if res:
                                return res
                    return None
                draws = find_draws(json_data)
            
            if draws and isinstance(draws, list) and len(draws) > 0:
                draw = draws[0]
                draw_number = draw.get('drawNumber') or draw.get('number')
                numbers = []
                if 'results' in draw and len(draw['results']) > 0:
                    numbers = draw['results'][0].get('numbers', [])
                if draw_number and numbers:
                    logger.info(f"✅ Получен тираж №{draw_number}, числа: {numbers}")
                    return {'drawNumber': draw_number, 'numbers': numbers}
        
        # Если JSON не нашли, пробуем найти элементы в HTML (на случай если они есть)
        logger.warning("JSON в скриптах не найден, пробуем найти элементы напрямую")
        # Поиск номеров и чисел в HTML (старый метод)
        # Этот код из предыдущей версии
        draw_number = None
        # Поиск номера
        number_elem = (soup.find('span', class_='draws-item__number') or 
                       soup.find('span', class_='number') or 
                       soup.find('div', class_='draw-number'))
        if number_elem:
            text = number_elem.get_text(strip=True)
            match = re.search(r'\d+', text)
            if match:
                draw_number = int(match.group())
        else:
            for tag in soup.find_all(['span', 'div', 'p']):
                text = tag.get_text(strip=True)
                if '№' in text and re.search(r'\d+', text):
                    match = re.search(r'\d+', text)
                    draw_number = int(match.group())
                    break
        
        # Поиск чисел
        numbers = []
        ball_elems = (soup.find_all('span', class_='draws-item__number-ball') or 
                      soup.find_all('span', class_='ball') or 
                      soup.find_all('span', class_='number-ball'))
        for ball in ball_elems[:3]:
            text = ball.get_text(strip=True)
            if text.isdigit():
                numbers.append(int(text))
        
        if draw_number and len(numbers) == 3:
            logger.info(f"✅ Из HTML получен тираж №{draw_number}, числа: {numbers}")
            return {'drawNumber': draw_number, 'numbers': numbers}
        
        # Если ничего не нашли, выведем часть страницы для отладки
        logger.warning("Не удалось извлечь данные. Вывожу первые 5000 символов страницы:")
        logger.warning(resp.text[:5000])
        return None
    except Exception as e:
        logger.error(f"Ошибка при парсинге: {e}", exc_info=True)
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
