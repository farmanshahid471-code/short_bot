"""
TEST 6: USER SCENARIO - PeterAKing + simpson_pimp (their exact accounts.json).
Verifies: saving on PeterAKing NEVER touches simpson_pimp, source save keeps both,
per-account client_secret upload goes to accounts/<name>/ only.
"""
import sys, json, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path

CLIP = Path("/home/user/yt_shorts_bot")
REPOST = Path("/home/user/yt_shorts_repost_bot")
for d in (CLIP, REPOST):
    acc = d / "accounts.json"
    if acc.exists():
        shutil.copy(acc, d / "accounts.json.bak")
        acc.unlink()

USER_ACCOUNTS = {
    "accounts": [
        {
            "name": "PeterAKing",
            "client_secret": "accounts/peteraking/client_secret.json",
            "token": "accounts/peteraking/token.json",
            "target_channels": ["https://www.youtube.com/@FamilyGuy-Fan/shorts",
                                "https://www.youtube.com/@Doughnutxex/shorts"],
            "max_daily_uploads": 6, "enabled": True, "process_mode": "render",
            "selection_order": "oldest", "title_prefix": "",
            "title_hashtags": "familyguy,peter,brian,stewie", "smart_titles": True,
            "top_watermark": "", "top_watermark_enabled": True,
            "watermark": "@PeterAKing", "watermark_enabled": True,
            "aspect": "3:4", "fill": "blur", "max_shorts_per_channel_cycle": 3,
            "min_minutes_between_uploads": 60, "delete_after_upload": True,
            "delete_r2_after_upload": False,
        },
        {
            "name": "simpson_pimp",
            "client_secret": "accounts/simpson_pimp/client_secret.json",
            "token": "accounts/simpson_pimp/token.json",
            "target_channels": ["https://www.youtube.com/@FamilyGuy-Fan/shorts",
                                "https://www.youtube.com/@Doughnutxex/shorts"],
            "max_daily_uploads": 6, "enabled": True, "process_mode": "render",
            "selection_order": "oldest", "title_prefix": "",
            "title_hashtags": "simpsons,bart,homer,magie,lisa", "smart_titles": True,
            "top_watermark": "", "top_watermark_enabled": False,
            "watermark": "@PeterAKing",  # the LEAKED value - should be repairable
            "watermark_enabled": True,
            "aspect": "3:4", "fill": "blur", "max_shorts_per_channel_cycle": 3,
            "min_minutes_between_uploads": 60, "delete_after_upload": True,
            "delete_r2_after_upload": False,
            "connected_channel": "Simpson Pimp",
        },
    ]
}
# repair simpson_pimp's leaked watermark (user will set their own in the panel)
USER_ACCOUNTS["accounts"][1]["watermark"] = ""

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

from yt_shorts_bot import webui as clip_webui
from yt_shorts_repost_bot import webui as repost_webui
app = clip_webui.create_app().test_client()
rapp = repost_webui.create_app().test_client()

(CLIP / "accounts.json").write_text(json.dumps(USER_ACCOUNTS, indent=2), encoding="utf-8")

print("\n=== 1. Save SETTINGS on PeterAKing -> simpson_pimp untouched ===")
r = app.post("/api/account-settings/save", data={
    "account": "PeterAKing",
    "title_prefix": "PETER",
    "title_hashtags": "familyguy,peter,brian,stewie",
    "smart_titles": "true",
    "max_daily_uploads": "8",
    "min_minutes_between_uploads": "30",
    "top_watermark": "PETER A KING",
    "top_watermark_enabled": "true",
    "watermark": "@PeterAKing",
    "watermark_enabled": "true",
    "aspect": "3:4", "fill": "blur",
    "delete_after_upload": "true",
})
check("redirect stays on PeterAKing", "account=PeterAKing" in r.headers.get("Location", ""))
data = json.loads((CLIP / "accounts.json").read_text())
pa = next(a for a in data["accounts"] if a["name"] == "PeterAKing")
sp = next(a for a in data["accounts"] if a["name"] == "simpson_pimp")
check("PeterAKing updated (prefix PETER, max 8)", pa["title_prefix"] == "PETER" and pa["max_daily_uploads"] == 8)
check("PeterAKing top watermark set", pa["top_watermark"] == "PETER A KING")
check("simpson_pimp prefix untouched", sp["title_prefix"] == "")
check("simpson_pimp hashtags still simpsons", sp["title_hashtags"] == "simpsons,bart,homer,magie,lisa")
check("simpson_pimp watermark still EMPTY (repaired, not re-leaked)", sp["watermark"] == "")
check("simpson_pimp top_watermark_enabled still False", sp["top_watermark_enabled"] is False)
check("simpson_pimp connected_channel kept", sp.get("connected_channel") == "Simpson Pimp")

print("\n=== 2. Save SOURCE on PeterAKing -> simpson_pimp preserved ===")
r = app.post("/api/accounts/save", data={
    "acc_name_0": "PeterAKing",
    "acc_channels_0": "https://www.youtube.com/@FamilyGuy-Fan/shorts",
    "acc_maxdaily_0": "8",
    "acc_processmode_0": "render",
    "acc_order_0": "newest",
    "acc_enabled_0": "true",
})
check("source save OK", r.status_code == 302)
data = json.loads((CLIP / "accounts.json").read_text())
check("BOTH accounts still present", [a["name"] for a in data["accounts"]] == ["PeterAKing", "simpson_pimp"])
sp = next(a for a in data["accounts"] if a["name"] == "simpson_pimp")
check("simpson_pimp channels kept", len(sp["target_channels"]) == 2)
check("simpson_pimp settings kept after source save", sp["title_hashtags"] == "simpsons,bart,homer,magie,lisa" and sp["watermark"] == "")

print("\n=== 3. Per-account client_secret upload ===")
import io
secret_json = b'{"installed":{"client_id":"test","project_id":"t","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","client_secret":"s"}}'
r = app.post("/api/client-secret", data={
    "account": "PeterAKing",
    "file": (io.BytesIO(secret_json), "client_secret.json"),
}, content_type="multipart/form-data")
check("upload redirects to PeterAKing tab", "account=PeterAKing" in r.headers.get("Location", ""))
dest = CLIP / "accounts" / "peteraking" / "client_secret.json"
check("file written to accounts/peteraking/client_secret.json", dest.exists() and dest.read_bytes() == secret_json)
data = json.loads((CLIP / "accounts.json").read_text())
pa = next(a for a in data["accounts"] if a["name"] == "PeterAKing")
check("accounts.json points at the per-account file", str(pa["client_secret"]).endswith("accounts/peteraking/client_secret.json"))
check("simpson_pimp secret path NOT touched", str(next(a for a in data["accounts"] if a["name"] == "simpson_pimp")["client_secret"]).endswith("accounts/simpson_pimp/client_secret.json"))
# no shared root file created by this upload
check("no bot-root client_secret.json created", not (CLIP / "client_secret.json").exists())

print("\n=== 4. Repost bot panel: same isolation ===")
(REPOST / "accounts.json").write_text(json.dumps(USER_ACCOUNTS, indent=2), encoding="utf-8")
r = rapp.post("/api/account-settings/save", data={
    "account": "simpson_pimp",
    "title_prefix": "SIMPSON",
    "watermark": "@SimpsonPimp",
    "max_shorts_per_channel_cycle": "5",
})
data = json.loads((REPOST / "accounts.json").read_text())
sp = next(a for a in data["accounts"] if a["name"] == "simpson_pimp")
pa = next(a for a in data["accounts"] if a["name"] == "PeterAKing")
check("simpson_pimp saved its OWN banner", sp["watermark"] == "@SimpsonPimp")
check("PeterAKing watermark untouched", pa["watermark"] == "@PeterAKing")

# ---- cleanup ----
shutil.rmtree(CLIP / "accounts" / "peteraking", ignore_errors=True)
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
