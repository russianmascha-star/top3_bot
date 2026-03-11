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

# Рабочий API (найден через браузер)
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

# ========== ЗАГОЛОВКИ ИЗ БРАУЗЕРА ==========
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.stoloto.ru/top3/archive',
    'Origin': 'https://www.stoloto.ru',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'X-Requested-With': 'XMLHttpRequest',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Ch-Ua': '"Chromium";v="128", "Not;A=Brand";v="24", "YaBrowser";v="24.10", "Yowser";v="2.5"',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    # Строка с куками (скопирована из браузера) – замените на свою актуальную
    'Cookie': 'afUserId=35bd8c8d-bc69-460e-bbe6-c0f860d6431a-p; _ga=GA1.1.2046642867.1738593657; _ga_W13573SET9=GS1.1.1739737222.2.1.1739738067.41.0.0; _ym_uid=1738593658432600190; _ym_d=1773996214; _ym_isad=2; _ymab_param=GmwkAQRTX3yeu_CfgqV0D0toUpyVqCyahDK5OHZB3mo6YXDJWZcplhwf7FB4VGsat2OKBvaw4n3UWZ21J85x44HBAWo; _ym_visorc=b; adtech_uid=90dd2e76-8e5d-48e8-bbc7-711a864f523e%3Astoloto.ru; top100_id=t1.7713245.1423689402.1773996219731; gnezdo_uid=194cc4204cab855102bd4f5c; tmr_lvid=dd07971b09d6dcd6eeb43279a0e3265d; tmr_lvidTS=1738593660214; AF_SYNC=1773996223005; fingerprint=3774101085; domain_sid=lwx-bSPlsv3b-Aqwn0A7I%3A1773996223262; adrdel=1773996223596; adrcid=AupxI9BFvXKHV8apKt8KADQ; advcake_track_id=93468fc3-8a00-4b78-1dd4-35938755f588; advcake_session_id=0e25c93c-e6ff-997a-f92d-939f9470f420; acs_3=%7B%22hash%22%3A%221aa3f9523ee6c2690cb34fc702d4143056487c0d%22%2C%22nst%22%3A1774082624623%2C%22sl%22%3A%7B%22224%22%3A1773996224623%2C%221228%22%3A1773996224623%7D%7D; uxs_uid=e7fc5bc0-2438-11f1-ae1a-f5df185c8117; flocktory-uuid=91b13743-a1d9-479a-9172-fb57fb141bc0-0; ga=1e86f2a700-566331-41b406-b68f85-13836177b21027; wimhash21=6e802444cf78ec59d80012c4d2ea5827; Scaleo_source=false; stlt_referral=ya.ru; stlt_clientids=ymcid1738593658432600190|uid1690847362; stlt_parameters=af_ad=c:perf:sc:y:on:1:p:pc:ap:y:s:yandex:g:pu:bt:cpc:a:ft:i:cid88698007-gid5462330338-adid1844984782753660734&pid=yandex&af_channel=cpc&c=ONG_MK_BRAND_FIRSTPAY_CPC-cid88698007; advcake_track_url=%3D20250113nJR5gzd7GrbDZiNqi4BGNa2SY6FYx1S%2F0crvCEAYnvOlcvrD9h2xA%2FKLQd1aCnM3fymg33hX8x6efIDpT%2BleZEZXZi14Bsn4gToi7gWvv7omGQeA6soVVB10Q%2Bjgx6Ma8mtSn0h0W0dNmZYhJxOvAxPRGmu4lwyXiajHGYQhuWeMWhs0gYZx9FWvkww%2BiiNldBuAtHJ1TtkF3pDvad7%2F%2FSULtzVkPJ%2B1nisYi%2BiV0JC8iN8AnfwYkOeM3KzeoDFwntF31NmX7JUaiFSXFpo9z70lOS1em0XF1g4F8jjwfFWr2hTxmvsGOcTfGKeUZFEemNjscx2A9whfWksY%2FkTEZdx9y06utoyyg%2B3vSYDU41cZpGK3kB6O4iK3sGYZr5%2BjKHbDQ5a7UTq5EFdKVzwOKQ6k%2Ffz%2BbYTT1IwJo2mEVkWVL8dSl2Zc8uLRgvOYJpfjtoQcg7kVaSNPKq0sc1AVSvlWxAnJy4Z%2FMxGAYP%2BrMWkFzgMxMPSRCiOK1aU7ce4IhTI52B4qsErtB51h3ZcYmLvodA3UU6P2Qx6pUvQlgRzT6Pj7Bf1sndM%2FIvBDufrfmAv%2BFjbUqVOBXmS97Ww69qJZ7PTmCfZLf2iY7dgIOdG5RnrzeD5o6mDH%2F2kO3YirK4Wq6u0%2FzmBalviDuGaVEBT0B%2BzW9VrGwkGzQw3L0OYgAL%2FkkbhJvWc%3D; tmr_detect=0%7C1773998028326; t3_sid_7713245=s1.737870141.1773996219737.1773998149361.1.39.6.1..'
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

# ==================== Получение последнего тиража ====================
def fetch_latest_draw():
    try:
        logger.info(f"Запрос к API: {API_URL}")
        resp = session.get(API_URL, timeout=10)
        logger.info(f"Статус: {resp.status_code}")
        logger.info(f"Content-Type: {resp.headers.get('Content-Type', 'не указан')}")
        
        if resp.status_code != 200:
            logger.error(f"Ошибка API: {resp.status_code}")
            if resp.text:
                logger.warning(f"Тело ответа: {resp.text[:500]}")
            return None
        
        data = resp.json()
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
        elif isinstance(data, list) and len(data) > 0:
            draw = data[0]
            draw_number = draw.get('drawNumber') or draw.get('number')
            numbers = []
            if 'results' in draw and len(draw['results']) > 0:
                numbers = draw['results'][0].get('numbers', [])
            logger.info(f"✅ Получен тираж №{draw_number}, числа: {numbers}")
            return {'drawNumber': draw_number, 'numbers': numbers}
        else:
            logger.warning(f"Неожиданная структура JSON: {data}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при запросе: {e}", exc_info=True)
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
