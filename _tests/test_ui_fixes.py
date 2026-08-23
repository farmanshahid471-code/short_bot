"""
TEST 9: '+' button (GET), delete robustness, repost single-URL = no subtitles.
"""
import sys, json, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path

CLIP = Path("/home/user/yt_shorts_bot")
REPOST = Path("/home/user/yt_shorts_repost_bot")
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        shutil.copy(acc, d / "accounts.json.bak"); acc.unlink()

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

from yt_shorts_repost_bot import webui as repost_webui
app = repost_webui.create_app().test_client()

print("\n=== 1. '+' button (GET link) now works ===")
r = app.get("/api/accounts/add", follow_redirects=False)
check("GET /api/accounts/add -> 302 (not 405)", r.status_code == 302, str(r.status_code))
loc = r.headers.get("Location", "")
check("redirects into the new tab", "account=New%20Channel%201" in loc or "account=New+Channel+1" in loc, loc)
data = json.loads((REPOST / "accounts.json").read_text())
check("account actually created", len(data["accounts"]) == 1 and data["accounts"][0]["name"] == "New Channel 1")
r = app.get("/api/accounts/add")
data = json.loads((REPOST / "accounts.json").read_text())
check("second + creates New Channel 2", [a["name"] for a in data["accounts"]] == ["New Channel 1", "New Channel 2"])
# the tab bar link renders as expected
html = repost_webui._render_page(loaded_account="New Channel 1")
check("+ tab link points at /api/accounts/add", 'href="/api/accounts/add"' in html)

print("\n=== 2. Delete robustness ===")
r = app.post("/api/accounts/delete", data={"account": "Ghost"})
loc = r.headers.get("Location", "")
check("deleting unknown account -> error, nothing lost", "type=err" in loc and "not+found" in loc, loc)
data = json.loads((REPOST / "accounts.json").read_text())
check("both accounts still there", len(data["accounts"]) == 2)
r = app.post("/api/accounts/delete", data={"account": "New Channel 2"})
loc = r.headers.get("Location", "")
check("delete OK, redirect to remaining tab", "account=New+Channel+1" in loc, loc)
data = json.loads((REPOST / "accounts.json").read_text())
check("deleted account gone", len(data["accounts"]) == 1 and data["accounts"][0]["name"] == "New Channel 1")
r = app.post("/api/accounts/delete", data={"account": "New Channel 1"})
data = json.loads((REPOST / "accounts.json").read_text())
check("deleting LAST account creates a fresh one (no phantom tab)", len(data["accounts"]) == 1
      and data["accounts"][0]["name"] == "New Channel 1", str(data))
# delete button has a confirm
html = repost_webui._render_page(loaded_account="New Channel 1")
check("delete button asks for confirmation", "confirm('Delete this account" in html)

print("\n=== 3. Repost single-URL path: NO subtitles, watermarks + title settings honored ===")
import yt_shorts_repost_bot.main as main_mod
import yt_shorts_repost_bot.reprocessor as rp_mod
import yt_shorts_repost_bot.processor as rproc
rproc.BGM_ENABLED = False
seen = {}
orig_process_short = rp_mod.ShortReprocessor.process_short
def spy(self, input_path, output_path=None, like_subscribe=None, like_subscribe_text=None,
        top_watermark_enabled=None, top_watermark_text=None, mode=None, subtitles=None,
        aspect=None, fill=None):
    seen.update({"subtitles": subtitles, "mode": mode,
                 "like_subscribe_text": like_subscribe_text,
                 "top_watermark_text": top_watermark_text})
    return orig_process_short(self, input_path, output_path=output_path,
                              like_subscribe=like_subscribe, like_subscribe_text=like_subscribe_text,
                              top_watermark_enabled=top_watermark_enabled,
                              top_watermark_text=top_watermark_text, mode=mode, subtitles=subtitles,
                              aspect=aspect, fill=fill)
rp_mod.ShortReprocessor.process_short = spy

# stub network: fetcher.download_short + get_short_info
class FakeFetcher:
    @staticmethod
    def download_short(url, output_path=None):
        out = Path("/tmp/fake_short.mp4")
        if not out.exists():
            import subprocess
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "color=c=0x141e3c:s=720x1280:d=3:r=30",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                            "-c:a", "aac", "-shortest", str(out)], check=True)
        return out
    @staticmethod
    def get_short_info(url):
        return {"id": "TEST12345678", "title": "Fake Short", "channel": "@fake"}
    @staticmethod
    def _extract_video_id(url):
        return "TEST12345678"
main_mod.ShortsFetcher = FakeFetcher

# fresh DB so "already reposted" never blocks this test (bot DB persists between runs)
from yt_shorts_repost_bot.models import StateDB as RealStateDB
if Path("/tmp/test_ui_fixes.db").exists(): Path("/tmp/test_ui_fixes.db").unlink()
main_mod.StateDB = lambda: RealStateDB(db_path=Path("/tmp/test_ui_fixes.db"))

from yt_shorts_repost_bot.uploader import YouTubeUploader
orig_upload = YouTubeUploader.upload_short
calls = {}
def spy_upload(self, video_path, original_video_id, original_title, original_url="",
               channel_name="", part_label=None, account="", account_max_daily=None,
               info=None, transcript_text="", extra_hashtags="", title_prefix=None,
               title_hashtags="", smart_titles=None, expected_channel=None):
    calls.update({"prefix": title_prefix, "hashtags": title_hashtags,
                  "expected": expected_channel, "account": account})
    return "mock_uploaded"
YouTubeUploader.upload_short = spy_upload

acc = {"name": "PeterAKing", "process_mode": "render", "subtitles_enabled": False,
       "watermark": "@PeterAKing", "watermark_enabled": True,
       "top_watermark": "PETER", "top_watermark_enabled": True,
       "title_prefix": "KING", "title_hashtags": "familyguy, peter",
       "expected_channel": "PeterAKing", "max_daily_uploads": 6,
       "client_secret": "", "token": ""}
main_mod.repost_one_url("https://www.youtube.com/shorts/TEST12345678", account=acc)
check("single-URL render gets subtitles=False", seen.get("subtitles") is False, str(seen.get("subtitles")))
check("single-URL render gets account watermarks", seen.get("like_subscribe_text") == "@PeterAKing"
      and seen.get("top_watermark_text") == "PETER", str(seen))
check("single-URL upload gets title prefix + hashtags", calls.get("prefix") == "KING"
      and calls.get("hashtags") == "familyguy, peter", str(calls))
check("single-URL upload gets safety lock", calls.get("expected") == "PeterAKing")
rp_mod.ShortReprocessor.process_short = orig_process_short
YouTubeUploader.upload_short = orig_upload

# ---- cleanup ----
for d in (CLIP, REPOST):
    acc_f = d / "accounts.json"
    if acc_f.exists(): acc_f.unlink()
    bak = d / "accounts.json.bak"
    if bak.exists(): shutil.move(bak, d / "accounts.json")

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
