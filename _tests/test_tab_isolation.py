"""
TEST 5: TAB ISOLATION - the "saves for both accounts" bug hunt.
Covers: redirect keeps the active tab, duplicate names can't merge tabs,
unique names on add, scheduler reads accounts.json fresh.
"""
import sys, json, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CLIP = Path("/home/user/yt_shorts_bot")
REPOST = Path("/home/user/yt_shorts_repost_bot")
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        shutil.copy(acc, d / "accounts.json.bak")
        acc.unlink()

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

from yt_shorts_bot import webui as clip_webui
from yt_shorts_repost_bot import webui as repost_webui

clip_app = clip_webui.create_app().test_client()
repost_app = repost_webui.create_app().test_client()

print("\n=== 1. Save on tab B stays on tab B (redirect keeps ?account=) ===")
clip_app.post("/api/accounts/add")   # New Channel 1
clip_app.post("/api/accounts/add")   # New Channel 2
r = clip_app.post("/api/account-settings/save", data={
    "account": "New Channel 2",
    "title_prefix": "PETER",
    "title_hashtags": "peter, king",
    "max_daily_uploads": "5",
    "top_watermark": "PETER A KING",
    "watermark": "SUBSCRIBE PETER",
    "aspect": "9:16",
})
loc = r.headers.get("Location", "")
q = parse_qs(urlparse(loc).query)
check("redirect goes back to tab 'New Channel 2'", q.get("account") == ["New Channel 2"], loc)

print("\n=== 2. Settings really are per-account ===")
data = json.loads((CLIP / "accounts.json").read_text())
accs = {a["name"]: a for a in data["accounts"]}
check("channel 2 got its settings", accs["New Channel 2"].get("title_prefix") == "PETER"
      and accs["New Channel 2"].get("top_watermark") == "PETER A KING"
      and accs["New Channel 2"].get("max_daily_uploads") == 5)
check("channel 1 untouched (no prefix)", "title_prefix" not in accs["New Channel 1"])

print("\n=== 3. Duplicate names can NOT merge tabs anymore ===")
# simulate a legacy accounts.json with two same-name entries (different case)
(CLIP / "accounts.json").write_text(json.dumps({"accounts": [
    {"name": "PeterAKing", "target_channels": [], "max_daily_uploads": 10, "enabled": True},
    {"name": "peteraking", "target_channels": [], "max_daily_uploads": 10, "enabled": True},
]}, indent=2), encoding="utf-8")
disk = clip_webui._accounts_from_disk()
check("dedupe on load: 1 account kept", len(disk) == 1 and disk[0]["name"] == "PeterAKing", str([a["name"] for a in disk]))
r = clip_app.post("/api/account-settings/save", data={"account": "PeterAKing", "title_prefix": "PK"})
data = json.loads((CLIP / "accounts.json").read_text())
check("save after dedupe touches only one entry", len(data["accounts"]) == 1
      and data["accounts"][0].get("title_prefix") == "PK", str(data["accounts"]))

print("\n=== 4. '+' never creates a duplicate name after deletions ===")
(CLIP / "accounts.json").write_text(json.dumps({"accounts": [
    {"name": "New Channel 1", "target_channels": [], "max_daily_uploads": 10, "enabled": True},
    {"name": "New Channel 2", "target_channels": [], "max_daily_uploads": 10, "enabled": True},
]}, indent=2), encoding="utf-8")
clip_app.post("/api/accounts/delete", data={"account": "New Channel 1"})
r = clip_app.post("/api/accounts/add")
data = json.loads((CLIP / "accounts.json").read_text())
names = [a["name"] for a in data["accounts"]]
check("new name is unique (New Channel 1, not a duplicate 2)", names == ["New Channel 2", "New Channel 1"], str(names))

print("\n=== 5. Scheduler re-reads accounts.json fresh (no restart needed) ===")
(CLIP / "accounts.json").write_text(json.dumps({"accounts": [
    {"name": "FreshAcc", "target_channels": [], "max_daily_uploads": 7, "enabled": True},
]}, indent=2), encoding="utf-8")
from yt_shorts_bot.scheduler import ShortsBotScheduler
s = ShortsBotScheduler()
check("scheduler sees the newly added account", [a["name"] for a in s.accounts] == ["FreshAcc"], str([a["name"] for a in s.accounts]))
check("scheduler reads its settings too", s.accounts[0].get("max_daily_uploads") == 7)

print("\n=== 6. Repost bot: same behavior ===")
repost_app.post("/api/accounts/add")
r = repost_app.post("/api/account-settings/save", data={
    "account": "New Channel 1", "title_prefix": "R1", "max_shorts_per_channel_cycle": "3",
    "min_minutes_between_uploads": "90"})
loc = r.headers.get("Location", "")
q = parse_qs(urlparse(loc).query)
check("repost redirect stays on tab", q.get("account") == ["New Channel 1"], loc)
data = json.loads((REPOST / "accounts.json").read_text())
a1 = data["accounts"][0]
check("repost per-account ints saved", a1.get("max_shorts_per_channel_cycle") == 3 and a1.get("min_minutes_between_uploads") == 90)

# ---- cleanup ----
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        acc.unlink()
    bak = d / "accounts.json.bak"
    if bak.exists():
        shutil.move(bak, d / "accounts.json")

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
