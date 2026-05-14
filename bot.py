import os, re, json, logging, tempfile
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction
import google.generativeai as genai
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
try:
    from moviepy.editor import (
        TextClip, ColorClip, CompositeVideoClip,
        AudioFileClip, concatenate_videoclips
    )
    MOVIEPY_OK = True
except:
    MOVIEPY_OK = False

# ============================================================
#   🔑 APNI KEYS YAHAN DAALEN
# ============================================================
TELEGRAM_TOKEN  = "8691481092:AAGEx2xPFCYPm3wyfbuuVGaqgZTeN_nKwmA"   # BotFather se mila token
GEMINI_API_KEY  = "AIzaSyDsAC5rDyKeoLQeCU2lekHJK5gvSDUecCY"        # aistudio.google.com
YOUTUBE_API_KEY = "AIzaSyBiW8UeSTc967iogC5L818Ke1XBFur4YUc"       # console.cloud.google.com
# ============================================================

# Railway/Render environment variables se bhi le sakta hai
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN",  TELEGRAM_TOKEN)
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY",  GEMINI_API_KEY)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", YOUTUBE_API_KEY)

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")
yt     = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)
SESSIONS: dict = {}

# ============================================================
#   HELPER FUNCTIONS
# ============================================================

def get_video_id(text: str) -> Optional[str]:
    """URL se video ID nikalta hai"""
    for pat in [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None

def search_youtube(query: str) -> Optional[str]:
    """Series name se YouTube search karke pehla video ID deta hai"""
    try:
        r = yt.search().list(
            part="snippet",
            q=query + " trailer official",
            type="video",
            maxResults=1
        ).execute()
        if r.get("items"):
            return r["items"][0]["id"]["videoId"]
    except Exception as e:
        log.error(f"YouTube search error: {e}")
    return None

def fetch_metadata(vid: str) -> dict:
    r = yt.videos().list(
        part="snippet,contentDetails,statistics", id=vid
    ).execute()
    if not r.get("items"):
        raise ValueError("Video not found")
    it  = r["items"][0]
    sn  = it["snippet"]
    st  = it.get("statistics", {})
    return {
        "id":          vid,
        "title":       sn.get("title", ""),
        "description": sn.get("description", "")[:800],
        "tags":        sn.get("tags", [])[:15],
        "channel":     sn.get("channelTitle", ""),
        "duration":    it["contentDetails"].get("duration", ""),
        "views":       st.get("viewCount", "0"),
    }

def fetch_transcript(vid: str) -> str:
    try:
        for lang in [["hi"], ["en"], None]:
            try:
                tl = YouTubeTranscriptApi.get_transcript(
                    vid, languages=lang
                ) if lang else YouTubeTranscriptApi.get_transcript(vid)
                return " ".join(t["text"] for t in tl)[:3500]
            except:
                continue
    except:
        pass
    return ""

def ai_analyze(meta: dict, transcript: str) -> dict:
    prompt = f"""You are a Hindi/English screenwriter.
Analyze this YouTube video and create an ORIGINAL web series blueprint.

VIDEO: Title={meta['title']} | Channel={meta['channel']}
Tags={','.join(meta['tags'])} | Views={meta['views']}
Description: {meta['description']}
Transcript: {transcript or 'Not available'}

Return ONLY valid JSON (no markdown, no backticks):
{{"genre":"...","tone":"...","target_audience":"...",
"original_series":{{"title_english":"...","title_hindi":"...",
"tagline_english":"...","tagline_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"..."}},
"episodes":[
{{"ep_number":1,"title_english":"...","title_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"...",
"key_scenes":["...","...","..."],"hook":"..."}},
{{"ep_number":2,"title_english":"...","title_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"...",
"key_scenes":["...","...","..."],"hook":"..."}},
{{"ep_number":3,"title_english":"...","title_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"...",
"key_scenes":["...","...","..."],"hook":"..."}},
{{"ep_number":4,"title_english":"...","title_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"...",
"key_scenes":["...","...","..."],"hook":"..."}},
{{"ep_number":5,"title_english":"...","title_hindi":"...",
"synopsis_english":"...","synopsis_hindi":"...",
"key_scenes":["...","...","..."],"hook":"..."}}
]}}

RULES: 100% ORIGINAL. Hindi in Devanagari. JSON ONLY."""
    raw = gemini.generate_content(prompt).text.strip()
    raw = re.sub(r"```json\s*|\s*```|```", "", raw).strip()
    return json.loads(raw)

def ai_script(ep: dict, analysis: dict) -> str:
    s = analysis["original_series"]
    prompt = f"""Write a FULL EPISODE SCRIPT (Hindi + English):
Series: {s['title_english']} / {s['title_hindi']}
Episode {ep['ep_number']}: {ep['title_english']} / {ep['title_hindi']}
Synopsis: {ep['synopsis_english']}
Key Scenes: {', '.join(ep['key_scenes'])}
Genre: {analysis['genre']} | Tone: {analysis['tone']}
Structure: COLD OPEN → ACT 1 → ACT 2 → ACT 3 → CLIFFHANGER
Format: Scene heading, Hindi dialogue, English translation.
Target: ~15 min when produced. Make it gripping!"""
    return gemini.generate_content(prompt).text

def make_tts(text: str, lang: str, path: str) -> str:
    gTTS(
        text=re.sub(r"[*#_`]+", "", text)[:2500],
        lang=lang, slow=False
    ).save(path)
    return path

def make_teaser_video(ep, analysis, out_dir):
    if not MOVIEPY_OK:
        raise RuntimeError("MoviePy not installed")
    n  = ep['ep_number']
    s  = analysis["original_series"]
    ap = os.path.join(out_dir, f"a{n}.mp3")
    op = os.path.join(out_dir, f"ep{n}.mp4")
    make_tts(
        f"Episode {n}. {ep['title_english']}. "
        f"{ep['synopsis_english']} Stay tuned!", "en", ap
    )
    c1 = CompositeVideoClip([
        ColorClip(size=(1280, 720), color=[8, 4, 20], duration=5),
        TextClip(s['title_english'], fontsize=56, color="gold",
                 font="DejaVu-Sans-Bold", size=(1200, None),
                 method="caption").set_position("center").set_duration(5),
        TextClip(f"Ep {n}: {ep['title_english']}", fontsize=32,
                 color="white", font="DejaVu-Sans", size=(1200, None),
                 method="caption").set_position(("center", 430)).set_duration(5)
    ])
    c2 = CompositeVideoClip([
        ColorClip(size=(1280, 720), color=[5, 12, 8], duration=8),
        TextClip(ep['synopsis_english'], fontsize=26,
                 color="lightgreen", font="DejaVu-Sans",
                 size=(1100, None), method="caption"
                 ).set_position("center").set_duration(8)
    ])
    final = concatenate_videoclips([c1, c2])
    audio = AudioFileClip(ap)
    final.set_audio(
        audio.set_duration(final.duration)
    ).write_videofile(
        op, fps=24, codec="libx264",
        audio_codec="aac", logger=None
    )
    return op

# ============================================================
#   COMMAND HANDLERS
# ============================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *YouTube Series Creator Bot*\n"
        "_100% FREE — Google Gemini + YouTube API_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *Commands:*\n"
        "• `/analyze Mirzapur` — Name se analyze\n"
        "• `/analyze https://youtu.be/xxx` — URL se analyze\n"
        "• `/series` — Series overview\n"
        "• `/script 1` — Full episode script\n"
        "• `/teaser 1` — Teaser video MP4\n"
        "• `/audio 1` — Hindi + English audio\n"
        "• `/help` — Info\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 Example:\n"
        "`/analyze Mirzapur`\n"
        "`/analyze Sacred Games`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆓 *FREE APIs Used:*\n\n"
        "✅ Google Gemini 1.5 Flash — 1500 req/day FREE\n"
        "✅ YouTube Data API v3 — 10k units/day FREE\n"
        "✅ gTTS — Unlimited FREE TTS\n"
        "✅ Telegram Bot API — FREE\n\n"
        "📌 *Usage:*\n"
        "`/analyze Mirzapur` — Series name\n"
        "`/analyze https://youtu.be/xxx` — YouTube URL\n\n"
        "⚖️ Legal: No downloading. All original content.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "❗ *Usage:*\n"
            "`/analyze Mirzapur`\n"
            "`/analyze Sacred Games`\n"
            "`/analyze https://youtu.be/xxx`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    uid   = update.effective_user.id
    query = " ".join(ctx.args)

    await update.message.chat.send_action(ChatAction.TYPING)
    msg = await update.message.reply_text(
        "🔍 *Step 1/4:* Finding video...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        # URL hai ya Series Name?
        vid = get_video_id(query)
        if not vid:
            # Series name se YouTube search
            await msg.edit_text(
                f"🔎 Searching YouTube: *{query}*...",
                parse_mode=ParseMode.MARKDOWN
            )
            vid = search_youtube(query)
            if not vid:
                await msg.edit_text(
                    f"❌ *'{query}'* ke liye koi video nahi mila.\n\n"
                    f"Try karein:\n`/analyze Mirzapur trailer`\n"
                    f"ya YouTube URL paste karein.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

        meta = fetch_metadata(vid)
        await msg.edit_text(
            f"✅ _{meta['title']}_\n\n"
            f"📝 *Step 2/4:* Transcript fetch ho raha hai...",
            parse_mode=ParseMode.MARKDOWN
        )

        transcript = fetch_transcript(vid)
        ts = f"{len(transcript)} chars" if transcript else "unavailable"

        await msg.edit_text(
            f"✅ Metadata | Transcript: {ts}\n\n"
            f"🤖 *Step 3/4:* Gemini AI analyze kar raha hai...",
            parse_mode=ParseMode.MARKDOWN
        )

        analysis = ai_analyze(meta, transcript)
        SESSIONS[uid] = {"meta": meta, "analysis": analysis}

        await msg.edit_text(
            "✅ Analysis done!\n\n"
            "🎬 *Step 4/4:* Series build ho rahi hai...",
            parse_mode=ParseMode.MARKDOWN
        )

        s   = analysis["original_series"]
        ep  = analysis["episodes"]

        result = (
            f"🎬 *ORIGINAL SERIES READY!*\n\n"
            f"🇬🇧 *{s['title_english']}*\n"
            f"🇮🇳 _{s['title_hindi']}_\n\n"
            f"💬 \"{s['tagline_english']}\"\n\n"
            f"🎭 {analysis['genre']} | 🎯 {analysis['tone']}\n\n"
            f"📖 {s['synopsis_english']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📺 *EPISODES:*\n\n"
        )
        for e in ep:
            result += (
                f"*Ep {e['ep_number']}:* {e['title_english']}\n"
                f"   _{e['title_hindi']}_\n"
                f"   {e['synopsis_english'][:80]}...\n\n"
            )
        result += "━━━━━━━━━━━━━━━━━━━━\n"
        result += "`/series` | `/script 1` | `/teaser 1` | `/audio 1`"

        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)

    except json.JSONDecodeError:
        await msg.edit_text(
            "❌ AI parse error. Dobara try karein:\n`/analyze Mirzapur`",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        log.error(f"analyze error: {e}")
        await msg.edit_text(f"❌ Error: {e}")

async def cmd_series(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ Pehle analyze karein:\n`/analyze Mirzapur`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    s   = sess["analysis"]["original_series"]
    eps = sess["analysis"]["episodes"]
    kb  = [[
        InlineKeyboardButton(
            f"Ep {e['ep_number']}", callback_data=f"ep_{e['ep_number']}"
        ) for e in eps
    ]]
    await update.message.reply_text(
        f"🎬 *{s['title_english']}*\n"
        f"_{s['title_hindi']}_\n\n"
        f"{s['synopsis_english']}\n\n"
        f"📺 Episode dekhne ke liye button dabayein:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cmd_script(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ Pehle analyze karein:\n`/analyze Mirzapur`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} nahi mila.")
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    s = await update.message.reply_text(
        f"✍️ Episode {n} ka script generate ho raha hai..."
    )
    script = ai_script(ep, sess["analysis"])
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(
            f"EPISODE {n}: {ep['title_english']} / "
            f"{ep['title_hindi']}\n{'='*60}\n\n{script}"
        )
        tmp = f.name
    await s.delete()
    await update.message.reply_document(
        document=open(tmp, "rb"),
        filename=f"Ep{n}_Script.txt",
        caption=f"📝 *Episode {n} Script*\n_{ep['title_hindi']}_",
        parse_mode=ParseMode.MARKDOWN
    )
    os.unlink(tmp)

async def cmd_teaser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ Pehle analyze karein:\n`/analyze Mirzapur`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} nahi mila.")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    s = await update.message.reply_text(
        f"🎬 Teaser Ep {n} ban raha hai... (~30-60 sec)"
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            vpath = make_teaser_video(ep, sess["analysis"], d)
            await s.edit_text("📤 Upload ho raha hai...")
            await update.message.reply_video(
                video=open(vpath, "rb"),
                caption=(
                    f"🎬 *Ep {n}: {ep['title_english']}*\n"
                    f"_{ep['title_hindi']}_\n\n"
                    f"🎯 {ep['hook']}"
                ),
                parse_mode=ParseMode.MARKDOWN,
                supports_streaming=True
            )
            await s.delete()
    except Exception as e:
        log.error(f"teaser error: {e}")
        await s.edit_text(f"❌ {e}")

async def cmd_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ Pehle analyze karein:\n`/analyze Mirzapur`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} nahi mila.")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_VOICE)
    s = await update.message.reply_text(
        "🔊 Hindi + English audio generate ho raha hai..."
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            enp = os.path.join(d, "en.mp3")
            hip = os.path.join(d, "hi.mp3")
            make_tts(
                f"Episode {n}. {ep['title_english']}. "
                f"{ep['synopsis_english']} Stay tuned!",
                "en", enp
            )
            make_tts(
                f"एपिसोड {n}। {ep['title_hindi']}। "
                f"{ep['synopsis_hindi']} जुड़े रहें!",
                "hi", hip
            )
            await update.message.reply_audio(
                audio=open(enp, "rb"),
                title=f"Ep {n} English",
                caption="🇬🇧 English Audio"
            )
            await update.message.reply_audio(
                audio=open(hip, "rb"),
                title=f"Ep {n} Hindi",
                caption="🇮🇳 हिंदी Audio"
            )
            await s.delete()
    except Exception as e:
        log.error(f"audio error: {e}")
        await s.edit_text(f"❌ {e}")

async def cb_ep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    n    = int(q.data.split("_")[1])
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await q.edit_message_text(
            "Session expire ho gaya. Dobara /analyze karein."
        )
        return
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        return
    await q.edit_message_text(
        f"📺 *Episode {n}*\n\n"
        f"🇬🇧 *{ep['title_english']}*\n"
        f"🇮🇳 _{ep['title_hindi']}_\n\n"
        f"📖 {ep['synopsis_english']}\n\n"
        f"🎯 Hook: _{ep['hook']}_\n\n"
        f"🎬 Scenes:\n"
        + "\n".join(f"• {sc}" for sc in ep['key_scenes'])
        + f"\n\n`/script {n}` | `/teaser {n}` | `/audio {n}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def auto_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "youtu" in text:
        ctx.args = [text.split()[0]]
        await cmd_analyze(update, ctx)

# ============================================================
#   MAIN
# ============================================================

def main():
    if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, YOUTUBE_API_KEY]):
        raise RuntimeError(
            "❌ Keys missing! Set TELEGRAM_TOKEN, GEMINI_API_KEY, YOUTUBE_API_KEY"
        )
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    for cmd, fn in [
        ("start",   cmd_start),
        ("help",    cmd_help),
        ("analyze", cmd_analyze),
        ("series",  cmd_series),
        ("script",  cmd_script),
        ("teaser",  cmd_teaser),
        ("audio",   cmd_audio),
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(
        CallbackQueryHandler(cb_ep, pattern=r"^ep_\d+$")
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, auto_url)
    )
    log.info("✅ Bot running! FREE: Gemini + YouTube API + gTTS")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
