import requests
from googletrans import Translator
import os
from datetime import datetime
import discord
from discord.ext import commands
import asyncio
import io
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lấy API key và token từ biến môi trường trên Render
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BOT1_TOKEN = os.getenv("BOT1_TOKEN")
BOT2_TOKEN = os.getenv("BOT2_TOKEN")

logger.info(f"GROQ_API_KEY: {'set' if GROQ_API_KEY else 'not set'}")
logger.info(f"BOT1_TOKEN: {'set' if BOT1_TOKEN else 'not set'}")
logger.info(f"BOT2_TOKEN: {'set' if BOT2_TOKEN else 'not set'}")

# Tệp txt chứa danh sách URL
IMAGE_URLS_FILE = "image_urls.txt"

# Thư mục lưu kết quả (tạm thời)
OUTPUT_DIR = "image_analysis_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Khởi tạo Google Translator
translator = Translator()

# Cấu hình bot
intents = discord.Intents.default()
intents.message_content = True

bot1 = commands.Bot(command_prefix="!", intents=intents)
bot2 = commands.Bot(command_prefix="$", intents=intents)

# Dummy HTTP server để Render detect port
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def start_http_server():
    port = int(os.getenv("PORT", 10000))  # Render cung cấp PORT qua biến môi trường, mặc định 10000
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    logger.info(f"Starting HTTP server on port {port}")
    server.serve_forever()

def read_image_urls(file_path):
    """Đọc danh sách URL từ tệp txt."""
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("")
        logger.info(f"Tạo tệp rỗng: {file_path}")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        logger.info(f"Đọc {len(urls)} URL từ {file_path}")
        return urls
    except Exception as e:
        logger.error(f"Lỗi khi đọc tệp URL: {e}")
        return []

def update_image_urls(file_path, url_to_remove):
    """Xóa URL đã phân tích thành công khỏi tệp txt."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
        url_to_remove = url_to_remove.strip()
        if url_to_remove in urls:
            urls.remove(url_to_remove)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(urls) + "\n" if urls else "")
            logger.info(f"Đã xóa URL {url_to_remove} khỏi {file_path}")
            return True
        logger.info(f"Không tìm thấy URL {url_to_remove} để xóa")
        return False
    except Exception as e:
        logger.error(f"Lỗi khi cập nhật tệp URL: {e}")
        return False

def analyze_image_with_groq(image_url, model="llama-3.2-11b-vision-preview", prompt="Describe the content of the image."):
    """Gửi yêu cầu đến Groq API để phân tích hình ảnh qua URL."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 100,
        "temperature": 0.7
    }
    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        description = result.get("choices", [{}])[0].get("message", {}).get("content", "No description found.")
        translated = translator.translate(description, dest="vi")
        logger.info(f"Phân tích URL {image_url} thành công")
        return description, translated.text
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e.response, "text"):
            error_msg += f" - Chi tiết: {e.response.text}"
        logger.error(f"Lỗi phân tích URL {image_url}: {error_msg}")
        return None, error_msg

# Bot 1: Xử lý URL và gửi tin nhắn
@bot1.event
async def on_ready():
    logger.info(f"Bot 1 ({bot1.user}) đã sẵn sàng!")
    channel = bot1.get_channel(1351152665358368805)
    if not channel:
        logger.error("Không tìm thấy kênh với ID 1351152665358368805. Kiểm tra Channel ID và quyền bot!")
        return
    logger.info(f"Bot 1 đang gửi tin nhắn vào kênh: {channel.name}")
    while True:
        image_urls = read_image_urls(IMAGE_URLS_FILE)
        if not image_urls:
            await channel.send("Không có URL nào trong tệp image_urls.txt! Đợi thêm URL mới...")
            await asyncio.sleep(60)
            continue
        await channel.send(f"Đã tìm thấy {len(image_urls)} URL để phân tích.")
        for url in image_urls:
            await channel.send(f"Đang phân tích: {url}")
            eng_desc, vi_desc = analyze_image_with_groq(url)
            if eng_desc:
                msg = f"URL: {url}\nMô tả (EN): {eng_desc}\nMô tả (VN): {vi_desc}"
                await channel.send(msg)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"analysis_{timestamp}.txt"
                content = f"Image URL: {url}\nEnglish description: {eng_desc}\nVietnamese description: {vi_desc}\n{'-'*50}\n\n"
                with io.StringIO(content) as file:
                    await channel.send(file=discord.File(file, filename))
                if update_image_urls(IMAGE_URLS_FILE, url):
                    await channel.send(f"Đã xóa URL {url} khỏi image_urls.txt")
                else:
                    await channel.send(f"Không xóa được URL {url} khỏi tệp!")
            else:
                await channel.send(f"Lỗi với {url}: {vi_desc}")
            await asyncio.sleep(1)
        await asyncio.sleep(60)

# Bot 2: Phản hồi tin nhắn từ Bot 1
@bot2.event
async def on_ready():
    logger.info(f"Bot 2 ({bot2.user}) đã sẵn sàng!")

@bot2.event
async def on_message(message):
    if message.author == bot1.user:
        if "Đang phân tích" in message.content:
            await message.channel.send(f"OK, xử lý đi nào!")
        elif "Mô tả (EN)" in message.content:
            await message.channel.send(f"Đã xử lý xong, tốt lắm!")
        elif "Lỗi với" in message.content:
            await message.channel.send(f"Thử lại đi, có lỗi kìa!")

# Chạy cả hai bot và HTTP server
async def run_bots():
    try:
        # Chạy HTTP server trong luồng riêng
        loop = asyncio.get_event_loop()
        import threading
        threading.Thread(target=start_http_server, daemon=True).start()
        await asyncio.gather(
            bot1.start(BOT1_TOKEN),
            bot2.start(BOT2_TOKEN)
        )
    except Exception as e:
        logger.error(f"Lỗi khi khởi động bot: {e}")

if __name__ == "__main__":
    logger.info("Bắt đầu chạy bot...")
    asyncio.run(run_bots())
