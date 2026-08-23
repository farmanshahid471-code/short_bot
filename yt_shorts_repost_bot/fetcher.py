"""
fetcher.py - For the REPOST bot: finds Shorts on target channels and downloads
them in full (they are small), without any clipping/heatmap logic.
"""
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import yt_dlp

from .config import (
    TARGET_CHANNELS,
    FETCH_LIMIT_PER_CHANNEL,
    MAX_SHORT_DURATION_SEC,
    FFMPEG_PATH,
    FFPROBE_PATH,
    YT_COOKIES_FILE,
    YT_COOKIES_FROM_BROWSER,
    BASE_DIR,
    TEMP_DIR,
    logger,
)


class ShortsFetcher:
    """Finds and downloads full YouTube Shorts from target channels."""

    def __init__(self, channels: Optional[List[str]] = None, fetch_limit: int = FETCH_LIMIT_PER_CHANNEL):
        self.channels = channels if channels is not None else TARGET_CHANNELS
        self.fetch_limit = fetch_limit

    @staticmethod
    def _cookies_opts() -> dict:
        opts = {}

        # Search several places for a cookies.txt so the repost bot can share
        # the one from the clip-farming bot (yt_shorts_bot/) automatically:
        #   1. YT_COOKIES_FILE from .env
        #   2. this bot's own folder: yt_shorts_repost_bot/cookies.txt
        #   3. sibling clip bot folder: yt_shorts_bot/cookies.txt
        #   4. project root: cookies.txt
        candidates = []
        if YT_COOKIES_FILE:
            candidates.append(Path(YT_COOKIES_FILE))
        candidates += [
            BASE_DIR / "cookies.txt",
            BASE_DIR.parent / "yt_shorts_bot" / "cookies.txt",
            BASE_DIR.parent / "cookies.txt",
        ]

        found = None
        for cf in candidates:
            p = cf if cf.is_absolute() else BASE_DIR / cf
            if p.exists():
                found = p
                break

        if found:
            opts["cookiefile"] = str(found)
            logger.info(f"Using YouTube cookies from file: {found}")
        elif YT_COOKIES_FILE:
            logger.warning(
                f"YT_COOKIES_FILE is set to '{YT_COOKIES_FILE}' but the file was not found. "
                "Also checked the repost folder, the clip-bot folder, and project root."
            )

        browser = YT_COOKIES_FROM_BROWSER.strip().lower()
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
            logger.info(f"Using YouTube cookies from browser: {browser}")
        return opts

    @staticmethod
    def _ffmpeg_opt() -> dict:
        if not FFMPEG_PATH:
            return {}
        return {"ffmpeg_location": str(Path(FFMPEG_PATH).resolve().parent)}

    @staticmethod
    def _is_bot_check_error(error: Exception) -> bool:
        text = str(error)
        return "Sign in to confirm" in text or "not a bot" in text

    @staticmethod
    def _extract_video_id(video_url: str) -> str:
        m = re.search(r"(?:v=|shorts/|youtu\.be/)([\w-]{11})", video_url)
        return m.group(1) if m else video_url.split("v=")[-1].split("&")[0]

    # ------------------------------------------------------------------
    def fetch_channel_recent_shorts(self, channel_url: str) -> List[Dict[str, Any]]:
        """
        Lists the newest Shorts from a channel (newest first), without downloading.
        Tries the /shorts tab first, then falls back to /videos and filters by duration.
        """
        logger.info(f"Scanning channel for recent Shorts: {channel_url}")
        url = channel_url.rstrip("/")
        candidates = []
        if "@" in url and not url.endswith(("/shorts", "/videos")):
            candidates = [f"{url}/shorts", f"{url}/videos"]
        else:
            candidates = [url]

        seen = set()
        shorts = []
        for feed in candidates:
            try:
                ydl_opts = {
                    "extract_flat": "in_playlist",
                    "playlistend": self.fetch_limit,
                    "sort": "date",  # newest first
                    "quiet": True,
                    "no_warnings": True,
                    **self._cookies_opts(),
                    **self._ffmpeg_opt(),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    res = ydl.extract_info(feed, download=False)
                entries = res.get("entries") or []
                logger.info(f"  {feed}: found {len(entries)} entries")
                for entry in entries:
                    if not entry:
                        continue
                    v_id = entry.get("id")
                    if not v_id or v_id in seen:
                        continue
                    duration = entry.get("duration") or 0
                    # Keep only Shorts: <= 60s (or unknown -> keep, verify later)
                    if 0 < duration <= MAX_SHORT_DURATION_SEC or not duration:
                        seen.add(v_id)
                        shorts.append({
                            "video_id": v_id,
                            "url": entry.get("url") or f"https://www.youtube.com/shorts/{v_id}",
                            "title": entry.get("title", f"Short {v_id}"),
                            "duration": duration,
                            "channel": channel_url,
                        })
                if shorts:
                    break  # the /shorts feed gave us enough
            except Exception as e:
                if self._is_bot_check_error(e):
                    logger.error(
                        "YouTube blocked the request ('Sign in to confirm you're not a bot'). "
                        "Set YT_COOKIES_FILE / YT_COOKIES_FROM_BROWSER in .env."
                    )
                else:
                    logger.warning(f"Could not read feed {feed}: {e}")

        # Filter out anything longer than a Short (when duration was unknown in the feed)
        shorts = [s for s in shorts if not s["duration"] or s["duration"] <= MAX_SHORT_DURATION_SEC]
        logger.info(f"Found {len(shorts)} candidate Shorts from {channel_url}")
        return shorts

    # ------------------------------------------------------------------
    def download_short(self, video_url: str, output_path: Optional[Path] = None) -> Path:
        """
        Downloads a full Short (video+audio, up to 4K if available) into an .mp4.
        """
        v_id = self._extract_video_id(video_url)
        if output_path is None:
            output_path = TEMP_DIR / f"short_{v_id}.mp4"

        logger.info(f"Downloading Short {video_url} -> {output_path}")
        if output_path.exists():
            output_path.unlink()

        # Try several player clients - YouTube serves streams differently per
        # client, and some (tv/android/ios) avoid HTTP 403 on Shorts.
        client_attempts = [
            {},                                  # default
            {"player_client": "tv"},
            {"player_client": "android"},
            {"player_client": "ios"},
        ]
        last_err = None
        for extra in client_attempts:
            ydl_opts = {
                "format": "bestvideo[height<=2160][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
                          "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": str(output_path),
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                **self._cookies_opts(),
                **self._ffmpeg_opt(),
                **extra,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                last_err = None
                break
            except Exception as e:
                last_err = e
                logger.warning(f"Download attempt (client={extra.get('player_client', 'default')}) failed: {e}")
                if self._is_bot_check_error(e):
                    logger.error(
                        "YouTube blocked the download ('Sign in to confirm you're not a bot'). "
                        "Set YT_COOKIES_FILE / YT_COOKIES_FROM_BROWSER in .env."
                    )
                    raise
        if last_err is not None:
            raise last_err

        # yt-dlp may append extensions for merged files; find the real output
        if not output_path.exists():
            matches = [p for p in TEMP_DIR.glob(f"short_{v_id}.*") if p.stat().st_size > 0]
            if not matches:
                raise RuntimeError(f"Download produced no usable file for {video_url}")
            output_path = max(matches, key=lambda p: p.stat().st_size)

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Downloaded Short ({size_mb:.2f} MB): {output_path}")
        return output_path

    # ------------------------------------------------------------------
    @staticmethod
    def get_short_info(video_url: str) -> Dict[str, Any]:
        """Small metadata fetch for a single Short URL."""
        ydl_opts = {
            "skip_download": True, "quiet": True, "no_warnings": True,
            "player_client": "tv",  # tv client is reliable for metadata
            **ShortsFetcher._cookies_opts(), **ShortsFetcher._ffmpeg_opt(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
