import asyncio
import os
import re
from queue import Queue
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pytgcalls import PyTgCalls, StreamType
from pytgcalls.types import AudioPiped, AudioQuality
import aiohttp

# ---------- ENV VARIABLES ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
STRING_SESSION = os.environ["STRING_SESSION"]

# ---------- CLIENTS ----------
app = Client(STRING_SESSION, api_id=API_ID, api_hash=API_HASH)
call = PyTgCalls(app)

# ---------- QUEUE & STATE ----------
playlist = Queue()
current = {}   # {title, duration_sec, duration_str, audio_url, message_id, chat_id, requested_by}
repeat = False
paused = False
current_vc = None
progress_updater = None  # task that updates progress bar

# ---------- SHRUTIBOTS.SITE API ----------
SHRUTI_API_BASE = "https://shrutibots.site"

async def fetch_audio_from_shrutibot(query: str):
    """Returns (audio_url, title, duration_sec, duration_str) or (None,None,None,None)"""
    async with aiohttp.ClientSession() as session:
        # Detect if it's YouTube link
        if re.search(r"(youtu\.be\/|youtube\.com\/watch\?v=)", query):
            url = f"{SHRUTI_API_BASE}/api?url={query}"
        else:
            url = f"{SHRUTI_API_BASE}/api/search?q={query}"
        
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None, None, None, None
                data = await resp.json()
                # 🔁 YAHAN APNE SITE KE ACTUAL RESPONSE KE ACCORDING CHANGE KAR
                audio_url = data.get("audio_url") or data.get("url")
                title = data.get("title")
                dur_str = data.get("duration") or data.get("duration_str") or "0:00"
                # Convert duration string to seconds (e.g., "3:45" -> 225)
                parts = dur_str.split(":")
                if len(parts) == 2:
                    dur_sec = int(parts[0]) * 60 + int(parts[1])
                else:
                    dur_sec = int(parts[0])
                return audio_url, title, dur_sec, dur_str
        except Exception as e:
            print(f"Shrutibot API error: {e}")
            return None, None, None, None

# ---------- PROGRESS BAR HELPERS ----------
def format_time(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

def make_progress_bar(current_sec, total_sec, length=20):
    if total_sec == 0:
        ratio = 0
    else:
        ratio = current_sec / total_sec
    filled = int(round(ratio * length))
    if filled <= 0:
        filled = 0
    elif filled >= length:
        filled = length
    bar = "▬" * filled + "🔘" + "▬" * (length - filled - 1) if filled < length else "🔘" + "▬" * (length - 1)
    return f"{format_time(current_sec)} {bar} {format_time(total_sec)}"

async def update_progress_message(chat_id, msg_id, title, duration_sec, duration_str, requested_by):
    """Background task: updates progress bar every 1 second"""
    while True:
        if not current or current.get("chat_id") != chat_id:
            break
        # Get current playback position in seconds
        try:
            pos_sec = await call.get_current_playback_position(chat_id)
            if pos_sec is None:
                pos_sec = 0
        except:
            pos_sec = 0
        progress_line = make_progress_bar(int(pos_sec), duration_sec)
        text = f"**Started streaming**\nTitle: {title}\nDuration: {duration_str}\nRequested by: {requested_by}\n\n{progress_line}"
        try:
            await app.edit_message_text(chat_id, msg_id, text, reply_markup=make_buttons())
        except:
            pass
        await asyncio.sleep(1)
        if not current or current.get("chat_id") != chat_id:
            break

def make_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data="pause"),
            InlineKeyboardButton("⏹ Skip", callback_data="skip"),
            InlineKeyboardButton("🔁 Repeat" if repeat else "🔂 Repeat", callback_data="repeat"),
        ],
        [
            InlineKeyboardButton("⏹ End", callback_data="end"),
            InlineKeyboardButton("📋 Queue", callback_data="queue"),
        ]
    ])

async def send_now_playing(chat_id, title, duration_sec, duration_str, requested_by, start_updater=False):
    global progress_updater
    # Cancel old updater if any
    if progress_updater and not progress_updater.done():
        progress_updater.cancel()
    progress_line = make_progress_bar(0, duration_sec)
    text = f"**Started streaming**\nTitle: {title}\nDuration: {duration_str}\nRequested by: {requested_by}\n\n{progress_line}"
    if current.get("message_id"):
        try:
            await app.edit_message_text(chat_id, current["message_id"], text, reply_markup=make_buttons())
        except:
            msg = await app.send_message(chat_id, text, reply_markup=make_buttons())
            current["message_id"] = msg.id
    else:
        msg = await app.send_message(chat_id, text, reply_markup=make_buttons())
        current["message_id"] = msg.id
        current["chat_id"] = chat_id
    if start_updater and duration_sec > 0:
        progress_updater = asyncio.create_task(
            update_progress_message(chat_id, current["message_id"], title, duration_sec, duration_str, requested_by)
        )

# ---------- PLAY NEXT ----------
async def play_next(chat_id):
    global paused, repeat, progress_updater
    if repeat and current.get("audio_url"):
        # repeat current song
        url = current["audio_url"]
        title = current["title"]
        dur_sec = current["duration_sec"]
        dur_str = current["duration_str"]
        req_by = current["requested_by"]
    else:
        if playlist.empty():
            await send_now_playing(chat_id, "Queue empty", 0, "0:00", "Bot", False)
            current.clear()
            return
        title, url, dur_sec, dur_str, req_by = playlist.get()
    paused = False
    current = {
        "title": title,
        "audio_url": url,
        "duration_sec": dur_sec,
        "duration_str": dur_str,
        "requested_by": req_by,
        "chat_id": chat_id,
        "message_id": current.get("message_id")  # keep existing if any
    }
    await send_now_playing(chat_id, title, dur_sec, dur_str, req_by, start_updater=True)
    try:
        await call.change_stream(chat_id, AudioPiped(url, AudioQuality.HIGH))
    except:
        await call.play(chat_id, AudioPiped(url, AudioQuality.HIGH))

# ---------- .play COMMAND ----------
@app.on_message(filters.command("play") & (filters.private | filters.group))
async def play_cmd(client: Client, message: Message):
    if not message.command[1:]:
        return await message.reply("Usage: `.play song name or YouTube link`")
    query = " ".join(message.command[1:])
    status_msg = await message.reply("🔍 Fetching from shrutibots.site...")
    audio_url, title, dur_sec, dur_str = await fetch_audio_from_shrutibot(query)
    if not audio_url:
        await status_msg.edit("❌ Failed. Check shrutibots.site API response format.")
        return
    requested_by = message.from_user.first_name or message.from_user.username
    playlist.put((title, audio_url, dur_sec, dur_str, requested_by))
    await status_msg.edit(f"✅ Added to queue\n**{title}**\n⏱ {dur_str}\nRequested by: {requested_by}")
    if not current:
        chat_id = message.chat.id
        if not current_vc:
            try:
                await call.join_call(chat_id)
            except:
                await call.start()
                await call.join_call(chat_id)
            current_vc = chat_id
        await play_next(chat_id)

# ---------- CALLBACK HANDLER ----------
@app.on_callback_query()
async def cb_handler(client: Client, cb: CallbackQuery):
    chat_id = cb.message.chat.id
    data = cb.data
    global paused, repeat, progress_updater

    if data == "pause":
        if not current: return await cb.answer("Nothing playing", True)
        if paused:
            await call.resume_stream(chat_id)
            paused = False
            await cb.answer("Resumed")
        else:
            await call.pause_stream(chat_id)
            paused = True
            await cb.answer("Paused")
        # restart updater if needed
        if not paused and current:
            if progress_updater and not progress_updater.done():
                progress_updater.cancel()
            progress_updater = asyncio.create_task(
                update_progress_message(chat_id, current["message_id"], current["title"], current["duration_sec"], current["duration_str"], current["requested_by"])
            )
        await send_now_playing(chat_id, current["title"], current["duration_sec"], current["duration_str"], current["requested_by"], start_updater=False)
    elif data == "skip":
        if not current: return await cb.answer("Nothing playing", True)
        await cb.answer("Skipping...")
        if progress_updater and not progress_updater.done():
            progress_updater.cancel()
        await play_next(chat_id)
    elif data == "repeat":
        repeat = not repeat
        await cb.answer(f"Repeat {'ON' if repeat else 'OFF'}")
        await send_now_playing(chat_id, current["title"], current["duration_sec"], current["duration_str"], current["requested_by"], start_updater=False)
    elif data == "end":
        if not current: return await cb.answer("Nothing playing", True)
        playlist.queue.clear()
        current.clear()
        if progress_updater and not progress_updater.done():
            progress_updater.cancel()
        await call.stop_stream(chat_id)
        await call.leave_call(chat_id)
        global current_vc
        current_vc = None
        paused = False
        await cb.message.edit_text("⏹ Playback ended. Queue cleared.")
    elif data == "queue":
        if playlist.empty():
            await cb.answer("Queue is empty", True)
        else:
            q_list = list(playlist.queue)
            text = "📋 **Queue:**\n" + "\n".join(f"{i+1}. {t[0]} (req by {t[4]})" for i,t in enumerate(q_list[:10]))
            await cb.answer(text, show_alert=True)

# ---------- TEXT COMMANDS ----------
@app.on_message(filters.command("pause"))
async def pause_cmd(client, msg):
    if not current: return await msg.reply("Nothing playing")
    global paused
    if paused:
        await call.resume_stream(msg.chat.id)
        paused = False
        await msg.reply("Resumed")
    else:
        await call.pause_stream(msg.chat.id)
        paused = True
        await msg.reply("Paused")
    await send_now_playing(msg.chat.id, current["title"], current["duration_sec"], current["duration_str"], current["requested_by"], start_updater=False)

@app.on_message(filters.command("skip"))
async def skip_cmd(client, msg):
    if not current: return await msg.reply("Nothing playing")
    if progress_updater and not progress_updater.done():
        progress_updater.cancel()
    await msg.reply("Skipping...")
    await play_next(msg.chat.id)

@app.on_message(filters.command("end"))
async def end_cmd(client, msg):
    if not current: return await msg.reply("Nothing playing")
    playlist.queue.clear()
    current.clear()
    if progress_updater and not progress_updater.done():
        progress_updater.cancel()
    await call.stop_stream(msg.chat.id)
    await call.leave_call(msg.chat.id)
    global current_vc, paused
    current_vc = None
    paused = False
    await msg.reply("Playback ended")

@app.on_message(filters.command("queue"))
async def queue_cmd(client, msg):
    if playlist.empty():
        await msg.reply("Queue empty")
    else:
        q_list = list(playlist.queue)
        text = "📋 **Queue:**\n" + "\n".join(f"{i+1}. {t[0]} (req by {t[4]})" for i,t in enumerate(q_list[:10]))
        await msg.reply(text)

@app.on_message(filters.command("repeat"))
async def repeat_cmd(client, msg):
    global repeat
    repeat = not repeat
    await msg.reply(f"Repeat {'ON' if repeat else 'OFF'}")

@app.on_message(filters.command("join"))
async def join_vc(client, msg):
    if current_vc:
        return await msg.reply("Already in VC")
    try:
        await call.join_call(msg.chat.id)
        current_vc = msg.chat.id
        await msg.reply("Joined voice chat")
    except Exception as e:
        await msg.reply(f"Failed: {e}")

@app.on_message(filters.command("leave"))
async def leave_vc(client, msg):
    if not current_vc:
        return await msg.reply("Not in VC")
    await call.leave_call(msg.chat.id)
    current_vc = None
    await msg.reply("Left VC")

# ---------- START ----------
async def main():
    await call.start()
    await app.start()
    print("Music userbot running with shrutibots.site + live progress bar")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
