"""
TEST 4: END-TO-END scheduler flow (dry-run, network stubbed).
Verifies: per-account settings thread through, never-post-twice, quota,
delete-after-upload (local copy + sidecar), process mode passthrough.
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

# ----- stub the fetcher / reprocessor classes (NO network) -----
class FakeFetcher:
    def __init__(self, channels=None, **kw):
        self.channels = channels or []
    @staticmethod
    def download_short(video_url, output_path=None):
        out = Path(output_path) if output_path else Path("/tmp/fake_short.mp4")
        shutil.copy(SRC, out)
        return out
    @staticmethod
    def get_short_info(video_url):
        return {"title": "Fake Short Title", "tags": ["fake"], "channel": "@fake"}
    def fetch_channel_recent_shorts(self, channel_url):
        return [
            {"video_id": "AAA111BBB22", "url": "https://www.youtube.com/shorts/AAA111BBB22", "title": "Short One", "duration": 30, "channel": channel_url},
            {"video_id": "CCC333DDD44", "url": "https://www.youtube.com/shorts/CCC333DDD44", "title": "Short Two", "duration": 25, "channel": channel_url},
        ]

import yt_shorts_repost_bot.scheduler as sched_mod
import yt_shorts_repost_bot.reprocessor as rp_mod
import yt_shorts_repost_bot.processor as rproc
rproc.BGM_ENABLED = False

from yt_shorts_repost_bot.reprocessor import ShortReprocessor
class FakeReprocessor(ShortReprocessor):
    def process_short(self, input_path, output_path=None, **kw):
        out = Path(output_path) if output_path else Path("/tmp/final_fake.mp4")
        shutil.copy(SRC, out)
        return out

# patch the names INSIDE the scheduler module
sched_mod.ShortsFetcher = FakeFetcher
sched_mod.ShortReprocessor = FakeReprocessor

def fake_transcribe(self, video_path, srt_path=None, mode="viral"):
    p = Path(srt_path) if srt_path else video_path.with_suffix(".srt")
    p.write_text("", encoding="utf-8")
    return p
rproc.VideoProcessor.transcribe_and_generate_srt = fake_transcribe

# ----- fresh DB -----
from yt_shorts_repost_bot.models import StateDB
TMPDB = Path("/tmp/test_state.db")
if TMPDB.exists(): TMPDB.unlink()
db = StateDB(db_path=TMPDB)

from yt_shorts_repost_bot.config import KEEP_SHORTS_DIR
KEEP_SHORTS_DIR.mkdir(parents=True, exist_ok=True)
from yt_shorts_repost_bot.uploader import YouTubeUploader

ACCOUNT = {
    "name": "TestAcc", "target_channels": ["https://www.youtube.com/@FakeChannel"],
    "max_daily_uploads": 10, "process_mode": "render", "selection_order": "newest",
    "max_shorts_per_channel_cycle": 5, "min_minutes_between_uploads": 0,
    "delete_after_upload": True, "delete_r2_after_upload": True,
    "title_prefix": "TEST", "title_hashtags": "funny, clips",
    "watermark": "SUBSCRIBE TEST", "watermark_enabled": True,
    "top_watermark": "MY CHANNEL", "top_watermark_enabled": True,
    "enabled": True,
}

print("\n=== 1. Full _process_one: render mode + delete-after-upload ===")
sched = sched_mod.ShortsRepostScheduler(interval_hours=1, accounts=[ACCOUNT])
sched.state_db = db
seen_modes = []
orig_process_short = ShortReprocessor.process_short
def spy_process_short(self, input_path, output_path=None, like_subscribe=None,
                      like_subscribe_text=None, top_watermark_enabled=None,
                      top_watermark_text=None, mode=None, subtitles=None,
                      aspect=None, fill=None):
    seen_modes.append(mode)
    return orig_process_short(self, input_path, output_path=output_path,
                              like_subscribe=like_subscribe, like_subscribe_text=like_subscribe_text,
                              top_watermark_enabled=top_watermark_enabled,
                              top_watermark_text=top_watermark_text, mode=mode,
                              subtitles=subtitles, aspect=aspect, fill=fill)
ShortReprocessor.process_short = spy_process_short
up = YouTubeUploader(client_secret_file=Path("/nonexistent/client.json"),  # -> DRY-RUN mock
                     token_file=Path("/nonexistent/token.json"), state_db=db)
ok = sched._process_one(
    "AAA111BBB22", "https://www.youtube.com/shorts/AAA111BBB22", "Short One",
    "https://www.youtube.com/@FakeChannel", account="TestAcc", max_daily=10,
    fetcher=FakeFetcher(), reprocessor=ShortReprocessor(), uploader=up,
    like_subscribe=True, like_subscribe_text="SUBSCRIBE TEST",
    top_watermark_enabled=True, top_watermark_text="MY CHANNEL",
    extra_hashtags="", title_prefix="TEST", title_hashtags="funny, clips",
    smart_titles=None, delete_after_upload=True, delete_r2_after_upload=True,
    process_mode="render")
check("dry-run upload 'succeeded' (mock id)", ok is True)
check("process_mode 'render' passed to reprocessor", seen_modes == ["render"], str(seen_modes))
check("upload recorded in DB (per account)", db.get_uploads_in_last_24_hours(account="TestAcc") == 1)
row = db.get_video_state("AAA111BBB22", account="TestAcc")
check("video marked UPLOADED_YOUTUBE", row and row["status"] == "UPLOADED_YOUTUBE")
copy_f = KEEP_SHORTS_DIR / "TestAcc_repost_AAA111BBB22.mp4"
side_f = KEEP_SHORTS_DIR / "TestAcc_repost_AAA111BBB22.txt"
check("local copy was DELETED after upload", not copy_f.exists())
check("sidecar was DELETED after upload", not side_f.exists())

print("\n=== 2. Never post the same video twice ===")
check("is_video_processed -> True (won't repost)", db.is_video_processed("AAA111BBB22", account="TestAcc"))
check("different account: not processed (per-account)", not db.is_video_processed("AAA111BBB22", account="OtherAcc"))

print("\n=== 3. Quota enforcement per account ===")
can, rem = db.can_upload_today(max_daily_uploads=10, account="TestAcc")
check("9 slots left for TestAcc", can and rem == 9, f"rem={rem}")
for i in range(10):
    db.record_upload(f"vid{i}", f"mock{i}", account="QuotaAcc")
can, rem = db.can_upload_today(max_daily_uploads=10, account="QuotaAcc")
check("QuotaAcc cap reached at 10", not can and rem == 0)
can2, rem2 = db.can_upload_today(max_daily_uploads=10, account="TestAcc")
check("TestAcc quota unaffected (separate per account)", can2 and rem2 == 9)

print("\n=== 4. Full scheduler cycle: skips already-posted, uploads the NEW one ===")
sched3 = sched_mod.ShortsRepostScheduler(interval_hours=1, accounts=[dict(ACCOUNT, process_mode="copy", delete_after_upload=False)])
sched3.state_db = db
n = sched3.run_single_cycle()
check("cycle uploaded exactly 1 short (the new one)", n == 1, str(n))
check("new short CCC333DDD44 now processed", db.is_video_processed("CCC333DDD44", account="TestAcc"))
check("old short AAA NOT double-posted (still 2 total)", db.get_uploads_in_last_24_hours(account="TestAcc") == 2)

print("\n=== 5. Disabled account is skipped ===")
if Path("/tmp/test_state5.db").exists(): Path("/tmp/test_state5.db").unlink()
db5 = StateDB(db_path=Path("/tmp/test_state5.db"))
sched5 = sched_mod.ShortsRepostScheduler(interval_hours=1, accounts=[
    {"name": "OffAcc", "target_channels": ["https://www.youtube.com/@FakeChannel"],
     "max_daily_uploads": 10, "enabled": False},
    {"name": "OnAcc", "target_channels": ["https://www.youtube.com/@FakeChannel"],
     "max_daily_uploads": 10, "max_shorts_per_channel_cycle": 1, "enabled": True}])
sched5.state_db = db5
made = sched5.run_single_cycle()
check("disabled account 0 uploads, enabled account 1", made == 1, str(made))
check("nothing recorded for OffAcc", db5.get_uploads_in_last_24_hours(account="OffAcc") == 0)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
