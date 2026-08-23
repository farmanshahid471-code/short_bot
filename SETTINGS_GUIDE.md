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
| `title_prefix` | Optional text before the clean source title. |
| `title_hashtags` | The only hashtags appended to titles/descriptions. |
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
{title_prefix} {clean source title} {user title_hashtags}
```

No reach/content hashtags are inferred. Legacy `smart_titles` names remain for
file compatibility but do not change this behavior. Metadata sidecars use the
exact metadata object used for the upload attempt.
