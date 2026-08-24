from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import yt_shorts_bot.processor as processor_module
import yt_shorts_repost_bot.fetcher as fetcher_module
from yt_shorts_bot.processor import VideoProcessor, _italic_font
from yt_shorts_repost_bot.fetcher import ShortsFetcher


def binaries():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("full ffmpeg/ffprobe binaries are not available")
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    if " drawtext " not in filters or " subtitles " not in filters:
        pytest.skip("FFmpeg build lacks drawtext/subtitles")
    return ffmpeg, ffprobe


def make_source(path: Path, with_audio: bool = False, landscape: bool = True):
    ffmpeg, _ = binaries()
    size = "640x360" if landscape else "360x640"
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x142040:s={size}:d=0.7:r=24",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.7", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path


def probe_size(path: Path):
    _, ffprobe = binaries()
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def configure_processor(monkeypatch):
    ffmpeg, ffprobe = binaries()
    monkeypatch.setattr(processor_module, "FFMPEG_PATH", ffmpeg)
    monkeypatch.setattr("yt_shorts_bot.config.FFPROBE_PATH", ffprobe)
    monkeypatch.setattr(processor_module, "BGM_ENABLED", False)
    return ffmpeg, ffprobe


def test_silent_video_and_special_watermark_text_render_safely(monkeypatch, tmp_path):
    configure_processor(monkeypatch)
    source = make_source(tmp_path / "silent.mp4", with_audio=False)
    output = VideoProcessor().process_clip_to_short(
        source,
        output_path=tmp_path / "out.mp4",
        aspect="9:16",
        subtitles=False,
        like_subscribe=True,
        like_subscribe_text="odd: [x]; %{n}' text",
        top_watermark_enabled=True,
        top_watermark_text="TOP, [safe]; %{pts}",
    )
    assert output.is_file() and output.stat().st_size > 0
    assert probe_size(output) == "1080,1920"


def test_subtitle_path_with_filter_characters_is_safe(monkeypatch, tmp_path):
    configure_processor(monkeypatch)
    source = make_source(tmp_path / "with audio.mp4", with_audio=True)
    subtitle = tmp_path / "odd,path's [caption].srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:00,500\nHELLO\n\n",
        encoding="utf-8",
    )
    output = VideoProcessor().process_clip_to_short(
        source,
        output_path=tmp_path / "captioned.mp4",
        srt_path=subtitle,
        aspect="9:16",
        subtitles=True,
        like_subscribe=False,
        top_watermark_enabled=False,
    )
    assert output.is_file() and output.stat().st_size > 0


def test_auto_landscape_is_forced_to_vertical(monkeypatch, tmp_path):
    configure_processor(monkeypatch)
    source = make_source(tmp_path / "landscape.mp4", with_audio=True)
    output = VideoProcessor().process_clip_to_short(
        source,
        output_path=tmp_path / "vertical.mp4",
        aspect="auto",
        fill="crop",
        subtitles=False,
        like_subscribe=False,
        top_watermark_enabled=False,
    )
    assert probe_size(output) == "1080,1920"


def test_logo_region_stays_inside_visible_foreground():
    region = VideoProcessor._resolve_logo_region(
        frame_x=0,
        frame_y=650,
        frame_w=1080,
        frame_h=620,
        position="bottom-right",
        size_pct=12,
        enabled=True,
    )
    x, y, width, height = region
    assert 0 <= x < 1080 and 650 <= y < 1270
    assert x + width <= 1080
    assert y + height <= 1270


def test_missing_drawtext_falls_back_instead_of_failing(monkeypatch, tmp_path):
    configure_processor(monkeypatch)
    source = make_source(tmp_path / "source.mp4")
    video_processor = VideoProcessor()
    video_processor._ffmpeg_filters = {
        "scale",
        "crop",
        "overlay",
        "split",
        "boxblur",
        "null",
    }
    output = video_processor.process_clip_to_short(
        source,
        output_path=tmp_path / "out.mp4",
        subtitles=False,
        like_subscribe=True,
        like_subscribe_text="text",
        top_watermark_enabled=False,
    )
    assert output.is_file() and output.stat().st_size > 0


def test_png_watermark_file_is_written(tmp_path):
    path = tmp_path / "mark.png"
    VideoProcessor().write_watermark_png(
        path,
        320,
        180,
        top_text="TOP",
        bottom_text="LIKE & SUBSCRIBE",
    )
    assert path.is_file() and path.stat().st_size > 0


def test_ass_watermark_file_contains_escaped_overlay_text(tmp_path):
    path = tmp_path / "mark.ass"
    VideoProcessor()._write_watermark_ass(
        path,
        1080,
        1920,
        top_text="TOP {ok}",
        bottom_text="LIKE",
    )
    text = path.read_text(encoding="utf-8")
    assert "Dialogue:" in text
    assert r"TOP \{ok\}" in text
    assert "LIKE" in text


def test_age_restricted_download_asks_for_adult_cookies(monkeypatch, tmp_path):
    class AgeBlockedYDL:
        seen = []

        def __init__(self, opts):
            self.__class__.seen.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            raise RuntimeError(
                "ERROR: [youtube] abc: Sign in to confirm your age. "
                "This video may be inappropriate for some users."
            )

    AgeBlockedYDL.seen = []
    monkeypatch.setattr(fetcher_module.yt_dlp, "YoutubeDL", AgeBlockedYDL)
    monkeypatch.setattr(fetcher_module, "TEMP_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="AGE_RESTRICTED"):
        ShortsFetcher().download_short("https://www.youtube.com/shorts/abcdefghijk")
    clients = [
        (opts.get("extractor_args") or {}).get("youtube", {}).get("player_client", [None])[0]
        for opts in AgeBlockedYDL.seen
    ]
    assert "tv_embedded" in clients
    from yt_shorts_repost_bot.scheduler import ShortsRepostScheduler

    assert (
        ShortsRepostScheduler._status_for_processing_error(
            RuntimeError("AGE_RESTRICTED: need cookies")
        )
        == "PROCESSING_FAILED"
    )


def test_transcription_uses_language_detection(monkeypatch, tmp_path):
    seen = {}

    class Info:
        language = "ur"
        language_probability = 0.9

    class Model:
        def transcribe(self, _path, **kwargs):
            seen.update(kwargs)
            return iter(()), Info()

    monkeypatch.setattr(processor_module, "WHISPER_LANGUAGE", "auto")
    video_processor = VideoProcessor()
    video_processor._whisper_model = Model()
    source = tmp_path / "audio.mp4"
    source.write_bytes(b"stub")
    video_processor.transcribe_and_generate_srt(source, tmp_path / "out.srt")
    assert seen["language"] is None
    assert seen["word_timestamps"] is True


def test_whisper_is_not_imported_at_processor_module_import():
    root = Path(__file__).resolve().parents[1]
    code = "import sys; import yt_shorts_repost_bot.processor; print('faster_whisper' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().endswith("False")


def test_windows_italic_helper_returns_a_real_file(monkeypatch, tmp_path):
    windows = tmp_path / "Windows"
    fonts = windows / "Fonts"
    fonts.mkdir(parents=True)
    italic = fonts / "ariali.ttf"
    italic.write_bytes(b"font")
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(processor_module.sys, "platform", "win32")
    assert Path(_italic_font()).is_file()


class FakeYDL:
    seen = []
    attempts = 0

    def __init__(self, opts):
        self.opts = opts
        self.__class__.seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def download(self, _urls):
        self.__class__.attempts += 1
        output = Path(self.opts["outtmpl"])
        if self.__class__.attempts == 1:
            Path(str(output) + ".part").write_bytes(b"partial")
            raise RuntimeError("first client failed")
        output.write_bytes(b"complete")

    def extract_info(self, _url, download=False):
        return {"id": "abcdefghijk", "title": "T"}


def test_yt_dlp_player_retries_use_extractor_args_and_clean_parts(
    monkeypatch, tmp_path
):
    FakeYDL.seen = []
    FakeYDL.attempts = 0
    monkeypatch.setattr(fetcher_module.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(ShortsFetcher, "_probe_duration", staticmethod(lambda _path: 30.0))
    monkeypatch.setattr(fetcher_module, "TEMP_DIR", tmp_path)
    output = ShortsFetcher().download_short("https://www.youtube.com/shorts/abcdefghijk")
    assert output.read_bytes() == b"complete"
    assert FakeYDL.seen[0]["extractor_args"]["youtube"]["player_client"] == [
        "android",
        "web",
    ]
    assert FakeYDL.seen[1]["extractor_args"]["youtube"]["player_client"] == [
        "tv_embedded"
    ]
    assert "/best" in FakeYDL.seen[0]["format"]
    assert not list(tmp_path.glob("*.part*"))
    assert "_" in output.stem  # random job suffix avoids cross-account collisions
