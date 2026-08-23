"""
TEST 10: SETTINGS CHAIN AUDIT - every per-account setting must flow from
accounts.json -> scheduler -> reprocessor/uploader. Top-to-bottom check.
"""
import sys, shutil, subprocess
sys.path.insert(0, "/home/user")
from pathlib import Path

SRC = Path("/home/user/_tests/source_test.mp4")
if not SRC.exists():
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x141e3c:s=1280x720:d=5:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-shortest", str(SRC)], check=True)

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

import yt_shorts_repost_bot.scheduler as sched_mod
import yt_shorts_repost_bot.reprocessor as rp_mod
import yt_shorts_repost_bot.processor as rproc
rproc.BGM_ENABLED = False
from yt_shorts_repost_bot.reprocessor import ShortReprocessor
from yt_shorts_repost_bot.models import StateDB
from yt_shorts_repost_bot.uploader import YouTubeUploader

class FakeFetcher:
    def __init__(self, channels=None, **kw): self.channels = channels or []
    @staticmethod
    def download_short(video_url, output_path=None):
        out = Path(output_path) if output_path else Path("/tmp/fake_short.mp4")
        shutil.copy(SRC, out); return out
    @staticmethod
    def get_short_info(video_url): return {"title": "Fake Short", "tags": ["fake"], "channel": "@fake"}
    def fetch_channel_recent_shorts(self, channel_url):
        return [{"video_id": "AAA111BBB22", "url": "https://www.youtube.com/shorts/AAA111BBB22",
                 "title": "Short One", "duration": 30, "channel": channel_url}]

sched_mod.ShortsFetcher = FakeFetcher
sched_mod.ShortReprocessor = ShortReprocessor

seen_proc, seen_up = {}, {}
orig_process = ShortReprocessor.process_short
def spy_process(self, input_path, output_path=None, like_subscribe=None, like_subscribe_text=None,
                top_watermark_enabled=None, top_watermark_text=None, mode=None, subtitles=None,
                aspect=None, fill=None):
    seen_proc.update({"mode": mode, "subtitles": subtitles, "aspect": aspect, "fill": fill,
                      "like_subscribe": like_subscribe, "like_subscribe_text": like_subscribe_text,
                      "top_wm_enabled": top_watermark_enabled, "top_wm_text": top_watermark_text})
    out = Path(output_path) if output_path else Path("/tmp/final_fake.mp4")
    shutil.copy(SRC, out); return out
ShortReprocessor.process_short = spy_process

orig_upload = YouTubeUploader.upload_short
def spy_upload(self, video_path, original_video_id, original_title, original_url="", channel_name="",
               part_label=None, account="", account_max_daily=None, info=None, transcript_text="",
               extra_hashtags="", title_prefix=None, title_hashtags="", smart_titles=None,
               expected_channel=None):
    seen_up.update({"account": account, "max_daily": account_max_daily, "prefix": title_prefix,
                    "hashtags": title_hashtags, "smart": smart_titles, "expected": expected_channel,
                    "extra_hashtags": extra_hashtags})
    if self.state_db is not None:
        self.state_db.record_upload(original_video_id, "mock_short", account=account)
    return "mock_short"
YouTubeUploader.upload_short = spy_upload

TMPDB = Path("/tmp/test_chain.db")
if TMPDB.exists(): TMPDB.unlink()

ACCOUNT = {
    "name": "ChainAcc", "target_channels": ["https://www.youtube.com/@FakeChannel"],
    "max_daily_uploads": 7,
    "process_mode": "render",
    "selection_order": "oldest",
    "max_shorts_per_channel_cycle": 2,
    "min_minutes_between_uploads": 0,
    "subtitles_enabled": False,                 # repost: no subtitles
    "watermark": "@ChainAcc", "watermark_enabled": True,
    "top_watermark": "CHAIN TOP", "top_watermark_enabled": True,
    "aspect": "3:4", "fill": "crop",
    "title_prefix": "CHAIN", "title_hashtags": "one, two", "smart_titles": True,
    "expected_channel": "ChainAcc",
    "delete_after_upload": True, "delete_r2_after_upload": True,
    "enabled": True,
}

print("\n=== Repost scheduler: every setting flows to the right layer ===")
sched = sched_mod.ShortsRepostScheduler(interval_hours=1, accounts=[ACCOUNT])
sched.state_db = StateDB(db_path=TMPDB)
n = sched.run_single_cycle()
check("cycle ran and uploaded", n == 1, str(n))
# --- process layer (render) ---
check("process_mode -> render", seen_proc.get("mode") == "render", str(seen_proc.get("mode")))
check("subtitles -> False (repost = watermark only)", seen_proc.get("subtitles") is False)
check("per-account aspect 3:4 passed to renderer", seen_proc.get("aspect") == "3:4", str(seen_proc.get("aspect")))
check("per-account fill crop passed to renderer", seen_proc.get("fill") == "crop")
check("bottom watermark text + enabled", seen_proc.get("like_subscribe_text") == "@ChainAcc"
      and seen_proc.get("like_subscribe") is True)
check("top watermark text + enabled", seen_proc.get("top_wm_text") == "CHAIN TOP"
      and seen_proc.get("top_wm_enabled") is True)
# --- upload layer ---
check("account name threaded", seen_up.get("account") == "ChainAcc")
check("max_daily 7 threaded", seen_up.get("max_daily") == 7)
check("title prefix threaded", seen_up.get("prefix") == "CHAIN")
check("title hashtags threaded", seen_up.get("hashtags") == "one, two")
check("smart_titles threaded", seen_up.get("smart") is True)
check("expected_channel (safety lock) threaded", seen_up.get("expected") == "ChainAcc")
check("extra_hashtags threaded (empty)", seen_up.get("extra_hashtags") == "")

print("\n=== DB side effects ===")
check("upload recorded for ChainAcc", StateDB(db_path=TMPDB).get_uploads_in_last_24_hours(account="ChainAcc") == 1)
row = StateDB(db_path=TMPDB).get_video_state("AAA111BBB22", account="ChainAcc")
check("video state UPLOADED_YOUTUBE", row and row["status"] == "UPLOADED_YOUTUBE")

print("\n=== Clip scheduler defaults: subtitles stay ON ===")
import yt_shorts_bot.scheduler as csched_mod
import yt_shorts_bot.processor as cproc
from yt_shorts_bot.processor import VideoProcessor
seen_clip = {}
orig_cproc = VideoProcessor.process_clip_to_short
def spy_clip(self, input_path, output_path=None, srt_path=None, bgm_path=None, aspect=None,
             fill=None, logo_position=None, like_subscribe=None, like_subscribe_text=None,
             top_watermark_enabled=None, top_watermark_text=None, subtitles=None):
    seen_clip.update({"subtitles": subtitles, "aspect": aspect, "fill": fill})
    return SRC
VideoProcessor.process_clip_to_short = spy_clip
cacc = {"name": "ClipAcc", "target_channels": ["https://www.youtube.com/@FakeChannel"],
        "max_daily_uploads": 10, "enabled": True}
s = csched_mod.ShortsBotScheduler(interval_hours=1, accounts=[cacc])
s.state_db = StateDB(db_path=Path("/tmp/test_chain_clip.db"))
# no network: stub the segment download to return the local test video
csched_mod.ShortsBotScheduler._download_window = lambda self, url, start, end: SRC
cs, tk = ("", "")
from yt_shorts_bot.uploader import YouTubeUploader as ClipUploader
s._process_video_windows(
    "VID00000001", "https://youtu.be/VID00000001", "Clip Title", "https://www.youtube.com/@FakeChannel",
    [{"start": 1.0, "end": 3.0}], account="ClipAcc", max_daily=10,
    uploader=ClipUploader(client_secret_file=Path("/nonexistent/c.json"), token_file=Path("/nonexistent/t.json"),
                          state_db=StateDB(db_path=Path("/tmp/test_chain_clip.db"))),
    subtitles_enabled=True, expected_channel=None)
check("clip bot subtitles default ON", seen_clip.get("subtitles") is True)
VideoProcessor.process_clip_to_short = orig_cproc

ShortReprocessor.process_short = orig_process
YouTubeUploader.upload_short = orig_upload

# cleanup
for p in ("/tmp/test_chain.db", "/tmp/test_chain_clip.db"):
    try: Path(p).unlink()
    except Exception: pass

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
