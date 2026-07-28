#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# بوت تحميل الفيديوهات – يدعم YouTube, TikTok, Instagram, Twitter, Facebook, Pinterest
# نسخة محسنة بدون أخطاء "Message is not modified" وبدون مشاكل الكوكيز

import os
import sys
import logging
import asyncio
import re
import hashlib
from datetime import datetime
from urllib.parse import urlparse, urlencode

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
    import yt_dlp
    import requests
except ImportError as e:
    print(f"❌ خطأ في استيراد المكتبات: {e}")
    print("يرجى تثبيت المكتبات المطلوبة:")
    print("pip install python-telegram-bot yt-dlp requests")
    sys.exit(1)

# ---------- إعدادات المالك ----------
OWNER_ID = 7330508457

# ---------- إعداد السجل ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- إنشاء المجلدات ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

for path in [DOWNLOADS_DIR, LOGS_DIR, TEMP_DIR]:
    os.makedirs(path, exist_ok=True)

# ---------- متعقب المستخدمين ----------
class UserTracker:
    def __init__(self):
        self.seen_file = os.path.join(LOGS_DIR, "seen_users.txt")
        self.seen_users = self._load()

    def _load(self):
        try:
            if os.path.exists(self.seen_file):
                with open(self.seen_file, 'r') as f:
                    return {int(line.strip()) for line in f if line.strip().isdigit()}
        except:
            pass
        return set()

    def _save(self):
        try:
            with open(self.seen_file, 'w') as f:
                for uid in self.seen_users:
                    f.write(f"{uid}\n")
        except:
            pass

    def is_new(self, user_id):
        return user_id not in self.seen_users

    def add(self, user_id):
        self.seen_users.add(user_id)
        self._save()

    async def notify_owner(self, context, user):
        try:
            msg = f"👤 <b>مستخدم جديد!</b>\n\n🆔 الأيدي: <code>{user.id}</code>\n👤 الاسم: {user.first_name or ''} {user.last_name or ''}\n📛 اليوزر: @{user.username if user.username else 'بدون'}\n📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            await context.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode='HTML')
        except:
            pass

user_tracker = UserTracker()

# ---------- مدقق المنصات ----------
class PlatformChecker:
    PATTERNS = {
        'youtube': [r'youtube\.com/watch\?v=', r'youtu\.be/', r'youtube\.com/shorts/'],
        'instagram': [r'instagram\.com/(p|reel|tv)/', r'instagr\.am/'],
        'tiktok': [r'tiktok\.com/@', r'vm\.tiktok\.com/', r'vt\.tiktok\.com/'],
        'twitter': [r'twitter\.com/', r'x\.com/'],
        'facebook': [r'facebook\.com/', r'fb\.watch/'],
        'pinterest': [r'pinterest\.com/pin/', r'pin\.it/']
    }

    @staticmethod
    def check(url):
        for platform, patterns in PlatformChecker.PATTERNS.items():
            for p in patterns:
                if re.search(p, url, re.IGNORECASE):
                    return {'valid': True, 'platform': platform}
        return {'valid': False, 'platform': None}

# ---------- TikTok Downloader (بدون كوكيز) ----------
class TikTokDownloader:
    HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    @staticmethod
    def extract_video_id(url):
        patterns = [r'tiktok\.com/@[\w.-]+/video/(\d+)', r'tiktok\.com/t/([\w-]+)', r'vm\.tiktok\.com/([\w-]+)', r'vt\.tiktok\.com/([\w-]+)']
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    async def download_from_tikmate(url, download_path):
        try:
            session = requests.Session()
            video_id = TikTokDownloader.extract_video_id(url)
            if not video_id:
                return {'success': False, 'error': 'لم يتم استخراج معرف الفيديو'}
            
            api_url = f"https://tikmate.app/api/video/{video_id}"
            response = session.get(api_url, headers=TikTokDownloader.HEADERS, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('url'):
                    return await TikTokDownloader._download_file(data['url'], url, download_path, session)
            return {'success': False, 'error': 'فشل تحميل من tikmate'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    async def download_from_snaptik(url, download_path):
        try:
            session = requests.Session()
            snaptik_url = "https://snaptik.app/en"
            data = {'url': url}
            response = session.post(snaptik_url, data=data, headers=TikTokDownloader.HEADERS, timeout=30)
            html = response.text
            patterns = [r'<a[^>]+href="([^"]+\.mp4)"', r'data-url="([^"]+\.mp4)"', r'<video[^>]+src="([^"]+\.mp4)"']
            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    video_url = match.group(1)
                    if video_url.startswith('//'):
                        video_url = 'https:' + video_url
                    return await TikTokDownloader._download_file(video_url, url, download_path, session)
            return {'success': False, 'error': 'فشل تحميل من snaptik'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    async def _download_file(video_url, original_url, download_path, session=None):
        try:
            if session is None:
                session = requests.Session()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tiktok_{timestamp}_{hashlib.md5(original_url.encode()).hexdigest()[:8]}.mp4"
            filepath = os.path.join(download_path, filename)
            response = session.get(video_url, headers=TikTokDownloader.HEADERS, timeout=60, stream=True)
            if response.status_code != 200:
                return {'success': False, 'error': f'فشل التحميل: {response.status_code}'}
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(filepath) < 1024:
                os.remove(filepath)
                return {'success': False, 'error': 'الملف تالف'}
            return {'success': True, 'filepath': filepath, 'title': f'TikTok Video', 'duration': 0, 'filesize': os.path.getsize(filepath)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

# ---------- Pinterest Downloader ----------
class PinterestDownloader:
    HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    @staticmethod
    async def download_from_klickpin(url, download_path):
        try:
            klickpin_url = f"https://klickpin.com/?{urlencode({'url': url})}"
            session = requests.Session()
            response = session.get(klickpin_url, headers=PinterestDownloader.HEADERS, timeout=30)
            if response.status_code != 200:
                return {'success': False, 'error': 'فشل الوصول إلى klickpin'}
            html = response.text
            patterns = [r'<video[^>]+src="([^"]+)"', r'src="([^"]+\.mp4)"', r'data-video-url="([^"]+)"']
            for pattern in patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    video_url = match.group(1)
                    if video_url.startswith('//'):
                        video_url = 'https:' + video_url
                    return await PinterestDownloader._download_file(video_url, url, download_path, session)
            return {'success': False, 'error': 'لم يتم العثور على رابط'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @staticmethod
    async def _download_file(video_url, original_url, download_path, session=None):
        try:
            if session is None:
                session = requests.Session()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pinterest_{timestamp}_{hashlib.md5(original_url.encode()).hexdigest()[:8]}.mp4"
            filepath = os.path.join(download_path, filename)
            response = session.get(video_url, headers=PinterestDownloader.HEADERS, timeout=60, stream=True)
            if response.status_code != 200:
                return {'success': False, 'error': f'فشل التحميل: {response.status_code}'}
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(filepath) < 1024:
                os.remove(filepath)
                return {'success': False, 'error': 'الملف تالف'}
            return {'success': True, 'filepath': filepath, 'title': 'Pinterest Video', 'duration': 0, 'filesize': os.path.getsize(filepath)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

# ---------- مدير التحميل ----------
class DownloadManager:
    def __init__(self):
        self.download_path = DOWNLOADS_DIR

    def _quality_format(self, quality):
        q_map = {'أفضل جودة': 'best', 'جودة عالية': 'best[height<=1080]', 'جودة متوسطة': 'best[height<=720]', 'جودة منخفضة': 'worst[height<=360]', 'صوت فقط': 'bestaudio/best'}
        return q_map.get(quality, 'best')

    async def download(self, url, platform, quality):
        # معالجة TikTok بالطرق البديلة أولاً
        if platform == 'tiktok':
            result = await TikTokDownloader.download_from_tikmate(url, self.download_path)
            if result['success']:
                return result
            result = await TikTokDownloader.download_from_snaptik(url, self.download_path)
            if result['success']:
                return result

        # معالجة Pinterest بالطرق البديلة
        if platform == 'pinterest':
            result = await PinterestDownloader.download_from_klickpin(url, self.download_path)
            if result['success']:
                return result

        # استخدام yt-dlp للمنصات الأخرى (مع إلغاء الكوكيز)
        try:
            ydl_opts = {
                'format': self._quality_format(quality),
                'outtmpl': os.path.join(self.download_path, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 3,
                'ignoreerrors': True,
                'cookiefile': None,
                'no_cookies': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            # إعدادات خاصة لـ TikTok عبر yt-dlp
            if platform == 'tiktok':
                ydl_opts['extractor_args'] = {'tiktok': {'cookies': False}}
                ydl_opts['http_headers'] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.tiktok.com/'
                }

            if quality == 'صوت فقط':
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if quality == 'صوت فقط':
                    filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                return {
                    'success': True,
                    'filepath': filename,
                    'title': info.get('title', 'فيديو'),
                    'duration': info.get('duration', 0),
                    'filesize': os.path.getsize(filename) if os.path.exists(filename) else 0
                }
        except Exception as e:
            # إذا فشل yt-dlp مع TikTok، نعيد الخطأ
            if platform == 'tiktok':
                return {'success': False, 'error': f'فشل التحميل: {str(e)}'}
            return {'success': False, 'error': str(e)}

# ---------- واجهة الأزرار ----------
class BotUI:
    @staticmethod
    def main_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 تحميل فيديو", callback_data="download")],
            [InlineKeyboardButton("ℹ️ المساعدة", callback_data="help"), InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("📞 تواصل مع المطور", url=f"tg://user?id={OWNER_ID}")]
        ])

    @staticmethod
    def quality_menu(url, platform):
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        qualities = ['أفضل جودة', 'جودة عالية', 'جودة متوسطة', 'جودة منخفضة', 'صوت فقط']
        buttons = []
        for i in range(0, len(qualities), 2):
            row = []
            for q in qualities[i:i+2]:
                row.append(InlineKeyboardButton(q, callback_data=f"dl:{platform}:{q}:{url_hash}"))
            buttons.append(row)
        buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
        return InlineKeyboardMarkup(buttons)

    @staticmethod
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @staticmethod
    def format_duration(sec):
        if sec < 60:
            return f"{sec} ث"
        elif sec < 3600:
            return f"{sec//60} د {sec%60} ث"
        else:
            return f"{sec//3600} س {(sec%3600)//60} د"

# ---------- البوت الرئيسي ----------
class VideoBot:
    def __init__(self, token):
        self.token = token
        self.downloader = DownloadManager()
        self.ui = BotUI()
        self.app = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    async def start(self, update, context):
        user = update.effective_user
        if user_tracker.is_new(user.id):
            user_tracker.add(user.id)
            await user_tracker.notify_owner(context, user)

        await update.message.reply_text(
            "🎬 <b>بوت تحميل الفيديوهات</b>\n\n📱 يدعم: YouTube, TikTok, Instagram, Twitter, Facebook, Pinterest\n\n📤 <b>أرسل رابط الفيديو الآن</b>",
            parse_mode='HTML',
            reply_markup=self.ui.main_menu()
        )

    async def help(self, update, context):
        await update.message.reply_text(
            "<b>🆘 المساعدة</b>\n\n1. أرسل رابط فيديو.\n2. اختر الجودة.\n3. انتظر لحظات.\n4. استلم الملف.\n\n⚠️ الحد الأقصى 50 ميغابايت.\n\n📞 للتواصل مع المطور، استخدم الزر الموجود في القائمة الرئيسية.",
            parse_mode='HTML'
        )

    async def status(self, update, context):
        try:
            files = [f for f in os.listdir(DOWNLOADS_DIR) if os.path.isfile(os.path.join(DOWNLOADS_DIR, f))]
            await update.message.reply_text(
                f"<b>📊 حالة البوت</b>\n\n✅ يعمل\n📁 الملفات المحفوظة: {len(files)}\n👥 المستخدمون: {len(user_tracker.seen_users)}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode='HTML'
            )
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")

    async def handle_text(self, update, context):
        url = update.message.text.strip()
        res = PlatformChecker.check(url)
        if not res['valid']:
            await update.message.reply_text("❌ رابط غير مدعوم.", parse_mode='HTML')
            return

        context.user_data['url'] = url
        context.user_data['platform'] = res['platform']
        await update.message.reply_text(
            f"✅ <b>{res['platform'].upper()}</b> – اختر الجودة:",
            reply_markup=self.ui.quality_menu(url, res['platform']),
            parse_mode='HTML'
        )

    async def handle_callback(self, update, context):
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "cancel":
            await query.edit_message_text("❌ تم الإلغاء.")
        elif data == "help":
            await query.edit_message_text("🆘 أرسل رابط الفيديو مباشرة.")
        elif data == "stats":
            await query.edit_message_text(f"👥 المستخدمون: {len(user_tracker.seen_users)}")
        elif data.startswith("dl:"):
            try:
                _, platform, quality, url_hash = data.split(":")
                url = context.user_data.get('url')
                if not url or hashlib.md5(url.encode()).hexdigest()[:8] != url_hash:
                    await query.edit_message_text("❌ الرابط منتهي الصلاحية.")
                    return

                # إرسال رسالة جاري التحميل
                try:
                    await query.edit_message_text(
                        f"🔄 جاري التحميل...\n📱 {platform}\n🎚️ {quality}",
                        parse_mode='HTML'
                    )
                except:
                    pass

                result = await self.downloader.download(url, platform, quality)
                if not result['success']:
                    await query.edit_message_text(f"❌ فشل: {result.get('error', 'خطأ غير معروف')[:200]}")
                    return

                filepath = result['filepath']
                caption = f"✅ تم التحميل\n📹 {result['title'][:50]}\n📊 {self.ui.format_size(result['filesize'])}\n⏱️ {self.ui.format_duration(result['duration'])}"

                with open(filepath, 'rb') as f:
                    if quality == 'صوت فقط':
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=f,
                            caption=caption,
                            title=result['title'][:64]
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=f,
                            caption=caption,
                            supports_streaming=True
                        )
                await query.delete_message()
            except Exception as e:
                await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")

    def run(self):
        print(f"🤖 البوت يعمل...")
        print(f"👑 أيدي المالك: {OWNER_ID}")
        print(f"📁 مجلد التحميلات: {DOWNLOADS_DIR}")
        self.app.run_polling()

# ---------- تشغيل البوت ----------
if __name__ == "__main__":
    TOKEN = os.environ.get("BOT_TOKEN", "8502033667:AAF6tPgPIz2DmHtTXg6Icsh_P51xpsVjcq8")
    bot = VideoBot(TOKEN)
    try:
        bot.run()
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت.")