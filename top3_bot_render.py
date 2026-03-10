import requests
import json
from datetime import datetime
import time
import threading
import os
import sys
from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode
import asyncio
import logging

# ==================== НАСТРОЙКИ ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GAME_NAME = "top3"  # возможно, нужно уточнить на сайте (top3, top3-1 и т.д.)
CHECK_INTERVAL_SECONDS = 60  # 1 минута (для теста; при блокировке увеличьте до 300-600)
USE_API = True               # True – использовать API, False – парсить HTML
USE_PROXY = False            # Если есть прокси, установите True и заполните PROXY_URL
PROXY_URL = "http://user:pass@ip:port"  # пример

# API endpoint (основной источник)
API_URL = f"https://www.stoloto.ru/p/api/mobile/api/v34/service/draws/archive?count=1&game={GAME_NAME}"

# HTML fallback (если API заблокирован)
HTML_URL = "https://www.stoloto.ru/top3/archive"  # страница архива тиражей "Топ-3"
# ===================================================

# Настройка логирования (вывод в консоль сразу, без буферизации)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Проверка наличия токенов
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы! Сообщения не будут отправляться.")

last_draw_number = None
app = Flask(__name__)

# Заголовки, максимально приближенные к браузерным
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.stoloto.ru/',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
}

# Сессия для сохранения cookies (если сервер их выдаёт)
session = requests.Session()
session.headers.update(HEADERS)

if USE_PROXY:
    session.proxies.update({'http': PROXY_URL, 'https': PROXY_URL})

# ==================== Функции для работы с Telegram ====================
async def send_telegram_message(text):
    """Асинхронная отправка сообщения в Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Невозможно отправить сообщение: нет токена или chat_id")
        return
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
        logger.info(f"✅ Сообщение отправлено: {text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")

def send_telegram_sync(text):
    """Синхронная обёртка для вызова асинхронной функции."""
    # Создаём новый event loop для каждого вызова (просто и надёжно)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_telegram_message(text))
    finally:
        loop.close()

# ==================== Парсинг данных ====================
def fetch_latest_draw_api():
    """Получение последнего тиража через API."""
    try:
        logger.info(f"Запрос к API: {API_URL}")
        response = session.get(API_URL, timeout=15)
        logger.info(f"Статус ответа: {response.status_code}")
        logger.debug(f"Тело ответа (первые 500 символов): {response.text[:500]}")
        
        # Если статус не 200, пробуем прочитать JSON с ошибкой
        if response.status_code != 200:
            logger.error(f"API вернул ошибку {response.status_code}")
            return None
        
        data = response.json()
        if data and 'draws' in data and len(data['draws']) > 0:
            draw = data['draws'][0]
            logger.info(f"Получен тираж №{draw.get('drawNumber')}")
            logger.debug(json.dumps(draw, indent=2, ensure_ascii=False)[:500])
            return draw
        else:
            logger.warning("В ответе отсутствует ключ 'draws' или он пуст")
            if data:
                logger.info(f"Структура ответа: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка HTTP-запроса: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка при запросе к API: {e}")
    return None

def fetch_latest_draw_html():
    """Запасной вариант: парсинг HTML-страницы архива."""
    try:
        logger.info(f"Парсинг HTML: {HTML_URL}")
        response = session.get(HTML_URL, timeout=15)
        logger.info(f"Статус ответа HTML: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"HTML-страница вернула ошибку {response.status_code}")
            return None
        
        # Здесь нужно написать парсер под конкретную структуру страницы stoloto.ru
        # Это пример, вам придётся адаптировать под реальный HTML.
        # Рекомендуется использовать BeautifulSoup.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Пример: ищем блок с последним тиражом (нужно подглядеть в реальной странице)
        # Допустим, тиражи находятся в таблице с классом "draws-table"
        table = soup.find('table', class_='draws-table')
        if not table:
            logger.warning("Не найдена таблица с тиражами")
            return None
        
        # Берём первую строку (последний тираж)
        first_row = table.find('tr', class_='draw')  # или другой селектор
        if not first_row:
            logger.warning("Не найдена строка с тиражом")
            return None
        
        # Извлекаем номер тиража и числа (нужно подстроить под реальную вёрстку)
        # Пример:
        draw_number = first_row.find('td', class_='number').text.strip()
        numbers_cells = first_row.find_all('td', class_='number-ball')
        numbers = [cell.text.strip() for cell in numbers_cells]
        
        # Формируем объект, похожий на API
        draw = {
            'drawNumber': int(draw_number),
            'results': [{'numbers': list(map(int, numbers))}]
        }
        logger.info(f"Из HTML получен тираж №{draw_number} числа {numbers}")
        return draw
    except Exception as e:
        logger.error(f"Ошибка при парсинге HTML: {e}")
        return None

def fetch_latest_draw():
    """Универсальная функция: пробует API, если не получилось – HTML (если разрешено)."""
    draw = None
    if USE_API:
        draw = fetch_latest_draw_api()
        if draw is None:
            logger.warning("API не дал данных, пробуем парсить HTML...")
            draw = fetch_latest_draw_html()
    else:
        draw = fetch_latest_draw_html()
    return draw

def format_numbers_only(draw):
    """Форматирует числа тиража для отправки в Telegram."""
    results = draw.get('results', [])
    if results and 'numbers' in results[0]:
        numbers = results[0]['numbers']
        return f"🎲 {'-'.join(map(str, numbers))}"
    return "🎲 ?-?-?"

# ==================== Основная логика проверки ====================
def check_new_draw():
    global last_draw_number
    now = datetime.now().strftime('%H:%M:%S')
    logger.info(f"=== Проверка в {now} ===")
    
    latest_draw = fetch_latest_draw()
    if not latest_draw:
        logger.warning("⚠️ Не удалось получить данные о тираже")
        return
    
    current_number = latest_draw.get('drawNumber')
    if current_number is None:
        logger.warning("В данных отсутствует номер тиража (drawNumber)")
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
    """Функция, выполняющаяся в фоновом потоке."""
    logger.info("🚀 Фоновый поток запущен")
    # Первая проверка сразу после старта
    check_new_draw()
    
    while True:
        logger.info(f"💤 Сон {CHECK_INTERVAL_SECONDS} сек...")
        time.sleep(CHECK_INTERVAL_SECONDS)
        check_new_draw()

# ==================== Flask-сервер для health checks ====================
@app.route('/')
def health():
    return "Bot is running", 200

@app.route('/status')
def status():
    return {
        'status': 'ok',
        'last_draw': last_draw_number,
        'check_interval': CHECK_INTERVAL_SECONDS
    }

# ==================== Точка входа ====================
if __name__ == "__main__":
    # Запускаем фоновый поток с проверками
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()
    
    # Запускаем Flask (блокирует главный поток)
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"✅ Запуск Flask на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
