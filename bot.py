"""
Discord bot powered by a local LLM via Ollama.

Features:
  - Responds to @mentions in any channel
  - /ask slash command for direct queries
  - /clear slash command to wipe channel history
  - /timeout slash command to put the bot in time out (default 30 minutes)
  - /untimeout slash command to remove time out immediately
  - Per-channel conversation memory (last N turns)
  - Reads last 50 channel messages for context
  - Typing indicator while generating

Setup: see README.md
"""

import os
import asyncio
import json
import httpx
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import re
import io
from PIL import Image
from bs4 import BeautifulSoup
import rag_store

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Configuration ──────────────────────────────────────────────────────────────

DISCORD_TOKEN   = os.environ.get("DISCORD_TOKEN", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL           = os.environ.get("OLLAMA_MODEL", "gemma4:e2b")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
GEMINI_MODEL    = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_MODELS   = [GEMINI_MODEL, "gemini-flash-latest"] if GEMINI_MODEL != "gemini-flash-latest" else ["gemini-flash-latest"]

# Cap memory context size so prompts fit comfortably within Ollama context windows without clipping or HTTP 400.
IMAGE_MEMORY_MAX_CHARS = int(os.environ.get("IMAGE_MEMORY_MAX_CHARS", "55000"))
TEXT_MEMORY_MAX_CHARS  = int(os.environ.get("TEXT_MEMORY_MAX_CHARS", "70000"))

CHAT_OPTIONS = {
    "num_ctx": int(os.environ.get("NUM_CTX", os.environ.get("OLLAMA_NUM_CTX", "24576"))),
    "num_predict": 180,
    "temperature": 0.7,
    "top_p": 0.9,
    "repeat_penalty": 1.15,
    "presence_penalty": 0.3,
    "frequency_penalty": 0.3,
}

COMMUNITY_MEMBERS_PROMPT = os.environ.get("COMMUNITY_MEMBERS_PROMPT", "").strip()
_COMMUNITY_BLOCK = f"{COMMUNITY_MEMBERS_PROMPT} " if COMMUNITY_MEMBERS_PROMPT else ""

SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are Gemma, a female Discord bot acting as an adult human community member. You are multimodal and capable of seeing pictures and watching videos. "
        "Do not claim that you cannot see images or videos, or that you are a text-only model; you are fully equipped with vision and video parsing capabilities "
        "and can analyze any pictures or videos attached to user messages or linked in chat. "
        f"{_COMMUNITY_BLOCK}"
        "BREVITY & LENGTH RULE: Keep all your responses short, punchy, and brief (1 to 3 sentences max). "
        "Do NOT write multi-paragraph responses, essays, or unsolicited over-explanations unless the user explicitly asks for a detailed breakdown, guide, or long explanation. "
        "Match the casual, snappy length of a normal Discord chat participant. Avoid formulaic or repetitive intro phrases. "
        "Do NOT include speaker prefixes (e.g. 'Gemma:', '[Gemma]:', or 'Username:') or 'Analyzing...' in your output. "
        "EMOJI USAGE RULE: You may use server custom emojis in your messages by writing their shortcodes like :emoji_name:. "
        "Only use custom emoji names explicitly listed in the [Server Emoji] section. Do not invent custom emoji names. "
        "Do not write raw numeric IDs or <:name:id> tags manually — simply write :name: and the system will automatically "
        "format it for Discord. If no suitable server custom emoji is listed, feel free to use standard Unicode emojis (like 😊 🔥 👀)."
    ),
)

GUILD_EMOJI_FILE = Path(os.environ.get("GUILD_EMOJI_FILE", Path(__file__).resolve().parent / "guild_emojis.json"))
EMOJI_DESC_FILE  = Path(os.environ.get("EMOJI_DESC_FILE", Path(__file__).resolve().parent / "emoji_descriptions.json"))

STANDARD_EMOJI_DESC_MAP = {
    "laughing": "😂",
    "laughing face": "😂",
    "thinking": "🤔",
    "thinking face": "🤔",
    "smile": "😊",
    "smiling": "😊",
    "smiling face": "😊",
    "sparkle": "✨",
    "sparkles": "✨",
    "thumbs up": "👍",
    "heart": "❤️",
    "love": "❤️",
    "fire": "🔥",
    "lit": "🔥",
    "skull": "💀",
    "dead": "💀",
    "eyes": "👀",
    "crying": "😢",
    "sad": "😢",
    "surprised": "😮",
    "wow": "😮",
    "angry": "😡",
    "mad": "😡",
    "100": "💯",
    "hundred": "💯",
    "party": "🎉",
    "celebrate": "🎉",
}


def get_guild_emoji_map(guild: discord.Guild | None = None) -> dict[str, str]:
    """Returns a dict mapping lowercase_emoji_name -> exact Discord emoji tag '<:name:id>' or '<a:name:id>'."""
    emoji_map = {}
    if GUILD_EMOJI_FILE.exists():
        try:
            emojis_json = json.loads(GUILD_EMOJI_FILE.read_text(encoding="utf-8"))
            for e in emojis_json:
                name = e.get("name", "")
                eid  = e.get("id", "")
                anim = e.get("animated", False)
                if name and eid:
                    prefix = "a" if anim else ""
                    emoji_map[name.lower()] = f"<{prefix}:{name}:{eid}>"
        except Exception as err:
            print(f"Failed to load guild_emojis.json: {err}")

    if guild and getattr(guild, "emojis", None):
        for e in guild.emojis:
            if getattr(e, "available", True):
                prefix = "a" if getattr(e, "animated", False) else ""
                emoji_map[e.name.lower()] = f"<{prefix}:{e.name}:{e.id}>"

    return emoji_map


def build_emoji_block_from_file(guild: discord.Guild | None = None) -> str:
    """Build a :name: shortcode reference block for the LLM system prompt."""
    emoji_map = get_guild_emoji_map(guild)
    if not emoji_map:
        return ""

    descriptions: dict = {}
    if EMOJI_DESC_FILE.exists():
        try:
            descriptions = json.loads(EMOJI_DESC_FILE.read_text(encoding="utf-8"))
        except Exception:
            descriptions = {}

    lines = []
    for name_lower, code in emoji_map.items():
        match = re.search(r'<a?:([a-zA-Z0-9_]+):\d+>', code)
        display_name = match.group(1) if match else name_lower
        desc = descriptions.get(display_name, "") or descriptions.get(name_lower, "")
        shortcode = f":{display_name}:"
        if desc:
            lines.append(f"- {shortcode} — {desc}")
        else:
            lines.append(f"- {shortcode}")

    return "[Server Emoji — use shortcode format :name:]:\n" + "\n".join(lines)


def clean_bot_response_prefix(text: str) -> str:
    """Removes leading speaker/user prefixes like '[Gemma]:', 'Gemma:', 'Username (display_name):', or 'Analyzing...' if generated by the LLM."""
    if not text:
        return text
    text = re.sub(r'^\s*\[Gemma(?:\s*\([^)]*\))?\]:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*Gemma:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*(?:\[?[A-Za-z0-9_\-]+\s*\([^)]*\)(?:\s+speaking\s+directly\s+to\s+Gemma)?\]?)\s*:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*Analyzing[…\.:]+\s*', '', text, flags=re.IGNORECASE)
    return text.strip()


def format_discord_emojis(text: str, guild: discord.Guild | None = None) -> str:
    """Post-processor that repairs malformed custom emoji tags and converts valid :shortcodes: or <emoji:...> into real Discord tags."""
    if not text:
        return text

    text = clean_bot_response_prefix(text)
    emoji_map = get_guild_emoji_map(guild)

    descriptions = {}
    if EMOJI_DESC_FILE.exists():
        try:
            descriptions = json.loads(EMOJI_DESC_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    def resolve_name_or_desc(term: str) -> str | None:
        term_clean = term.strip().lower()
        term_alphanumeric = re.sub(r'[^a-zA-Z0-9_]', '', term_clean)

        # 1. Exact match on server custom emoji name
        if term_alphanumeric in emoji_map:
            return emoji_map[term_alphanumeric]

        # 2. Check if term matches description of a server custom emoji
        if descriptions and emoji_map:
            for name_lower, code in emoji_map.items():
                match = re.search(r'<a?:([a-zA-Z0-9_]+):\d+>', code)
                display_name = match.group(1) if match else name_lower
                desc = descriptions.get(display_name, "").lower()
                if desc and (term_clean in desc or desc in term_clean):
                    return code

        # 3. Check standard fallback map
        if term_clean in STANDARD_EMOJI_DESC_MAP:
            return STANDARD_EMOJI_DESC_MAP[term_clean]
        if term_alphanumeric in STANDARD_EMOJI_DESC_MAP:
            return STANDARD_EMOJI_DESC_MAP[term_alphanumeric]

        return None

    def replace_emoji_match(match: re.Match) -> str:
        # Group 1: <emoji:description or name>
        if match.group(1):
            resolved = resolve_name_or_desc(match.group(1))
            return resolved if resolved else match.group(0)

        # Group 2: existing custom tag like <:name:id> or <a:name:id>
        if match.group(2):
            tag = match.group(2)
            m = re.search(r'<a?:([a-zA-Z0-9_]+):?\d*>', tag)
            if m:
                resolved = resolve_name_or_desc(m.group(1))
                if resolved:
                    return resolved
            return tag

        # Group 3: bare shortcode like :name:
        if match.group(3):
            resolved = resolve_name_or_desc(match.group(3))
            return resolved if resolved else match.group(0)

        return match.group(0)

    pattern = r'<emoji:([^>]+)>|(<a?:[a-zA-Z0-9_]+:?\d*>)|:([a-zA-Z0-9_]{2,}):'
    return re.sub(pattern, replace_emoji_match, text)

MAX_HISTORY_PAIRS  = 20
CONTEXT_MESSAGES   = int(os.environ.get("CONTEXT_MESSAGES", "25"))
AUTO_RESPONSE_THRESHOLD = 25
AUTO_EVALUATE_SILENCE_MINUTES = 2
DISCORD_MAX_LEN    = 1900

# Visual image records and passive background viewer tracking
visual_records_by_message: dict[int, list[dict]] = defaultdict(list)
channel_visual_records: dict[int, list[dict]] = defaultdict(list)
active_passive_view_tasks: dict[int, asyncio.Task] = {}
AUTO_IDLE_REPLY_HOURS = float(os.environ.get("AUTO_IDLE_REPLY_HOURS", "1"))
AUTO_IDLE_CHECK_SECONDS = int(os.environ.get("AUTO_IDLE_CHECK_SECONDS", "60"))
AUTO_IDLE_CHANNEL_IDS = {
    int(channel_id.strip())
    for channel_id in os.environ.get("AUTO_IDLE_CHANNEL_IDS", "").split(",")
    if channel_id.strip().isdigit()
}
AUTO_IDLE_CHANNEL_NAMES = {
    name.strip().lower()
    for name in os.environ.get("AUTO_IDLE_CHANNEL_NAMES", "general").split(",")
    if name.strip()
}
MEMORY_FILE = Path(os.environ.get("MEMORY_FILE", "general_memory.json"))
MEMORY_LOOKBACK_DAYS = int(os.environ.get("MEMORY_LOOKBACK_DAYS", "365"))
PROMPT_LOG_FILE = Path(os.environ.get("PROMPT_LOG_FILE", "prompts.log"))
MEMORY_CHUNK_DAYS = int(os.environ.get("MEMORY_CHUNK_DAYS", "30"))
MEMORY_REFRESH_HOURS = float(os.environ.get("MEMORY_REFRESH_HOURS", "24"))
MEMORY_MAX_CHARS = int(os.environ.get("MEMORY_MAX_CHARS", "12000"))
MEMORY_CHANNEL_NAMES = {
    name.strip().lower()
    for name in os.environ.get("MEMORY_CHANNEL_NAMES", "general").split(",")
    if name.strip()
}

LIVE_LOG_CHANNEL_NAME = os.environ.get("LIVE_LOG_CHANNEL_NAME", "live-bot-log").strip().lstrip("#").lower()
LIVE_LOG_CHANNEL_ID = int(os.environ.get("LIVE_LOG_CHANNEL_ID", "0")) if os.environ.get("LIVE_LOG_CHANNEL_ID", "").isdigit() else None
LIVE_LOG_FILE = Path(os.environ.get("LIVE_LOG_FILE", Path(__file__).resolve().parent / "bot.log"))

# ── Bot setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY_PAIRS * 2))
last_prompt_payload: dict[int, list[dict]] = {}
messages_since_last_bot_message: dict[int, int] = defaultdict(int)
messages_since_last_bot_reaction: dict[int, int] = defaultdict(int)
last_bot_reaction_time: dict[int, datetime] = {}
idle_replied_message_ids: set[int] = set()
text_evaluation_evaluated_message_ids: set[int] = set()
idle_watcher_task: asyncio.Task | None = None
memory_task: asyncio.Task | None = None
log_streamer_task: asyncio.Task | None = None
memory_lock = asyncio.Lock()
bot_timeout_until: datetime | None = None


def is_bot_timed_out() -> bool:
    global bot_timeout_until
    if bot_timeout_until is None:
        return False
    if discord.utils.utcnow() >= bot_timeout_until:
        bot_timeout_until = None
        return False
    return True


async def handle_timeout_text_command(message: discord.Message) -> bool:
    global bot_timeout_until
    content = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    lowered = content.lower()

    if lowered.startswith("!untimeout") or lowered == "untimeout" or "untimeout" in lowered:
        if not is_bot_timed_out():
            await message.reply("ℹ️ Bot is not currently in time out.")
        else:
            bot_timeout_until = None
            await message.reply("⏰ Time out removed! Bot is active again.")
        return True

    if lowered.startswith("!timeout") or lowered == "timeout" or "timeout" in lowered:
        parts = content.split()
        minutes = 30
        for part in parts:
            if part.isdigit():
                minutes = int(part)
                break
            elif part.lower() in ("0", "off", "clear", "cancel"):
                minutes = 0
                break

        if minutes <= 0:
            bot_timeout_until = None
            await message.reply("⏰ Time out cleared! Bot is active.")
        else:
            bot_timeout_until = discord.utils.utcnow() + timedelta(minutes=minutes)
            ts = int(bot_timeout_until.timestamp())
            await message.reply(f"🤫 Bot is now in time out for **{minutes}** minute(s) (until <t:{ts}:t>, <t:{ts}:R>).")
        return True

    return False


def can_bot_react(channel_id: int) -> bool:
    # Cooldown of at least 50 messages
    if messages_since_last_bot_reaction[channel_id] < 50:
        return False
    # Cooldown of at least 15 minutes
    last_time = last_bot_reaction_time.get(channel_id)
    if last_time:
        elapsed = discord.utils.utcnow() - last_time
        if elapsed < timedelta(minutes=15):
            return False
    return True


def process_image_bytes(data: bytes) -> str | None:
    """Decodes raw image bytes with PIL, converts to standard RGB JPEG, resizes if huge, and returns clean base64 string."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = img.convert("RGB")
            img.thumbnail((1536, 1536))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"Failed to process image with PIL: {e}")
        return None


def get_media_mime_type(attachment: discord.Attachment) -> tuple[str | None, str]:
    """Returns (mime_type, media_category) where category is 'image', 'video', or 'none'."""
    ct = (attachment.content_type or "").lower()
    fn = (attachment.filename or "").lower()

    if ct.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic")):
        if "png" in ct or fn.endswith(".png"):
            return "image/png", "image"
        if "webp" in ct or fn.endswith(".webp"):
            return "image/webp", "image"
        if "gif" in ct or fn.endswith(".gif"):
            return "image/gif", "image"
        return "image/jpeg", "image"

    if ct.startswith("video/") or fn.endswith((".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi")):
        if "webm" in ct or fn.endswith(".webm"):
            return "video/webm", "video"
        if "quicktime" in ct or fn.endswith(".mov"):
            return "video/quicktime", "video"
        if "x-m4v" in ct or fn.endswith(".m4v"):
            return "video/x-m4v", "video"
        return "video/mp4", "video"

    return None, "none"


IMAGE_URL_PATTERN = re.compile(r'(https?://\S+\.(?:png|jpg|jpeg|webp|gif|heic)(?:\?\S*)?)', re.IGNORECASE)
VIDEO_URL_PATTERN = re.compile(r'(https?://\S+\.(?:mp4|webm|mov|m4v|mkv)(?:\?\S*)?)', re.IGNORECASE)


async def parse_media_with_gemini(
    media_bytes: bytes,
    mime_type: str,
    prompt: str = "Describe what is shown or occurring in this media in detail, noting key subjects, actions, text, and context.",
    timeout: float = 60.0
) -> str | None:
    """Multimodal media parser using Gemini API (supports both video and images with zero local VRAM overhead)."""
    if not GEMINI_API_KEY:
        return None

    # Cap size at 25MB for inline base64 payload to prevent memory spikes
    if len(media_bytes) > 25 * 1024 * 1024:
        print(f"Media exceeds 25MB limit ({len(media_bytes)} bytes), skipping multimodal parse.")
        return None

    b64_data = base64.b64encode(media_bytes).decode("utf-8")
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": b64_data
                        }
                    }
                ]
            }
        ]
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(p.get("text", "") for p in parts).strip()
                        if text:
                            return text
                else:
                    print(f"Gemini media parse error ({model}) {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                print(f"Error querying Gemini media parse ({model}): {e}")
    return None


# ── Visual Records & Passive Image Viewing ─────────────────────────────────────

async def parse_image_with_ollama(b64_image: str, prompt: str = "Describe what is shown in this picture in detail.") -> str | None:
    """Fallback vision parser using local Ollama model with image input."""
    try:
        messages = [
            {
                "role": "user",
                "content": prompt,
                "images": [b64_image]
            }
        ]
        return await query_ollama_raw(messages, timeout=60.0, options={"temperature": 0.2})
    except Exception as e:
        print(f"Ollama vision parse error: {e}")
        return None


async def analyze_and_describe_image(
    img_bytes: bytes,
    mime_type: str,
    filename: str,
    context_hint: str = ""
) -> str | None:
    """Analyzes an image using Gemini multimodal if available, with Ollama vision fallback."""
    prompt = (
        f"Describe what is shown in this picture ({filename}) in detail (key subjects, text, objects, colors, atmosphere)."
        + (f" Context: '{context_hint}'" if context_hint else "")
    )
    if GEMINI_API_KEY:
        res = await parse_media_with_gemini(img_bytes, mime_type, prompt=prompt)
        if res:
            return res

    b64_str = process_image_bytes(img_bytes)
    if b64_str:
        res = await parse_image_with_ollama(b64_str, prompt=prompt)
        if res:
            return res

    return None


def create_named_visual_record(
    filename: str,
    author_name: str,
    message: discord.Message | discord.Interaction,
    description: str,
    b64_image: str | None = None
) -> dict:
    """Names a visual record and stores it in context data structures."""
    msg_id = getattr(message, "id", 0)
    created_at = getattr(message, "created_at", None) or discord.utils.utcnow()
    timestamp_str = created_at.strftime("%I:%M %p")
    channel_id = getattr(message, "channel_id", None) or (message.channel.id if hasattr(message, "channel") and message.channel else 0)
    clean_fn = Path(filename).name if filename else "image"
    record_name = f"Visual Record ({clean_fn} by {author_name})"
    record = {
        "record_name": record_name,
        "filename": clean_fn,
        "author": author_name,
        "message_id": msg_id,
        "channel_id": channel_id,
        "timestamp": timestamp_str,
        "description": description.strip(),
        "b64_image": b64_image,
        "created_at": created_at
    }

    # Store in per-message records
    if msg_id:
        visual_records_by_message[msg_id].append(record)

    # Store in per-channel records (ordered most recent first, max 50)
    if channel_id:
        ch_records = channel_visual_records[channel_id]
        ch_records.insert(0, record)
        if len(ch_records) > 50:
            channel_visual_records[channel_id] = ch_records[:50]

    return record


async def cancel_passive_image_viewing(channel_id: int, reason: str = "pertinent trigger"):
    """Cancels any running passive image viewing task in the specified channel to prioritize a pertinent action."""
    task = active_passive_view_tasks.get(channel_id)
    if task and not task.done():
        print(f"🛑 [Passive Image Viewing] Cancelling background task in channel {channel_id} due to {reason}!")
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    active_passive_view_tasks.pop(channel_id, None)


async def passive_image_viewer(message: discord.Message):
    """Passively views images in a non-trigger message in the background.
    Sends all pictures through ordered from most recent to oldest,
    and names a visual record for each that can be provided in context of 25 messages.
    If a trigger arrives, this task is cancelled immediately to perform the more pertinent action."""
    channel = message.channel
    author_name = f"{message.author.display_name} ({message.author.name})"
    ch_name = getattr(channel, "name", "DM")

    try:
        # Sort attachments from MOST RECENT TO OLDEST (higher attachment ID = uploaded later)
        media_attachments = [
            a for a in message.attachments
            if get_media_mime_type(a)[1] in ("image", "video")
        ]
        media_attachments.sort(key=lambda a: a.id, reverse=True)

        # Image URLs in content (most recent to oldest)
        image_urls = list(reversed(IMAGE_URL_PATTERN.findall(message.content)))

        if not media_attachments and not image_urls:
            return

        print(f"👁️ [Passive Image Viewing] Viewing {len(media_attachments) + len(image_urls)} picture(s) in #{ch_name} from {author_name} (most recent to oldest)...")

        # 1. Process attachments from most recent to oldest
        for attachment in media_attachments:
            await asyncio.sleep(0.05)
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()

            mime_type, media_cat = get_media_mime_type(attachment)
            if media_cat == "image":
                try:
                    img_bytes = await attachment.read()
                    b64_str = process_image_bytes(img_bytes)
                    desc = await analyze_and_describe_image(
                        img_bytes, mime_type, attachment.filename, context_hint=message.content
                    )
                    if desc:
                        rec = create_named_visual_record(
                            attachment.filename, author_name, message, desc, b64_image=b64_str
                        )
                        print(f"📷 [Passive Image Viewing] Named {rec['record_name']}: {desc[:80]}...")
                        try:
                            emb = await rag_store.embed_text(desc[:1000])
                            if emb:
                                rag_store.add_chunk(
                                    content=f"[{rec['record_name']}]: {desc}",
                                    embedding=emb,
                                    source="passive_image_view",
                                    channel_id=channel.id,
                                    author=author_name
                                )
                        except Exception as e:
                            print(f"Failed to index passive visual record in RAG: {e}")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"Error in passive image view for {attachment.filename}: {e}")

            elif media_cat == "video" and GEMINI_API_KEY:
                try:
                    vid_bytes = await attachment.read()
                    desc = await parse_media_with_gemini(
                        vid_bytes, mime_type,
                        prompt=f"Describe what happens in this video clip ({attachment.filename}) in detail."
                    )
                    if desc:
                        rec = create_named_visual_record(
                            attachment.filename, author_name, message, desc
                        )
                        print(f"🎥 [Passive Image Viewing] Named {rec['record_name']}: {desc[:80]}...")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"Error in passive video view for {attachment.filename}: {e}")

        # 2. Process image URLs from most recent to oldest
        for url in image_urls:
            await asyncio.sleep(0.05)
            if asyncio.current_task().cancelled():
                raise asyncio.CancelledError()

            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=10.0)
                    if resp.status_code == 200:
                        ext = url.split("?")[0].split(".")[-1].lower()
                        mime = f"image/{ext}" if ext in ["png", "webp", "gif"] else "image/jpeg"
                        fn = url.split("/")[-1].split("?")[0] or "web_image.jpg"
                        b64_str = process_image_bytes(resp.content)
                        desc = await analyze_and_describe_image(
                            resp.content, mime, fn, context_hint=message.content
                        )
                        if desc:
                            rec = create_named_visual_record(
                                fn, author_name, message, desc, b64_image=b64_str
                            )
                            print(f"🌐 [Passive Image Viewing] Named {rec['record_name']}: {desc[:80]}...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"Error in passive view of {url}: {e}")

        print(f"✅ [Passive Image Viewing] Finished in #{ch_name} for message {message.id}")

    except asyncio.CancelledError:
        print(f"🛑 [Passive Image Viewing] Cancelled in #{ch_name} for message {message.id} to yield to pertinent action.")
        raise
    finally:
        active_passive_view_tasks.pop(channel.id, None)


# ── Helpers ────────────────────────────────────────────────────────────────────

async def get_channel_context(channel, before=None, limit: int | None = None) -> str:
    """Builds channel context from the last N messages (default 25), including named visual records."""
    limit = limit or CONTEXT_MESSAGES
    lines = []
    recent_visual_records: list[dict] = []

    async for msg in channel.history(limit=limit, before=before):
        content = msg.content.strip()

        # Check for named visual records associated with this message
        msg_records = visual_records_by_message.get(msg.id, [])
        record_tags = []
        for r in msg_records:
            record_tags.append(f"[{r['record_name']}: {r['description']}]")
            recent_visual_records.append(r)

        # Fallback tags if attachments exist but have not been fully described yet
        if not msg_records and msg.attachments:
            for a in msg.attachments:
                mime_type, media_cat = get_media_mime_type(a)
                if media_cat in ("image", "video"):
                    record_tags.append(f"[Attached {media_cat}: {a.filename}]")

        if record_tags:
            content = f"{content} {' '.join(record_tags)}".strip()

        if not content:
            continue

        # Filter out any error strings, temporary malfunction messages, or broken bot responses from context
        if "Error talking to Ollama" in content or "temporary malfunction" in content or "Couldn't reach Ollama" in content:
            continue

        if msg.author == channel.guild.me or msg.author.bot:
            if content.endswith(("…", "...", "That's a concerning", "That’s a… concerning")):
                continue
            cleaned_lines = [l for l in content.splitlines() if l.strip()]
            if cleaned_lines:
                last_line = cleaned_lines[-1].strip()
                if not last_line.endswith((".", "!", "?", "😊", "✨", "```", ")", "'", '"', ">")):
                    continue  # skip truncated bot response from history context

        author = f"{msg.author.display_name} ({msg.author.name})"
        lines.append(f"{author}: {content}")

    if not lines:
        return ""
    lines.reverse()

    context_body = "\n".join(lines)

    # Provide a dedicated named visual records block for the context of 25 messages
    # Ordered MOST RECENT TO OLDEST
    if recent_visual_records:
        recent_visual_records.sort(key=lambda r: r.get("message_id", 0), reverse=True)
        seen_names = set()
        record_lines = []
        for r in recent_visual_records:
            name = r.get("record_name")
            if name and name not in seen_names:
                seen_names.add(name)
                record_lines.append(
                    f"• {name} (sent {r.get('timestamp', 'recently')}): {r.get('description', '')}"
                )
        if record_lines:
            records_block = (
                f"[Named Visual Records in Recent {limit} Messages (Most Recent to Oldest)]:\n"
                + "\n".join(record_lines)
                + "\n\n"
            )
            return records_block + context_body

    return context_body


def load_memory() -> dict:
    try:
        return json.loads(MEMORY_FILE.read_text())
    except Exception:
        return {"version": 1, "channels": {}}


def save_memory(memory: dict):
    MEMORY_FILE.write_text(json.dumps(memory, indent=2, sort_keys=True))


def _build_budgeted_memory_context(overall: str, chunks: list, generated_at: str, max_chars: int) -> str:
    """Builds a memory block capped at ~max_chars, balanced between long-term consolidated memory and recent chunks."""
    header = "Here is the long-term compressed memory database for this channel:\n\n"
    sep = "\n\n---\n\n"
    net_budget = max_chars - len(header)
    if net_budget <= 0:
        return ""

    # Split target: 50% for recent chunks, 50% for long-term consolidated summary
    target_chunks = net_budget // 2
    target_overall = net_budget - target_chunks

    # 1. Select recent chunks newest-first
    selected_chunks = []
    chunk_budget = target_chunks
    for idx in range(len(chunks) - 1, -1, -1):
        chunk = chunks[idx]
        summary = chunk.get("summary", "").strip()
        if not summary:
            continue
        start_dt = datetime.fromisoformat(chunk["start"]).date()
        end_dt = datetime.fromisoformat(chunk["end"]).date()
        block = f"**Chunk {idx+1} ({start_dt} to {end_dt}):**\n{summary}"
        cost = len(block) + len(sep)
        if cost <= chunk_budget:
            selected_chunks.append(block)
            chunk_budget -= cost
        else:
            if not selected_chunks:
                # If even the newest chunk alone exceeds budget, take its recent portion
                keep = max(0, chunk_budget - len(sep) - 80)
                if keep > 200:
                    selected_chunks.append(f"**Chunk {idx+1} ({start_dt} to {end_dt}, recent portion):**\n…{summary[-keep:]}")
                    chunk_budget = 0
            break

    # Leftover chunk budget transfers to overall summary
    overall_budget = target_overall + chunk_budget
    selected_chunks.reverse()

    parts = []
    # 2. Add Overall Summary (prioritizing Character Profiles & Core Lore from the beginning)
    if overall and overall_budget > 300:
        prefix = f"### Long-Term Consolidated Summary\nLast updated: {generated_at}\n\n"
        avail = overall_budget - len(prefix)
        if len(overall) <= avail:
            parts.append(prefix + overall)
        else:
            snippet = overall[:avail - 60]
            last_nl = snippet.rfind("\n")
            if last_nl == -1 or last_nl < len(snippet) // 2:
                last_dot = snippet.rfind(". ")
                if last_dot > len(snippet) // 2:
                    last_nl = last_dot + 1
            if last_nl > 200:
                snippet = snippet[:last_nl]
            parts.append(f"### Long-Term Consolidated Summary (core profiles & lore)\nLast updated: {generated_at}\n\n{snippet}\n\n… [additional historical lore condensed]")

    # 3. Add Recent Chunks (Chronological)
    if selected_chunks:
        chunks_header = "### Recent Memory Chunks (Chronological)"
        chunks_content = sep.join(selected_chunks)
        parts.append(f"{chunks_header}\n\n{chunks_content}")

    if not parts:
        return ""
    return header + sep.join(parts)


def get_channel_memory_context(channel_id: int, max_chars: int | None = None) -> str:
    memory = load_memory()
    channel_memory = memory.get("channels", {}).get(str(channel_id))
    if not channel_memory:
        return ""

    overall = channel_memory.get("overall_summary", "").strip()
    chunks = channel_memory.get("chunks", [])
    generated_at = channel_memory.get("generated_at", "unknown time")

    if max_chars is not None:
        return _build_budgeted_memory_context(overall, chunks, generated_at, max_chars)

    parts = []
    if overall:
        parts.append(
            "### Long-Term Consolidated Summary\n"
            f"Last updated: {generated_at}\n\n"
            f"{overall}"
        )

    if chunks:
        parts.append("### Detailed Monthly Memory Chunks (Chronological)")
        for idx, chunk in enumerate(chunks):
            start_dt = datetime.fromisoformat(chunk["start"]).date()
            end_dt = datetime.fromisoformat(chunk["end"]).date()
            summary = chunk.get("summary", "").strip()
            parts.append(
                f"**Chunk {idx+1} ({start_dt} to {end_dt}):**\n"
                f"{summary}"
            )

    if not parts:
        return ""

    return (
        "Here is the long-term compressed memory database for this channel:\n\n"
        + "\n\n---\n\n".join(parts)
    )


async def query_ollama_raw(messages: list[dict], timeout: float = 300.0, options: dict | None = None) -> str:
    default_opts = {"num_ctx": CHAT_OPTIONS.get("num_ctx", 24576), "num_predict": 180}
    if options:
        default_opts.update(options)
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": os.environ.get("OLLAMA_THINK", "false").lower() == "true",
        "options": default_opts,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        )
        if not resp.is_success:
            print(f"Ollama error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()


async def search_gemini_rag(query: str) -> str | None:
    """Perform real-time grounded search using Google AI Studio Gemini API with Google Search Grounding."""
    if not GEMINI_API_KEY:
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"Provide the exact, current, up-to-date facts, weather conditions, or real-time details for: {query}"}
                ]
            }
        ],
        "tools": [
            {"google_search": {}}
        ]
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        candidate = candidates[0]
                        parts = candidate.get("content", {}).get("parts", [])
                        text = "".join(p.get("text", "") for p in parts).strip()
                        
                        sources = []
                        g_meta = candidate.get("groundingMetadata", {})
                        chunks = g_meta.get("groundingChunks", [])
                        for chunk in chunks[:3]:
                            web = chunk.get("web", {})
                            title = web.get("title", "")
                            uri = web.get("uri", "")
                            if title and uri:
                                sources.append(f"- [{title}]({uri})")
                                
                        if text:
                            res = f"Google Grounded Search Results for \"{query}\":\n{text}"
                            if sources:
                                res += "\n\nSources:\n" + "\n".join(sources)
                            return res
                else:
                    print(f"Gemini API Search error ({model}) {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                print(f"Error querying Gemini API Search Grounding ({model}): {e}")
    return None


async def search_duckduckgo(query: str) -> str:
    # 1. Specialized weather provider if weather/temperature query
    query_lower = query.lower()
    if any(k in query_lower for k in ["weather", "temperature", "forecast", "rain", "snow", "degrees"]):
        try:
            # Clean location string by stripping common query fluff
            loc = re.sub(r'(?i)\b(current|today|forecast|what|is|the|weather|temperature|in|for|at|like|how|s)\b', '', query).strip()
            if not loc:
                loc = "Oklahoma City"

            url = f"https://wttr.in/{urllib.parse.quote(loc)}?format=%l:+%C,+%t+(feels+like+%f),+Humidity:+%h,+Wind:+%w"
            headers = {"User-Agent": "curl/7.68.0"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                if resp.status_code == 200 and resp.text.strip() and "Unknown location" not in resp.text:
                    return f"Current Weather Data for {loc}:\n{resp.text.strip()}"
        except Exception as e:
            print(f"Weather lookup error: {e}")

    # 2. DuckDuckGo Instant Answer JSON API
    try:
        api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, headers=headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText", "").strip()
                heading = data.get("Heading", "").strip()
                if abstract:
                    return f"1. {heading}\n   Snippet: {abstract}"
    except Exception:
        pass

    # 3. DuckDuckGo Lite POST scraper
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    data = {"q": query, "kl": "us-en"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, data=data, timeout=8.0)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                results = []
                links = soup.find_all("a", class_="result-link")
                snippets = soup.find_all("td", class_="result-snippet")
                for i, link in enumerate(links[:3]):
                    title = link.get_text(strip=True)
                    href = link.get("href", "")
                    snippet = snippets[i].get_text(strip=True) if i < len(snippets) else ""
                    results.append(f"{i+1}. {title}\n   Link: {href}\n   Snippet: {snippet}")
                if results:
                    return "\n\n".join(results)
    except Exception as e:
        print(f"Error during search: {e}")

    return "No search results found."


async def perform_web_search(query: str) -> tuple[str, str]:
    """Unified search entry point. Uses Google Gemini API Search Grounding if GEMINI_API_KEY is available, else DuckDuckGo/wttr.in."""
    if GEMINI_API_KEY:
        print(f"Performing Google AI Studio Gemini RAG Search for: '{query}'")
        g_results = await search_gemini_rag(query)
        if g_results:
            return ("Google Gemini AI Studio RAG", g_results)
        print("Gemini API RAG search returned no results, falling back to DuckDuckGo/wttr.in...")

    print(f"Performing DuckDuckGo/wttr.in search for: '{query}'")
    ddg_results = await search_duckduckgo(query)
    return ("DuckDuckGo", ddg_results)



async def analyze_prompt_for_search(user_message: str, context: str = "") -> str | None:
    """Lean prompt analysis to determine if a message should trigger a web search."""
    clean_text = re.sub(r'^\s*\[[^\]]+\]:\s*', '', user_message).strip()
    if not clean_text or len(clean_text) < 3:
        return None

    # Fast bypass for time/date questions — live system clock in system prompt handles this directly
    clean_lower = clean_text.lower()
    time_date_phrases = [
        "what time", "what's the time", "current time", "tell me what time", "tell me the time",
        "what date", "what's the date", "current date", "today's date", "tell me the date",
        "what day is today", "what day is it", "what year", "what month",
    ]
    if any(p in clean_lower for p in time_date_phrases):
        return None

    # Keep context snippet lean (last 2 non-empty lines max if context provided)
    context_snippet = ""
    if context:
        lines = [line.strip() for line in context.splitlines() if line.strip()]
        if lines:
            context_snippet = "Recent context:\n" + "\n".join(lines[-2:]) + "\n\n"

    eval_messages = [
        {
            "role": "system",
            "content": (
                "You are a search query decision engine. Your goal is to determine if answering the user message "
                "requires or would benefit from up-to-date facts, external information, definitions, web search, "
                "media/game details, technical documentation, news, dates, locations, science, or real-world knowledge.\n\n"
                "CRITICAL INSTRUCTION: Be AGGRESSIVE in triggering web searches. If the user message asks a question or mentions "
                "any real-world topic, person, place, event, code, error message, game, movie, book, product, software, "
                "scientific concept, or fact, ALWAYS trigger a search. When in doubt, trigger a search!\n\n"
                "SERVER MEMBERS EXCLUSION: " + (f"Community members include {os.environ.get('COMMUNITY_MEMBERS', '').strip()}. " if os.environ.get('COMMUNITY_MEMBERS') else "") +
                "NEVER search the web for server members, their gender, personal identities, or internal community discussions. "
                "Return NONE for messages about server members.\n\n"
                "Only return NONE if the message is purely conversational social chatter, greetings, simple emotional banter, or personal chit-chat "
                "(e.g., 'hello', 'lol', 'thanks', 'how are you', 'I agree', 'cool').\n\n"
                "If a search is recommended, respond with ONLY: SEARCH: <concise search query>\n"
                "If NO search is needed, respond with ONLY: NONE\n"
                "Output nothing else."
            ),
        },
        {"role": "user", "content": f"{context_snippet}User Message: {clean_text}"},
    ]

    try:
        eval_reply = await query_ollama_raw(eval_messages, timeout=45.0, options={"temperature": 0.0})
        eval_reply = eval_reply.strip()
        print(f"Lean prompt search evaluation: '{eval_reply}'")
        if eval_reply.upper().startswith("SEARCH:"):
            query = re.sub(r'^\s*SEARCH:\s*', '', eval_reply, flags=re.IGNORECASE).strip(' "`\'.-')
            # Filter out hallucinated date queries and server member searches
            if query and query.upper() != "NONE" and not any(h in query.lower() for h in ["july 5", "july 5 2026"]):
                member_terms = ["kai character", "kai baby", "kai gender", "kai transphobia", "kai orion8605", "kai gemmabot"]
                if any(m in query.lower() for m in member_terms):
                    return None
                return query
    except Exception as e:
        print(f"Error during lean prompt search analysis: {type(e).__name__}: {e}")
    return None


def format_err(err: Exception) -> str:
    msg = str(err).strip()
    name = type(err).__name__
    return f"{name}: {msg}".rstrip(": ") if msg else name


async def query_ollama(
    channel_id: int,
    user_message: str,
    context: str = "",
    images: list[str] | None = None,
    media_descriptions: list[str] | None = None,
    author_name: str | None = None,
    is_tagged: bool = False,
    is_reply: bool = False,
    guild: discord.Guild | None = None,
    is_idle_check: bool = False
) -> str:
    hist = history[channel_id]

    # Initial lean prompt analysis for DuckDuckGo search (skip during automated background idle checks)
    search_query = None
    if not is_idle_check:
        search_query = await analyze_prompt_for_search(user_message, context)

    prefix = ""
    if author_name:
        if is_tagged:
            prefix = f"[{author_name} speaking directly to Gemma]: "
        elif is_reply:
            prefix = f"[{author_name} replying directly to Gemma's message]: "
        else:
            prefix = f"[{author_name}]: "

    formatted_message = prefix + user_message

    has_media = bool(images or media_descriptions)
    if has_media:
        tags = []
        if images:
            tags.append(f"{len(images)} image(s)")
        if media_descriptions:
            tags.append(f"{len(media_descriptions)} media analysis")
        hist.append({"role": "user", "content": formatted_message + f" [{', '.join(tags)} attached]"})
    else:
        hist.append({"role": "user", "content": formatted_message})

    now_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    print(f"System date/time initialized for prompt: {now_str}")

    # Build background context blocks first so reference data comes before personality instructions
    context_blocks = []

    # Visual & Video media analysis parsed upstream (Gemini multimodal parser)
    if media_descriptions:
        context_blocks.append(
            "[Visual & Video Media Analysis (Parsed Upstream)]:\n"
            + "\n\n".join(media_descriptions)
            + "\n\nUse the visual media analysis above to understand what is depicted/happening in the attached picture(s) or video(s) and converse about it naturally in your own persona."
        )

        # Index parsed media descriptions into RAG vector memory so Gemma remembers them
        if not is_idle_check:
            for md in media_descriptions:
                try:
                    emb = await rag_store.embed_text(md[:1000])
                    if emb:
                        rag_store.add_chunk(
                            content=md,
                            embedding=emb,
                            source="media_upload",
                            channel_id=channel_id,
                            author=author_name or "User"
                        )
                except Exception as e:
                    print(f"Failed to index media analysis in RAG: {e}")

    memory_context = get_channel_memory_context(
        channel_id, max_chars=IMAGE_MEMORY_MAX_CHARS if has_media else TEXT_MEMORY_MAX_CHARS
    )
    if memory_context:
        context_blocks.append(memory_context)

    emoji_block = build_emoji_block_from_file(guild)
    if emoji_block:
        context_blocks.append(emoji_block)

    if search_query:
        search_engine_name, search_results = await perform_web_search(search_query)
        print(f"{search_engine_name} search results retrieved:\n{search_results}")
        context_blocks.append(
            f"[{search_engine_name} Live Search Context for \"{search_query}\"]:\n"
            f"{search_results}\n\n"
            "Use these live search results to provide a highly accurate, grounded, up-to-date response. "
            "Base your factual statements strictly on the retrieved search results to prevent hallucinations. "
            "Cite details from the search results if helpful, but keep the response extremely brief (1-3 sentences max)."
        )

    # RAG Vector Semantic Retrieval
    if not is_idle_check and user_message:
        try:
            q_emb = await rag_store.embed_text(user_message)
            if q_emb:
                rag_matches = rag_store.query_rag(q_emb, top_k=3, channel_id=channel_id)
                high_score_matches = [m for m in rag_matches if m.get("score", 0) >= 0.35]
                if high_score_matches:
                    print(f"RAG Vector Store: Retrieved {len(high_score_matches)} semantically relevant passage(s) (top score: {high_score_matches[0]['score']:.2f})")
                    rag_snippets = []
                    for m in high_score_matches:
                        rag_snippets.append(f"• [{m['source']}] (relevance: {m['score']:.2f}):\n{m['content']}")
                    context_blocks.append(
                        "[Semantically Retrieved Vector Memory & Knowledge (RAG)]:\n"
                        + "\n\n".join(rag_snippets)
                        + "\n\nUse the retrieved vector memory above to accurately answer questions about past server history, user details, or indexed documents."
                    )
        except Exception as e:
            print(f"RAG retrieval error: {e}")

    if context:
        # If media is present, trim channel context to keep text tokens lean
        if has_media and len(context) > 1000:
            context = context[-1000:]
        context_blocks.append(
            "Here are the last messages from this channel so you have context "
            "for what's been discussed:\n\n"
            + context
        )

    # Place date/time and background context first, then place SYSTEM_PROMPT (personality) at the end of the system message
    system_parts = [f"[Current Live Date & Time: {now_str}]"]
    if context_blocks:
        system_parts.extend(context_blocks)
    system_parts.append(f"[Core Personality & Instructions]:\n{SYSTEM_PROMPT}")
    system = "\n\n".join(system_parts)

    # Minimal fallback system prompt (no memory/search/RAG) for context-overflow retries
    lean_parts = [f"[Current Live Date & Time: {now_str}]"]
    if emoji_block:
        lean_parts.append(emoji_block)
    lean_parts.append(f"[Core Personality & Instructions]:\n{SYSTEM_PROMPT}")
    lean_system = "\n\n".join(lean_parts)

    # Sanitize in-memory history to filter out any truncated or error turns
    clean_hist = []
    for msg in hist:
        c = msg.get("content", "").strip()
        if "Error talking to Ollama" in c or "temporary malfunction" in c or "Couldn't reach Ollama" in c:
            continue
        if msg.get("role") == "assistant":
            if c and not c.endswith((".", "!", "?", "😊", "✨", "```", ")", "'", '"', ">")):
                continue
        clean_hist.append(msg)

    messages = [{"role": "system", "content": system}] + [dict(msg) for msg in clean_hist]
    if messages and messages[-1]["role"] == "user":
        live_anchor = f"\n\n[Live System Date & Time Anchor: {now_str}]"
        reminder = (
            f"{live_anchor}\n"
            "(REMINDER: Keep your reply STRICTLY SHORT and concise (1-3 sentences max). "
            "Do NOT write multi-paragraph responses or over-explain unless the user explicitly requested detail. "
            "Never prefix your message with any username or speaker tag. Act like a casual Discord user.)"
        )
        messages[-1]["content"] += reminder
        if images:
            # Ollama /api/chat native format: plain base64 array on the message object
            messages[-1]["images"] = images

    # Maintain a global reference of the last prompt payload for DMs (excluding base64 image strings to stay under character limit)
    global last_prompt_payload
    clean_messages = []
    for msg in messages:
        clean_msg = dict(msg)
        if "images" in clean_msg:
            clean_msg["images"] = [f"[Image data hidden: {len(img)} chars]" for img in clean_msg["images"]]
        clean_messages.append(clean_msg)
    last_prompt_payload[channel_id] = clean_messages

    # Log the payload to prompts.log
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "channel_id": channel_id,
            "messages": clean_messages
        }
        with open(PROMPT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Failed to write to prompts log: {e}")

    try:
        reply = await query_ollama_raw(messages, timeout=300.0, options=CHAT_OPTIONS)
    except httpx.ConnectError as e:
        print(f"query_ollama ConnectError: {type(e).__name__}: {e}")
        hist.pop()
        return (
            "⚠️ Couldn't reach Ollama. Make sure it's running:\n"
            "```\nollama serve\n```"
        )
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
        # Timeout — retry once with a pruned (system + last user message only) context
        print(f"query_ollama timeout ({type(e).__name__}), retrying with pruned context...")
        try:
            pruned_messages = [messages[0], messages[-1]]
            reply = await query_ollama_raw(pruned_messages, timeout=300.0, options=CHAT_OPTIONS)
        except Exception as retry_err:
            print(f"query_ollama retry also failed: {format_err(retry_err)}")
            hist.pop()
            return f"⚠️ Error talking to Ollama: {format_err(retry_err)}"
    except Exception as e:
        err_msg = str(e)
        print(f"query_ollama exception: {format_err(e)}")
        if "exceed" in err_msg.lower() or "400" in err_msg:
            print(f"Context size limit exceeded, retrying with lean system prompt (no memory) and last message only...")
            try:
                pruned_messages = [{"role": "system", "content": lean_system}, messages[-1]]
                reply = await query_ollama_raw(pruned_messages, timeout=300.0, options=CHAT_OPTIONS)
            except Exception as retry_err:
                print(f"query_ollama pruned retry failed: {format_err(retry_err)}")
                hist.pop()
                return f"⚠️ Error talking to Ollama: {format_err(retry_err)}"
        else:
            hist.pop()
            return f"⚠️ Error talking to Ollama: {format_err(e)}"

    # Post-process reply to guarantee valid Discord emoji tags
    formatted_reply = format_discord_emojis(reply, guild)

    # Log the response to prompts.log
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            "timestamp": timestamp,
            "channel_id": channel_id,
            "raw_response": reply,
            "formatted_response": formatted_reply
        }
        with open(PROMPT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Failed to write response to prompts log: {e}")

    hist.append({"role": "assistant", "content": formatted_reply})
    return formatted_reply


def format_message_for_memory(message: discord.Message) -> str:
    timestamp = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    content = message.content.strip()
    if not content:
        return ""
    return f"[{timestamp}] {message.author.display_name}: {content}"


def split_memory_lines(lines: list[str], max_chars: int = MEMORY_MAX_CHARS) -> list[str]:
    batches = []
    current = []
    current_chars = 0

    for line in lines:
        line_len = len(line) + 1
        if current and current_chars + line_len > max_chars:
            batches.append("\n".join(current))
            current = []
            current_chars = 0

        current.append(line)
        current_chars += line_len

    if current:
        batches.append("\n".join(current))

    return batches


async def summarize_memory_batch(existing_summary: str, batch_text: str, label: str) -> str:
    prompt = (
        "Compress this Discord #general history into durable memory for a bot.\n"
        "Preserve stable facts, recurring topics, relationships, preferences, inside jokes, "
        "open questions, decisions, and notable events. Ignore spam, greetings, and transient chatter.\n"
        "Write concise bullets grouped by theme. Do not invent details.\n\n"
        "CRITICAL INSTRUCTION: Do NOT write any introduction, conversational filler (e.g., 'Okay, here is the summary', 'Sure, let's break down this snippet'), "
        "meta-review, or evaluation of the input. Start directly with the first theme heading or bullet point. "
        "Write ONLY the compressed summary text itself.\n\n"
        f"Time window: {label}\n\n"
        f"Existing summary to update:\n{existing_summary or '(none)'}\n\n"
        f"Messages:\n{batch_text}"
    )
    return await query_ollama_raw(
        [
            {
                "role": "system",
                "content": (
                    "You are a state-compression engine. Output ONLY raw Markdown summaries grouped by theme, "
                    "with absolutely no intro, conversational filler, or outro."
                )
            },
            {"role": "user", "content": prompt},
        ],
        timeout=240.0,
        options={"temperature": 0.0, "num_ctx": 4096},
    )


async def summarize_chunk(lines: list[str], label: str) -> str:
    summary = ""
    for batch in split_memory_lines(lines):
        summary = await summarize_memory_batch(summary, batch, label)
    return summary.strip()


async def build_overall_summary(chunk_summaries: list[str], existing_summary: str = "") -> str:
    prompt = (
        "Merge these time-sliced #general summaries into one compact long-term memory.\n"
        "Keep facts useful for future replies: who people are, ongoing projects, preferences, "
        "community norms, unresolved threads, and recurring humor. Remove duplicates and stale one-off details.\n"
        "Use concise bullets grouped by theme.\n\n"
        "CRITICAL INSTRUCTION: Do NOT write any introduction, commentary, meta-review, or evaluation of the summaries. "
        "Do NOT say 'Here is the summary' or 'This is a fantastic summary!'. "
        "Start directly with the first theme heading or bullet point. Write ONLY the final summary text itself.\n\n"
        f"Previous overall summary:\n{existing_summary or '(none)'}\n\n"
        "Time-sliced summaries to merge:\n"
        + "\n\n".join(chunk_summaries)
    )
    return await query_ollama_raw(
        [
            {
                "role": "system",
                "content": (
                    "You are a database system that merges and outputs raw summaries. Output ONLY raw Markdown bullets "
                    "grouped by theme, with absolutely no intro, conversational filler, conversational response, or outro."
                )
            },
            {"role": "user", "content": prompt},
        ],
        timeout=240.0,
        options={"temperature": 0.0, "num_ctx": 4096},
    )


def should_summarize_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False

    if MEMORY_CHANNEL_NAMES and channel.name.lower() not in MEMORY_CHANNEL_NAMES:
        return False

    member = channel.guild.me
    if member is None:
        return False

    permissions = channel.permissions_for(member)
    return permissions.view_channel and permissions.read_message_history


async def fetch_memory_lines(channel: discord.TextChannel, after: datetime, before: datetime | None = None) -> list[str]:
    lines = []
    async for message in channel.history(after=after, before=before, oldest_first=True, limit=None):
        if message.author == bot.user:
            continue

        line = format_message_for_memory(message)
        if line:
            lines.append(line)

    return lines


async def backfill_channel_memory(channel: discord.TextChannel):
    async with memory_lock:
        memory = load_memory()
        channels = memory.setdefault("channels", {})
        channel_id = str(channel.id)
        existing = channels.get(channel_id, {})
        if existing.get("backfilled"):
            return

        print(f"Memory backfill starting for #{channel.name}")
        now = discord.utils.utcnow()
        start = now - timedelta(days=MEMORY_LOOKBACK_DAYS)
        chunks = []
        chunk_start = start

        while chunk_start < now:
            chunk_end = min(chunk_start + timedelta(days=MEMORY_CHUNK_DAYS), now)
            lines = await fetch_memory_lines(channel, after=chunk_start, before=chunk_end)
            label = f"{chunk_start.date()} to {chunk_end.date()}"

            if lines:
                print(f"Memory summarizing #{channel.name} {label}: {len(lines)} messages")
                summary = await summarize_chunk(lines, label)
                chunks.append(
                    {
                        "start": chunk_start.isoformat(),
                        "end": chunk_end.isoformat(),
                        "message_count": len(lines),
                        "summary": summary,
                    }
                )

            chunk_start = chunk_end

        chunk_summaries = [f"{chunk['start']} to {chunk['end']}:\n{chunk['summary']}" for chunk in chunks]
        overall_summary = await build_overall_summary(chunk_summaries, existing.get("overall_summary", ""))

        channels[channel_id] = {
            "guild_id": channel.guild.id,
            "guild_name": channel.guild.name,
            "channel_id": channel.id,
            "channel_name": channel.name,
            "generated_at": now.isoformat(),
            "backfilled": True,
            "lookback_days": MEMORY_LOOKBACK_DAYS,
            "chunk_days": MEMORY_CHUNK_DAYS,
            "last_refresh_at": now.isoformat(),
            "chunks": chunks,
            "overall_summary": overall_summary,
        }
        save_memory(memory)
        print(f"Memory backfill complete for #{channel.name}: {len(chunks)} chunks")


async def refresh_channel_memory(channel: discord.TextChannel):
    async with memory_lock:
        memory = load_memory()
        channel_memory = memory.get("channels", {}).get(str(channel.id))
        if not channel_memory or not channel_memory.get("backfilled"):
            return

        last_refresh = datetime.fromisoformat(channel_memory["last_refresh_at"])
        now = discord.utils.utcnow()
        if now - last_refresh < timedelta(hours=MEMORY_REFRESH_HOURS):
            return

        lines = await fetch_memory_lines(channel, after=last_refresh, before=now)
        channel_memory["last_refresh_at"] = now.isoformat()
        channel_memory["generated_at"] = now.isoformat()

        if lines:
            label = f"{last_refresh.date()} to {now.date()}"
            print(f"Memory refreshing #{channel.name} {label}: {len(lines)} messages")
            summary = await summarize_chunk(lines, label)
            channel_memory.setdefault("chunks", []).append(
                {
                    "start": last_refresh.isoformat(),
                    "end": now.isoformat(),
                    "message_count": len(lines),
                    "summary": summary,
                }
            )
            recent_summaries = [
                f"{chunk['start']} to {chunk['end']}:\n{chunk['summary']}"
                for chunk in channel_memory["chunks"][-12:]
            ]
            channel_memory["overall_summary"] = await build_overall_summary(
                recent_summaries,
                channel_memory.get("overall_summary", ""),
            )

        save_memory(memory)


async def memory_watcher():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if not should_summarize_channel(channel):
                    continue

                try:
                    await backfill_channel_memory(channel)
                    await refresh_channel_memory(channel)
                except Exception as e:
                    print(f"Memory update failed in #{channel}: {e}")

        await asyncio.sleep(3600)


def split_message(text: str, limit: int = DISCORD_MAX_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def should_monitor_channel(channel: discord.abc.GuildChannel) -> bool:
    if channel.name.lower() == LIVE_LOG_CHANNEL_NAME or (LIVE_LOG_CHANNEL_ID and channel.id == LIVE_LOG_CHANNEL_ID):
        return False

    if AUTO_IDLE_CHANNEL_IDS and channel.id not in AUTO_IDLE_CHANNEL_IDS:
        return False

    if not isinstance(channel, discord.TextChannel):
        return False

    if not AUTO_IDLE_CHANNEL_IDS and AUTO_IDLE_CHANNEL_NAMES and channel.name.lower() not in AUTO_IDLE_CHANNEL_NAMES:
        return False

    member = channel.guild.me
    if member is None:
        return False

    permissions = channel.permissions_for(member)
    return permissions.view_channel and permissions.read_message_history and permissions.send_messages


async def maybe_reply_to_idle_channel(channel: discord.TextChannel):
    if is_bot_timed_out():
        return

    async for last_message in channel.history(limit=1):
        break
    else:
        return

    if last_message.author == bot.user:
        return

    if last_message.id in idle_replied_message_ids:
        return

    idle_for = discord.utils.utcnow() - last_message.created_at
    if idle_for < timedelta(hours=AUTO_IDLE_REPLY_HOURS):
        return

    user_text = last_message.content.strip()
    if not user_text:
        return

    idle_replied_message_ids.add(last_message.id)
    author = last_message.author.display_name
    prompt = (
        f"The Discord channel has been quiet for over {AUTO_IDLE_REPLY_HOURS:g} hours. "
        f"Reply naturally to the most recent message from {author}: {user_text}"
    )

    async with channel.typing():
        context = await get_channel_context(channel)
        reply = await query_ollama(channel.id, prompt, context, author_name="System", guild=channel.guild)

    for chunk in split_message(reply):
        await channel.send(chunk)


def extract_emoji(text: str) -> str | None:
    text = text.strip().strip('"').strip("'").strip()
    if not text:
        return None
        
    # Check for custom emoji <:name:id> or <a:name:id>
    custom_match = re.search(r'<(a?):([a-zA-Z0-9_]+):([0-9]+)>', text)
    if custom_match:
        return custom_match.group(0)
        
    # Clean standard text, try to find any emoji.
    cleaned = re.sub(r'[a-zA-Z0-9\s\.,\-\!\?_:\(\)\[\]\{\}\'"/\\|#@\$%\^\&\*\+\=~`<>]+', '', text)
    if cleaned:
        return cleaned[:4].strip()
    
    if len(text) <= 5:
        return text
    return None


async def select_and_react(message: discord.Message, system_context: str):
    # Check if we already reacted to this message
    for reaction in message.reactions:
        if reaction.me:
            return  # Already reacted

    # Load emoji descriptions
    descriptions = {}
    try:
        desc_file = EMOJI_DESC_FILE
        if desc_file.exists():
            descriptions = json.loads(desc_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load emoji descriptions: {e}")

    emoji_lines = []
    for e in message.channel.guild.emojis:
        if not e.available:
            continue
        desc = descriptions.get(e.name, "")
        emoji_code = f"<:{e.name}:{e.id}>"
        if desc:
            emoji_lines.append(f"- {emoji_code} (Description: {desc})")
        else:
            emoji_lines.append(f"- {emoji_code} (Name/Theme: {e.name})")

    custom_emojis_block = "\n".join(emoji_lines)
    standard_emojis = ["👍", "❤️", "😂", "😮", "😢", "😡", "🔥", "🎉", "💯", "💀", "👀", "🤔", "✨"]
    standard_emojis_str = ", ".join(standard_emojis)

    if custom_emojis_block:
        emoji_choices_str = (
            "You must react using one of the custom server emojis from this list. Choose the one that best matches the tone, emotion, or context:\n"
            f"{custom_emojis_block}\n\n"
            f"If and ONLY if absolutely none of the server custom emojis fit the message context, you may fallback to a standard Unicode emoji (like: {standard_emojis_str})."
        )
    else:
        emoji_choices_str = f"Choose any standard Unicode emoji (like: {standard_emojis_str})."

    author_name = f"{message.author.display_name} ({message.author.name})"
    reaction_prompt = (
        f"The last message sent in this channel by {author_name} was:\n"
        f"\"{message.content}\"\n\n"
        f"You decided that you liked this message. Now, select a single emoji to react to it.\n"
        f"{emoji_choices_str}\n\n"
        f"Respond with ONLY the exact emoji code (e.g., <:emoji_name:id> or a standard emoji like 👍), "
        f"with absolutely no other text, explanation, or punctuation."
    )

    messages_reaction = [
        {"role": "system", "content": system_context},
        {"role": "user", "content": reaction_prompt}
    ]

    # Log reaction prompt
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages_reaction]
        log_entry = {
            "timestamp": timestamp,
            "channel_id": message.channel.id,
            "type": "reaction_choice",
            "messages": clean_messages
        }
        with open(PROMPT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass

    emoji_response = await query_ollama_raw(messages_reaction)
    print(f"Reaction emoji response for message {message.id}: {emoji_response}")

    emoji_to_react = extract_emoji(emoji_response)
    if emoji_to_react:
        emoji_map = get_guild_emoji_map(message.guild)
        extracted_name = re.sub(r'[^a-zA-Z0-9_]', '', emoji_to_react).lower()
        if extracted_name in emoji_map:
            emoji_to_react = emoji_map[extracted_name]
        elif not emoji_to_react.startswith("<"):
            for e in message.channel.guild.emojis:
                if e.name.lower() == extracted_name:
                    prefix = "a" if getattr(e, "animated", False) else ""
                    emoji_to_react = f"<{prefix}:{e.name}:{e.id}>"
                    break

        try:
            await message.add_reaction(emoji_to_react)
            print(f"Successfully reacted to message {message.id} with {emoji_to_react}")
            messages_since_last_bot_reaction[message.channel.id] = 0
            last_bot_reaction_time[message.channel.id] = discord.utils.utcnow()
        except Exception as react_err:
            print(f"Failed to add reaction '{emoji_to_react}' to message {message.id}: {react_err}")


async def count_recent_active_users(channel: discord.TextChannel, minutes: int = 30) -> int:
    """Count unique non-bot users who sent a message in the channel within the last `minutes` minutes."""
    cutoff = discord.utils.utcnow() - timedelta(minutes=minutes)
    unique_users: set[int] = set()
    async for msg in channel.history(limit=200, after=cutoff):
        if not msg.author.bot:
            unique_users.add(msg.author.id)
    return len(unique_users)


async def maybe_evaluate_and_respond_to_idle_channel(channel: discord.TextChannel):
    if is_bot_timed_out():
        return

    async for last_message in channel.history(limit=1):
        break
    else:
        return

    if last_message.author == bot.user:
        return

    # Check if we already evaluated this message for text/reaction
    if last_message.id in text_evaluation_evaluated_message_ids:
        return

    # Check if silent for 2 minutes
    idle_for = discord.utils.utcnow() - last_message.created_at
    if idle_for < timedelta(minutes=AUTO_EVALUATE_SILENCE_MINUTES):
        return

    # Mark as evaluated so we only run this once per message
    text_evaluation_evaluated_message_ids.add(last_message.id)

    author_name = f"{last_message.author.display_name} ({last_message.author.name})"
    context = await get_channel_context(channel, before=last_message)

    # Construct a lean system context for evaluation to keep prompt processing sub-second
    now_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    eval_system_parts = [f"[Current Live Date & Time: {now_str}]"]
    if context:
        # Keep context snippet lean (last 5 lines max for idle evaluation)
        context_lines = [line.strip() for line in context.splitlines() if line.strip()]
        if context_lines:
            eval_system_parts.append("Recent context:\n" + "\n".join(context_lines[-5:]))
    eval_system_parts.append(SYSTEM_PROMPT)
    eval_system = "\n\n".join(eval_system_parts)

    # Cooldown checks
    allow_respond = messages_since_last_bot_message[channel.id] >= 5
    allow_react = can_bot_react(channel.id)

    # Count unique users active in the last 30 minutes to weight response eagerness
    active_user_count = await count_recent_active_users(channel, minutes=30)
    print(f"Idle eval for #{channel.name}: {active_user_count} active user(s) in last 30 min")

    if allow_respond:
        if active_user_count >= 5:
            # Busy channel – many people chatting, bot can engage more freely
            respond_instruction = (
                "1. Choose 'RESPOND' if the message is interesting, funny, thought-provoking, or contains a question "
                "that you can meaningfully contribute to. The channel is lively with many active participants so feel "
                "free to join the conversation naturally. Still avoid responding to completely mundane or off-hand remarks."
            )
        elif active_user_count >= 3:
            # Moderate activity – be somewhat willing to chime in
            respond_instruction = (
                "1. Choose 'RESPOND' if the message contains a clear question, a genuinely interesting or funny topic, "
                "or something you have unique insight on. The channel has moderate activity so you can participate "
                "when it adds value, but don't force your way into every exchange."
            )
        elif active_user_count >= 2:
            # Light conversation between a couple of people – be more cautious
            respond_instruction = (
                "1. Choose 'RESPOND' ONLY if the message contains a direct question intended for you, a highly "
                "compelling topic that benefits from your expertise, or something truly noteworthy. Only a couple of "
                "people are chatting so be careful not to dominate the conversation. Err on the side of 'NONE' or 'REACT'."
            )
        else:
            # Solo user or near-empty channel – be very conservative
            respond_instruction = (
                "1. Choose 'RESPOND' ONLY if the message is of extreme importance, contains a clear and direct question "
                "intended for you (or an inquiry that strongly benefits from your specific expertise), or is an incredibly "
                "captivating and major topic that absolutely demands a verbal reply. Do NOT choose 'RESPOND' for normal "
                "conversation, opinions, questions directed at others, casual comments, or updates. Err heavily on the "
                "side of 'NONE' or 'REACT'."
            )
    else:
        respond_instruction = (
            "1. [DISABLED] Do not choose 'RESPOND' right now because you have spoken too recently. "
            "Choose 'REACT' or 'NONE' instead."
        )

    if allow_react:
        react_instruction = (
            "2. Choose 'REACT' only if the message is exceptionally funny, highly surprising, or clearly "
            "deserves a reaction. Do not choose 'REACT' for standard statements or normal updates."
        )
    else:
        react_instruction = (
            "2. [DISABLED] Do not choose 'REACT' right now because you have reacted too recently. "
            "Choose 'NONE' instead."
        )

    # Evaluation prompt
    activity_note = (
        f"[Channel activity: {active_user_count} unique user(s) have spoken in the last 30 minutes.]\n\n"
    )
    eval_prompt = (
        f"{activity_note}"
        f"A message was left in the channel by {author_name}:\n"
        f"\"{last_message.content}\"\n\n"
        f"The conversation has paused. Evaluate if this message is interesting, funny, or relevant enough to warrant your interaction.\n"
        f"You must be selective. Choose one of three actions:\n"
        f"{respond_instruction}\n"
        f"{react_instruction}\n"
        f"3. Choose 'NONE' if the message is standard conversation, casual chatter, neutral, or does not clearly stand out.\n\n"
        f"Respond with exactly one word: 'RESPOND', 'REACT', or 'NONE'. No other text, explanation, or punctuation."
    )

    try:
        messages = [
            {"role": "system", "content": eval_system},
            {"role": "user", "content": eval_prompt}
        ]
        
        # Log eval prompt
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            clean_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
            log_entry = {
                "timestamp": timestamp,
                "channel_id": channel.id,
                "type": "idle_message_eval_check",
                "messages": clean_messages
            }
            with open(PROMPT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass

        eval_response = await query_ollama_raw(messages, timeout=30.0, options={"temperature": 0.0})
        match = re.search(r'\b(RESPOND|REACT|NONE)\b', eval_response.strip().upper())
        eval_action = match.group(1) if match else "NONE"
        print(f"Idle message {last_message.id} evaluation action: {eval_action}")

        if eval_action == "RESPOND":
            if allow_respond:
                # Generate text response!
                async with channel.typing():
                    # Format user text and query model
                    user_text = last_message.content.replace(f"<@{bot.user.id}>", "").strip()
                    if not user_text:
                        user_text = "[Conversation continues]"

                    reply = await query_ollama(
                        channel.id,
                        user_text,
                        context,
                        author_name=author_name,
                        is_tagged=False,
                        is_reply=False,
                        guild=channel.guild,
                        is_idle_check=True
                    )
                
                # Send text response ONLY if it's a valid message (not an error string)
                if reply.startswith("⚠️"):
                    print(f"Idle channel evaluation response returned error: {reply}. Suppressing Discord post.")
                else:
                    for chunk in split_message(reply):
                        await channel.send(chunk)
                    messages_since_last_bot_message[channel.id] = 0
            else:
                eval_action = "REACT" if allow_react else "NONE"

        if eval_action == "REACT":
            if allow_react:
                await select_and_react(last_message, eval_system)
            else:
                eval_action = "NONE"

    except Exception as e:
        print(f"Error in maybe_evaluate_and_respond_to_idle_channel: {type(e).__name__}: {e}")


async def idle_watcher():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if not should_monitor_channel(channel):
                    continue

                try:
                    await maybe_reply_to_idle_channel(channel)
                except Exception as e:
                    print(f"Idle reply failed in #{channel}: {e}")

                try:
                    await maybe_evaluate_and_respond_to_idle_channel(channel)
                except Exception as e:
                    print(f"Idle evaluation check failed in #{channel}: {e}")

        await asyncio.sleep(AUTO_IDLE_CHECK_SECONDS)


async def find_live_log_channel() -> discord.TextChannel | None:
    """Finds the text channel intended for live bot logging."""
    if LIVE_LOG_CHANNEL_ID:
        ch = bot.get_channel(LIVE_LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            return ch
        try:
            ch = await bot.fetch_channel(LIVE_LOG_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                return ch
        except Exception:
            pass

    target_name = LIVE_LOG_CHANNEL_NAME.lower().lstrip("#")
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name.lower() == target_name:
                return channel
    return None


async def live_log_streamer():
    """Tails bot.log and streams new lines to the #live-bot-log channel in real-time."""
    await bot.wait_until_ready()

    log_path = LIVE_LOG_FILE
    last_pos = 0

    # Wait until the log file exists, then position at the current end of file
    while not bot.is_closed():
        if log_path.exists():
            try:
                last_pos = log_path.stat().st_size
            except Exception:
                last_pos = 0
            break
        await asyncio.sleep(2)

    log_buffer: list[str] = []

    async def flush_buffer(channel: discord.TextChannel):
        nonlocal log_buffer
        if not log_buffer:
            return

        raw_text = "".join(log_buffer)
        log_buffer.clear()

        # Split into chunks fitting inside Discord's 2000 char limit (using 1850 safety margin)
        max_chunk_size = 1850
        while raw_text:
            if len(raw_text) <= max_chunk_size:
                chunk = raw_text
                raw_text = ""
            else:
                split_idx = raw_text.rfind("\n", 0, max_chunk_size)
                if split_idx <= 0:
                    split_idx = max_chunk_size
                else:
                    split_idx += 1
                chunk = raw_text[:split_idx]
                raw_text = raw_text[split_idx:]

            chunk_content = chunk.strip("\r\n")
            if chunk_content:
                formatted_msg = f"```\n{chunk_content}\n```"
                try:
                    await channel.send(formatted_msg)
                except discord.HTTPException:
                    pass
                except Exception:
                    pass

    target_channel: discord.TextChannel | None = None

    while not bot.is_closed():
        try:
            if target_channel is None or target_channel.guild not in bot.guilds:
                target_channel = await find_live_log_channel()

            if target_channel is not None and log_path.exists():
                try:
                    current_size = log_path.stat().st_size
                    if current_size < last_pos:
                        last_pos = 0

                    if current_size > last_pos:
                        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_pos)
                            new_text = f.read()
                            last_pos = f.tell()

                        if new_text:
                            log_buffer.append(new_text)
                            if sum(len(b) for b in log_buffer) >= 1500:
                                await flush_buffer(target_channel)
                except Exception:
                    pass

            if target_channel is not None and log_buffer:
                await flush_buffer(target_channel)

        except Exception:
            pass

        await asyncio.sleep(2.0)


# ── Events ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    global idle_watcher_task, memory_task, log_streamer_task

    now_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    search_provider = "Google Gemini AI Studio RAG (Live Search Grounding)" if GEMINI_API_KEY else "DuckDuckGo / wttr.in"
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    print(f"   Live Time: {now_str}")
    print(f"   Model   : {MODEL}")
    print(f"   Search  : {search_provider}")
    print(f"   Ollama  : {OLLAMA_BASE_URL}")
    print(f"   Context : last {CONTEXT_MESSAGES} messages")
    print(f"   Threshold: {AUTO_RESPONSE_THRESHOLD} messages")
    print(f"   Idle    : reply after {AUTO_IDLE_REPLY_HOURS:g} hours")
    print(f"   Idle ch : {', '.join(sorted(AUTO_IDLE_CHANNEL_NAMES)) or 'channel IDs only'}")
    print(f"   Memory  : {MEMORY_LOOKBACK_DAYS} days, {MEMORY_CHUNK_DAYS}-day chunks")
    print(f"   Live Log: #{LIVE_LOG_CHANNEL_NAME} ({LIVE_LOG_FILE})")
    try:
        await asyncio.wait_for(tree.sync(), timeout=30)
        for guild in bot.guilds:
            try:
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
            except Exception as ge:
                print(f"   Guild command sync failed for {guild.name}: {ge}")
        print("   Slash commands synced globally and to connected guilds. Ready!\n")
    except Exception as e:
        print(f"   Slash command sync skipped/failed: {e}")
        print("   Mention replies are ready.\n")

    if idle_watcher_task is None or idle_watcher_task.done():
        idle_watcher_task = asyncio.create_task(idle_watcher())

    if log_streamer_task is None or log_streamer_task.done():
        log_streamer_task = asyncio.create_task(live_log_streamer())

    # Background memory updates are handled externally by Antigravity schedule
    # if memory_task is None or memory_task.done():
    #     memory_task = asyncio.create_task(memory_watcher())


@bot.event
async def on_message(message: discord.Message):
    # Reset count if it's the bot's own message
    if message.author == bot.user:
        messages_since_last_bot_message[message.channel.id] = 0
        return

    # Check for text commands (!timeout, !untimeout, or mention + timeout/untimeout)
    raw_content = message.content.strip()
    lowered = raw_content.lower()
    is_tagged = bot.user in message.mentions

    if lowered.startswith("!timeout") or lowered.startswith("!untimeout") or (is_tagged and ("timeout" in lowered or "untimeout" in lowered)):
        if await handle_timeout_text_command(message):
            return

    # Skip bot responses if bot is currently in time out
    if is_bot_timed_out():
        await bot.process_commands(message)
        return

    # Increment counter for monitored channels
    is_monitored = should_monitor_channel(message.channel)
    if is_monitored:
        messages_since_last_bot_message[message.channel.id] += 1
        messages_since_last_bot_reaction[message.channel.id] += 1

    # Check triggers
    is_tagged = bot.user in message.mentions

    is_reply_to_bot = False
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None and message.reference.message_id:
            try:
                resolved = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                pass
        if isinstance(resolved, discord.Message) and resolved.author == bot.user:
            is_reply_to_bot = True

    is_threshold_met = is_monitored and messages_since_last_bot_message[message.channel.id] >= AUTO_RESPONSE_THRESHOLD

    # Pre-check if there are attachments or media URLs
    has_potential_media = bool(
        message.attachments
        or IMAGE_URL_PATTERN.search(message.content)
        or VIDEO_URL_PATTERN.search(message.content)
    )

    # If none of the triggers are met, run passive viewing on media in background or exit early
    if not (is_tagged or is_reply_to_bot or is_threshold_met):
        if has_potential_media:
            await cancel_passive_image_viewing(message.channel.id, reason="new passive media arrived")
            active_passive_view_tasks[message.channel.id] = asyncio.create_task(passive_image_viewer(message))
        await bot.process_commands(message)
        return

    # Trigger encountered: cancel passive image viewing immediately to perform the more pertinent action
    trigger_type = "mention" if is_tagged else ("reply" if is_reply_to_bot else "auto-threshold")
    await cancel_passive_image_viewing(message.channel.id, reason=f"{trigger_type} trigger")

    user_text = message.content.replace(f"<@{bot.user.id}>", "").strip()

    # If it's a direct user ping/reply with no text and no potential media, prompt the help greeting immediately
    if (is_tagged or is_reply_to_bot) and not user_text and not has_potential_media:
        await message.reply("Hi! Mention me with a question (or images, videos, emojis) and I'll answer 😊")
        return

    # Reset the counter immediately before querying to prevent race condition/double triggering
    if is_threshold_met:
        messages_since_last_bot_message[message.channel.id] = 0

    author_name = f"{message.author.display_name} ({message.author.name})"
    ch_name = message.channel.name if hasattr(message.channel, "name") else "DM"
    print(f"Received {trigger_type} trigger from {author_name} in #{ch_name}: '{user_text[:100]}'")

    # Trigger typing indicator immediately during media downloading, parsing, and LLM generation
    async with message.channel.typing():
        images_list = []
        media_descriptions = []

        # 1. Check attachments (images & videos, up to 5) - MOST RECENT TO OLDEST
        sorted_attachments = sorted(
            [a for a in message.attachments if get_media_mime_type(a)[1] in ("image", "video")],
            key=lambda a: a.id,
            reverse=True
        )
        for attachment in sorted_attachments[:5]:
            mime_type, media_cat = get_media_mime_type(attachment)
            if media_cat == "image":
                try:
                    img_bytes = await attachment.read()
                    b64_str = process_image_bytes(img_bytes)
                    if b64_str:
                        images_list.append(b64_str)
                    # Parse image with multimodal Gemini or Ollama vision fallback
                    parse_res = await analyze_and_describe_image(
                        img_bytes, mime_type, attachment.filename, context_hint=user_text
                    )
                    if parse_res:
                        rec = create_named_visual_record(
                            attachment.filename, author_name, message, parse_res, b64_image=b64_str
                        )
                        media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
                except Exception as e:
                    print(f"Failed to read image attachment {attachment.filename}: {e}")
            elif media_cat == "video":
                try:
                    vid_bytes = await attachment.read()
                    if GEMINI_API_KEY:
                        prompt = (
                            f"The user attached this video clip ({attachment.filename}) and wrote: '{user_text}'. "
                            "Describe what happens in this video in detail (visual sequence, action, subjects, audible speech or text)."
                            if user_text else
                            f"Describe what happens in this video clip ({attachment.filename}) in detail (visual sequence, action, subjects, audible speech or text)."
                        )
                        parse_res = await parse_media_with_gemini(vid_bytes, mime_type, prompt=prompt)
                        if parse_res:
                            rec = create_named_visual_record(
                                attachment.filename, author_name, message, parse_res
                            )
                            media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
                    else:
                        print(f"Cannot parse video attachment {attachment.filename}: GEMINI_API_KEY is not configured.")
                except Exception as e:
                    print(f"Failed to read video attachment {attachment.filename}: {e}")

        # 2. Check for image URLs pasted in the message content (most recent to oldest, up to 5)
        image_url_matches = list(reversed(IMAGE_URL_PATTERN.findall(message.content)))
        if image_url_matches:
            for url in image_url_matches[:5]:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(url, timeout=10.0)
                        if resp.status_code == 200:
                            b64_str = process_image_bytes(resp.content)
                            if b64_str:
                                images_list.append(b64_str)
                            ext = url.split("?")[0].split(".")[-1].lower()
                            mime = f"image/{ext}" if ext in ["png", "webp", "gif"] else "image/jpeg"
                            fn = url.split("/")[-1].split("?")[0] or "web_image.jpg"
                            parse_res = await analyze_and_describe_image(
                                resp.content, mime, fn, context_hint=user_text
                            )
                            if parse_res:
                                rec = create_named_visual_record(
                                    fn, author_name, message, parse_res, b64_image=b64_str
                                )
                                media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
                except Exception as e:
                    print(f"Failed to download image from URL {url}: {e}")

        # 3. Check for video URLs pasted in the message content (most recent to oldest, up to 3)
        video_url_matches = list(reversed(VIDEO_URL_PATTERN.findall(message.content)))
        if video_url_matches:
            for url in video_url_matches[:3]:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(url, timeout=15.0)
                        if resp.status_code == 200:
                            if GEMINI_API_KEY:
                                ext = url.split("?")[0].split(".")[-1].lower()
                                mime = "video/webm" if ext == "webm" else ("video/quicktime" if ext == "mov" else "video/mp4")
                                parse_res = await parse_media_with_gemini(resp.content, mime, prompt="Describe what happens in this linked video clip:")
                                if parse_res:
                                    rec = create_named_visual_record(
                                        url.split("/")[-1].split("?")[0] or "web_video",
                                        author_name, message, parse_res
                                    )
                                    media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
                except Exception as e:
                    print(f"Failed to download video from URL {url}: {e}")

        # 4. If current trigger message didn't contain direct images, pass recent pictures through by most recent to oldest (up to 3)
        if not images_list and channel_visual_records.get(message.channel.id):
            recent_cached_images = []
            for r in channel_visual_records[message.channel.id]:
                if r.get("b64_image"):
                    recent_cached_images.append(r["b64_image"])
                if len(recent_cached_images) >= 3:
                    break
            if recent_cached_images:
                images_list = recent_cached_images
                print(f"🖼️ Injected {len(images_list)} recent visual record image(s) (most recent to oldest) into prompt payload.")

        has_media = bool(images_list or media_descriptions)

        # For auto-threshold trigger, if user_text is empty, we still want a prompt context
        if is_threshold_met and not user_text:
            user_text = "[Conversation continues]"

        if has_media and not user_text:
            user_text = "Describe or react to the attached media (pictures/videos)."

        # If after parsing there was actually no text and no media found, bail
        if not user_text and not has_media:
            await message.reply("Hi! Mention me with a question (or images, videos, emojis) and I'll answer 😊")
            return

        if images_list or media_descriptions:
            print(f"Processed {len(images_list)} image(s) and {len(media_descriptions)} media analysis for prompt payload.")

        context = await get_channel_context(message.channel, before=message)
        reply = await query_ollama(
            message.channel.id,
            user_text,
            context,
            images=images_list if images_list else None,
            media_descriptions=media_descriptions if media_descriptions else None,
            author_name=author_name,
            is_tagged=is_tagged,
            is_reply=is_reply_to_bot,
            guild=message.guild
        )

    # Send response
    if is_tagged or is_reply_to_bot:
        # Direct reply to user
        print(f"Sending direct reply to {author_name} in #{ch_name}: '{reply[:100]}...'")
        for chunk in split_message(reply):
            await message.reply(chunk)
    else:
        # Auto-threshold response: send without pinging/threading
        print(f"Sending threshold response to #{ch_name}: '{reply[:100]}...'")
        for chunk in split_message(reply):
            await message.channel.send(chunk)

    # Background auto-index user message into RAG vector database
    if user_text and len(user_text) > 15:
        async def _index_bg():
            try:
                emb = await rag_store.embed_text(user_text)
                if emb:
                    rag_store.add_chunk(
                        content=f"[{author_name}]: {user_text}",
                        embedding=emb,
                        source=f"chat:#{ch_name}",
                        channel_id=message.channel.id,
                        author=author_name
                    )
            except Exception as e:
                print(f"Background RAG indexing error: {e}")
        asyncio.create_task(_index_bg())

    await bot.process_commands(message)


# ── Slash commands ─────────────────────────────────────────────────────────────

@tree.command(name="timeout", description="Put the bot in time out (default 30 minutes)")
@app_commands.describe(minutes="Duration of timeout in minutes (default 30)")
async def timeout_cmd(interaction: discord.Interaction, minutes: int = 30):
    global bot_timeout_until
    if minutes <= 0:
        bot_timeout_until = None
        await interaction.response.send_message("⏰ Time out cleared! Bot is active.", ephemeral=False)
        return

    bot_timeout_until = discord.utils.utcnow() + timedelta(minutes=minutes)
    ts = int(bot_timeout_until.timestamp())
    author_name = f"{interaction.user.display_name} ({interaction.user.name})"
    ch_name = interaction.channel.name if hasattr(interaction.channel, "name") else "DM"
    print(f"Slash command /timeout ({minutes}m) executed by {author_name} in #{ch_name}")
    await interaction.response.send_message(
        f"🤫 Bot is now in time out for **{minutes}** minute(s) (until <t:{ts}:t>, <t:{ts}:R>).",
        ephemeral=False
    )


@tree.command(name="untimeout", description="Remove the bot from time out immediately")
async def untimeout_cmd(interaction: discord.Interaction):
    global bot_timeout_until
    if not is_bot_timed_out():
        await interaction.response.send_message("ℹ️ Bot is not currently in time out.", ephemeral=True)
        return

    bot_timeout_until = None
    author_name = f"{interaction.user.display_name} ({interaction.user.name})"
    print(f"Slash command /untimeout executed by {author_name}")
    await interaction.response.send_message("⏰ Time out removed! Bot is active again.", ephemeral=False)


@tree.command(name="ask", description="Ask Gemma a question (with optional picture or video)")
@app_commands.describe(
    question="Your question or prompt",
    attachment="Optional picture or video to analyze"
)
async def ask(interaction: discord.Interaction, question: str, attachment: discord.Attachment | None = None):
    if is_bot_timed_out():
        ts = int(bot_timeout_until.timestamp())
        await interaction.response.send_message(
            f"⏰ I am currently in time out until <t:{ts}:R>. Use `/untimeout` to end the time out early.",
            ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    author_name = f"{interaction.user.display_name} ({interaction.user.name})"
    ch_name = interaction.channel.name if hasattr(interaction.channel, "name") else "DM"
    print(f"Slash command /ask executed by {author_name} in #{ch_name}: '{question[:100]}'")

    # Cancel any active passive image viewing in this channel immediately to prioritize /ask
    await cancel_passive_image_viewing(interaction.channel_id, reason="slash command /ask")

    images_list = []
    media_descriptions = []
    if attachment:
        mime_type, media_cat = get_media_mime_type(attachment)
        if media_cat == "image":
            try:
                img_bytes = await attachment.read()
                b64_str = process_image_bytes(img_bytes)
                if b64_str:
                    images_list.append(b64_str)
                parse_res = await analyze_and_describe_image(
                    img_bytes, mime_type, attachment.filename, context_hint=question
                )
                if parse_res:
                    rec = create_named_visual_record(
                        attachment.filename, author_name, interaction, parse_res, b64_image=b64_str
                    )
                    media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
            except Exception as e:
                print(f"Failed to read image attachment in /ask: {e}")
        elif media_cat == "video":
            try:
                vid_bytes = await attachment.read()
                if GEMINI_API_KEY:
                    parse_res = await parse_media_with_gemini(
                        vid_bytes, mime_type,
                        prompt=f"The user attached this video clip ({attachment.filename}) and asked: '{question}'. Describe what happens in detail to answer the user."
                    )
                    if parse_res:
                        rec = create_named_visual_record(
                            attachment.filename, author_name, interaction, parse_res
                        )
                        media_descriptions.append(f"[{rec['record_name']}]:\n{parse_res}")
            except Exception as e:
                print(f"Failed to read video attachment in /ask: {e}")

    # If no direct attachment in /ask, inject recent images from context (most recent to oldest)
    if not images_list and channel_visual_records.get(interaction.channel_id):
        recent_cached_images = []
        for r in channel_visual_records[interaction.channel_id]:
            if r.get("b64_image"):
                recent_cached_images.append(r["b64_image"])
            if len(recent_cached_images) >= 3:
                break
        if recent_cached_images:
            images_list = recent_cached_images
            print(f"🖼️ [/ask] Injected {len(images_list)} recent visual record image(s) (most recent to oldest).")

    context = await get_channel_context(interaction.channel)
    reply = await query_ollama(
        interaction.channel_id,
        question,
        context,
        images=images_list if images_list else None,
        media_descriptions=media_descriptions if media_descriptions else None,
        author_name=author_name,
        is_tagged=True,
        guild=interaction.guild
    )
    for i, chunk in enumerate(split_message(reply)):
        if i == 0:
            await interaction.followup.send(chunk)
        else:
            await interaction.channel.send(chunk)


@tree.command(name="index", description="Index an attached file or text into the RAG vector database")
@app_commands.describe(file="Text or markdown file to index into vector memory", text="Text passage to index into vector memory")
async def index_cmd(interaction: discord.Interaction, file: discord.Attachment | None = None, text: str | None = None):
    if is_bot_timed_out():
        ts = int(bot_timeout_until.timestamp())
        await interaction.response.send_message(
            f"⏰ I am currently in time out until <t:{ts}:R>. Use `/untimeout` to end the time out early.",
            ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    indexed_count = 0
    author_name = f"{interaction.user.display_name} ({interaction.user.name})"
    print(f"Slash command /index executed by {author_name} (file={file.filename if file else None})")
    
    if file:
        if any(file.filename.endswith(ext) for ext in ['.txt', '.md', '.json', '.csv', '.py']):
            try:
                content_bytes = await file.read()
                content_str = content_bytes.decode('utf-8', errors='ignore').strip()
                if content_str:
                    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content_str) if p.strip()]
                    for p in paragraphs[:25]:
                        emb = await rag_store.embed_text(p)
                        if emb:
                            rag_store.add_chunk(p, emb, source=f"doc:{file.filename}", channel_id=interaction.channel_id, author=author_name)
                            indexed_count += 1
            except Exception as e:
                print(f"Error indexing attached file: {e}")
        else:
            mime_type, media_cat = get_media_mime_type(file)
            if media_cat in ["image", "video"]:
                try:
                    media_bytes = await file.read()
                    if GEMINI_API_KEY:
                        parse_res = await parse_media_with_gemini(
                            media_bytes, mime_type,
                            prompt=f"Provide a comprehensive, detailed factual analysis and description of this {media_cat} ({file.filename}) suitable for long-term knowledge retrieval."
                        )
                        if parse_res:
                            emb = await rag_store.embed_text(parse_res[:1000])
                            if emb:
                                rag_store.add_chunk(
                                    f"[{media_cat.capitalize()} Knowledge: {file.filename}]:\n{parse_res}",
                                    emb,
                                    source=f"media:{file.filename}",
                                    channel_id=interaction.channel_id,
                                    author=author_name
                                )
                                indexed_count += 1
                except Exception as e:
                    print(f"Error indexing attached media file: {e}")
                
    if text:
        emb = await rag_store.embed_text(text)
        if emb:
            rag_store.add_chunk(text, emb, source="user_indexed_text", channel_id=interaction.channel_id, author=author_name)
            indexed_count += 1

    if indexed_count > 0:
        await interaction.followup.send(f"✅ Successfully indexed {indexed_count} passage(s) into vector RAG memory!")
    else:
        await interaction.followup.send("⚠️ Please provide a valid text string or attached document/image/video to index.")


@tree.command(name="clear", description="Clear this channel's conversation history")
async def clear(interaction: discord.Interaction):
    history[interaction.channel_id].clear()
    await interaction.response.send_message("🗑️ Conversation history cleared.", ephemeral=True)


@tree.command(name="model", description="Show which model is currently loaded")
async def model_info(interaction: discord.Interaction):
    embed_info = f" • RAG Embeddings: `{rag_store.EMBED_MODEL}` (fallback: `{rag_store.FALLBACK_EMBED_MODEL}`)"
    vision_info = f" • Multimodal Vision & Video: `{GEMINI_MODELS[0]}` (Google Gemini)" if GEMINI_API_KEY else " • Multimodal: local Ollama images only"
    await interaction.response.send_message(
        f"🤖 **Active Bot Models:**\n"
        f" • Primary LLM: **{MODEL}** via Ollama (`{OLLAMA_BASE_URL}`)\n"
        f"{vision_info}\n"
        f"{embed_info}",
        ephemeral=True,
    )


@tree.command(name="memory", description="Show long-term memory status or inspect specific chunks")
@app_commands.describe(chunk_num="The specific chunk number to inspect (1 to N)")
async def memory_info(interaction: discord.Interaction, chunk_num: int | None = None):
    memory = load_memory()
    channel_memory = memory.get("channels", {}).get(str(interaction.channel_id))
    if not channel_memory:
        await interaction.response.send_message(
            "No compressed memory has been built for this channel yet.",
            ephemeral=True,
        )
        return

    chunks = channel_memory.get("chunks", [])
    if not chunks:
        await interaction.response.send_message(
            "No memory chunks found for this channel.",
            ephemeral=True,
        )
        return

    if chunk_num is None:
        message_count = sum(chunk.get("message_count", 0) for chunk in chunks)
        updated = channel_memory.get("generated_at", "unknown")
        
        lines = [
            f"ℹ️ **Memory status for #{channel_memory.get('channel_name', 'unknown')}**:",
            f"• Total Chunks: **{len(chunks)}**",
            f"• Total Messages Summarized: **{message_count}**",
            f"• Last Updated: `{updated}`",
            "\n**Available Chunks (Use `/memory <number>` to view):**"
        ]
        
        for idx, chunk in enumerate(chunks):
            start_dt = datetime.fromisoformat(chunk["start"]).date()
            end_dt = datetime.fromisoformat(chunk["end"]).date()
            lines.append(f"• **Chunk {idx+1}**: {start_dt} to {end_dt} ({chunk['message_count']} msgs)")
            
        text = "\n".join(lines)
        chunks_to_send = split_message(text)
        await interaction.response.send_message(chunks_to_send[0], ephemeral=True)
        for extra_chunk in chunks_to_send[1:]:
            await interaction.followup.send(extra_chunk, ephemeral=True)
    else:
        if chunk_num < 1 or chunk_num > len(chunks):
            await interaction.response.send_message(
                f"❌ Invalid chunk number. Please choose a number between 1 and {len(chunks)}.",
                ephemeral=True,
            )
            return

        chunk = chunks[chunk_num - 1]
        start_dt = datetime.fromisoformat(chunk["start"]).date()
        end_dt = datetime.fromisoformat(chunk["end"]).date()
        
        header = f"🗓️ **Memory Chunk {chunk_num} ({start_dt} to {end_dt})** — *{chunk['message_count']} messages*\n\n"
        content = chunk.get("summary", "No summary content found.")
        text = header + content
        
        await interaction.response.defer(thinking=True, ephemeral=True)
        chunks_to_send = split_message(text)
        for chunk_text in chunks_to_send:
            await interaction.followup.send(chunk_text, ephemeral=True)


@tree.command(name="respond", description="Respond to the last message in this channel")
async def respond_last(interaction: discord.Interaction):
    if is_bot_timed_out():
        ts = int(bot_timeout_until.timestamp())
        await interaction.response.send_message(
            f"⏰ I am currently in time out until <t:{ts}:R>. Use `/untimeout` to end the time out early.",
            ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True, ephemeral=True)

    # Find the last message in the channel that is not from the bot itself
    last_msg = None
    async for msg in interaction.channel.history(limit=20):
        if msg.author != bot.user:
            last_msg = msg
            break

    if not last_msg:
        await interaction.followup.send("❌ No recent messages found to respond to.", ephemeral=True)
        return

    user_text = last_msg.content.strip()
    if not user_text:
        if last_msg.attachments:
            user_text = "[Shared an attachment]"
        else:
            await interaction.followup.send("❌ The last message does not contain any text to respond to.", ephemeral=True)
            return

    author_name = f"{last_msg.author.display_name} ({last_msg.author.name})"
    async with interaction.channel.typing():
        context = await get_channel_context(interaction.channel)
        reply = await query_ollama(
            interaction.channel_id,
            user_text,
            context,
            author_name=author_name,
            is_tagged=True,
            guild=interaction.guild
        )

    # Reply directly to the message
    for chunk in split_message(reply):
        await last_msg.reply(chunk)

    await interaction.followup.send("✅ Responded to the last message!", ephemeral=True)


@tree.command(name="last_prompt", description="Direct messages you the last full prompt payload sent to Ollama for this channel")
async def last_prompt(interaction: discord.Interaction):
    payload = last_prompt_payload.get(interaction.channel_id)
    if not payload:
        await interaction.response.send_message(
            "❌ No prompts have been recorded for this channel since the bot started.",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        formatted_json = json.dumps(payload, indent=2, ensure_ascii=False)
        message_chunks = split_message(
            f"📜 **Last Prompt Payload for channel <#{interaction.channel_id}>:**\n"
            f"```json\n{formatted_json}\n```",
            limit=1900
        )
        
        # Send via DM to the user
        dm_channel = interaction.user.dm_channel or await interaction.user.create_dm()
        for chunk in message_chunks:
            await dm_channel.send(chunk)
        
        await interaction.followup.send("✅ Sent the last prompt history to your DMs!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Failed to DM you. Please enable DMs from server members in your Privacy settings.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error sending DM: {e}", ephemeral=True)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit(
            "❌ DISCORD_TOKEN is not set.\n"
            "   Export it before running:\n"
            "   export DISCORD_TOKEN=your_token_here"
        )
    bot.run(DISCORD_TOKEN)
