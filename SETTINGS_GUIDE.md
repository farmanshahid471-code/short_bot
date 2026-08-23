# 📖 Settings Guide — Every Setting Explained & Tested
**For both bots:** 🎬 `yt_shorts_bot` (clip farmer) and 🔁 `yt_shorts_repost_bot` (Short reposter)

This guide walks through **every single setting** in the control panel, what it does,
where it's stored, and how it affects what gets uploaded to YouTube. Everything below
was **actually tested** (111 automated checks: account handling, title/hashtag building,
video rendering with pixel-level watermark position checks, quota, deletion, never-post-twice).

> Version: v5.4+ (Aug 16). Open the panel with `run_ui.bat` (Windows) or
> `./run_bot.sh --mode webui` (Linux). Clip bot = port **5000**, repost bot = port **5100**.

---

## 🗂 0. The Big Idea: one TAB = one YouTube channel

> ### ⚠️ THE #1 RULE: one YouTube channel = one Google account
> A Google OAuth login can only upload to **its own channel(s)** — and if an
> account owns several channels, uploads always go to the **primary** one.
> That's why "ACCOUNT 'PeterAKing' is connected to CHANNEL 'Simpson Pimp'"
> means: **the Google login used in the PeterAKing tab belongs to the Simpson
> Pimp channel** (both channels under one account, or signed in with the wrong
> account). The bot cannot guess which channel you meant — so:
> 1. Give each channel its own Google account (e.g. `peteraking@gmail.com` owns
>    ONLY the PeterAKing channel).
> 2. Connect that tab signed in with THAT account.
> 3. Type the channel title in **"Expected channel (safety lock)"** — the bot
>    then refuses to upload if the login ever points at a different channel.

The panel looks like a Chrome browser. **Every tab is one of YOUR channels.**

| Concept | What it means |
|---|---|
| **Tab** | One channel you own + its own settings + its own Google login |
| **Green dot** on a tab | That channel is connected (token.json exists) |
| **Yellow dot** | Account is turned OFF (enabled unchecked) |
| **Grey dot** | Not connected to YouTube yet |
| **+ tab** | Add another channel — as many as you want |

Each tab has 3 boxes:
1. **🔑 Credentials** — which Google account this tab uploads to
2. **⚙️ Settings** — how Shorts look + upload pacing for this tab
3. **📁 Source channels** — which channels this tab takes videos FROM

> Everything is saved in **`accounts.json`** (next to the bot). It survives restarts.
> Deleting a tab removes that channel from `accounts.json` (its token file stays on disk
> unless you delete it yourself).

### Adding / deleting accounts (tested ✅)
- **Add:** click the **`+`** tab → "New Channel N" appears. Do this 10 times = 10 channels.
- **Delete:** open the tab → red **🗑 Delete this account** button. Other tabs are untouched.
- **Turn off (but keep):** uncheck **enabled** in "Source channels" → the bot skips it.
- **Rename:** edit the account name in `accounts.json` (the panel keeps the name in a hidden field).
  Renaming keeps credentials + connection.

### 🔑 Connecting a channel — YOUR case: one separate Google account per channel
You said you'll use **whole separate Google Cloud accounts** (not one account with many
projects) — that's fully supported and actually the cleanest setup:

1. Create a separate Google account for each channel (e.g. `channel1@gmail.com`, `channel2@gmail.com`…).
2. In **that** Google account, go to **console.cloud.google.com** → create **one project per channel**
   (this is still the normal Google Cloud way — each project lives inside that account).
3. Enable **YouTube Data API v3**, create the **OAuth consent screen** (add that same Google
   account email to Test users), create an **OAuth Client ID (Desktop app)**, **Download JSON**.
   *(Full click-by-click steps: `SETUP_YOUTUBE.md`.)*
4. In the bot: open that channel's tab → **Upload client_secret.json** → **Connect / Test YouTube** →
   sign in with **that channel's own Google account** → Allow.
5. Repeat per tab. Each tab now has its own `token.json` = its own channel.

> Per-channel files live in `accounts/<name>/client_secret.json` + `token.json`.
> If you only ever upload ONE file to the bot root, every tab falls back to it, and the
> **Connect** step decides which channel each tab posts to.
> ⚠️ Testing-mode tokens expire (~7 days): if a tab stops uploading, press **Connect** again
> and re-login — the account's own settings are kept.

---

## 🎬 CLIP BOT (`yt_shorts_bot`) — Settings

### ⚙️ Settings for this account (per tab)

| Setting (exact UI label) | What it does | Verified behavior |
|---|---|---|
| **Title prefix** | Text added at the START of every Short title. **Empty = no prefix, no emoji.** | `"🔥"` → `🔥 Video Title #tag`; `""` → `Video Title #tag` (tested: empty stays empty) |
| **Title hashtags** | **The ONLY hashtags the bot ever uses.** Comma or space separated, `#` optional. Empty = **NO hashtags anywhere**. | `simpsons, homer, bart` → title ends `…#simpsons #homer #bart`, description repeats them (tested: no auto/reach/content tags ever) |
| **Smart titles** | When ON, the description also gets content keywords from the source video's title/description/tags + the CPU transcription (free, local). It NEVER adds hashtags. | Only affects description text; title and hashtags untouched |
| **Max uploads / day** | This tab's rolling 24h upload cap (YouTube quota is per Google account: ~10,000 API units/day ≈ 6–10 uploads). | Tested: at the cap the bot stops and queues the clip for the next window |
| **Shorts per video (auto cycles)** | How many Shorts to make from ONE source video: 1 = the single best heatmap moment; 2–5 = the top N best moments. | Multi-part Shorts get "Part 1 - …" in the title; DB tracks each part separately (never re-posted) |
| **Min minutes between uploads** | Minimum gap between this tab's uploads. 0 = as fast as possible; 60 = one per hour; 120 = one per 2h. | Tested: upload #2 waits if the last upload was less than N minutes ago |
| **Top watermark** | Light channel-name text, **plain text only — no box/band/shadow**, centered in the TOP blur area. Empty = **no top watermark** (an empty field stays empty — no auto account-name fallback anymore). | Tested at pixel level: 3:4 → y≈139px (12% of height), horizontally centered ±4%, white at 50% opacity (bright but not full-white), italic |
| **Top watermark on** | Master switch for the top text. | Unchecking removes it even if text is set |
| **Bottom banner text** | Bottom text, **plain text only**, near the bottom edge (usually "LIKE & SUBSCRIBE" or your channel name). | Tested: y≈1262px (90% of height) in 3:4, white at 100% opacity (pure white), italic, no background |
| **Bottom banner on** | Master switch for the bottom text. | Unchecking removes it |
| **Aspect ratio** | `3:4` = 1080×1440 (the iShowSpeed/deagzzzshorts edit style) · `9:16` = 1080×1920 (classic Shorts). | Tested with ffprobe: both outputs exactly 1080×1440 / 1080×1920 |
| **Fill mode** | `Blur` = whole frame visible, blurred background fills the rest, **nothing is cut**. `Crop` = center-crop to fill, **edges are cut**. | Tested with a white bar at the frame edge: blur keeps it, crop removes it |
| **Delete local copy after upload** | ON = the local copy in `finished_shorts/` **and its .txt sidecar** are deleted as soon as YouTube confirms the upload. OFF = copies stay for review. | Tested end-to-end: file + sidecar gone after upload; the Short stays on YouTube |
| **Delete R2 backup after upload** | ON = also delete the Cloudflare R2 backup of the Short after upload. (Requires real R2 credentials; in dry-run nothing is deleted — no crash.) | Tested: safe when R2 is not configured |
| **Burn subtitles (render mode)** | 🔁 REPOST BOT: OFF by default = render burns **watermarks only** (source Shorts already have captions baked in — no re-transcription, faster). ON = also transcribe + burn viral subtitles. 🎬 CLIP BOT: ON by default (subtitles are the point of clip farming). | Tested at pixel level: OFF = no subtitle text in the middle band, watermarks still burned, zero transcription calls |
| **Expected channel (safety lock)** | Type the exact channel title this tab should upload to. Before EVERY upload the bot verifies the connected Google login really owns that channel — if not, the upload is **BLOCKED** with a clear error. This is the guard that would have stopped "PeterAKing tab → posted to Simpson Pimp". | Tested: mismatched login → upload returns None, zero API calls; matching login → upload proceeds |
| **Bot cycle interval (hours, whole bot)** | How often the 24/7 scheduler scans source channels (all tabs share this one). 1 = check every hour. | Saved to `.env` as `CYCLE_INTERVAL_HOURS` |

### 🔑 Credentials (per tab)
| UI element | What it does |
|---|---|
| **Upload client_secret.json** | v5.7: saves into **`accounts/<tab-name>/client_secret.json`** — ONLY for that tab — and points the tab's account at it. The shared bot-root file is only a fallback. (Older builds always saved to the bot root and overwrote the shared file.) |
| **Connect / Test YouTube** | Runs the Google login for THIS tab → saves `accounts/<name>/token.json` → prints which channel it's connected to. |
| Status line | ✅/❌ client_secret present · ✅/❌ token present · 📁 this tab's secret path · 🔑 this tab's token path |

### 📁 Source channels for this account
| Field | What it does |
|---|---|
| **Text area** | Channels this tab **downloads FROM**, one per line (URLs or @handles). Its own channel = where it uploads. |
| **uploads/day** | Same as "Max uploads / day" — a quick copy in this box. |
| **mode** | ⚙️ CLIP BOT: this select is for the **repost bot**. The clip bot always renders (subtitles + watermarks). |
| **order** | Which video to pick from each source channel: `newest first` / `oldest first` / `random` / `order: global` (uses `.env` `SELECTION_ORDER`). Tested: resets back to "global" work. |
| **enabled** | Uncheck to pause this tab without deleting it. |

> ✅ **Tested fix:** saving "Source channels" on ONE tab **no longer deletes the other tabs**
> (a serious bug found during this review — older builds wiped `accounts.json`).

### ▶ Run the bot (shared, all tabs)
| Button | What it does |
|---|---|
| **Run One Cycle Now** | Scans every enabled tab's source channels once, processes + uploads everything allowed right now. |
| **Start 24/7 Scheduler** | Runs a cycle immediately, then repeats every "cycle interval" hours forever. |
| **Stop Scheduler** | Stops the loop (current upload finishes). |

### 🔗 Repost one specific Short
Paste any Short URL → pick which tab (account) should own it → the clip bot makes a clip
from it with **that tab's** settings (watermark, hashtags, prefix…) and uploads to that tab's channel.

### 📁 Finished Shorts
Every finished Short appears here with a **matching `.txt` sidecar** showing the exact
title / description / tags that were (or would be) uploaded — handy in dry-run mode.
Click a name to watch it in the browser.

---

## 🔁 REPOST BOT (`yt_shorts_repost_bot`) — Settings

Everything from the clip bot applies, with these differences:

| Setting | Difference vs clip bot |
|---|---|
| **Max shorts per channel / cycle** | How many Shorts to repost from ONE source channel per cycle (e.g. 2). Total is still capped by "Max uploads / day". Tested: with 1, exactly one Short is posted per channel per cycle. |
| **mode** (in Source channels) | **`copy (keep original - NO watermark)`** = re-encode to a clean mp4, keeps the Short's original look 1:1 (fast, safe). **`render (subtitles+watermark)`** = transcribe + burn viral subtitles + add THIS TAB'S watermarks + BGM (slower). |
| Shorts per video | Not used (a Short is already a Short — no heatmap clipping). |

> ⚠️ **Watermarks only apply in `render` mode.** If you set watermarks but the tab is in
> `copy` mode, the bot logs a warning: "Watermarks are configured … but process_mode is 'copy'".
> Tested at pixel level: copy = pixel-identical to the original (diff = 0), render = watermarks burned in.

---

## 📤 What YouTube actually receives (tested)

For every upload the bot builds (and you can preview in the `.txt` sidecar):

```
TITLE      : {prefix} {source video title} {#your #hashtags}      (max 100 chars)
DESCRIPTION: 🎬 High-engagement highlight clip from: {title}
             💡 Subscribe for daily curated shorts & insights!
             {#your #hashtags}
             (plus smart-title keywords if Smart titles is ON)
             — NO source URL, ever
TAGS       : your hashtags + the source channel's clean handle   (no URLs, max 480 bytes)
CATEGORY   : Entertainment (24)   ·   PRIVACY: public   ·   MadeForKids: false
```

- **Never the same video twice** on the same tab (SQLite `bot_state.db`, keyed per account).
  Tested: a second cycle skips what's already posted.
- **Dry-run mode** (no `client_secret.json`): the bot does everything — renders, keeps a
  copy, writes the sidecar — and simulates the upload (mock ID). Nothing goes live.
- **Live mode**: full real upload with progress %, then prints
  `https://www.youtube.com/shorts/{id}`.

---

## 🔧 Global `.env` settings (used when a tab doesn't override)

Found in `yt_shorts_bot/.env` / `yt_shorts_repost_bot/.env` (copy from `.env.example`).

| Key | Default | Meaning |
|---|---|---|
| `TARGET_CHANNELS` | (example channels) | Fallback source channels when a tab has none |
| `CLIP_DURATION_SEC` | 18.0 | Clip length (bot keeps 15–20s) |
| `WHISPER_MODEL_SIZE` | `tiny.en` | Subtitle transcription accuracy vs speed. `base.en` = better, slower |
| `SUBTITLE_STYLE_MODE` | `viral` | `viral` = 1–2 UPPERCASE words per caption (TikTok style) · `standard` = 3–4 words |
| `VIRAL_WORDS_PER_LINE` | 2 | Words per caption in viral mode |
| `SUBTITLE_FONT_NAME` / `SUBTITLE_FONT_SIZE` | Arial / 22 | Subtitle font (Arial on Windows, DejaVu Sans on Linux) |
| `BGM_ENABLED` / `BGM_VOLUME` / `VOICE_VOLUME` | true / 0.18 / 1.00 | Background music from `bgm/` folder at 18% volume under the voice |
| `SHORT_ASPECT` / `FILL_MODE` | 3:4 / blur | Global fallback for aspect + fill |
| `VIDEO_CRF` / `VIDEO_PRESET` / `AUDIO_BITRATE` | 18 / medium / 192k | Render quality (18 ≈ visually lossless) |
| `TOP_WATERMARK_*` | color white, opacity 0.5, size 56, italic, y 12% | Global top-watermark style |
| `BOTTOM_BANNER_*` | size 56, opacity 1.0, italic, y 90% | Global bottom-banner style |
| `SELECTION_ORDER` | newest | Global video pick order |
| `MAX_DAILY_UPLOADS` | 10 | Global 24h cap |
| `CYCLE_INTERVAL_HOURS` | 2 | Scheduler scan interval |
| `DELETE_AFTER_UPLOAD` / `DELETE_R2_AFTER_UPLOAD` | false / false | Global delete defaults |
| `KEEP_LOCAL_SHORTS` | true | Save every finished Short into `finished_shorts/` |
| `YT_COOKIES_FILE` | `cookies.txt` | Browser cookies file (fixes "Sign in to confirm you're not a bot") |
| `WEBUI_HOST` / `WEBUI_PORT` | 0.0.0.0 / 5000 · 5100 | Panel address (leave as-is for the VPS) |
| `R2_*` | placeholders | Cloudflare R2 backup (optional; dry-run until filled) |

---

## 🧪 Tab isolation — what "separate" means (tested)

Every setting is saved **per account name** in `accounts.json` — saving in the
"PeterAKing" tab only ever writes to "PeterAKing". Tested with two tabs: different
prefix/hashtags/watermark/quota on each, saving on one leaves the other untouched.
Two guards make sure this can never break:
- **After saving, the panel stays on the SAME tab** (the redirect now carries `?account=…`).
  In older builds it jumped back to the first tab, which looked like the save "went
  to both accounts".
- **Duplicate tab names are impossible + self-healing**: the `+` button always picks an
  unused name, and any legacy duplicate entries in `accounts.json` are merged on load
  and cleaned on the next save. (Two tabs with the same name would be the SAME account.)
- **The scheduler re-reads `accounts.json` on every cycle** — no panel restart needed
  after editing tabs.

> ⚠️ The ONLY truly shared setting is **"Bot cycle interval (hours, whole bot)"** — it
> lives in `.env`, by design. Everything else is per-tab.

## ✅ What was fixed during this review (v5.4+)

1. **"Shorts per video" / "Max shorts per channel / cycle" were MISSING from the panel**
   (a leftover template placeholder `@@NUM_SETTING_ROW@@` was rendered as text). Both rows now
   appear and save correctly.
2. **Saving one tab's Source channels silently DELETED all other tabs** — now tabs merge by
   name and untouched tabs are preserved.
3. **Checkbox values `"false"` were read as `true`** (e.g. "Delete R2 backup" could save as ON).
   Real booleans and strings `true/false/on/off/1/0` are now handled correctly.
4. **"Min minutes between uploads" was saved as text** instead of a number — now an int.
5. **Order could never be reset to "global"** after changing it — empty now saves as empty.
6. **The source channel URL leaked into the invisible YouTube "tags" field** — only a clean
   handle is used now; no URLs anywhere in title/description/tags.
7. **Empty top-watermark text was overridden with the account name** ("GAMING") — empty now
   means OFF everywhere (scheduler + single-URL path).
8. **Default title prefix changed from 🔥 to empty** — a fresh tab never gets an emoji it
   didn't ask for.
9. **v5.6 (tab isolation):** saves now stay on the tab you edited, duplicate account names
   can't merge tabs, `+` never creates a duplicate name, and settings apply to the
   scheduler immediately (no restart).
10. **v5.7 (per-account secrets):** the "Upload client_secret.json" button now saves into
    `accounts/<tab>/client_secret.json` for that tab only (older builds always wrote to the
    bot root, overwriting the shared file — which made separate Google Cloud accounts
    collide). The status box shows which files each tab actually uses.
11. **v5.8 (the "connected to the WRONG channel" bug):** a tab with no token of its own
    used to silently fall back to the bot-root `token.json` — which belongs to whichever
    channel was connected LAST (e.g. "ACCOUNT 'PeterAKing' is connected to CHANNEL 'Simpson Pimp'").
    Now the bot **never reuses another account's token**: missing per-account token = a
    fresh Google login for that tab (saved to `accounts/<name>/token.json`). The root
    `token.json` is only used by accounts that have no credential paths at all (legacy mode).

12. **v5.9 (wrong-channel upload + no-subtitles):**
    - **Channel safety lock**: per-account "Expected channel" setting — before every
      upload the bot verifies the connected login owns that channel and **blocks the
      upload** otherwise (this stops the "posted on Simpson Pimp" scenario).
    - **"Burn subtitles" toggle**: repost bot render mode defaults to **watermark only,
      no subtitles** (source Shorts already have captions); clip bot keeps subtitles ON.
    - Connect flow now warns loudly on a channel mismatch.

13. **v6.0 (UI + full-chain audit):**
    - **"+" tab fixed** — it's a plain link that sent a GET request while the server
      only accepted POST → "Method Not Allowed". Both methods are accepted now.
    - **Delete fixed** — deleting an unknown account now says so (no fake success),
      deleting the last account auto-creates a fresh "New Channel 1" (no phantom tab),
      and the button asks "Are you sure?" before removing.
    - **Repost bot NEVER burns subtitles by default anywhere** — including the
      "Repost one specific Short" box and `--mode process-url` (they used to ignore
      the account's `subtitles_enabled` and transcribe anyway). Only the per-account
      "Burn subtitles" checkbox turns them on.
    - **"Repost one specific Short" now honors EVERY account setting** — watermarks,
      title prefix, title hashtags, smart titles, subtitles toggle and the channel
      safety lock (previously it only used the mode).
    - **Repost render mode now uses the account's Aspect/Fill** (it used to ignore
      them and always use the global `.env` values).

14. **v6.1 (no more blur bars + hashtag guarantee):**
    - **New "Aspect: auto (like the original - NO blur bars)"** — the repost bot now
      probes the downloaded Short and uses its EXACT shape (9:16 Short → 1080×1920,
      3:4 → 1080×1440, anything else → matched). When the canvas aspect equals the
      source aspect, blur bars/pillarbox are impossible. Watermarks still burn on top.
      This is the new DEFAULT for the repost bot (accounts without an aspect setting,
      and the dropdown's first option). If you still want a fixed canvas, pick 3:4 or 9:16.
    - **Hashtags always survive**: if a source video title is long, the bot used to
      DROP your hashtags to stay under 100 chars. Now it shortens the video-title part
      instead — your Title Hashtags always appear in full.
    - **Source-title hashtags removed**: the source video's own `#tags` are stripped
      from the title and the description quote — only YOUR Title Hashtags ever appear.

15. **v6.2 (the "every account connects to Simpson Pimp" bug — ROOT CAUSE FIXED):**
    - **The bug:** accounts created with the `+` button had NO `token` path, and the
      credential resolver silently fell back to the bot-ROOT `token.json` — which
      belongs to whichever channel was connected LAST. Since that token was still
      valid, "Connect" never even opened Google's login page; every new tab reused
      Simpson Pimp's identity no matter which client_secret you uploaded.
    - **The fix:** a named account's token can NEVER come from the bot root. It always
      resolves to `accounts/<name>/token.json` — missing file = fresh Google login for
      THAT account. The `+` button, Connect, and client-secret upload all pin both
      per-account paths now. Only the legacy single-account mode (no accounts.json)
      still uses the root files.
    - **Also:** the Google login now ALWAYS shows the account chooser
      (`select_account`) so the browser can't silently use the wrong Google account,
      and the log prints exactly which secret/token files each tab uses on Connect.

Test suite lives in `_tests/` (run with `.venv/bin/python _tests/test_*.py`): **245 checks, all passing.**
