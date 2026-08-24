# Settings guide

## Account tabs

One tab is one destination channel. Settings are stored in ignored
`yt_shorts_bot/accounts.json` or `yt_shorts_repost_bot/accounts.json`.

| Account field | Meaning |
|---|---|
| `name` | Local display name; path separators are rejected. |
| `target_channels` | Sources owned/licensed by you. Empty means the account is skipped. |
| `enabled` | Whether automatic cycles include this account. |
| `client_secret` / `token` | Project-relative, isolated OAuth files. |
| `connected_channel` | Channel title observed at connection time. |
| `connected_channel_id` | Immutable ID used by the upload safety lock. |
| `expected_channel` | Exact fallback title lock when no channel ID is available. |
| `max_daily_uploads` | Local rolling 24-hour cap for real successful uploads. |
| `selection_order` | `newest`, `oldest`, or `random`. |
| `min_minutes_between_uploads` | Interruptible delay from the previous real upload. |
| `posting_timezone` | IANA US zone used for this tab's automatic posting window. |
| `posting_start_time` | Inclusive local `HH:MM` opening time. |
| `posting_end_time` | Exclusive local `HH:MM` closing time. |
| `title_prefix` | Optional text before the generated title. |
| `title_hashtags` | The only hashtags appended to titles/descriptions. |
| `smart_titles` | When on, invent a new title from the source title + transcript/description. Off keeps the cleaned source title. Hashtags stay user-typed either way. |
| `watermark` | Bottom text in render mode. Empty text stays off. |
| `top_watermark` | Top text in render mode. Empty text stays off. |
| `aspect` | `auto`, `3:4`, or `9:16`. |
| `fill` | `crop` or `blur`. |
| `subtitles_enabled` | Clip default true; repost default false. |
| `delete_after_upload` | Delete local review copy after a real upload only. |
| `delete_r2_after_upload` | Delete optional R2 backup after a real upload only. |

The repost bot additionally uses `process_mode` (`copy` or `render`) and
`max_shorts_per_channel_cycle`. The clip bot uses `shorts_per_video` and optional
logo-removal fields.

### Posting-window examples

```ini
# Pacific local time, 5 AM through 5 PM
posting_timezone = America/Los_Angeles
posting_start_time = 05:00
posting_end_time = 17:00
```

These values are account fields saved by the panel, not global `.env` values.
Daylight-saving time is automatic. An overnight range (`17:00`–`05:00`) crosses
midnight. Empty values or equal start/end permit 24/7 posting. Invalid or partial
settings fail closed and the account is skipped.

Start Scheduler and Stop Scheduler are global controls for all enabled tabs.
Every tab still has an independent posting window. Manual specific-URL processing
overrides the window; automatic cycles do not.

## Upload states

| State | Terminal? | Meaning |
|---|---:|---|
| `PENDING_UPLOAD` | No | Video prepared; upload not yet confirmed. |
| `QUOTA_WAIT` | No | Local/API quota prevented upload. |
| `AUTH_REQUIRED` | No | Credentials must be connected/repaired. |
| `CHANNEL_MISMATCH` | No | Destination lock blocked the attempt. |
| `DRY_RUN_READY` | No | Explicit preview; no API call/quota record. |
| `UPLOAD_FAILED` | No | YouTube attempt failed. |
| `PROCESSING_FAILED` | No | Download/render failed. |
| `UPLOADED_YOUTUBE` | Yes | Real YouTube ID was returned and recorded. |
| `PROCESSED_MULTI` | Yes | Every requested part was uploaded. |

## Important global settings

### Safety and operation

```ini
DRY_RUN=false
MAX_DAILY_UPLOADS=10
CYCLE_INTERVAL_HOURS=2
KEEP_LOCAL_SHORTS=true
DELETE_AFTER_UPLOAD=false
DELETE_R2_AFTER_UPLOAD=false
```

`DRY_RUN=true` never records uploads. The scheduler reloads account settings and
the interval before later cycles. Stop interrupts interval and pacing waits.

### Web UI

```ini
WEBUI_HOST="127.0.0.1"
WEBUI_PORT=5000
WEBUI_USERNAME="admin"
WEBUI_PASSWORD=""
WEBUI_SECRET_KEY=""
WEBUI_COOKIE_SECURE=false
```

A non-local host requires a password. Use HTTPS/SSH tunnelling remotely. Every
state-changing form also requires a CSRF token.

### Rendering

```ini
SHORT_ASPECT="3:4"
FILL_MODE="blur"
VIDEO_CRF=18
VIDEO_PRESET="medium"
AUDIO_BITRATE="192k"
FFMPEG_TIMEOUT_SEC=900
WHISPER_MODEL_SIZE="tiny.en"
WHISPER_LANGUAGE="auto"
SUBTITLE_STYLE_MODE="viral"
```

`auto` preserves vertical source shape. Landscape/square sources use 9:16.
Whisper is imported only when subtitles are requested. Sources without audio
skip transcription and can still render.

### Text style

```ini
TOP_WATERMARK_COLOR="white"
TOP_WATERMARK_OPACITY=0.5
TOP_WATERMARK_FONT_SIZE=56
TOP_WATERMARK_Y_PCT=12
BOTTOM_BANNER_FONT_SIZE=56
BOTTOM_BANNER_OPACITY=1.0
BOTTOM_BANNER_Y_PCT=90
```

Overlay text is read by FFmpeg from controlled UTF-8 text files, so punctuation
cannot alter the filter graph.

### Optional R2

```ini
R2_ACCOUNT_ID=""
R2_ACCESS_KEY_ID=""
R2_SECRET_ACCESS_KEY=""
R2_BUCKET_NAME="youtube-shorts-clips"
R2_ENDPOINT_URL=""
R2_MAX_BUCKET_BYTES=8589934592
```

Blank credentials skip R2. Pruning only touches `shorts/` and `reposts/` keys.

### Download cookies

```ini
YT_COOKIES_FILE=""
YT_COOKIES_FROM_BROWSER=""
```

Cookies are private credentials. Keep exported files ignored and rotate them if
an older repository commit exposed them.

## Metadata guarantee

The published title is:

```text
{title_prefix} {title body} {user title_hashtags}
```

With `smart_titles` on (the default), the title body is rewritten from the
source title plus spoken words or the video description so it is not a copy
of the original. With it off, the body is the cleaned source title.

No reach/content hashtags are inferred. Metadata sidecars use the exact
metadata object used for the upload attempt.
