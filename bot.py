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

TELEGRAM_TOKEN  = os.getenv("8691481092:AAGEx2xPFCYPm3wyfbuuVGaqgZTeN_nKwmA", "")
GEMINI_API_KEY  = os.getenv("AIzaSyDsAC5rDyKeoLQeCU2lekHJK5gvSDUecCY", "")
YOUTUBE_API_KEY = os.getenv("AIzaSyBiW8UeSTc967iogC5L818Ke1XBFur4YUc", "")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")
yt     = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)
SESSIONS: dict = {}

def get_video_id(url: str) -> Optional[str]:
    for pat in [r"youtu\.be/([A-Za-z0-9_-]{11})",
                r"youtube\.com/watch\?v=([A-Za-z0-9_-]{11})",
                r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"]:
        m = re.search(pat, url)
        if m: return m.group(1)
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
        "id": vid,
        "title": sn.get("title", ""),
        "description": sn.get("description", "")[:800],
        "tags": sn.get("tags", [])[:15],
        "channel": sn.get("channelTitle", ""),
        "duration": it["contentDetails"].get("duration", ""),
        "views": st.get("viewCount", "0"),
    }

def fetch_transcript(vid: str) -> str:
    try:
        for lang in [["hi"], ["en"], None]:
            try:
                tl = YouTubeTranscriptApi.get_transcript(
                    vid, languages=lang
                ) if lang else YouTubeTranscriptApi.get_transcript(vid)
                return " ".join(t["text"] for t in tl)[:3500]
            except: continue
    except: pass
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

def make_title_card(title_en, title_hi, ep_num, out):
    w, h = 1280, 720
    img  = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        p = y / h
        draw.line(
            [(0,y),(w,y)],
            fill=(int(8+p*25), int(4+p*8), int(20+p*55))
        )
    for t in range(4):
        draw.rectangle(
            [18+t, 18+t, w-18-t, h-18-t],
            outline=(200, 160, 40)
        )
    try:
        fb = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54
        )
        fm = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30
        )
    except:
        fb = fm = ImageFont.load_default()
    draw.text((w//2, h//2-80), title_en,
              fill=(255,215,60), font=fb, anchor="mm")
    draw.text((w//2, h//2+10), title_hi,
              fill=(220,200,255), font=fm, anchor="mm")
    draw.text((w//2, h//2+70), f"Episode {ep_num}",
              fill=(180,180,180), font=fm, anchor="mm")
    draw.text((w//2, h-35), "Original AI Series",
              fill=(80,80,80), font=fm, anchor="mm")
    img.save(out, "PNG")
    return out

def make_teaser_video(ep, analysis, out_dir):
    if not MOVIEPY_OK:
        raise RuntimeError("MoviePy not installed")
    n = ep['ep_number']
    s = analysis["original_series"]
    ap = os.path.join(out_dir, f"a{n}.mp3")
    op = os.path.join(out_dir, f"ep{n}.mp4")
    make_tts(
        f"Episode {n}. {ep['title_english']}. "
        f"{ep['synopsis_english']} Stay tuned!", "en", ap
    )
    c1 = CompositeVideoClip([
        ColorClip(size=(1280,720), color=[8,4,20], duration=5),
        TextClip(s['title_english'], fontsize=56, color="gold",
                 font="DejaVu-Sans-Bold", size=(1200,None),
                 method="caption").set_position("center").set_duration(5),
        TextClip(f"Ep {n}: {ep['title_english']}", fontsize=32,
                 color="white", font="DejaVu-Sans", size=(1200,None),
                 method="caption").set_position(("center",430)).set_duration(5)
    ])
    c2 = CompositeVideoClip([
        ColorClip(size=(1280,720), color=[5,12,8], duration=8),
        TextClip(ep['synopsis_english'], fontsize=26,
                 color="lightgreen", font="DejaVu-Sans",
                 size=(1100,None), method="caption"
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

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *YouTube Series Creator Bot*\n"
        "_100% FREE — Google Gemini + YouTube API_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 *Commands:*\n"
        "• `/analyze ` — Analyze & generate\n"
        "• `/series` — Series overview\n"
        "• `/script 1` — Full episode script\n"
        "• `/teaser 1` — Teaser video MP4\n"
        "• `/audio 1` — Hindi + English audio\n"
        "• `/help` — Info\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 Start: `/analyze https://youtu.be/G-3JSyi_Ss0`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆓 *FREE APIs Used:*\n\n"
        "✅ Google Gemini 1.5 Flash — 1500 req/day FREE\n"
        "✅ YouTube Data API v3 — 10k units/day FREE\n"
        "✅ gTTS — Unlimited FREE TTS\n"
        "✅ Telegram Bot API — FREE\n\n"
        "⚖️ Legal: No downloading. All original content.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/analyze `",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    vid = get_video_id(ctx.args[0])
    if not vid:
        await update.message.reply_text("❌ Invalid URL.")
        return
    uid = update.effective_user.id
    await update.message.chat.send_action(ChatAction.TYPING)
    msg = await update.message.reply_text(
        "🔍 *Step 1/4:* Fetching metadata...",
        parse_mode=ParseMode.MARKDOWN
    )
    try:
        meta = fetch_metadata(vid)
        await msg.edit_text(
            f"✅ _{meta['title']}_\n\n"
            f"📝 *Step 2/4:* Transcript...",
            parse_mode=ParseMode.MARKDOWN
        )
        transcript = fetch_transcript(vid)
        ts = f"{len(transcript)} chars" if transcript else "unavailable"
        await msg.edit_text(
            f"✅ Metadata | Transcript: {ts}\n\n"
            f"🤖 *Step 3/4:* Gemini AI (FREE)...",
            parse_mode=ParseMode.MARKDOWN
        )
        analysis = ai_analyze(meta, transcript)
        SESSIONS[uid] = {"meta": meta, "analysis": analysis}
        await msg.edit_text(
            "✅ Done!\n\n🎬 *Step 4/4:* Building series...",
            parse_mode=ParseMode.MARKDOWN
        )
        s, ep = analysis["original_series"], analysis["episodes"]
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
        result += "`/script 1` | `/teaser 1` | `/audio 1`"
        await msg.edit_text(result, parse_mode=ParseMode.MARKDOWN)
    except json.JSONDecodeError:
        await msg.edit_text("❌ AI parse error. Try again.")
    except Exception as e:
        log.error(f"analyze: {e}")
        await msg.edit_text(f"❌ Error: {e}")

async def cmd_series(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ First `/analyze `",
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
        f"🎬 *{s['title_english']}*\n_{s['title_hindi']}_\n\n"
        f"{s['synopsis_english']}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cmd_script(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ First `/analyze `",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} not found.")
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    s = await update.message.reply_text(
        f"✍️ Generating Episode {n} script..."
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
            "❗ First `/analyze `",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} not found.")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
    s = await update.message.reply_text(
        f"🎬 Building teaser Ep {n}... (~30-60 sec)"
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            vpath = make_teaser_video(ep, sess["analysis"], d)
            await s.edit_text("📤 Uploading...")
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
        log.error(f"teaser: {e}")
        await s.edit_text(f"❌ {e}")

async def cmd_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await update.message.reply_text(
            "❗ First `/analyze `",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    n  = int(ctx.args[0]) if ctx.args else 1
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep:
        await update.message.reply_text(f"❌ Episode {n} not found.")
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_VOICE)
    s = await update.message.reply_text(
        "🔊 Generating Hindi + English audio..."
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
                caption="🇬🇧 English"
            )
            await update.message.reply_audio(
                audio=open(hip, "rb"),
                title=f"Ep {n} Hindi",
                caption="🇮🇳 हिंदी"
            )
            await s.delete()
    except Exception as e:
        log.error(f"audio: {e}")
        await s.edit_text(f"❌ {e}")

async def cb_ep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    n   = int(q.data.split("_")[1])
    uid = update.effective_user.id
    sess = SESSIONS.get(uid)
    if not sess:
        await q.edit_message_text("Session expired. /analyze again.")
        return
    ep = next(
        (e for e in sess["analysis"]["episodes"] if e["ep_number"] == n),
        None
    )
    if not ep: return
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

def main():
    if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, YOUTUBE_API_KEY]):
        raise RuntimeError(
            "Set TELEGRAM_TOKEN, GEMINI_API_KEY, YOUTUBE_API_KEY"
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
