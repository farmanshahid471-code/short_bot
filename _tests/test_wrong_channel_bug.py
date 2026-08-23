"""
TEST 12: THE WRONG-CHANNEL BUG (v6.2) - a named account must NEVER resolve to
the bot-root token.json (which belongs to whichever channel was connected last).
Reproduces the user's exact scenario: "New Channel 1" + root Simpson token.
"""
import sys, json, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path

CLIP = Path("/home/user/yt_shorts_bot")
REPOST = Path("/home/user/yt_shorts_repost_bot")

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

for bot in (CLIP, REPOST):
    name = bot.name
    # isolate state
    acc = bot / "accounts.json"
    had = acc.exists()
    if had: shutil.copy(acc, bot / "accounts.json.bak")
    # root token = SIMPSON'S (old flow leftover)
    (bot / "token.json").write_text('{"token": "SIMPSONS_TOKEN"}', encoding="utf-8")

    from importlib import import_module
    up = import_module(f"yt_shorts_bot.uploader" if bot == CLIP else "yt_shorts_repost_bot.uploader")
    cfg = import_module(f"yt_shorts_bot.config" if bot == CLIP else "yt_shorts_repost_bot.config")
    webui = import_module(f"yt_shorts_bot.webui" if bot == CLIP else "yt_shorts_repost_bot.webui")

    print(f"\n=== {name} ===")

    # 1. account created by '+' in the OLD build (no credential paths)
    acc.write_text(json.dumps({"accounts": [
        {"name": "New Channel 1", "target_channels": [], "max_daily_uploads": 6, "enabled": True}
    ]}, indent=2), encoding="utf-8")
    loaded = [x for x in cfg._load_accounts() if x["name"] == "New Channel 1"][0]
    check("old-format account gets per-account token path on load",
          str(loaded.get("token") or "").endswith("accounts/new channel 1/token.json"), str(loaded.get("token")))

    # 2. runtime resolve (account dict fresh from disk, no token key)
    disk_acc = next(x for x in webui._accounts_from_disk() if x["name"] == "New Channel 1")
    cs, tk = up.resolve_credentials(disk_acc)
    check("runtime resolve NEVER uses root (Simpson) token",
          str(tk).endswith("accounts/new channel 1/token.json") and "SIMPSONS" not in str(tk), str(tk))
    check("client secret per-account too", str(cs).endswith("accounts/new channel 1/client_secret.json"), str(cs))

    # 3. '+' button creates accounts WITH both paths
    client = webui.create_app().test_client()
    client.get("/api/accounts/add")
    data = json.loads(acc.read_text(encoding="utf-8"))
    newacc = next(x for x in data["accounts"] if x["name"] != "New Channel 1")
    check("'+' creates client_secret path", str(newacc.get("client_secret") or "").endswith(f"accounts/{newacc['name'].lower()}/client_secret.json"))
    check("'+' creates token path", str(newacc.get("token") or "").endswith(f"accounts/{newacc['name'].lower()}/token.json"))

    # 4. client-secret upload pins BOTH paths
    import io
    r = client.post("/api/client-secret", data={
        "account": "New Channel 1",
        "file": (io.BytesIO(b'{"installed":{"client_id":"x","project_id":"x","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","client_secret":"x"}}'), "client_secret.json"),
    }, content_type="multipart/form-data")
    data = json.loads(acc.read_text(encoding="utf-8"))
    a1 = next(x for x in data["accounts"] if x["name"] == "New Channel 1")
    check("secret upload pins token path too", str(a1.get("token") or "").endswith("accounts/new channel 1/token.json"))
    # remove test-created secret dir
    shutil.rmtree(bot / "accounts" / "new channel 1", ignore_errors=True)

    # 5. legacy single-account mode (no accounts.json) still uses root
    acc.unlink(missing_ok=True)
    cs_l, tk_l = up.resolve_credentials({"client_secret": "", "token": ""})
    check("legacy (no name) still uses root token", str(tk_l).endswith("token.json") and "accounts" not in str(tk_l), str(tk_l))

    # cleanup
    (bot / "token.json").unlink(missing_ok=True)
    if had:
        acc.unlink(missing_ok=True)
        shutil.move(bot / "accounts.json.bak", acc)
    else:
        acc.unlink(missing_ok=True)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
