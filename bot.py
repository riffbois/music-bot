"""
Bot Musik Voice Chat Telegram
Cara pakai di grup:
  /play <judul lagu>  - putar lagu di voice chat
  /skip               - lewati lagu sekarang
  /stop               - berhenti & keluar dari voice chat
  /pause              - jeda
  /resume             - lanjutkan
  /queue              - lihat antrean

Arsitektur: DUA klien Telegram
  - `bot` (token dari @BotFather): terima perintah /play dll dari user.
  - `assistant` (akun user biasa via STRING_SESSION): yang join voice chat
    dan muter audionya. Akun BOT Telegram tidak bisa join voice chat,
    hanya akun user yang bisa — makanya butuh akun asisten.
"""
import os
import asyncio
import urllib.request
import urllib.parse
import json
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from yt_dlp import YoutubeDL

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

if not STRING_SESSION:
    print("⚠️  STRING_SESSION kosong! Akun asisten tidak bisa login, "
          "voice chat tidak akan jalan. Lihat README bagian 'Akun asisten'.")

# 1. Bot: terima perintah dari user
bot = Client("music-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
# 2. Asisten (akun user biasa): join voice chat & streaming audio
assistant = Client(
    "music-assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
)
call = PyTgCalls(assistant)

queue: dict[int, list[dict]] = {}

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "noplaylist": True,
}


def youtube_api_search(query: str) -> dict | None:
    """Cari lagu pakai YouTube Data API resmi."""
    if not YOUTUBE_API_KEY:
        return None
    try:
        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoCategoryId": "10",  # Music
            "maxResults": 1,
            "key": YOUTUBE_API_KEY,
        })
        url = f"https://www.googleapis.com/youtube/v3/search?{params}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        items = data.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        title = items[0]["snippet"]["title"]
        return {"video_id": video_id, "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}"}
    except Exception as e:
        print(f"YouTube API error: {e}")
        return None


def search_song(query: str) -> dict | None:
    # Coba YouTube API dulu (lebih akurat & resmi)
    yt = youtube_api_search(query)
    search_target = yt["url"] if yt else query

    with YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(search_target, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return {
                "title": yt["title"] if yt else info.get("title", "Unknown"),
                "url": info.get("webpage_url", ""),
                "audio": info.get("url", ""),
                "duration": info.get("duration", 0),
            }
        except Exception as e:
            print(f"Search error: {e}")
            return None


async def play_next(chat_id: int):
    q = queue.get(chat_id, [])
    if not q:
        return
    song = q[0]
    try:
        await call.play(chat_id, MediaStream(song["audio"]))
    except Exception as e:
        print(f"Play error: {e}")


@bot.on_message(filters.command("start"))
async def start_cmd(_: Client, msg: Message):
    await msg.reply(
        "🎵 **Bot Musik Voice Chat**\n\n"
        "Perintah:\n"
        "/play <judul> - putar lagu\n"
        "/skip - lewati\n"
        "/stop - berhenti\n"
        "/pause - jeda\n"
        "/resume - lanjut\n"
        "/queue - antrean\n\n"
        "Syarat: bot + akun asisten jadi anggota grup, "
        "asisten jadi admin (atau punya izin voice chat), "
        "& voice chat sudah dibuka!"
    )


@bot.on_message(filters.command("play") & filters.group)
async def play_cmd(_: Client, msg: Message):
    if len(msg.command) < 2:
        return await msg.reply("Kasih judul lagunya! Contoh: `/play shape of you`")
    query = msg.text.split(None, 1)[1]
    chat_id = msg.chat.id

    status = await msg.reply(f"🔍 Nyari: `{query}`...")
    song = await asyncio.to_thread(search_song, query)
    if not song:
        return await status.edit(
            "❌ Lagu nggak ketemu / gagal ambil audio.\n"
            "Kalau error-nya soal YouTube (403 / 'sign in to confirm'), "
            "kemungkinan IP server diblokir YouTube — lihat README bagian Troubleshooting."
        )

    queue.setdefault(chat_id, []).append(song)

    if len(queue[chat_id]) == 1:
        try:
            await call.play(chat_id, MediaStream(song["audio"]))
            await status.edit(f"▶️ **Now playing:** {song['title']}")
        except Exception as e:
            queue[chat_id].pop(0)
            await status.edit(
                f"❌ Gagal join voice chat: {e}\n"
                "Pastikan: voice chat sudah dibuka, akun ASISTEN sudah join grup, "
                "dan asisten punya izin kelola voice chat!"
            )
    else:
        await status.edit(f"📝 Ditambah ke antrean #{len(queue[chat_id])}: {song['title']}")


@bot.on_message(filters.command("skip") & filters.group)
async def skip_cmd(_: Client, msg: Message):
    chat_id = msg.chat.id
    q = queue.get(chat_id, [])
    if not q:
        return await msg.reply("Antrean kosong.")
    q.pop(0)
    if q:
        await play_next(chat_id)
        await msg.reply(f"⏭️ Skip! Now playing: {q[0]['title']}")
    else:
        await call.leave_call(chat_id)
        await msg.reply("⏭️ Antrean habis, keluar dari voice chat.")


@bot.on_message(filters.command("stop") & filters.group)
async def stop_cmd(_: Client, msg: Message):
    chat_id = msg.chat.id
    queue.pop(chat_id, None)
    try:
        await call.leave_call(chat_id)
    except Exception:
        pass
    await msg.reply("⏹️ Berhenti.")


@bot.on_message(filters.command("pause") & filters.group)
async def pause_cmd(_: Client, msg: Message):
    try:
        await call.pause(msg.chat.id)
        await msg.reply("⏸️ Dijeda.")
    except Exception as e:
        await msg.reply(f"❌ {e}")


@bot.on_message(filters.command("resume") & filters.group)
async def resume_cmd(_: Client, msg: Message):
    try:
        await call.resume(msg.chat.id)
        await msg.reply("▶️ Dilanjut.")
    except Exception as e:
        await msg.reply(f"❌ {e}")


@bot.on_message(filters.command("queue") & filters.group)
async def queue_cmd(_: Client, msg: Message):
    q = queue.get(msg.chat.id, [])
    if not q:
        return await msg.reply("Antrean kosong.")
    text = "📝 **Antrean:**\n"
    for i, s in enumerate(q, 1):
        text += f"{i}. {s['title']}\n"
    await msg.reply(text)


async def main():
    await assistant.start()
    await bot.start()
    await call.start()
    print("🎵 Bot musik jalan! (bot + asisten terhubung)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    bot.run(main())
