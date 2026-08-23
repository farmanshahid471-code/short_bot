"""
TEST 8: Subtitle toggle (repost render = watermark only) + channel safety lock.
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

# ---------- 1. subtitles toggle ----------
import yt_shorts_repost_bot.processor as rproc
rproc.BGM_ENABLED = False
from yt_shorts_repost_bot.reprocessor import ShortReprocessor

transcribed = []
orig_transcribe = rproc.VideoProcessor.transcribe_and_generate_srt
def spy_transcribe(self, video_path, srt_path=None, mode="viral"):
    transcribed.append(str(video_path))
    p = Path(srt_path) if srt_path else Path(video_path).with_suffix(".srt")
    p.write_text("1\n00:00:00,000 --> 00:00:01,000\nHELLO WORLD\n\n", encoding="utf-8")
    return p
rproc.VideoProcessor.transcribe_and_generate_srt = spy_transcribe

rp = ShortReprocessor()
print("\n=== 1. Repost render mode: subtitles OFF = watermark only ===")
out = rp.process_short(SRC, output_path=Path("/tmp/no_subs.mp4"), mode="render",
                       subtitles=False,
                       like_subscribe=True, like_subscribe_text="SUBSCRIBE",
                       top_watermark_enabled=True, top_watermark_text="MY CHANNEL")
check("render with subtitles=False does NOT transcribe", len(transcribed) == 0, str(transcribed))
# frame: bottom banner + top watermark present
def frame(video_path, png, t=0.5):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(t), "-i", str(video_path), "-frames:v", "1", str(png)], check=True)
    from PIL import Image
    return Image.open(png)
img = frame(out, "/tmp/frame_no_subs.png")
from PIL import Image as I
img = img.convert("RGB")
px = img.load()
def band_bright(y_lo, y_hi, x_lo=0.3, x_hi=0.7):
    pts = []
    for y in range(y_lo, min(y_hi, img.height)):
        for x in range(int(img.width*x_lo), int(img.width*x_hi)):
            if (px[x, y][0]+px[x, y][1]+px[x, y][2])/3 > 150:
                pts.append((x, y))
    return len(pts) > 0
check("bottom watermark burned (watermark-only mode)", band_bright(int(0.86*img.height), int(0.96*img.height)))
check("top watermark burned", band_bright(int(0.05*img.height), int(0.2*img.height)))
# middle should have NO subtitle text (source is plain color)
mid = sum(1 for y in range(int(0.35*img.height), int(0.65*img.height))
          for x in range(int(0.3*img.width), int(0.7*img.width))
          if (px[x, y][0]+px[x, y][1]+px[x, y][2])/3 > 150)
check("no subtitle text in the middle band", mid < 30, str(mid))

print("\n=== 2. Repost render mode: subtitles ON transcribes ===")
transcribed.clear()
out2 = rp.process_short(SRC, output_path=Path("/tmp/with_subs.mp4"), mode="render",
                        subtitles=True,
                        like_subscribe=True, like_subscribe_text="SUBSCRIBE",
                        top_watermark_enabled=True, top_watermark_text="MY CHANNEL")
check("render with subtitles=True DOES transcribe", len(transcribed) == 1)
rproc.VideoProcessor.transcribe_and_generate_srt = orig_transcribe

print("\n=== 3. UI save: subtitles_enabled + expected_channel ===")
import json
from pathlib import Path as P
CLIP = P("/home/user/yt_shorts_bot")
REPOST = P("/home/user/yt_shorts_repost_bot")
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        shutil.copy(acc, d / "accounts.json.bak"); acc.unlink()
from yt_shorts_repost_bot import webui as repost_webui
app = repost_webui.create_app().test_client()
app.post("/api/accounts/add")  # New Channel 1
r = app.post("/api/account-settings/save", data={
    "account": "New Channel 1",
    "subtitles_enabled": "false",   # hidden twin
    "expected_channel": "PeterAKing",
})
data = json.loads((REPOST / "accounts.json").read_text())
a = data["accounts"][0]
check("subtitles_enabled saved False (hidden twin)", a.get("subtitles_enabled") is False)
check("expected_channel saved", a.get("expected_channel") == "PeterAKing")
r = app.post("/api/account-settings/save", data={
    "account": "New Channel 1",
    "subtitles_enabled": "false",
    "subtitles_enabled": "true",    # checked checkbox wins (flask getlist order)
})
data = json.loads((REPOST / "accounts.json").read_text())
a = data["accounts"][0]
check("subtitles_enabled saved True when checked", a.get("subtitles_enabled") is True)
# expected_channel survives second save (merge, not wipe)
check("expected_channel kept after second save", a.get("expected_channel") == "PeterAKing")
# default when never set
r = app.post("/api/accounts/add")  # New Channel 2 - no settings saved
data = json.loads((REPOST / "accounts.json").read_text())
a2 = next(x for x in data["accounts"] if x["name"] == "New Channel 2")
check("unsaved account has no subtitles_enabled key (default False at runtime)", "subtitles_enabled" not in a2)

print("\n=== 4. Channel safety lock blocks wrong-channel uploads ===")
from yt_shorts_repost_bot.uploader import YouTubeUploader
from yt_shorts_repost_bot.models import StateDB

class FakeService:
    def __init__(self, titles):
        self.titles = titles
        self.insert_called = False
    def channels(self):
        class _C:
            def __init__(s, titles): s.titles = titles
            def list(s, part=None, mine=None):
                class _L:
                    def __init__(s, titles): s.titles = titles
                    def execute(s):
                        return {"items": [{"snippet": {"title": t}} for t in s.titles]}
                return _L(s.titles)
        return _C(self.titles)
    def videos(self):
        class _V:
            def __init__(s): s.insert_called = False
            def insert(s, part=None, body=None, media_body=None):
                s.insert_called = True
                class _Req:
                    def next_chunk(s):
                        return None, {"id": "mock123"}
                return _Req()
        self._v = _V()
        return self._v

# 4a. mismatch -> blocked
svc = FakeService(["Simpson Pimp"])
up = YouTubeUploader(client_secret_file=P("/x"), token_file=P("/y"), state_db=StateDB())
up.youtube_service = svc
ok = up._verify_channel(svc, "PeterAKing")
check("_verify_channel detects mismatch", ok[0] is False and "Simpson Pimp" in ok[1])
sid = up.upload_short(video_path=SRC, original_video_id="vid1", original_title="T",
                      account="PeterAKing", expected_channel="PeterAKing")
v_created = getattr(svc, "_v", None)
check("upload BLOCKED on mismatch (returns None, no API call)", sid is None and v_created is None)

# 4b. match -> allowed
svc2 = FakeService(["PeterAKing"])
ok2 = up._verify_channel(svc2, "PeterAKing")
check("_verify_channel accepts match", ok2[0] is True)
# dry-run path (no real service) is NOT blocked by the lock
up2 = YouTubeUploader(client_secret_file=P("/nonexistent/client.json"), token_file=P("/nonexistent/token.json"),
                      state_db=StateDB())
sid2 = up2.upload_short(video_path=SRC, original_video_id="vid2", original_title="T",
                        account="PeterAKing", expected_channel="PeterAKing")
check("dry-run (no service) still allowed", sid2 is not None)

# ---- cleanup ----
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists(): acc.unlink()
    bak = d / "accounts.json.bak"
    if bak.exists(): shutil.move(bak, d / "accounts.json")
for p in ("/tmp/no_subs.mp4", "/tmp/with_subs.mp4", "/tmp/frame_no_subs.png"):
    try: Path(p).unlink()
    except Exception: pass

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
