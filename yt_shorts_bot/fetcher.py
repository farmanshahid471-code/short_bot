"""
fetcher.py - Target selection, newest-to-oldest channel listing, heatmap peak analysis,
and section-only downloading using yt-dlp and FFmpeg.
"""
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from uuid import uuid4

import yt_dlp
import numpy as np

from .config import (
    TARGET_CHANNELS,
    FETCH_LIMIT_PER_CHANNEL,
    CLIP_DURATION_SEC,
    MIN_CLIP_DURATION_SEC,
    MAX_CLIP_DURATION_SEC,
    FFMPEG_PATH,
    FFPROBE_PATH,
    YT_COOKIES_FILE,
    YT_COOKIES_FROM_BROWSER,
    BASE_DIR,
    TEMP_DIR,
    logger,
)


class YouTubeFetcher:
    """
    Fetches video metadata from target channels, extracts 'Most Replayed' (heatmap) data
    without downloading full videos, calculates the optimal 15-20s engagement window,
    and downloads ONLY that segment.
    """
    def __init__(self, channels: Optional[List[str]] = None, fetch_limit: int = FETCH_LIMIT_PER_CHANNEL):
        self.channels = channels if channels is not None else TARGET_CHANNELS
        self.fetch_limit = fetch_limit

    @staticmethod
    def _ffmpeg_opt() -> dict:
        """
        Tells yt-dlp where our FFmpeg lives so format merging (video+audio)
        works even when the bundled ffmpeg is not on the system PATH.
        """
        if not FFMPEG_PATH:
            return {}
        return {"ffmpeg_location": str(Path(FFMPEG_PATH).resolve().parent)}

    @staticmethod
    def _cookies_opts() -> dict:
        """
        Returns yt-dlp options for YouTube authentication cookies.
        Fixes: "Sign in to confirm you're not a bot".
        """
        opts = {}

        if YT_COOKIES_FILE:
            cf_path = Path(YT_COOKIES_FILE)
            if not cf_path.is_absolute():
                cf_path = BASE_DIR / cf_path
            if cf_path.exists():
                opts["cookiefile"] = str(cf_path)
                logger.info(f"Using YouTube cookies from file: {cf_path}")
                if not YouTubeFetcher._cookies_look_valid(cf_path):
                    logger.warning(
                        "cookies.txt exists but does NOT contain YouTube login cookies "
                        "(looks empty or expired). Re-export it while LOGGED IN on "
                        "youtube.com - otherwise YouTube can still show the bot check."
                    )
            else:
                logger.warning(
                    f"YT_COOKIES_FILE is set to '{YT_COOKIES_FILE}' but that file was not found. "
                    "Skipping cookies - YouTube may ask you to sign in."
                )

        browser = YT_COOKIES_FROM_BROWSER.strip().lower()
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
            logger.info(f"Using YouTube cookies from browser: {browser}")

        return opts

    @staticmethod
    def _cookies_look_valid(cf_path: Path) -> bool:
        """
        Cheap sanity check: a valid exported YouTube cookie file (Netscape format)
        contains lines for .youtube.com with auth cookies like SID/SSID/APISID/HSID
        or __Secure-1PSID. Returns False if the file looks empty/expired.
        """
        try:
            text = cf_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False
        if "# Netscape HTTP Cookie File" not in text and ".youtube.com" not in text:
            return False
        auth_markers = ("SID", "APISID", "HSID", "SSID", "SAPISID")
        has_auth = any(
            marker in line
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
            and ".youtube.com" in line
            for marker in auth_markers
        )
        return has_auth

    def fetch_channel_recent_videos(self, channel_url: str) -> List[Dict[str, Any]]:
        """
        Lists the newest videos from a YouTube channel URL without downloading.
        Returns a list of dicts with video_id, url, title, duration.
        """
        logger.info(f"Scanning channel for recent videos: {channel_url}")
        # Normalize channel URL to its videos tab if needed
        url = channel_url.rstrip("/")
        if not url.endswith("/videos") and "@" in url:
            url = f"{url}/videos"

        ydl_opts = {
            "extract_flat": "in_playlist",
            "playlistend": self.fetch_limit,
            "sort": "date",  # Sort newest to oldest
            "quiet": True,
            "no_warnings": True,
            **self._cookies_opts(),
            **self._ffmpeg_opt(),
        }

        videos = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(url, download=False)
                if not res:
                    logger.warning(f"No response from yt-dlp for channel: {channel_url}")
                    return []
                entries = res.get("entries", [])
                for entry in entries:
                    if not entry:
                        continue
                    v_id = entry.get("id")
                    if not v_id:
                        continue
                    v_url = entry.get("webpage_url") or entry.get("url") or ""
                    if not str(v_url).startswith(("http://", "https://")):
                        v_url = f"https://www.youtube.com/watch?v={v_id}"
                    duration = entry.get("duration", 0) or 0
                    # Ignore existing YouTube Shorts (< 60s) or extremely short videos (< 45s)
                    if 0 < duration < 60:
                        logger.debug(f"Skipping video '{entry.get('title')}' - already a short ({duration}s)")
                        continue

                    videos.append({
                        "video_id": v_id,
                        "url": v_url,
                        "title": entry.get("title", f"Video {v_id}"),
                        "duration": duration,
                        "channel": channel_url,
                    })
        except Exception as e:
            logger.error(f"Error listing channel {channel_url}: {e}")

        logger.info(f"Found {len(videos)} candidate videos from {channel_url}")
        return videos

    @staticmethod
    def _is_bot_check_error(error: Exception) -> bool:
        """True if yt-dlp hit YouTube's 'Sign in to confirm you're not a bot' wall."""
        if YouTubeFetcher._is_restricted_error(error):
            return False
        text = str(error).lower()
        return "not a bot" in text or "sign in to confirm you're not a bot" in text

    @staticmethod
    def _is_restricted_error(error: Exception) -> bool:
        text = str(error).lower()
        return any(
            marker in text
            for marker in (
                "confirm your age",
                "age-restricted",
                "inappropriate for some users",
                "join this channel to get access",
                "members-only",
                "private video",
            )
        )

    def extract_heatmap_and_select_window(self, video_url: str) -> Tuple[Dict[str, Any], float, float, float]:
        """
        Extracts full video metadata including 'heatmap' (Most Replayed) data without downloading.
        Finds the peak engagement timestamp and calculates a 15-20 second window around it.
        
        Returns:
            (metadata_dict, peak_time_sec, clip_start_sec, clip_end_sec)
        """
        logger.info(f"Extracting heatmap metadata for: {video_url}")
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            **self._cookies_opts(),
            **self._ffmpeg_opt(),
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            if self._is_restricted_error(e):
                raise RuntimeError(
                    "SKIPPED_RESTRICTED: YouTube blocked this video (age-restricted or "
                    "members-only). Export a logged-in adult cookies.txt to process it."
                ) from e
            if self._is_bot_check_error(e):
                logger.error(
                    "YouTube blocked the request with 'Sign in to confirm you're not a bot'. "
                    "Fix: set YT_COOKIES_FILE (exported cookies.txt) or YT_COOKIES_FROM_BROWSER "
                    "in yt_shorts_bot/.env - see README 'YouTube cookies' section."
                )
            raise

        duration = float(info.get("duration") or 0.0)
        heatmap = info.get("heatmap") or []

        peak_time = 0.0
        best_score = 0.0
        used_heatmap = False
        used_energy = False

        if heatmap and len(heatmap) > 0:
            logger.info(f"Heatmap data found ({len(heatmap)} buckets). Calculating peak engagement...")
            win = self._best_window_from_heatmap(heatmap, duration)
            peak_time = (win["start"] + win["end"]) / 2.0
            best_score = win["score"]
            used_heatmap = True
            logger.info(f"Peak heatmap engagement found at timestamp {peak_time:.1f}s (score={best_score:.3f})")
        else:
            # Fallback 1: audio-energy analysis (works for live streams / VODs
            # where YouTube does not provide heatmap data - the most 'exciting'
            # loud segment is a good proxy for the most-watched part).
            logger.warning("No heatmap data available in metadata. Trying audio-energy analysis...")
            try:
                win = self.select_window_by_audio_energy(video_url, duration)
                peak_time = (win["start"] + win["end"]) / 2.0
                best_score = win["score"]
                used_energy = True
                logger.info(
                    f"Audio-energy peak found at timestamp {peak_time:.1f}s "
                    f"(energy score={best_score:.3f}) - fallback for videos without heatmap."
                )
            except Exception as e:
                logger.warning(f"Audio-energy analysis failed ({e}). Using smart fallback hook window.")
                if duration >= 60.0:
                    # Pick a hook window after intro at ~15% of duration or at 30 seconds
                    peak_time = min(45.0, max(15.0, duration * 0.15))
                else:
                    peak_time = duration / 2.0

        # Calculate 15 to 20-second window centered on peak_time
        clip_duration = CLIP_DURATION_SEC
        clip_start = max(0.0, peak_time - clip_duration / 2.0)
        clip_end = clip_start + clip_duration

        if duration > 0 and clip_end > duration:
            clip_end = duration
            clip_start = max(0.0, clip_end - clip_duration)

        # Enforce min/max clip duration bounds (15 to 20 seconds)
        if clip_end - clip_start < MIN_CLIP_DURATION_SEC and duration >= MIN_CLIP_DURATION_SEC:
            clip_end = min(duration, clip_start + MIN_CLIP_DURATION_SEC)
        elif clip_end - clip_start > MAX_CLIP_DURATION_SEC:
            clip_end = clip_start + MAX_CLIP_DURATION_SEC

        logger.info(
            f"Selected segment [{clip_start:.2f}s -> {clip_end:.2f}s] "
            f"(Duration: {clip_end - clip_start:.2f}s, Heatmap used: {used_heatmap}, "
            f"Audio-energy used: {used_energy})"
        )

        # Annotate info with heatmap selection metadata
        info["_peak_time"] = peak_time
        info["_clip_start"] = clip_start
        info["_clip_end"] = clip_end
        info["_used_heatmap"] = used_heatmap
        info["_used_energy"] = used_energy

        return info, peak_time, clip_start, clip_end

    # ------------------------------------------------------------------
    # Window scoring helpers (heatmap + audio-energy)
    # ------------------------------------------------------------------
    @staticmethod
    def _best_window_from_heatmap(heatmap: List[Dict[str, Any]], duration: float) -> Dict[str, Any]:
        """Finds the highest-average-engagement 15-20s window from YouTube's heatmap buckets."""
        best_win_score = -1.0
        best_win_center = 0.0

        for item in heatmap:
            t_mid = (item.get("start_time", 0.0) + item.get("end_time", 0.0)) / 2.0
            half_win = CLIP_DURATION_SEC / 2.0
            win_start = max(0.0, t_mid - half_win)
            win_end = win_start + CLIP_DURATION_SEC

            in_win = [
                h.get("value", 0.0) for h in heatmap
                if win_start <= (h.get("start_time", 0.0) + h.get("end_time", 0.0)) / 2.0 <= win_end
            ]
            score = sum(in_win) / max(1, len(in_win))
            if score > best_win_score:
                best_win_score = score
                best_win_center = t_mid

        clip_start = max(0.0, best_win_center - CLIP_DURATION_SEC / 2.0)
        clip_end = clip_start + CLIP_DURATION_SEC
        if duration > 0 and clip_end > duration:
            clip_end = duration
            clip_start = max(0.0, clip_end - CLIP_DURATION_SEC)

        return {"start": clip_start, "end": clip_end, "score": best_win_score}

    def _measure_audio_energy(self, stream_url: str, start: float, dur: float) -> float:
        """
        Pulls a short audio segment from the direct stream URL and returns its
        RMS energy (0.0 = silence, larger = louder/more exciting). Downloads only
        the few seconds it needs - never the whole video.
        """
        if not FFMPEG_PATH:
            raise RuntimeError("FFmpeg not found - cannot run audio-energy analysis.")

        cmd = [
            FFMPEG_PATH, "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
            "-i", stream_url,
            "-f", "s16le", "-ac", "1", "-ar", "16000",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0 or len(proc.stdout) < 3200:  # at least 0.1s of audio
            raise RuntimeError(f"Could not decode audio at {start:.0f}s")

        samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples ** 2)))

    def select_window_by_audio_energy(self, video_url: str, duration: float) -> Dict[str, Any]:
        """
        Fallback for videos WITHOUT heatmap data (live stream VODs etc.).
        Samples audio energy across the whole video, finds the loudest/most
        exciting 15-20s window, then refines around it with a finer pass.
        Returns {"start", "end", "score"}.
        """
        if duration <= 0:
            raise RuntimeError("Unknown duration - cannot analyze energy")

        # Get a direct audio stream URL (fast - metadata only)
        ydl_opts = {"format": "bestaudio/best", "quiet": True, "no_warnings": True, **self._cookies_opts(), **self._ffmpeg_opt()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
        stream_url = info.get("url")
        if not stream_url:
            raise RuntimeError("No direct stream URL available")

        sample_len = min(CLIP_DURATION_SEC, 20.0)
        # Coarse pass: up to 40 evenly-spaced samples (keeps download tiny)
        n_samples = max(8, min(40, int(duration / max(30.0, sample_len * 2))))
        step = max(sample_len, (duration - sample_len) / max(1, n_samples - 1))

        logger.info(f"Audio-energy scan: {n_samples} sample points over {duration:.0f}s video...")
        best_t, best_e = 0.0, -1.0
        for i in range(n_samples):
            t = min(max(0.0, i * step), max(0.0, duration - sample_len))
            try:
                e = self._measure_audio_energy(stream_url, t, sample_len)
            except Exception as exc:
                logger.debug("Audio sample at %.1fs failed: %s", t, exc)
                continue
            if e > best_e:
                best_e, best_t = e, t

        if best_e < 0:
            raise RuntimeError("All audio samples failed")

        # Refine pass: 9 finer samples around the coarse winner
        refine_center = best_t + sample_len / 2.0
        refine_half = 45.0
        refined_t, refined_e = best_t, best_e
        for i in range(9):
            t = refine_center - refine_half + i * (2 * refine_half / 8.0)
            t = min(max(0.0, t - sample_len / 2.0), max(0.0, duration - sample_len))
            try:
                e = self._measure_audio_energy(stream_url, t, sample_len)
            except Exception as exc:
                logger.debug("Refined audio sample at %.1fs failed: %s", t, exc)
                continue
            if e > refined_e:
                refined_e, refined_t = e, t

        clip_start = max(0.0, refined_t)
        clip_end = min(duration, clip_start + sample_len)
        if clip_end - clip_start < MIN_CLIP_DURATION_SEC:
            clip_end = min(duration, clip_start + MIN_CLIP_DURATION_SEC)

        logger.info(
            f"Audio-energy analysis complete: best window [{clip_start:.1f}s -> {clip_end:.1f}s] "
            f"(energy={refined_e:.4f})"
        )
        return {"start": clip_start, "end": clip_end, "score": refined_e}

    def select_top_windows(self, video_url: str, count: int = 3) -> List[Dict[str, Any]]:
        """
        Returns the top `count` non-overlapping 15-20s windows for a video,
        using heatmap data when available, otherwise audio-energy analysis.
        Used to make MULTIPLE shorts from one video.
        Returns list of {"start", "end", "score", "source"}.
        """
        ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True, **self._cookies_opts(), **self._ffmpeg_opt()}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            if self._is_restricted_error(e):
                raise RuntimeError(
                    "SKIPPED_RESTRICTED: YouTube blocked this video (age-restricted or "
                    "members-only). Export a logged-in adult cookies.txt to process it."
                ) from e
            if self._is_bot_check_error(e):
                logger.error(
                    "YouTube blocked the request with 'Sign in to confirm you're not a bot'. "
                    "Fix: set YT_COOKIES_FILE (exported cookies.txt) or YT_COOKIES_FROM_BROWSER "
                    "in yt_shorts_bot/.env - see README 'YouTube cookies' section."
                )
            raise

        duration = float(info.get("duration") or 0.0)
        heatmap = info.get("heatmap") or []

        candidates: List[Dict[str, Any]] = []

        if heatmap and len(heatmap) > 0:
            logger.info(f"Heatmap data found ({len(heatmap)} buckets). Ranking top {count} windows...")
            half = CLIP_DURATION_SEC / 2.0
            for item in heatmap:
                t_mid = (item.get("start_time", 0.0) + item.get("end_time", 0.0)) / 2.0
                start = max(0.0, t_mid - half)
                end = start + CLIP_DURATION_SEC
                if duration > 0 and end > duration:
                    end = duration
                    start = max(0.0, end - CLIP_DURATION_SEC)
                in_win = [
                    h.get("value", 0.0) for h in heatmap
                    if start <= (h.get("start_time", 0.0) + h.get("end_time", 0.0)) / 2.0 <= end
                ]
                score = sum(in_win) / max(1, len(in_win))
                candidates.append({"start": start, "end": end, "score": score, "source": "heatmap"})
        else:
            logger.info("No heatmap data. Using audio-energy analysis to rank windows...")
            sample_len = min(CLIP_DURATION_SEC, 20.0)
            ydl_audio = {"format": "bestaudio/best", "quiet": True, "no_warnings": True, **self._cookies_opts(), **self._ffmpeg_opt()}
            try:
                with yt_dlp.YoutubeDL(ydl_audio) as ydl:
                    ainfo = ydl.extract_info(video_url, download=False)
            except Exception as e:
                if self._is_bot_check_error(e):
                    logger.error(
                        "YouTube blocked the request with 'Sign in to confirm you're not a bot'. "
                        "Fix: set YT_COOKIES_FILE (exported cookies.txt) or YT_COOKIES_FROM_BROWSER "
                        "in yt_shorts_bot/.env - see README 'YouTube cookies' section."
                    )
                raise
            stream_url = ainfo.get("url")
            if not stream_url:
                raise RuntimeError("No direct audio stream URL available")
            n_samples = max(20, min(60, int(duration / 20.0)))
            step = max(sample_len, (duration - sample_len) / max(1, n_samples - 1))
            for i in range(n_samples):
                t = min(max(0.0, i * step), max(0.0, duration - sample_len))
                try:
                    e = self._measure_audio_energy(stream_url, t, sample_len)
                except Exception as exc:
                    logger.debug("Ranked audio sample at %.1fs failed: %s", t, exc)
                    continue
                candidates.append({
                    "start": t,
                    "end": min(duration, t + sample_len),
                    "score": e,
                    "source": "audio_energy",
                })

        if not candidates:
            raise RuntimeError("Could not rank any windows for this video")

        # Greedy: pick highest-scoring window, then skip anything overlapping it
        candidates.sort(key=lambda w: w["score"], reverse=True)
        chosen: List[Dict[str, Any]] = []
        for w in candidates:
            if len(chosen) >= count:
                break
            overlap = any(
                w["start"] < c["end"] - 2.0 and c["start"] < w["end"] - 2.0
                for c in chosen
            )
            if not overlap:
                chosen.append(w)

        logger.info(f"Selected {len(chosen)} top windows: " +
                    ", ".join(f"[{w['start']:.0f}s-{w['end']:.0f}s]({w['score']:.2f})" for w in chosen))
        return chosen

    def download_clip_section(
        self,
        video_url: str,
        clip_start: float,
        clip_end: float,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Downloads ONLY the specific [clip_start -> clip_end] segment.
        Tries three strategies in order:
          A. Fast single progressive-format stream URL (no merging)  -> ~1s
          B. Fast video + audio stream pair (1080p h264 + m4a)        -> ~1-2s
          C. Full yt-dlp download then local FFmpeg slice (always works)
        Each result is verified with ffprobe before being accepted.
        """
        if output_path is None:
            v_id = self._extract_video_id(video_url)
            output_path = TEMP_DIR / (
                f"raw_clip_{v_id}_{int(clip_start)}_{int(clip_end)}_{uuid4().hex[:10]}.mp4"
            )

        logger.info(
            f"Downloading segment [{clip_start:.2f}s -> {clip_end:.2f}s] "
            f"for {video_url} to {output_path}..."
        )
        if output_path.exists():
            output_path.unlink()

        # Strategy A: single progressive URL (video+audio in one stream)
        try:
            clip_path = self._slice_progressive(video_url, clip_start, clip_end, output_path)
            logger.info(f"Downloaded clip section via progressive stream ({clip_path.stat().st_size / 1024 / 1024:.2f} MB)")
            return clip_path
        except Exception as e:
            output_path.unlink(missing_ok=True)
            logger.debug(f"Strategy A (progressive single URL) failed: {e}")

        # Strategy B: best video + best audio stream pair
        try:
            clip_path = self._slice_av_pair(video_url, clip_start, clip_end, output_path)
            logger.info(f"Downloaded clip section via video+audio streams ({clip_path.stat().st_size / 1024 / 1024:.2f} MB)")
            return clip_path
        except Exception as e:
            output_path.unlink(missing_ok=True)
            logger.debug(f"Strategy B (AV pair) failed: {e}")

        # Strategy C: full download + local slice (slow, but always works)
        logger.warning("Fast stream slicing failed. Falling back to full download + local slice...")
        try:
            clip_path = self._download_full_then_slice(
                video_url, clip_start, clip_end, output_path
            )
            logger.info(
                "Downloaded clip via full download + slice (%.2f MB)",
                clip_path.stat().st_size / 1024 / 1024,
            )
            return clip_path
        except Exception:
            output_path.unlink(missing_ok=True)
            for fragment in output_path.parent.glob(f"{output_path.name}*.part*"):
                fragment.unlink(missing_ok=True)
            raise

    @staticmethod
    def _extract_video_id(video_url: str) -> str:
        """Extracts an 11-char YouTube video ID from watch/shorts/youtu.be URLs."""
        import re
        m = re.search(r"(?:v=|shorts/|youtu\.be/)([\w-]{11})", video_url)
        if m:
            return m.group(1)
        return video_url.split("v=")[-1].split("&")[0]

    @staticmethod
    def _verify_slice(output_path: Path, clip_start: float, clip_end: float) -> bool:
        """Returns True only if the file exists and its duration roughly matches the requested window."""
        if not output_path.exists() or output_path.stat().st_size < 10_000:
            return False
        if not FFPROBE_PATH:
            logger.warning("ffprobe not found - skipping clip verification.")
            return True
        try:
            out = subprocess.run(
                [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(output_path)],
                capture_output=True, text=True, timeout=30
            )
            dur = float(out.stdout.strip())
            expected = clip_end - clip_start
            return abs(dur - expected) <= max(2.0, expected * 0.15)
        except Exception:
            return False

    @staticmethod
    def _ffmpeg_slice(input_args: List[str], output_path: Path) -> None:
        """Runs ffmpeg: input_args = ['-ss', start, '-to', end, '-i', <input>...] -> output_path."""
        if not FFMPEG_PATH:
            raise RuntimeError(
                "FFmpeg was not found. Run setup.bat / setup.sh, or install FFmpeg "
                "and add it to PATH."
            )
        cmd = [
            FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
            *input_args,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, timeout=180)

    def _slice_progressive(self, video_url: str, clip_start: float, clip_end: float, output_path: Path) -> Path:
        """Strategy A: find the best single progressive (combined A/V) mp4 format and slice its URL directly."""
        ydl_opts = {"format": "best[ext=mp4]/best", "quiet": True, "no_warnings": True, **self._cookies_opts(), **self._ffmpeg_opt()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

        progressive = [
            f for f in info.get("formats", [])
            if f.get("vcodec") not in ("none", None)
            and f.get("acodec") not in ("none", None)
            and f.get("ext") == "mp4"
            and f.get("url")
        ]
        if not progressive:
            raise RuntimeError("No progressive mp4 format available")
        fmt = max(progressive, key=lambda x: x.get("height", 0) or 0)

        self._ffmpeg_slice(
            ["-ss", str(clip_start), "-to", str(clip_end), "-i", fmt["url"]],
            output_path
        )
        if not self._verify_slice(output_path, clip_start, clip_end):
            raise RuntimeError("Progressive slice produced an invalid file")
        return output_path

    def _slice_av_pair(self, video_url: str, clip_start: float, clip_end: float, output_path: Path) -> Path:
        """Strategy B: slice the best mp4 video (h264 preferred) + best m4a audio stream pair."""
        ydl_opts = {
            "format": "bestvideo[height<=2160][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/""bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
            **self._cookies_opts(),
            **self._ffmpeg_opt(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

        formats = info.get("formats", [])
        videos = [
            f for f in formats
            if f.get("vcodec") not in ("none", None)
            and f.get("height", 0) <= 2160
            and f.get("ext") == "mp4"
            and f.get("url")
        ]
        audios = [
            f for f in formats
            if f.get("acodec") not in ("none", None)
            and f.get("vcodec") in ("none", None)
            and f.get("ext") == "m4a"
            and f.get("url")
        ]
        if not videos or not audios:
            raise RuntimeError("No suitable video/audio stream pair available")

        # Prefer h264 (avc1) streams over av1/vp9 - far more reliable for direct slicing
        videos.sort(key=lambda x: (str(x.get("vcodec", "")).startswith("avc1"), x.get("height", 0) or 0), reverse=True)
        audios.sort(key=lambda x: x.get("abr", 0) or 0, reverse=True)

        self._ffmpeg_slice(
            [
                "-ss", str(clip_start), "-to", str(clip_end), "-i", videos[0]["url"],
                "-ss", str(clip_start), "-to", str(clip_end), "-i", audios[0]["url"],
            ],
            output_path
        )
        if not self._verify_slice(output_path, clip_start, clip_end):
            raise RuntimeError("AV pair slice produced an invalid file")
        return output_path

    def _download_full_then_slice(self, video_url: str, clip_start: float, clip_end: float, output_path: Path) -> Path:
        """Strategy C: yt-dlp downloads the full video, FFmpeg slices it locally, then the full file is deleted."""
        v_id = self._extract_video_id(video_url)
        job_id = uuid4().hex[:10]
        full_prefix = f"full_{v_id}_{job_id}"
        full_tmpl = str(TEMP_DIR / f"{full_prefix}.%(ext)s")

        ydl_opts = {
            "format": "bestvideo[height<=2160][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/""bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": full_tmpl,
            "quiet": True,
            "no_warnings": True,
            **self._cookies_opts(),
            **self._ffmpeg_opt(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        matches = [p for p in TEMP_DIR.glob(f"{full_prefix}.*") if p.stat().st_size > 0]
        if not matches:
            raise RuntimeError("Full download produced no usable file")
        full_path = max(matches, key=lambda p: p.stat().st_size)

        try:
            self._ffmpeg_slice(
                ["-ss", str(clip_start), "-to", str(clip_end), "-i", str(full_path)],
                output_path
            )
            if not self._verify_slice(output_path, clip_start, clip_end):
                raise RuntimeError("Slice of full download produced an invalid file")
        finally:
            # Free disk: delete the full video + any fragments immediately
            for p in TEMP_DIR.glob(f"{full_prefix}*"):
                try:
                    p.unlink()
                except OSError:
                    pass
        return output_path
