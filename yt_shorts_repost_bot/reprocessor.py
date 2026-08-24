"""
reprocessor.py - Prepares a downloaded Short for upload to YOUR channel.

  PROCESS_MODE="copy"   -> re-encode to a clean mp4 (h264+aac, same look).
  PROCESS_MODE="render" -> transcribe + burn viral subtitles + add BGM
                           (reuses the full VideoProcessor from the clip bot).
"""
import subprocess
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .config import (
    PROCESS_MODE,
    VIDEO_CRF_COPY,
    VIDEO_PRESET,
    AUDIO_BITRATE,
    FFMPEG_PATH,
    FFMPEG_TIMEOUT_SEC,
    TEMP_DIR,
    logger,
)
from .processor import VideoProcessor


class ShortReprocessor:
    """Turns a downloaded Short into the final uploadable file."""

    def __init__(self):
        self.video_processor = VideoProcessor()

    # ------------------------------------------------------------------
    def process_short(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        like_subscribe: Optional[bool] = None,
        like_subscribe_text: Optional[str] = None,
        top_watermark_enabled: Optional[bool] = None,
        top_watermark_text: Optional[str] = None,
        mode: Optional[str] = None,
        subtitles: Optional[bool] = None,
        aspect: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> Path:
        if output_path is None:
            output_path = TEMP_DIR / f"final_{input_path.stem}_{uuid4().hex[:10]}.mp4"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not Path(input_path).exists():
            raise FileNotFoundError(f"Downloaded Short not found: {input_path}")

        # Repost bot: subtitles are OFF unless explicitly enabled.
        # (Source Shorts already have their own captions - render = watermark only.)
        subs = False if subtitles is None else bool(subtitles)
        # Per-account mode wins over the global .env PROCESS_MODE
        use_mode = (mode or PROCESS_MODE or "copy").strip().lower()
        if use_mode == "render":
            logger.info(
                "Render mode: "
                + ("transcribing + burning subtitles + " if subs else "")
                + "burning watermarks + mixing BGM..."
            )
            return self.video_processor.process_clip_to_short(
                input_path,
                output_path=output_path,
                srt_path=None,
                bgm_path=None,
                like_subscribe=like_subscribe,
                like_subscribe_text=like_subscribe_text,
                top_watermark_enabled=top_watermark_enabled,
                top_watermark_text=top_watermark_text,
                subtitles=subs,
                aspect=aspect,
                fill=fill,
            )

        # ---- copy mode: keep the source look, but still burn watermarks ----
        if not FFMPEG_PATH:
            raise RuntimeError("FFmpeg was not found; run setup or configure FFMPEG_PATH")
        banner_on = False if like_subscribe is False else True
        banner_text = str(like_subscribe_text or "").strip() or (
            "LIKE & SUBSCRIBE" if banner_on else ""
        )
        top_on = False if top_watermark_enabled is False else bool(str(top_watermark_text or "").strip())
        top_text = str(top_watermark_text or "").strip()
        want_marks = bool((banner_on and banner_text) or (top_on and top_text))
        overlay = None
        if want_marks:
            size = self.video_processor._probe_video_size(input_path) or (1080, 1920)
            overlay = TEMP_DIR / f"overlay_{uuid4().hex}.png"
            self.video_processor.write_watermark_png(
                overlay,
                size[0],
                size[1],
                top_text=top_text if top_on else "",
                bottom_text=banner_text if banner_on else "",
            )
            logger.info("Copy mode: re-encoding %s with watermark overlay...", input_path.name)
        else:
            logger.info("Copy mode: re-encoding %s to a clean mp4...", input_path.name)
        cmd = [
            FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
        ]
        if overlay:
            cmd += [
                "-loop", "1", "-i", str(overlay),
                "-filter_complex",
                "[0:v][1:v]overlay=0:0:format=auto,scale=trunc(iw/2)*2:trunc(ih/2)*2[v]",
                "-map", "[v]", "-map", "0:a?",
            ]
        else:
            cmd += [
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-map", "0:v:0", "-map", "0:a?",
            ]
        cmd += [
            "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF_COPY),
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart", "-threads", "0", "-shortest",
            str(output_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=FFMPEG_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            if overlay:
                overlay.unlink(missing_ok=True)
            raise RuntimeError(
                f"FFmpeg copy-mode render timed out after {FFMPEG_TIMEOUT_SEC} seconds"
            ) from exc
        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            if overlay:
                overlay.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg copy-mode render failed: {result.stderr[-4000:]}")
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            if overlay:
                overlay.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg copy mode produced no output")
        if overlay:
            overlay.unlink(missing_ok=True)
        logger.info(
            "Re-encoded: %s (%.2f MB)",
            output_path,
            output_path.stat().st_size / 1024 / 1024,
        )
        return output_path
