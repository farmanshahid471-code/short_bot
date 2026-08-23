"""
processor.py - Video editing, 9:16 center cropping, CPU transcription with faster-whisper,
timestamped SRT generation, and TikTok-style subtitle burning via FFmpeg.
"""
import os
import re
import sys
import subprocess
import datetime
import random
from pathlib import Path
from typing import List, Optional, Tuple, Any
from faster_whisper import WhisperModel

from .config import (
    VERTICAL_WIDTH,
    VERTICAL_HEIGHT,
    SHORT_ASPECT,
    FILL_MODE,
    VIDEO_CRF,
    VIDEO_PRESET,
    AUDIO_BITRATE,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    MAX_WORDS_PER_SUBTITLE_LINE,
    SUBTITLE_MAX_DURATION_SEC,
    SUBTITLE_STYLE_MODE,
    VIRAL_WORDS_PER_LINE,
    SUBTITLE_UPPERCASE,
    SUBTITLE_FONT_NAME,
    SUBTITLE_FORCE_STYLE,
    BGM_DIR,
    BGM_ENABLED,
    BGM_VOLUME,
    VOICE_VOLUME,
    LOGO_REMOVE_ENABLED,
    LOGO_POSITION,
    LOGO_SIZE_PCT,
    LOGO_POSITIONS,
    LIKE_AND_SUBSCRIBE_ENABLED,
    LIKE_AND_SUBSCRIBE_TEXT,
    TOP_WATERMARK_ENABLED,
    TOP_WATERMARK_TEXT,
    TOP_WATERMARK_COLOR,
    TOP_WATERMARK_OPACITY,
    TOP_WATERMARK_FONT_SIZE,
    TOP_WATERMARK_ITALIC,
    TOP_WATERMARK_Y_PCT,
    BOTTOM_BANNER_FONT_SIZE,
    BOTTOM_BANNER_OPACITY,
    BOTTOM_BANNER_ITALIC,
    BOTTOM_BANNER_Y_PCT,
    FFMPEG_PATH,
    TEMP_DIR,
    logger,
)


def _italic_font() -> Optional[str]:
    """
    Returns a fontfile path that renders ITALIC, or None if no italic font is
    installed. Uses fontfile (not font name) because drawtext has no fontstyle
    option and font-name-with-style doesn't work. Falls back to regular font.
    """
    import glob
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # generic search
    found = glob.glob("/usr/share/fonts/**/*Italic*.ttf", recursive=True) +             glob.glob("/usr/share/fonts/**/*Oblique*.ttf", recursive=True) +             glob.glob("/usr/share/fonts/**/*italic*.ttf", recursive=True)
    if found:
        return found[0]
    if sys.platform.startswith("win"):
        # Windows: Arial Italic via font name works with drawtext (fontconfig present)
        return "Arial Italic"
    return None


class VideoProcessor:
    """
    Processes video segments for YouTube Shorts:
    1. Transcribes audio locally on CPU for free using faster-whisper.
    2. Generates dynamic, high-readability timestamped SRT subtitles (TikTok/Shorts style).
    3. Uses FFmpeg to center-crop the video to 9:16 vertical aspect ratio (1080x1920)
       and burns subtitles directly into the video with a bold, readable font.
    """
    def __init__(self, model_size: str = WHISPER_MODEL_SIZE):
        self.model_size = model_size
        self._whisper_model: Optional[WhisperModel] = None

    def _get_whisper_model(self) -> WhisperModel:
        """Lazy-load the Faster-Whisper model on CPU."""
        if self._whisper_model is None:
            logger.info(
                f"Loading faster-whisper model '{self.model_size}' on "
                f"{WHISPER_DEVICE.upper()} ({WHISPER_COMPUTE_TYPE})..."
            )
            self._whisper_model = WhisperModel(
                self.model_size,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
            logger.info("faster-whisper CPU model loaded successfully.")
        return self._whisper_model

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        """Convert float seconds to SRT timestamp format: HH:MM:SS,mmm"""
        td = datetime.timedelta(seconds=max(0.0, seconds))
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def transcribe_and_generate_srt(
        self,
        video_path: Path,
        srt_path: Optional[Path] = None,
        mode: str = SUBTITLE_STYLE_MODE
    ) -> Path:
        """
        Transcribes the video audio using faster-whisper on CPU and writes an SRT file.
        Supports:
          - mode='viral': 1-2 words per line, bold UPPERCASE (CapCut / Hormozi / TikTok style)
          - mode='standard': 3-4 words per line
        """
        if srt_path is None:
            srt_path = video_path.with_suffix(".srt")

        logger.info(f"Transcribing audio from {video_path.name} using CPU whisper (mode={mode})...")
        model = self._get_whisper_model()

        segments, info = model.transcribe(str(video_path), word_timestamps=True, language="en")
        logger.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")

        subtitle_entries: List[Tuple[float, float, str]] = []
        words_limit = VIRAL_WORDS_PER_LINE if mode == "viral" else MAX_WORDS_PER_SUBTITLE_LINE

        for segment in segments:
            words = getattr(segment, "words", None)
            if words and len(words) > 0:
                current_words = []
                chunk_start = words[0].start
                chunk_end = words[0].end

                for w in words:
                    raw_word = w.word.strip()
                    word_text = raw_word.upper() if (mode == "viral" or SUBTITLE_UPPERCASE) else raw_word
                    current_words.append(word_text)
                    chunk_end = w.end
                    if (
                        len(current_words) >= words_limit
                        or (chunk_end - chunk_start) >= SUBTITLE_MAX_DURATION_SEC
                    ):
                        text_line = " ".join(current_words).strip()
                        if text_line:
                            subtitle_entries.append((chunk_start, chunk_end, text_line))
                        current_words = []
                        chunk_start = w.end
                
                if current_words:
                    text_line = " ".join(current_words).strip()
                    if text_line:
                        subtitle_entries.append((chunk_start, chunk_end, text_line))
            else:
                text = segment.text.strip()
                if mode == "viral" or SUBTITLE_UPPERCASE:
                    text = text.upper()
                if text:
                    subtitle_entries.append((segment.start, segment.end, text))

        with open(srt_path, "w", encoding="utf-8") as f:
            for idx, (start_ts, end_ts, text) in enumerate(subtitle_entries, start=1):
                ts_start_str = self._format_srt_timestamp(start_ts)
                ts_end_str = self._format_srt_timestamp(end_ts)
                f.write(f"{idx}\n")
                f.write(f"{ts_start_str} --> {ts_end_str}\n")
                f.write(f"{text}\n\n")

        logger.info(f"Generated SRT subtitles at {srt_path} ({len(subtitle_entries)} lines)")
        return srt_path

    @staticmethod
    def _probe_video_size(path) -> Optional[Tuple[int, int]]:
        """Probe the source video's pixel dimensions (width, height) with ffprobe."""
        try:
            from .config import FFPROBE_PATH
            if not FFPROBE_PATH:
                return None
            r = subprocess.run(
                [FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30)
            line = r.stdout.strip().splitlines()
            if not line:
                return None
            parts = line[0].split(",")
            if len(parts) != 2:
                return None
            return int(parts[0]), int(parts[1])
        except Exception:
            return None

    @staticmethod
    def _resolve_logo_region(W: int, H: int, position: Optional[str], size_pct: float, enabled: bool) -> Optional[Tuple[int, int, int, int]]:
        """
        Returns (x, y, w, h) of the corner region to blur for logo/watermark
        removal, or None if disabled / unknown position.
        """
        # An explicit position (from CLI/UI) always wins, even if the global
        # LOGO_REMOVE_ENABLED is off. The global flag only controls the default.
        if position is None:
            if not enabled:
                return None
            pos = LOGO_POSITION
        else:
            pos = str(position).strip().lower()
        if pos in ("", "off", "none", "false", "disabled"):
            return None
        if pos not in LOGO_POSITIONS:
            logger.warning(f"Unknown logo position '{pos}' - ignoring. Use one of {LOGO_POSITIONS}.")
            return None
        w = max(48, int(W * float(size_pct) / 100.0))
        h = max(30, int(w * 0.62))
        m = max(10, int(W * 0.015))
        if pos == "top-left":
            x, y = m, m
        elif pos == "top-right":
            x, y = W - w - m, m
        elif pos == "bottom-left":
            x, y = m, H - h - m
        else:  # bottom-right
            x, y = W - w - m, H - h - m
        return x, y, w, h

    def process_clip_to_short(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        srt_path: Optional[Path] = None,
        bgm_path: Optional[Path] = None,
        aspect: Optional[str] = None,
        fill: Optional[str] = None,
        logo_position: Optional[str] = None,
        like_subscribe: Optional[bool] = None,
        like_subscribe_text: Optional[str] = None,
        top_watermark_enabled: Optional[bool] = None,
        top_watermark_text: Optional[str] = None,
        subtitles: Optional[bool] = None
    ) -> Path:
        """
        1. Transcribes input video to SRT subtitles (1-2 word viral mode or standard mode).
           subtitles=False skips transcription + subtitle burning entirely
           (watermarks only) - used by the repost bot's render mode.
        2. Fits the video to a vertical canvas (default 3:4 like reference Shorts, or 9:16).
           fill="blur" keeps the WHOLE frame visible with a blurred background
           (nothing is cut); fill="crop" center-crops to fill the canvas.
        3. Burns bold yellow/white TikTok-style subtitles directly into the video.
        4. If background music is present in BGM_DIR, loops and mixes the BGM track
           under the voice audio at a clean volume ratio (-15dB to -20dB).
        5. If logo removal is enabled, blurs the logo corner (e.g. streamer overlay).
        """
        nonlocal_W, nonlocal_H = VERTICAL_WIDTH, VERTICAL_HEIGHT
        if aspect is None:
            aspect = SHORT_ASPECT
        aspect = str(aspect).strip().lower()
        if aspect in ("auto", "match", "source", "original"):
            # "auto" = match the SOURCE video's exact shape (e.g. 9:16 Short in,
            # 9:16 out) - NO blur bars / pillarbox on the sides. This is what
            # the repost bot should use so the Short looks exactly like the
            # original video, with only the watermarks added.
            src = self._probe_video_size(input_path)
            if src and src[0] > 0 and src[1] > 0:
                sw, sh = src
                W = 1080
                H = max(2, int(round(1080.0 * sh / sw / 2.0) * 2))  # keep even (yuv420p)
                aspect = f"{sw}:{sh}"
                fill = "crop"  # exact aspect => the crop does nothing, no bars, no cut
                logger.info(f"Aspect 'auto': source is {sw}x{sh} -> canvas {W}x{H} (like the original)")
            else:
                W, H = nonlocal_W, nonlocal_H
                logger.warning("Aspect 'auto' could not probe the source - using default canvas.")
        elif aspect == "3:4":
            W, H = 1080, 1440
        elif aspect == "9:16":
            W, H = 1080, 1920
        else:
            W, H = nonlocal_W, nonlocal_H
            logger.warning(f"Unknown aspect '{aspect}', using {W}x{H}")
        fill = (fill or FILL_MODE).strip().lower()
        if fill not in ("crop", "blur"):
            fill = "blur"

        if output_path is None:
            output_path = TEMP_DIR / f"processed_short_{input_path.stem}.mp4"

        if not Path(input_path).exists():
            raise FileNotFoundError(
                f"Input clip does not exist: {input_path}. The clip download step failed earlier."
            )

        # Step 1: Generate subtitles (skipped entirely when subtitles=False)
        subtitles_enabled = True if subtitles is None else bool(subtitles)
        if subtitles_enabled:
            if srt_path is None or not srt_path.exists():
                srt_path = self.transcribe_and_generate_srt(input_path)

        # Step 2: Check for Background Music (BGM)
        selected_bgm: Optional[Path] = None
        if bgm_path and bgm_path.exists():
            selected_bgm = bgm_path
        elif BGM_ENABLED and BGM_DIR.exists():
            candidate_tracks = [
                p for p in BGM_DIR.iterdir()
                if p.suffix.lower() in [".mp3", ".wav", ".m4a", ".aac"]
            ]
            if candidate_tracks:
                selected_bgm = random.choice(candidate_tracks)
                logger.info(f"Selected background music track: '{selected_bgm.name}'")

        logger.info(
            f"Rendering {W}x{H} ({aspect}, fill={fill}) and "
            f"burning subtitles into {output_path.name}..."
        )

        escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        # If the SRT file is missing/empty (e.g. a music-only clip with no speech,
        # or subtitles=False = watermark-only mode), skip burning subtitles.
        srt_usable = (
            subtitles_enabled
            and srt_path is not None
            and Path(srt_path).exists()
            and Path(srt_path).stat().st_size > 0
        )
        sub_filter = f"subtitles='{escaped_srt}':force_style='{SUBTITLE_FORCE_STYLE}'" if srt_usable else None

        # Build the video filter:
        #  - "crop": center-crop source to canvas aspect, scale to canvas.
        #  - "blur": keep the WHOLE frame visible and fill the rest with a
        #    blurred copy (nothing gets cut - classic TikTok/Shorts style).
        # Optional logo/watermark removal is applied to the FOREGROUND frame
        # (the actual video), so corner coordinates match the source video
        # regardless of how it is centered in the canvas.
        logo = self._resolve_logo_region(W, H, logo_position, LOGO_SIZE_PCT, LOGO_REMOVE_ENABLED)
        if logo:
            x, y, lw, lh = logo
            logger.info(f"Blurring logo/watermark at ({x},{y}) size {lw}x{lh}...")

        if fill == "crop":
            aspect_expr = f"{W}/{H}"
            crop_part = (
                f"[0:v]crop='if(gt(iw/ih,{aspect_expr}),ih*({aspect_expr}),iw)':"
                f"'if(gt(iw/ih,{aspect_expr}),ih,iw/({aspect_expr}))',"
                f"scale={W}:{H}"
            )
            if logo:
                video_chain = (
                    f"{crop_part}[vcrop];"
                    f"[vcrop]split[vl1][vl2];"
                    f"[vl2]crop={lw}:{lh}:{x}:{y},boxblur=20:5[lg];"
                    f"[vl1][lg]overlay={x}:{y}[vfit]"
                )
            else:
                video_chain = f"{crop_part}[vfit]"
            sub_source = "vfit"
        else:
            bg_part = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},boxblur=20:5[bg];"
                f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease"
            )
            if logo:
                video_chain = (
                    f"{bg_part}[fgraw];"
                    f"[fgraw]split[vl1][vl2];"
                    f"[vl2]crop={lw}:{lh}:{x}:{y},boxblur=20:5[lg];"
                    f"[vl1][lg]overlay={x}:{y}[fg2];"
                    f"[bg][fg2]overlay=(W-w)/2:(H-h)/2[vfit]"
                )
            else:
                video_chain = (
                    f"{bg_part}[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vfit]"
                )
            sub_source = "vfit"

        # Build the overlay chain: subtitles -> bottom "LIKE & SUBSCRIBE" banner
        # -> top channel watermark (light, semi-transparent).
        esc_font = SUBTITLE_FONT_NAME.replace(":", "\\:")
        stage_label = sub_source

        # ---- stage 1: subtitles ----
        stage = f"[{stage_label}]{sub_filter}[v_s1]" if sub_filter else f"[{stage_label}]null[v_s1]"
        stage_label = "v_s1"

        # ---- stage 2: bottom LIKE & SUBSCRIBE banner ----
        # like_subscribe: None -> use config default; True/False -> force on/off.
        show_banner = LIKE_AND_SUBSCRIBE_ENABLED if like_subscribe is None else bool(like_subscribe)
        # Per-account override of the banner text (e.g. different watermark per channel)
        banner_text = (like_subscribe_text or LIKE_AND_SUBSCRIBE_TEXT or "LIKE & SUBSCRIBE").strip()
        if show_banner and banner_text:
            esc_banner = banner_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            banner_fs = BOTTOM_BANNER_FONT_SIZE          # plain text, fixed size
            # y computed in Python (text_h is unreliable in chained drawtext):
            # text height ~= 1.2 x fontsize, so half ~= 0.6 x fontsize
            banner_y = max(0, int(H * BOTTOM_BANNER_Y_PCT / 100.0) - int(banner_fs * 0.6))
            it_b = _italic_font() if BOTTOM_BANNER_ITALIC else None
            if it_b:
                stage += (
                    f";[{stage_label}]drawtext=text='{esc_banner}':fontfile='{it_b}':fontsize={banner_fs}:"
                    f"fontcolor=white@{BOTTOM_BANNER_OPACITY}:"
                    f"x=(w-text_w)/2:y={banner_y}[v_s2]"
                )
            else:
                stage += (
                    f";[{stage_label}]drawtext=text='{esc_banner}':font='{esc_font}':fontsize={banner_fs}:"
                    f"fontcolor=white@{BOTTOM_BANNER_OPACITY}:"
                    f"x=(w-text_w)/2:y={banner_y}[v_s2]"
                )
            stage_label = "v_s2"
            logger.info(f"Adding '{banner_text}' banner at bottom of {output_path.name}")

        # ---- stage 3: top channel watermark (light) ----
        # top_watermark_enabled: None -> use config default; True/False -> force on/off.
        # top_watermark_text: None -> use config default; "" -> explicitly OFF;
        # otherwise use the given text (no fallback so "off" really means off).
        show_top = TOP_WATERMARK_ENABLED if top_watermark_enabled is None else bool(top_watermark_enabled)
        if top_watermark_text is None:
            top_text = (TOP_WATERMARK_TEXT or "").strip()
        else:
            top_text = top_watermark_text.strip()
        if show_top and top_text:
            esc_top = top_text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            top_fs = TOP_WATERMARK_FONT_SIZE             # plain text, fixed size
            top_y = max(0, int(H * TOP_WATERMARK_Y_PCT / 100.0) - int(top_fs * 0.6))
            it_t = _italic_font() if TOP_WATERMARK_ITALIC else None
            if it_t:
                stage += (
                    f";[{stage_label}]drawtext=text='{esc_top}':fontfile='{it_t}':fontsize={top_fs}:"
                    f"fontcolor={TOP_WATERMARK_COLOR}@{TOP_WATERMARK_OPACITY}:"
                    f"x=(w-text_w)/2:y={top_y}[vout]"
                )
            else:
                stage += (
                    f";[{stage_label}]drawtext=text='{esc_top}':font='{esc_font}':fontsize={top_fs}:"
                    f"fontcolor={TOP_WATERMARK_COLOR}@{TOP_WATERMARK_OPACITY}:"
                    f"x=(w-text_w)/2:y={top_y}[vout]"
                )
            stage_label = "vout"
            logger.info(f"Adding top watermark '{top_text}' (light) at top of {output_path.name}")
        else:
            stage += f";[{stage_label}]null[vout]"
            stage_label = "vout"

        sub_stage = stage
        final_label = "vout"

        if selected_bgm and selected_bgm.exists():
            logger.info(
                f"Mixing BGM '{selected_bgm.name}' at {int(BGM_VOLUME*100)}% volume "
                f"with main speech at {int(VOICE_VOLUME*100)}% volume..."
            )
            filter_complex = (
                f"{video_chain};"
                f"{sub_stage};"
                f"[0:a]volume={VOICE_VOLUME}[a0];"
                f"[1:a]volume={BGM_VOLUME}[a1];"
                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd = [
                FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(input_path),
                "-stream_loop", "-1", "-i", str(selected_bgm),
                "-filter_complex", filter_complex,
                "-map", f"[{final_label}]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
                "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-movflags", "+faststart",
                "-threads", "0",
                str(output_path)
            ]
        else:
            filter_complex = (
                f"{video_chain};"
                f"{sub_stage}"
            )
            cmd = [
                FFMPEG_PATH, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(input_path),
                "-filter_complex", filter_complex,
                "-map", f"[{final_label}]", "-map", "0:a",
                "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
                "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                "-movflags", "+faststart",
                "-threads", "0",
                str(output_path)
            ]

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Successfully rendered vertical short: {output_path} ({output_path.stat().st_size / 1024 / 1024:.2f} MB)")
            return output_path
        except subprocess.CalledProcessError as e:
            # Windows safety net: if the configured font does not exist on this
            # machine (e.g. DejaVu Sans), retry once with Arial before giving up.
            if sys.platform.startswith("win"):
                retry_cmd = []
                changed = False
                for arg in cmd:
                    if isinstance(arg, str) and "Fontname=" in arg:
                        new_arg = re.sub(r"Fontname=[^,]+", "Fontname=Arial", arg)
                        if new_arg != arg:
                            changed = True
                        retry_cmd.append(new_arg)
                    else:
                        retry_cmd.append(arg)
                if changed:
                    logger.warning(
                        "FFmpeg render failed - retrying once with 'Arial' font "
                        "(the configured font is probably not installed on Windows)."
                    )
                    try:
                        subprocess.run(retry_cmd, check=True)
                        logger.info(
                            f"Successfully rendered vertical short (Arial retry): {output_path} "
                            f"({output_path.stat().st_size / 1024 / 1024:.2f} MB)"
                        )
                        return output_path
                    except subprocess.CalledProcessError as e2:
                        logger.error(f"FFmpeg failed again with Arial font: {e2}")
                        raise
            logger.error(f"FFmpeg failed while processing short: {e}")
            raise
