"""
reprocessor.py - Prepares a downloaded Short for upload to YOUR channel.

  PROCESS_MODE="copy"   -> re-encode to a clean mp4 (h264+aac, same look).
  PROCESS_MODE="render" -> transcribe + burn viral subtitles + add BGM
                           (reuses the full VideoProcessor from the clip bot).
"""
import subprocess
from pathlib import Path
from typing import Optional

from .config import (
    PROCESS_MODE,
    VIDEO_CRF,
    VIDEO_CRF_COPY,
    VIDEO_PRESET,
    AUDIO_BITRATE,
    FFMPEG_PATH,
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
            output_path = TEMP_DIR / f"final_{input_path.stem}.mp4"

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

        # ---- copy mode: clean re-encode (keeps the Short's look) ----
        logger.info(f"Copy mode: re-encoding {input_path.name} to a clean mp4...")
        cmd = [
            FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # keep even dimensions
            "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF_COPY),
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart",
            "-threads", "0",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, timeout=300)
        logger.info(f"Re-encoded: {output_path} ({output_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return output_path
