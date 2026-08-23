"""
TEST 1: Account add/delete + per-tab settings save via the web UI API.
Uses Flask's test client (no network, no browser).
"""
import sys, json, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path

CLIP = Path("/home/user/yt_shorts_bot")
REPOST = Path("/home/user/yt_shorts_repost_bot")

# --- isolate state: back up any real accounts.json, then start CLEAN ---
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        shutil.copy(acc, d / "accounts.json.bak")
        acc.unlink()
    env = d / ".env"
    if env.exists():
        shutil.copy(env, d / ".env.bak")

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

from yt_shorts_bot import webui as clip_webui
from yt_shorts_repost_bot import webui as repost_webui

clip_app = clip_webui.create_app().test_client()
repost_app = repost_webui.create_app().test_client()

# ============ 1. ADD many accounts ============
print("\n=== 1. ADD accounts (as many as you want) ===")
for i in range(5):
    r = clip_app.post("/api/accounts/add")
    check(f"add #{i+1} redirects", r.status_code == 302)

data = json.loads((CLIP / "accounts.json").read_text())
names = [a["name"] for a in data["accounts"]]
check("5 accounts added", len(names) == 5, str(names))
check("auto names New Channel 1..5", names == [f"New Channel {i}" for i in range(1, 6)])

# ============ 2. Save per-tab settings ============
print("\n=== 2. Save different settings per account tab ===")
r = clip_app.post("/api/account-settings/save", data={
    "account": "New Channel 1",
    "title_prefix": "",                       # explicit empty must STAY empty
    "title_hashtags": "simpsons, homer, bart",
    "smart_titles": "true",
    "max_daily_uploads": "7",
    "shorts_per_video": "3",
    "min_minutes_between_uploads": "45",
    "top_watermark": "SIMPSON PIMP",
    "top_watermark_enabled": "true",
    "watermark": "SUBSCRIBE FOR MORE",
    "watermark_enabled": "true",
    "aspect": "3:4",
    "fill": "blur",
    "delete_after_upload": "true",
    "delete_r2_after_upload": "false",
    "cycle_interval_hours": "1",
})
check("settings save OK", r.status_code == 302)

r = clip_app.post("/api/account-settings/save", data={
    "account": "New Channel 2",
    "title_prefix": "🔥",
    "title_hashtags": "finance, money",
    "max_daily_uploads": "10",
    "top_watermark": "FINANCE DAILY",
    "watermark": "LIKE & SUBSCRIBE",
    "aspect": "9:16",
    "fill": "crop",
})
check("settings save #2 OK", r.status_code == 302)

data = json.loads((CLIP / "accounts.json").read_text())
accs = {a["name"]: a for a in data["accounts"]}
a1, a2 = accs["New Channel 1"], accs["New Channel 2"]
check("prefix '' stays empty (no emoji fallback)", a1.get("title_prefix", "MISSING") == "", repr(a1.get("title_prefix")))
check("hashtags saved", a1.get("title_hashtags") == "simpsons, homer, bart")
check("smart_titles bool", a1.get("smart_titles") is True)
check("max_daily=7", a1.get("max_daily_uploads") == 7)
check("shorts_per_video=3", a1.get("shorts_per_video") == 3)
check("min_minutes=45", a1.get("min_minutes_between_uploads") == 45)
check("top watermark text", a1.get("top_watermark") == "SIMPSON PIMP")
check("bottom banner text", a1.get("watermark") == "SUBSCRIBE FOR MORE")
check("aspect 3:4", a1.get("aspect") == "3:4")
check("fill blur", a1.get("fill") == "blur")
check("delete_after_upload True", a1.get("delete_after_upload") is True)
check("delete_r2 False", a1.get("delete_r2_after_upload") is False)
# isolation: account 2 untouched by account 1's save
check("acc2 prefix kept 🔥", a2.get("title_prefix") == "🔥")
check("acc2 aspect 9:16", a2.get("aspect") == "9:16")
check("acc2 fill crop", a2.get("fill") == "crop")
check("acc2 max_daily default 10", a2.get("max_daily_uploads") == 10)

env_txt = (CLIP / ".env").read_text() if (CLIP / ".env").exists() else ""
check("cycle_interval_hours written to .env", "CYCLE_INTERVAL_HOURS=1" in env_txt)

# ============ 3. Save source channels (indexed form) ============
print("\n=== 3. Save Source channels per account ===")
r = clip_app.post("/api/accounts/save", data={
    "acc_name_0": "New Channel 1",
    "acc_channels_0": "https://www.youtube.com/@SimpsonsChannel\nhttps://www.youtube.com/@HomerFan",
    "acc_maxdaily_0": "7",
    "acc_processmode_0": "render",
    "acc_order_0": "oldest",
    "acc_enabled_0": "true",
})
check("save source OK", r.status_code == 302)
data = json.loads((CLIP / "accounts.json").read_text())
a1 = next(a for a in data["accounts"] if a["name"] == "New Channel 1")
check("channels saved (2)", len(a1.get("target_channels") or []) == 2, str(a1.get("target_channels")))
check("process_mode render saved", a1.get("process_mode") == "render")
check("selection_order oldest saved", a1.get("selection_order") == "oldest")
check("enabled kept True", a1.get("enabled") is True)
# credentials preserved (not wiped by source save)
check("client_secret path preserved", "accounts/new channel 1/client_secret.json" in str(a1.get("client_secret")))

# ============ 4. CRITICAL: save one tab must NOT wipe other tabs ============
print("\n=== 4. Save source on ONE tab preserves OTHER tabs (data-loss regression) ===")
r = clip_app.post("/api/accounts/save", data={
    "acc_name_0": "New Channel 1",
    "acc_channels_0": "https://www.youtube.com/@SimpsonsChannel",
    "acc_maxdaily_0": "7",
    "acc_processmode_0": "copy",          # switch back from render -> copy
    "acc_order_0": "",                    # reset order to global
    "acc_enabled_0": "true",
})
check("save source OK", r.status_code == 302)
data = json.loads((CLIP / "accounts.json").read_text())
names = [a["name"] for a in data["accounts"]]
check("ALL 5 accounts still exist after one-tab save", len(names) == 5, str(names))
a1 = next(a for a in data["accounts"] if a["name"] == "New Channel 1")
a3 = next(a for a in data["accounts"] if a["name"] == "New Channel 3")
check("process_mode reset to copy", a1.get("process_mode") == "copy")
check("selection_order reset to global ''", a1.get("selection_order") == "")
check("channels updated to 1", len(a1.get("target_channels") or []) == 1)
check("other tab untouched (New Channel 3 has no channels)", not a3.get("target_channels"))
check("other tab settings intact (max_daily 10 default)", a3.get("max_daily_uploads") == 10)

# ============ 5. Delete ============
print("\n=== 5. Delete account ===")
r = clip_app.post("/api/accounts/delete", data={"account": "New Channel 2"})
check("delete OK", r.status_code == 302)
data = json.loads((CLIP / "accounts.json").read_text())
names = [a["name"] for a in data["accounts"]]
check("deleted account gone, others kept", "New Channel 2" not in names and len(names) == 4, str(names))
r = clip_app.post("/api/accounts/delete", data={"account": "Does Not Exist"})
data = json.loads((CLIP / "accounts.json").read_text())
check("delete unknown account harmless", len(data["accounts"]) == 4)

# ============ 6. Repost bot same API ============
print("\n=== 6. Repost bot: add + process mode select ===")
repost_app.post("/api/accounts/add")
repost_app.post("/api/account-settings/save", data={
    "account": "New Channel 1",
    "title_prefix": "REPOST",
    "title_hashtags": "funny, clips",
    "top_watermark": "MY CHANNEL",
    "watermark": "LIKE & SUBSCRIBE",
    "aspect": "9:16", "fill": "blur",
    "max_shorts_per_channel_cycle": "4",
    "min_minutes_between_uploads": "60",
})
r = repost_app.post("/api/accounts/save", data={
    "acc_name_0": "New Channel 1",
    "acc_channels_0": "https://www.youtube.com/@Speedzyshorts",
    "acc_maxdaily_0": "8",
    "acc_processmode_0": "copy",
    "acc_order_0": "newest",
    "acc_enabled_0": "true",
})
check("repost save source OK", r.status_code == 302)
data = json.loads((REPOST / "accounts.json").read_text())
a1 = next(a for a in data["accounts"] if a["name"] == "New Channel 1")
check("repost process_mode copy", a1.get("process_mode") == "copy")
check("repost max_shorts_per_channel_cycle=4", a1.get("max_shorts_per_channel_cycle") == 4)
check("repost min_minutes=60", a1.get("min_minutes_between_uploads") == 60)
check("repost watermark text", a1.get("watermark") == "LIKE & SUBSCRIBE")

# ============ 7. HTML renders without placeholders ============
print("\n=== 7. Rendered pages ===")
h = clip_webui._render_page(loaded_account="My Gaming Channel")
check("clip page: no @@ placeholders", "@@" not in h)
check("clip page: all settings visible", all(s in h for s in [
    "Title prefix", "Title hashtags", "Smart titles", "Max uploads / day",
    "Shorts per video", "Min minutes between uploads", "Top watermark",
    "Bottom banner text", "Aspect ratio", "Fill mode",
    "Delete local copy after upload", "Delete R2 backup after upload",
    "Bot cycle interval", "Source channels", "Delete this account"]))
h2 = repost_webui._render_page(loaded_account="New Channel 1")
check("repost page: no @@ placeholders", "@@" not in h2)
check("repost page: Max shorts per channel visible", "Max shorts per channel / cycle" in h2)

# ---- cleanup: remove test accounts, restore real .env ----
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        acc.unlink()
    bak = d / "accounts.json.bak"
    if bak.exists():
        shutil.move(bak, d / "accounts.json")
    env = d / ".env"
    if env.exists() and (d / ".env.bak").exists():
        env.unlink()
        shutil.move(d / ".env.bak", env)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
