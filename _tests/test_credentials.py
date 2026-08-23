"""
TEST 7: resolve_credentials - a tab must NEVER silently use another
channel's token (the "connected to Simpson Pimp" bug). v6.2 rules:
  named account  -> accounts/<name>/token.json + client_secret.json (never root token)
  unnamed legacy -> bot-root token.json + client_secret.json
"""
import sys, shutil
sys.path.insert(0, "/home/user")
from pathlib import Path

REPOST = Path("/home/user/yt_shorts_repost_bot")
CLIP = Path("/home/user/yt_shorts_bot")

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

for bot in (CLIP, REPOST):
    from importlib import import_module
    up = import_module(f"yt_shorts_bot.uploader" if bot == CLIP else "yt_shorts_repost_bot.uploader")
    cfg = import_module(f"yt_shorts_bot.config" if bot == CLIP else "yt_shorts_repost_bot.config")
    BASE_DIR = cfg.BASE_DIR

    print(f"\n=== {bot.name}: resolve_credentials (v6.2) ===")
    root_tok = BASE_DIR / "token.json"
    root_tok.write_text('{"token": "SIMPSONS_TOKEN"}', encoding="utf-8")

    # 1. named account, per-account paths set, files MISSING + root token exists
    acc = {"name": "PeterAKing",
           "client_secret": str(BASE_DIR / "accounts/peteraking/client_secret.json"),
           "token": str(BASE_DIR / "accounts/peteraking/token.json")}
    cs, tk = up.resolve_credentials(acc)
    check("missing per-account token NEVER falls back to root",
          str(tk) == str(BASE_DIR / "accounts/peteraking/token.json"), str(tk))
    check("missing per-account secret resolves to per-account path (stored there on next Connect)",
          str(cs) == str(BASE_DIR / "accounts/peteraking/client_secret.json"), str(cs))

    # 2. named account with NO paths at all (e.g. '+' from old build)
    cs2, tk2 = up.resolve_credentials({"name": "New Channel 1"})
    check("named account w/o paths -> per-account token (never root)",
          str(tk2) == str(BASE_DIR / "accounts/new channel 1/token.json"), str(tk2))
    check("named account w/o paths -> per-account secret",
          str(cs2) == str(BASE_DIR / "accounts/new channel 1/client_secret.json"), str(cs2))

    # 3. existing per-account token IS used
    acc_dir = BASE_DIR / "accounts" / "peteraking"
    acc_dir.mkdir(parents=True, exist_ok=True)
    (acc_dir / "token.json").write_text('{"token": "PETER_TOKEN"}', encoding="utf-8")
    cs3, tk3 = up.resolve_credentials(acc)
    check("existing per-account token is used", tk3.read_text() == '{"token": "PETER_TOKEN"}')

    # 4. unnamed/legacy account still uses bot-root files
    cs4, tk4 = up.resolve_credentials({"client_secret": "", "token": ""})
    check("legacy (no name) uses root token", str(tk4) == str(root_tok), str(tk4))
    check("legacy (no name) uses root secret", str(cs4) == str(BASE_DIR / "client_secret.json"), str(cs4))
    cs4b, tk4b = up.resolve_credentials(None)
    check("None account uses root files", str(tk4b) == str(root_tok))

    root_tok.unlink(missing_ok=True)
    shutil.rmtree(BASE_DIR / "accounts" / "peteraking", ignore_errors=True)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
