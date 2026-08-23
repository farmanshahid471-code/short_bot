"""
config.py - Configuration management, environment variables, thresholds, and logging setup.
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load .env file if present
# IMPORTANT: load_dotenv() with no arguments only searches the current working
# directory and its parents - it would MISS the .env that lives inside this
# folder when the bot is launched from elsewhere (e.g. run_ui.bat). So we load
# the .env next to this file explicitly.
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)
else:
    load_dotenv()  # fallback: plain load from CWD (e.g. server setups)

# --- PROJECT DIRECTORIES ---
BASE_DIR = Path(__file__).resolve().parent


def _resolve_path(value) -> Path:
    """Resolve a possibly-relative path against BASE_DIR so the bot works the same
    no matter which folder it is launched from (important for the Windows UI)."""
    p = Path(value)
    return p if p.is_absolute() else BASE_DIR / p


TEMP_DIR = _resolve_path(os.getenv("TEMP_DIR", BASE_DIR / "temp_clips"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = _resolve_path(os.getenv("DB_PATH", BASE_DIR / "bot_state.db"))
LOG_FILE = _resolve_path(os.getenv("LOG_FILE", BASE_DIR / "shorts_bot.log"))

# --- TARGET SELECTION ---
# Comma-separated channel URLs or Channel IDs in .env, e.g. "https://www.youtube.com/@channel1,https://www.youtube.com/@channel2"
_channels_env = os.getenv(
    "TARGET_CHANNELS",
    "https://www.youtube.com/@TEDEd,https://www.youtube.com/@Kurzgesagt"
)
TARGET_CHANNELS: List[str] = [c.strip() for c in _channels_env.split(",") if c.strip()]

# How many newest videos to inspect per channel per cycle
FETCH_LIMIT_PER_CHANNEL: int = int(os.getenv("FETCH_LIMIT_PER_CHANNEL", "5"))

# --- HEATMAP & CLIP SETTINGS ---
CLIP_DURATION_SEC: float = float(os.getenv("CLIP_DURATION_SEC", "18.0"))  # 15-20 second window
HEATMAP_SMOOTH_WINDOW_SEC: float = float(os.getenv("HEATMAP_SMOOTH_WINDOW_SEC", "18.0"))
MIN_CLIP_DURATION_SEC: float = 15.0
MAX_CLIP_DURATION_SEC: float = 20.0

# --- VIDEO EDITING & SUBTITLES ---
# Output canvas. "3:4" matches the reference Short style (1080x1440, like
# deagzzzshorts/iShowSpeed edits). "9:16" is the classic Shorts format (1080x1920).
SHORT_ASPECT: str = os.getenv("SHORT_ASPECT", "3:4").strip().lower()

# How to fit the source video into the vertical canvas:
#   "blur" = whole frame visible, blurred background fills the rest (nothing is cut)
#   "crop" = center-crop the frame to fill the canvas (edges are cut)
FILL_MODE: str = os.getenv("FILL_MODE", "blur").strip().lower()

if SHORT_ASPECT == "3:4":
    VERTICAL_WIDTH: int = 1080
    VERTICAL_HEIGHT: int = 1440
else:  # default 9:16
    SHORT_ASPECT = "9:16"
    VERTICAL_WIDTH: int = 1080
    VERTICAL_HEIGHT: int = 1920
ASPECT_RATIO_EXPRESSION: str = SHORT_ASPECT

# Encode quality (higher quality than the old defaults; slower but clips are short)
VIDEO_CRF: int = int(os.getenv("VIDEO_CRF", "18"))          # lower = better quality (18 ~ visually lossless)
VIDEO_PRESET: str = os.getenv("VIDEO_PRESET", "medium")     # medium = good quality/speed balance
AUDIO_BITRATE: str = os.getenv("AUDIO_BITRATE", "192k")

# --- LOGO / WATERMARK REMOVAL (beta) ---
# Streamer VODs often have a logo/watermark burned into a corner. The bot can
# blur that corner region so it does not show in the Short.
#   LOGO_REMOVE_ENABLED = "true" to always apply, "false" to only apply when
#   explicitly requested via the control panel / CLI.
#   LOGO_POSITION = "top-left" | "top-right" | "bottom-left" | "bottom-right"
#   LOGO_SIZE_PCT = logo width as % of the canvas width (12 ≈ medium corner logo)
LOGO_REMOVE_ENABLED: bool = os.getenv("LOGO_REMOVE_ENABLED", "false").lower() == "true"
LOGO_POSITION: str = os.getenv("LOGO_POSITION", "top-right").strip().lower()
LOGO_SIZE_PCT: float = float(os.getenv("LOGO_SIZE_PCT", "12"))
LOGO_POSITIONS: tuple = ("top-left", "top-right", "bottom-left", "bottom-right")

# --- "LIKE & SUBSCRIBE" BOTTOM BANNER ---
# Burns a small pill banner at the bottom of the video (in the blurred band):
#   LIKE_AND_SUBSCRIBE_ENABLED = "true" to always show it, "false" to only
#   show it when explicitly requested (control panel / CLI).
#   LIKE_AND_SUBSCRIBE_TEXT = the text shown (default "LIKE & SUBSCRIBE").
LIKE_AND_SUBSCRIBE_ENABLED: bool = os.getenv("LIKE_AND_SUBSCRIBE_ENABLED", "true").lower() == "true"
LIKE_AND_SUBSCRIBE_TEXT: str = os.getenv("LIKE_AND_SUBSCRIBE_TEXT", "LIKE & SUBSCRIBE")

# --- TOP CHANNEL WATERMARK (light, in the upper blur band) ---
# A subtle semi-transparent channel name at the top of the video, so it does
# not disturb the viewing experience. Set TOP_WATERMARK_TEXT to your channel
# name (empty = no top watermark).
TOP_WATERMARK_ENABLED: bool = os.getenv("TOP_WATERMARK_ENABLED", "true").lower() == "true"
TOP_WATERMARK_TEXT: str = os.getenv("TOP_WATERMARK_TEXT", "")

# Faster-Whisper CPU Settings
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "tiny.en")  # tiny.en, base.en, small
WHISPER_DEVICE: str = "cpu"
WHISPER_COMPUTE_TYPE: str = "int8"
MAX_WORDS_PER_SUBTITLE_LINE: int = int(os.getenv("MAX_WORDS_PER_SUBTITLE_LINE", "4"))
SUBTITLE_MAX_DURATION_SEC: float = 2.0  # Fast TikTok-style subtitle pacing

# Subtitle Styling Mode: "viral" (1-2 word UPPERCASE CapCut/Hormozi/Speedzyy style) vs "standard" (3-4 words)
SUBTITLE_STYLE_MODE: str = os.getenv("SUBTITLE_STYLE_MODE", "viral")
VIRAL_WORDS_PER_LINE: int = int(os.getenv("VIRAL_WORDS_PER_LINE", "2"))
SUBTITLE_UPPERCASE: bool = os.getenv("SUBTITLE_UPPERCASE", "true").lower() == "true"

# FFmpeg Subtitle Styling (TikTok / Shorts Aesthetic - Bold Yellow/White with Black Outline)
# Font is auto-chosen per OS: "Arial" on Windows (always present), "DejaVu Sans" elsewhere.
# Override with SUBTITLE_FONT_NAME in .env if you want something else.
_DEFAULT_FONT = "Arial" if sys.platform.startswith("win") else "DejaVu Sans"
SUBTITLE_FONT_NAME: str = os.getenv("SUBTITLE_FONT_NAME", _DEFAULT_FONT)
# Guard: older .env files may still say "DejaVu Sans", which does NOT exist on
# Windows and makes FFmpeg's subtitle renderer fail (exit 69). Force Arial there.
if sys.platform.startswith("win") and SUBTITLE_FONT_NAME.strip().lower() == "dejavu sans":
    SUBTITLE_FONT_NAME = "Arial"
SUBTITLE_FONT_SIZE: int = int(os.getenv("SUBTITLE_FONT_SIZE", "28"))
SUBTITLE_FORCE_STYLE: str = (
    f"Fontname={SUBTITLE_FONT_NAME},Fontsize={SUBTITLE_FONT_SIZE},Bold=1,"
    "PrimaryColour=&H0000FFFF,SecondaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=3,Shadow=2,Alignment=2,MarginV=85"
)

# --- BACKGROUND MUSIC (BGM) DUCKING & MIXING ---
BGM_DIR: Path = _resolve_path(os.getenv("BGM_DIR", BASE_DIR / "bgm"))
BGM_DIR.mkdir(parents=True, exist_ok=True)
BGM_ENABLED: bool = os.getenv("BGM_ENABLED", "true").lower() == "true"
BGM_VOLUME: float = float(os.getenv("BGM_VOLUME", "0.18"))  # 18% volume relative to speech
VOICE_VOLUME: float = float(os.getenv("VOICE_VOLUME", "1.00"))

# --- CLOUD STORAGE (CLOUDFLARE R2 / S3-COMPATIBLE) ---
R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "youtube-shorts-clips")
R2_ENDPOINT_URL: str = os.getenv(
    "R2_ENDPOINT_URL",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else ""
)

# Storage Limit: Free tier is 10 GB. Threshold set to 8 GB (8 * 1024^3 bytes)
R2_MAX_BUCKET_BYTES: int = int(os.getenv("R2_MAX_BUCKET_BYTES", str(8 * 1024 * 1024 * 1024)))

# --- YOUTUBE DATA API V3 SETTINGS ---
YOUTUBE_CLIENT_SECRET_FILE: Path = _resolve_path(os.getenv("YOUTUBE_CLIENT_SECRET_FILE", BASE_DIR / "client_secret.json"))
YOUTUBE_TOKEN_FILE: Path = _resolve_path(os.getenv("YOUTUBE_TOKEN_FILE", BASE_DIR / "token.json"))
YOUTUBE_API_SERVICE_NAME: str = "youtube"
YOUTUBE_API_VERSION: str = "v3"
YOUTUBE_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# Strict daily upload limit enforced by YouTube API v3 (~10,000 units quota; upload = ~1,600 units)
MAX_DAILY_UPLOADS: int = int(os.getenv("MAX_DAILY_UPLOADS", "10"))

# --- MULTI-ACCOUNT SUPPORT ---
# accounts.json (in this folder) lets you run several YouTube channels with
# different content and credentials, each with its own quota:
# {
#   "accounts": [
#     {
#       "name": "Gaming",
#       "client_secret": "accounts/gaming/client_secret.json",
#       "token": "accounts/gaming/token.json",
#       "target_channels": ["https://www.youtube.com/@GamingChannel1"],
#       "max_daily_uploads": 10,
#       "aspect": "9:16",
#       "fill": "blur",
#       "shorts_per_video": 1,
#       "enabled": true
#     }
#   ]
# }
# If accounts.json is missing, one default account is used (the global .env
# settings: client_secret.json + token.json + TARGET_CHANNELS).
ACCOUNTS_FILE: Path = BASE_DIR / "accounts.json"


def _load_accounts() -> List[dict]:
    import json as _json
    _log = logging.getLogger("YTShortsBot")

    defaults = {
        "name": "default",
        "client_secret": str(YOUTUBE_CLIENT_SECRET_FILE),
        "token": str(YOUTUBE_TOKEN_FILE),
        "target_channels": TARGET_CHANNELS,
        "max_daily_uploads": MAX_DAILY_UPLOADS,
        "aspect": SHORT_ASPECT,
        "fill": FILL_MODE,
        "shorts_per_video": SHORTS_PER_VIDEO,
        "enabled": True,
    }

    if ACCOUNTS_FILE.exists():
        try:
            data = _json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
            raw = data.get("accounts", []) if isinstance(data, dict) else []
            accounts = []
            for acc in raw:
                if not isinstance(acc, dict) or not acc.get("name"):
                    continue
                merged = dict(defaults)
                merged.update(acc)
                merged["name"] = str(merged["name"]).strip()
                # PER-ACCOUNT CREDENTIAL PATHS (v6.2): every named account gets
                # its OWN accounts/<name>/client_secret.json + token.json.
                # Never default a named account to the bot-ROOT token - the root
                # token belongs to whichever channel was connected last and
                # silently connected every new tab to the WRONG channel.
                _acc_lower = merged["name"].lower()
                if not str(merged.get("client_secret") or "").strip() \
                   or str(merged.get("client_secret") or "").strip() == str(YOUTUBE_CLIENT_SECRET_FILE):
                    merged["client_secret"] = str(BASE_DIR / "accounts" / _acc_lower / "client_secret.json")
                if not str(merged.get("token") or "").strip() \
                   or str(merged.get("token") or "").strip() == str(YOUTUBE_TOKEN_FILE):
                    merged["token"] = str(BASE_DIR / "accounts" / _acc_lower / "token.json")
                # resolve relative credential paths against BASE_DIR,
                # but never let a FOLDER be used as a file path
                for key in ("client_secret", "token"):
                    v = merged.get(key)
                    if v:
                        p = Path(v)
                        p = p if p.is_absolute() else BASE_DIR / p
                        if p.is_dir():  # bad value (folder) - clear it so fallback works
                            merged[key] = ""
                        else:
                            merged[key] = str(p)
                # normalize channels to a list
                ch = merged.get("target_channels")
                if isinstance(ch, str):
                    merged["target_channels"] = [c.strip() for c in ch.split(",") if c.strip()]
                elif isinstance(ch, list):
                    merged["target_channels"] = [str(c).strip() for c in ch if str(c).strip()]
                else:
                    merged["target_channels"] = defaults["target_channels"]
                merged["enabled"] = bool(merged.get("enabled", True))
                merged["max_daily_uploads"] = int(merged.get("max_daily_uploads") or MAX_DAILY_UPLOADS)
                accounts.append(merged)
            # Dedupe by case-insensitive name: duplicate names would make the
            # scheduler run the same channel twice and the panel merge tabs.
            seen, unique_accounts = set(), []
            for a in accounts:
                k = str(a.get("name") or "").strip().lower()
                if not k or k in seen:
                    continue
                seen.add(k)
                unique_accounts.append(a)
            accounts = unique_accounts
            if accounts:
                _log.info(f"Loaded {len(accounts)} account(s) from accounts.json: "
                          + ", ".join(a["name"] for a in accounts))
                return accounts
        except Exception as e:
            _log.error(f"Failed to parse accounts.json ({e}). Using default single account.")

    return [defaults]


# --- SCHEDULER SETTINGS ---
# Cycle interval in hours (e.g. check for new videos every 2 hours)
CYCLE_INTERVAL_HOURS: int = int(os.getenv("CYCLE_INTERVAL_HOURS", "2"))

# --- VIDEO SELECTION ORDER (which videos to pick from a source channel) ---
# "newest" = most recent first (default) | "oldest" = oldest first | "random" = random order.
# The bot NEVER posts the same video twice to the same account (tracked in bot_state.db).
SELECTION_ORDER: str = os.getenv("SELECTION_ORDER", "newest").strip().lower()
if SELECTION_ORDER not in ("newest", "oldest", "random"):
    SELECTION_ORDER = "newest"

# --- DELETE AFTER UPLOAD ---
# DELETE_AFTER_UPLOAD = "true" -> delete the local finished_shorts copy (+ .txt
# sidecar) as soon as the video is successfully uploaded to YouTube.
# DELETE_R2_AFTER_UPLOAD = "true" -> also delete the R2 backup after upload.
# Both can be overridden per-account in the Settings panel.
DELETE_AFTER_UPLOAD: bool = os.getenv("DELETE_AFTER_UPLOAD", "false").lower() == "true"
DELETE_R2_AFTER_UPLOAD: bool = os.getenv("DELETE_R2_AFTER_UPLOAD", "false").lower() == "true"

# --- WATERMARK STYLE ---
# Top watermark: PLAIN TEXT only - no background band, no border, no shadow.
#   color "white" (or any ffmpeg color), opacity 0.5 = 50% visible.
TOP_WATERMARK_COLOR: str = os.getenv("TOP_WATERMARK_COLOR", "white")
TOP_WATERMARK_OPACITY: float = float(os.getenv("TOP_WATERMARK_OPACITY", "0.5"))
TOP_WATERMARK_FONT_SIZE: int = int(os.getenv("TOP_WATERMARK_FONT_SIZE", "56"))
TOP_WATERMARK_ITALIC: bool = os.getenv("TOP_WATERMARK_ITALIC", "true").lower() == "true"
# Vertical position of the top watermark as % of screen height.
# The top blur band is roughly the top ~10-30% of the screen, so ~12 = nicely
# inside the top blur area, horizontally centered (x is always centered).
TOP_WATERMARK_Y_PCT: float = float(os.getenv("TOP_WATERMARK_Y_PCT", "12"))
# Bottom banner: PLAIN TEXT only, 100% visible.
BOTTOM_BANNER_FONT_SIZE: int = int(os.getenv("BOTTOM_BANNER_FONT_SIZE", "56"))
BOTTOM_BANNER_OPACITY: float = float(os.getenv("BOTTOM_BANNER_OPACITY", "1.0"))
BOTTOM_BANNER_ITALIC: bool = os.getenv("BOTTOM_BANNER_ITALIC", "true").lower() == "true"
# Vertical position of the bottom text as % of screen height (90 = near bottom)
BOTTOM_BANNER_Y_PCT: float = float(os.getenv("BOTTOM_BANNER_Y_PCT", "90"))
TOP_WATERMARK_BAND: bool = os.getenv("TOP_WATERMARK_BAND", "false").lower() == "true"

# How many Shorts to make from each new video in automatic cycles.
# 1 = only the single best moment (heatmap peak / audio-energy peak).
# 2-5 = the top N non-overlapping best moments from that video.
SHORTS_PER_VIDEO: int = int(os.getenv("SHORTS_PER_VIDEO", "1"))

# --- KEEP LOCAL COPIES OF FINISHED SHORTS ---
# When True, every finished Short is ALSO saved into KEEP_SHORTS_DIR before the
# bot deletes its working files (handy if you want to review what it made).
# Disable to save disk space (the Short still goes to R2 / YouTube).
KEEP_LOCAL_SHORTS: bool = os.getenv("KEEP_LOCAL_SHORTS", "true").lower() == "true"
KEEP_SHORTS_DIR: Path = _resolve_path(os.getenv("KEEP_SHORTS_DIR", BASE_DIR / "finished_shorts"))
KEEP_SHORTS_DIR.mkdir(parents=True, exist_ok=True)

# Load multi-account config AFTER all defaults are defined
ACCOUNTS: List[dict] = _load_accounts()

# --- YOUTUBE COOKIES (fixes "Sign in to confirm you're not a bot") ---
# Option 1: YT_COOKIES_FILE - path to a cookies.txt file exported from your browser
#           (Netscape format - use the "Get cookies.txt LOCALLY" browser extension,
#           go to youtube.com, export, and drop the file here).
# Option 2: YT_COOKIES_FROM_BROWSER - read cookies straight from an installed
#           browser: "chrome", "edge", "firefox", "opera", "brave".
#           NOTE: the browser must be fully CLOSED for Chrome/Edge to work.
# Leave both empty to run without cookies (may trigger bot checks).
YT_COOKIES_FILE: str = os.getenv("YT_COOKIES_FILE", "")
YT_COOKIES_FROM_BROWSER: str = os.getenv("YT_COOKIES_FROM_BROWSER", "")

# --- WEB CONTROL PANEL (webui) ---
WEBUI_HOST: str = os.getenv("WEBUI_HOST", "0.0.0.0")
WEBUI_PORT: int = int(os.getenv("WEBUI_PORT", "5000"))

# --- SMART TITLES & HASHTAGS (free, content-aware) ---
# The bot generates the Short title + hashtags from the source video's
# title/description/tags/channel and the CPU transcription - no paid AI.
ENABLE_SMART_TITLES: bool = os.getenv("ENABLE_SMART_TITLES", "true").lower() == "true"
MAX_TITLE_HASHTAGS: int = int(os.getenv("MAX_TITLE_HASHTAGS", "4"))
REACH_HASHTAGS: str = os.getenv("REACH_HASHTAGS", "shorts,viral,fyp,trending")
EXTRA_HASHTAGS: str = os.getenv("EXTRA_HASHTAGS", "")
TITLE_PREFIX: str = os.getenv("TITLE_PREFIX", "")
def setup_logging(log_level: int = logging.INFO) -> logging.Logger:
    """
    Configures robust logging with both colored console output and rotating file log.
    Tracks API limits, errors, bucket usage, and bot status.
    """
    logger = logging.getLogger("YTShortsBot")
    logger.setLevel(log_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(module)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating file handler (10 MB max per file, 5 backups)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not initialize rotating file logger: {e}")

    return logger

# Global logger instance
logger = setup_logging()

# ---------------------------------------------------------------------------
# FFMPEG / FFPROBE RESOLUTION
# The bot needs ffmpeg + ffprobe for video cutting, cropping, and subtitle burning.
# Resolution order (first hit wins):
#   1. FFMPEG_PATH / FFPROBE_PATH from .env or environment
#   2. A bundled local copy in  yt_shorts_bot/ffmpeg/bin/  (setup.bat downloads
#      this automatically on Windows when a system FFmpeg is missing)
#   3. Any ffmpeg/ffprobe already on the system PATH
# ---------------------------------------------------------------------------

def _find_binary(name: str):
    """Returns the full path to `name` (ffmpeg/ffprobe) or None if not found."""
    env_key = "FFMPEG_PATH" if name == "ffmpeg" else "FFPROBE_PATH"
    env_val = os.getenv(env_key)
    if env_val:
        p = _resolve_path(env_val)
        if p.exists():
            return str(p)
        logger.warning(f"{env_key} is set to '{env_val}' but that file does not exist; falling back.")

    local = BASE_DIR / "ffmpeg" / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if local.exists():
        return str(local)

    import shutil
    return shutil.which(name)


FFMPEG_PATH = _find_binary("ffmpeg")
FFPROBE_PATH = _find_binary("ffprobe")

if not FFMPEG_PATH:
    logger.warning(
        "FFmpeg was not found. Install it (run setup.bat / setup.sh) or put ffmpeg.exe "
        "in yt_shorts_bot/ffmpeg/bin/ so the bot can render videos."
    )
else:
    logger.debug(f"Using FFmpeg: {FFMPEG_PATH}")
    logger.debug(f"Using FFprobe: {FFPROBE_PATH}")
