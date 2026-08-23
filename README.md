# YouTube Shorts Clip and Repost Bots

This repository contains two independent Python applications:

- **`yt_shorts_bot`** selects high-engagement 15–20 second windows from regular
  YouTube videos, transcribes them, renders vertical clips, and uploads them.
- **`yt_shorts_repost_bot`** downloads complete Shorts and either cleanly
  re-encodes them (`copy`) or renders overlays/captions/music (`render`).

Only process and upload media you own or have permission to reuse.

## Security first

Private/runtime files are intentionally ignored by Git: `.env`, `accounts.json`,
OAuth clients/tokens, cookies, DBs, logs, generated videos and downloaded FFmpeg
binaries. See [SECURITY.md](SECURITY.md) for the mandatory credential-rotation
and old-history cleanup steps if an older checkout exposed them.

The control panels listen on `127.0.0.1` by default. A non-local bind is refused
unless `WEBUI_PASSWORD` is configured. Use HTTPS or an SSH tunnel for remote
access.

## Installation

### Linux

```bash
bash setup.sh
cp yt_shorts_bot/.env.example yt_shorts_bot/.env
# edit yt_shorts_bot/.env, then:
./run_bot.sh --mode webui
```

`setup.sh` installs FFmpeg through the Debian/Ubuntu package manager and creates
`.venv`. On other distributions, install a full FFmpeg build (including
`drawtext`, `subtitles`, libfreetype/fontconfig and libass) yourself first.

### Windows

1. Run `setup.bat` once.
2. Run `run_ui.bat` for the clip bot.
3. Run `yt_shorts_repost_bot\setup.bat` and then its `run_ui.bat` for the repost
   bot.

The Windows setup scripts download a local FFmpeg build when one is not already
available. Downloaded binaries are not committed.

## Account model

One account tab represents one YouTube destination channel. Account settings are
stored locally in each bot's ignored `accounts.json`. A typical account is:

```json
{
  "name": "Gaming",
  "client_secret": "accounts/gaming/client_secret.json",
  "token": "accounts/gaming/token.json",
  "target_channels": ["https://www.youtube.com/@OwnedSource/shorts"],
  "connected_channel": "My Gaming Channel",
  "connected_channel_id": "UC...",
  "expected_channel": "My Gaming Channel",
  "max_daily_uploads": 6,
  "enabled": true
}
```

Credential paths are stored project-relative and normalized to a traversal-safe
account folder. Each account must have its own token. The destination safety lock
is mandatory for uploads and is populated when **Connect / Test YouTube** succeeds.
The lock checks the immutable channel ID when available, otherwise an exact
channel-title match. Verification errors block uploads rather than failing open.

An explicitly empty `target_channels` list means **do nothing**. Named accounts
never fall back to packaged example channels.

## Clip-bot pipeline

```text
channel scan
  -> heatmap best window
     (audio-energy fallback when no heatmap exists)
  -> section download
  -> optional faster-whisper transcription
  -> vertical FFmpeg render
  -> local review copy
  -> optional R2 backup
  -> destination verification
  -> atomic quota reservation
  -> YouTube upload
  -> SQLite state update
```

Multiple windows can be selected from one source. Completed parts are skipped on
retry, while failed/quota-waiting parts remain retryable.

## Repost-bot pipeline

```text
Shorts feed scan
  -> full Short download and duration verification
  -> copy mode OR render mode
  -> local review copy
  -> optional R2 backup
  -> destination verification
  -> atomic quota reservation
  -> YouTube upload
  -> SQLite state update
```

- `copy`: H.264/AAC re-encode, no new overlays.
- `render`: vertical fit, optional captions, BGM, logo blur and account text.

## Real uploads, dry-run and retry states

`DRY_RUN=true` is an explicit preview mode. It prepares the video and metadata
but does **not**:

- call the YouTube upload API;
- insert a `daily_uploads` row;
- consume a local quota slot; or
- mark the source as uploaded.

Missing/broken OAuth is `AUTH_REQUIRED`, not a fake success. Quota-limited files
are `QUOTA_WAIT`; API failures are `UPLOAD_FAILED`; R2-only work is
`PENDING_UPLOAD`. Those states remain retryable. Only `UPLOADED_YOUTUBE` (and
completed multi-part records) are terminal.

A retry currently reconstructs the source when needed; review copies remain in
`finished_shorts` unless delete-after-upload is enabled.

## Concurrency and state

SQLite uses WAL mode and a busy timeout. Processing leases atomically prevent two
workers from handling the same `(video_id, account)`. Upload reservations make
the rolling local limit safe across concurrent workers, and upload rows are
unique per source/account.

Within one bot process, full pipelines are serialized because they share an
encoder and temp area. Temporary filenames also include random job IDs. The clip
and repost bots use separate state and can run independently.

The 24/7 loop reloads `accounts.json` before every cycle. Its interval is read
again from `.env`, and Stop interrupts both the interval wait and upload-pacing
wait. An active FFmpeg/API call finishes before shutdown.

## Video behavior

- `auto` preserves a vertical source's shape. Landscape/square input is forced
  into a 9:16 canvas so the result remains a vertical Short.
- Audio mapping is optional; silent sources no longer fail rendering.
- Overlay text is passed through temporary UTF-8 text files rather than injected
  into FFmpeg filter syntax.
- Subtitle paths are copied to controlled filenames before filtering.
- FFmpeg capabilities are checked before rendering and every render has a timeout.
- `WHISPER_LANGUAGE=auto` enables language detection. Set a language code only
  when every source uses it.
- The repost bot lazily imports Whisper only when captions are requested.
- yt-dlp client retries use `extractor_args` and partial fragments are removed.

## Titles, hashtags and sidecars

Metadata is deliberately user-controlled:

```text
{title_prefix} {clean source title} {title_hashtags}
```

The bot does not infer or silently add reach/content hashtags. Legacy
`smart_titles` configuration names are accepted for compatibility but do not
change that guarantee. A clean source-channel handle may be added as a YouTube
API tag; generic URL suffixes such as `/shorts` and `/videos` are excluded.

Each `.txt` sidecar is generated from the exact metadata object used by the
upload attempt, including prefix, part label and account hashtags.

## Optional Cloudflare R2

R2 is a backup, not a requirement. If credentials are blank, backup is skipped
without reporting a simulated success. Before upload, the incoming file is
included in the storage-limit calculation. Automatic pruning only deletes bot
objects under `shorts/` or `reposts/`; unrelated bucket objects are never deleted.
If usage cannot be measured safely, backup upload is refused.

## CLI

Clip bot:

```bash
./run_bot.sh --mode status
./run_bot.sh --mode once --account Gaming
./run_bot.sh --mode scheduler
./run_bot.sh --mode process-url --account Gaming --url "https://www.youtube.com/watch?v=..."
./run_bot.sh --mode webui
```

Repost bot:

```bash
cd yt_shorts_repost_bot
./run_bot.sh --mode status
./run_bot.sh --mode once --account Gaming
./run_bot.sh --mode scheduler
./run_bot.sh --mode process-url --account Gaming --url "https://www.youtube.com/shorts/..."
./run_bot.sh --mode webui
```

When multiple accounts exist, a destination account is required for a specific
URL. CLI account matching is case-insensitive. `--channels` overrides the sources
of the selected account(s) for that process.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Tests use temporary databases/directories and never modify real accounts,
credentials, logs or generated output.
