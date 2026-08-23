# 🔁 YouTube Shorts Repost Bot

A second, separate 24/7 bot that **scans channels, downloads their Shorts, and
uploads them to YOUR channel** — with its own control panel, quota tracking,
and Windows one-click installers. It lives in its own folder so it never
interferes with the clip-farming bot.

## What it does
1. Scans your `TARGET_CHANNELS` (newest Shorts first, Shorts = ≤60s).
2. Downloads each Short **in full** (up to 4K source, small files).
3. Prepares it:
   - `PROCESS_MODE="copy"` (default): re-encodes to a clean mp4 (h264+aac),
     keeping the Short's original look — fast.
   - `PROCESS_MODE="render"`: transcribes + burns viral subtitles + adds BGM,
     like the clip bot (slower).
4. Keeps a copy in `finished_shorts/`, optionally backs up to Cloudflare R2.
5. Uploads to your channel via YouTube Data API v3, respecting the
   **10 uploads/24h** cap (SQLite-tracked).
6. Runs 24/7 (cycle every 3h by default) with a web control panel.

## Windows quickstart
1. Copy this whole `yt_shorts_repost_bot` folder to your PC (e.g. `F:\youtube 2\`).
2. Double-click **`setup.bat`** — installs FFmpeg + Python packages + creates `.env`.
3. Optional: edit `.env` with Notepad — set `TARGET_CHANNELS` to the channels
   you want to grab Shorts from, add `YT_COOKIES_FILE="cookies.txt"` if YouTube
   shows a bot-check, drop `client_secret.json` here for real uploads.
4. Double-click **`run_ui.bat`** — control panel opens at `http://127.0.0.1:5100`.

## Commands (Linux/macOS)
```bash
bash setup.sh                      # one-time install
./run_bot.sh --mode once           # one scan+repost cycle
./run_bot.sh --mode scheduler      # 24/7 loop
./run_bot.sh --mode process-url --url "https://www.youtube.com/shorts/XXX"
./run_bot.sh --mode status
./run_bot.sh --mode webui          # control panel
```

## Notes & warnings
- **Copyright:** reposting other people's Shorts without permission violates
  copyright and YouTube's rules — channels doing this get strikes/banned.
  Only repost content you own or have rights to.
- YouTube's API quota (~10,000 units/day; ~1,600 per upload) caps real uploads
  around 6–10/day regardless of `MAX_DAILY_UPLOADS`. Shorts over the cap are
  saved locally + R2 for later.
- Cookies expire: if you see "Sign in to confirm you're not a bot", re-export
  `cookies.txt` from a logged-in browser session.

---

## 👥 Multi-account (post to several channels)

1. Copy `accounts.example.json` → `accounts.json` in this folder.
2. Edit it: one entry per channel you own (name, its client_secret/token
   paths, its source channels, its max uploads/day, its process_mode).
3. Put each channel's `client_secret.json` into `accounts/<name>/`; the bot
   runs Google's auth flow on first upload and saves token.json there.
4. Restart. The control panel shows an **Accounts** section + account dropdown
   on "Repost a specific Short".
5. CLI: `--mode once --account Gaming` runs only that account; without
   `--account` all enabled accounts run.

### Per-account watermark

In `accounts.json`, each account can carry its own banner text:

```json
{
  "name": "Comedy",
  ...
  "process_mode": "render",
  "watermark": "SUBSCRIBE FOR LAUGHS",
  "watermark_enabled": true
}
```

Note: the watermark only renders in `"process_mode": "render"` (re-encode +
subtitles). In `"copy"` mode the original Short is kept untouched, so no
banner is added.

### Top channel watermark (light) + bottom LIKE & SUBSCRIBE

In `accounts.json`, each account can set a light top watermark (channel name)
and a bottom banner:
```json
{
  "name": "Comedy",
  "process_mode": "render",
  "top_watermark": "COMEDY CLIPS",
  "top_watermark_enabled": true,
  "watermark": "SUBSCRIBE FOR LAUGHS",
  "watermark_enabled": true
}
```
Global defaults live in `.env` (`TOP_WATERMARK_TEXT`, `LIKE_AND_SUBSCRIBE_TEXT`).
Watermarks only apply in `"process_mode": "render"`.

### Smart titles & hashtags (free, content-aware)

Same as the clip bot: for each reposted Short the bot pulls the source's
title/description/tags/channel/category and builds a catchy title + reach
hashtags (e.g. `#simpsons #bart #homer #shorts #viral`). Per-account:
`"extra_hashtags": "comedy, funny"` in `accounts.json`; globals in `.env`
(`ENABLE_SMART_TITLES`, `REACH_HASHTAGS`, `EXTRA_HASHTAGS`, `TITLE_PREFIX`).


### Video selection order

The bot picks which video to process from each source channel in this order:
- **newest** (default): most recent first
- **oldest**: oldest first
- **random**: shuffled each cycle

Set it globally in `.env` (`SELECTION_ORDER="newest|oldest|random"`) or per-account
in the Settings panel (each "My Channel" box has its own order dropdown).
**A video is never posted twice to the same account** - the bot records every
upload in `bot_state.db` (keyed by account) and skips anything already done.


### Upload pacing (min minutes between uploads)

In Settings → Account settings, `Min minutes between uploads` sets the gap between
uploads for that account: **0** = post as fast as possible, **60** = one per hour.
The bot waits that long between uploads (measured from the previous upload's time),
so 10 uploads with a 60-min gap takes ~9 hours. Respects Max uploads/day too.


### Delete after upload

Per-account toggles (Settings → Account settings):
- **Delete local copy after upload** - removes the finished_shorts .mp4 + .txt
  sidecar as soon as the Short is successfully uploaded to YouTube (keeps disk clean).
- **Delete R2 backup after upload** - also deletes the Cloudflare R2 copy after upload.

Both default off; enable per account. Temp working files are always deleted anyway.
