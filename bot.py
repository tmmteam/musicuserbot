import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio
from pytgcalls.types.stream import StreamType

# =========================
# CONFIG FROM ENV
# =========================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
STRING_SESSION = os.environ["STRING_SESSION"]

# =========================
# RADIO STATIONS
# =========================
RADIO_STATION = {
    "Air Bilaspur": "http://air.pc.cdn.bitgravity.com/air/live/pbaudio110/playlist.m3u8",
    "Air Raipur": "http://air.pc.cdn.bitgravity.com/air/live/pbaudio118/playlist.m3u8",
    "Capital FM": "http://media-ice.musicradio.com/CapitalMP3?.mp3",
    "English": "https://hls-01-regions.emgsound.ru/11_msk/playlist.m3u8",
    "Mirchi": "http://peridot.streamguys.com:7150/Mirchi",
    "Bollywood Love": "https://nl4.mystreaming.net/uber/bollywoodlove/icecast.audio",
    "Radio Today": "http://stream.zenolive.com/8wv4d8g4344tv",
    "Bollywood": "https://stream-159.zeno.fm/143d7gty24zuv"
}

# =========================
# APP SETUP
# =========================
app = Client(
    "radio_userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION
)

call = PyTgCalls(app)

# =========================
# COMMANDS
# =========================

@app.on_message(filters.command("radio", prefixes="."))
async def radio_cmd(_, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: `.radio station name`")

    station_name = " ".join(message.command[1:])

    if station_name not in RADIO_STATION:
        return await message.reply("❌ Station not found. Use `.stations`")

    url = RADIO_STATION[station_name]

    print(f"[RADIO] Requested: {station_name}")
    print(f"[RADIO] URL: {url}")

    try:
        await call.join_group_call(
            message.chat.id,
            AudioPiped(
                url,
                HighQualityAudio(),
            ),
            stream_type=StreamType().live_stream
        )

        await message.reply(f"📻 Streaming **{station_name}**")

    except Exception as e:
        print(f"[RADIO ERROR] {e}")
        await message.reply(f"Error: {e}")


@app.on_message(filters.command("stations", prefixes="."))
async def stations_cmd(_, message: Message):
    txt = "**📻 Available Stations:**\n\n"
    for s in RADIO_STATION:
        txt += f"• `{s}`\n"

    await message.reply(txt)


@app.on_message(filters.command("stop", prefixes="."))
async def stop_cmd(_, message: Message):
    try:
        await call.leave_group_call(message.chat.id)
        print("[RADIO] Stopped stream")
        await message.reply("⏹ Radio stopped.")
    except Exception as e:
        print(f"[STOP ERROR] {e}")
        await message.reply(f"Error: {e}")


# =========================
# MAIN
# =========================
async def main():
    await app.start()
    await call.start()
    print("✅ Radio Bot Started Successfully")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
