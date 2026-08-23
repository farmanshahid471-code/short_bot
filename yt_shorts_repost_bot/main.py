"""
main.py - CLI for the Shorts REPOST bot.
Modes: scheduler, once, process-url, status, webui
"""
import argparse
import sys
import shutil
from pathlib import Path
from typing import Optional

from tabulate import tabulate

from .config import (
    logger,
    TARGET_CHANNELS,
    CYCLE_INTERVAL_HOURS,
    KEEP_LOCAL_SHORTS,
    KEEP_SHORTS_DIR,
    WEBUI_HOST,
    WEBUI_PORT,
    MAX_DAILY_UPLOADS,
    ACCOUNTS,
)
from .models import StateDB
from .fetcher import ShortsFetcher
from .reprocessor import ShortReprocessor
from .storage import CloudStorageManager
from .uploader import YouTubeUploader
from .scheduler import ShortsRepostScheduler


def print_status() -> None:
    db = StateDB()
    videos = db.get_all_processed_videos(limit=20)
    count_24h = db.get_uploads_in_last_24_hours()

    print("\n=== SHORTS REPOST BOT - STATUS REPORT ===")
    print(f"YouTube Uploads in Last 24 Hours: {count_24h} / {MAX_DAILY_UPLOADS}\n")

    for acc in ACCOUNTS:
        name = acc.get("name", "default")
        max_daily = int(acc.get("max_daily_uploads") or MAX_DAILY_UPLOADS)
        used = db.get_uploads_in_last_24_hours(account=name)
        mark = "✅" if acc.get("enabled", True) else "⏸"
        print(f"  {mark} Account '{name}': {used} / {max_daily} uploads in 24h")

    if not videos:
        print("\nNo Shorts reposted yet.")
    else:
        table = []
        for v in videos:
            table.append([
                v.get("account", ""),
                v.get("video_id", ""),
                (v.get("title") or "")[:30],
                v.get("status", ""),
                v.get("youtube_short_id", "-"),
                (v.get("updated_at") or "")[:16],
            ])
        print(tabulate(table, headers=["Account", "Short ID", "Title", "Status", "My Short ID", "Updated"], tablefmt="grid"))

    storage = CloudStorageManager()
    total_bytes, objects = storage.get_bucket_usage()
    print(f"\nR2 bucket usage: {total_bytes / (1024**3):.3f} GB ({len(objects)} clips)\n")


def repost_one_url(url: str, account: Optional[dict] = None) -> None:
    """Reposts ONE specific Short URL to your channel (optionally for one account)."""
    from pathlib import Path as _Path

    # If no account given, use the FIRST enabled account so the bot never
    # silently falls back to .env "default" (which has no watermarks/settings).
    if account is None:
        try:
            from .config import ACCOUNTS_FILE
            import json as _json
            data = _json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8")) if ACCOUNTS_FILE.exists() else {}
            accs = data.get("accounts", []) if isinstance(data, dict) else []
            for a in accs:
                if a.get("enabled", True):
                    account = a
                    break
            else:
                account = accs[0] if accs else None
        except Exception:
            account = None

    if account is not None:
        acc_name = account.get("name", "default")
        max_daily = int(account.get("max_daily_uploads") or MAX_DAILY_UPLOADS)
        logger.info(f"=== REPOSTING SINGLE SHORT FOR ACCOUNT '{acc_name}': {url} ===")
    else:
        acc_name = "default"
        max_daily = None

    fetcher = ShortsFetcher()
    reprocessor = ShortReprocessor()
    storage = CloudStorageManager()
    if account is not None:
        from .uploader import resolve_credentials
        cs, tk = resolve_credentials(account)
        uploader = YouTubeUploader(
            client_secret_file=cs,
            token_file=tk,
            state_db=StateDB(),
        )
    else:
        uploader = YouTubeUploader()
    db = StateDB()
    extra_hashtags = str((account or {}).get("extra_hashtags") or "").strip() or ""

    info = fetcher.get_short_info(url)
    v_id = info.get("id") or fetcher._extract_video_id(url)
    v_title = info.get("title") or f"Short {v_id}"

    if db.is_video_processed(v_id, account=acc_name):
        logger.info(f"[{acc_name}] Short {v_id} was already reposted - skipping.")
        return

    raw_path = fetcher.download_short(url)
    acc_mode = (account or {}).get("process_mode") or None
    # Repost bot: NO subtitles by default (watermarks only). Per-account override.
    subs = (account or {}).get("subtitles_enabled", False)
    wm_enabled = (account or {}).get("watermark_enabled")
    wm_text = ((account or {}).get("watermark") or "").strip() or None
    top_wm_enabled = (account or {}).get("top_watermark_enabled")
    top_wm_text = ((account or {}).get("top_watermark") or "").strip() or None
    expected_channel = ((account or {}).get("expected_channel") or "").strip() or None
    final_path = reprocessor.process_short(
        raw_path,
        mode=acc_mode,
        subtitles=subs,
        like_subscribe=(None if wm_enabled is None else bool(wm_enabled)),
        like_subscribe_text=wm_text,
        top_watermark_enabled=(None if top_wm_enabled is None else bool(top_wm_enabled)),
        top_watermark_text=top_wm_text,
        aspect=(account or {}).get("aspect") or "auto",
        fill=(account or {}).get("fill") or "crop",
    )

    if KEEP_LOCAL_SHORTS and final_path.exists():
        dest = KEEP_SHORTS_DIR / f"{acc_name}_repost_{v_id}.mp4"
        try:
            shutil.copy2(final_path, dest)
            logger.info(f"💾 Saved local copy: {dest}")
        except Exception as e:
            logger.warning(f"Could not keep local copy: {e}")

    r2_key = f"reposts/{v_id}.mp4"
    uploaded_key = storage.upload_file(final_path, r2_key=r2_key)
    if uploaded_key:
        r2_key = uploaded_key

    short_id = uploader.upload_short(
        video_path=final_path,
        original_video_id=v_id,
        original_title=v_title,
        original_url=url,
        channel_name=info.get("channel") or "",
        account=acc_name,
        account_max_daily=max_daily,
        info=info,
        transcript_text="",
        extra_hashtags=extra_hashtags,
        title_prefix=(account or {}).get("title_prefix"),
        title_hashtags=str((account or {}).get("title_hashtags") or "").strip(),
        smart_titles=(account or {}).get("smart_titles"),
        expected_channel=expected_channel,
    )

    db.record_video_state(
        video_id=v_id, video_url=url, title=v_title,
        r2_key=r2_key, youtube_short_id=short_id or "",
        status="UPLOADED_YOUTUBE" if short_id and short_id != "QUOTA_LIMIT_REACHED" else "UPLOADED_R2",
        account=acc_name,
    )

    # Save title + hashtags alongside the Short (works in dry-run too)
    try:
        meta = uploader.generate_short_metadata(
            original_title=v_title,
            original_url=url,
            channel_name=info.get("channel") or "",
            info=info,
            transcript_text="",
            extra_hashtags=extra_hashtags,
        )
        from .hashtags import save_metadata_sidecar
        sidecar_target = KEEP_SHORTS_DIR / f"{acc_name}_repost_{v_id}.mp4"
        if not sidecar_target.exists():
            sidecar_target = final_path
        save_metadata_sidecar(
            sidecar_target, meta,
            source_url=url,
            short_id=short_id or "",
            account=acc_name,
        )
    except Exception as e:
        logger.warning(f"Could not save metadata sidecar: {e}")

    logger.info(f"✅ Reposted Short saved locally at: {final_path}")
    if short_id and short_id != "QUOTA_LIMIT_REACHED":
        logger.info(f"Uploaded to your channel -> Short ID: {short_id}")
    elif short_id == "QUOTA_LIMIT_REACHED":
        logger.warning("YouTube 24h cap reached - Short is saved locally + R2 for later.")

    try:
        for p in (raw_path, final_path):
            if p and Path(p).exists():
                Path(p).unlink()
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="24/7 YouTube Shorts REPOST bot - grab Shorts from channels and upload to YOUR channel"
    )
    parser.add_argument(
        "--mode",
        choices=["scheduler", "once", "process-url", "status", "webui"],
        default="scheduler",
        help="Operation mode",
    )
    parser.add_argument("--url", type=str, help="Short URL to repost (with --mode process-url)")
    parser.add_argument("--channels", type=str, help="Comma-separated channel URLs to override .env")
    parser.add_argument("--account", type=str, default=None,
                        help="Only run this account (name from accounts.json). Default: all enabled accounts.")
    parser.add_argument("--interval", type=int, default=CYCLE_INTERVAL_HOURS, help="Hours between cycles")
    parser.add_argument("--host", type=str, default=WEBUI_HOST, help="Web UI bind host")
    parser.add_argument("--port", type=int, default=WEBUI_PORT, help="Web UI port")

    args = parser.parse_args()
    channels = [c.strip() for c in args.channels.split(",") if c.strip()] if args.channels else TARGET_CHANNELS

    if args.account:
        selected_accounts = [a for a in ACCOUNTS if a.get("name") == args.account]
        if not selected_accounts:
            print(f"Error: no account named '{args.account}' found in accounts.json")
            sys.exit(1)
    else:
        selected_accounts = [a for a in ACCOUNTS if a.get("enabled", True)]

    if args.mode == "status":
        print_status()
        return

    if args.mode == "process-url":
        if not args.url:
            print("Error: --url is required with --mode process-url")
            sys.exit(1)
        repost_one_url(args.url, account=selected_accounts[0] if selected_accounts else None)
        return

    if args.mode == "once":
        logger.info(f"Running a single repost cycle (accounts: {[a.get('name') for a in selected_accounts]})...")
        ShortsRepostScheduler(channels=channels, interval_hours=args.interval, accounts=selected_accounts).run_single_cycle()
        return

    if args.mode == "scheduler":
        ShortsRepostScheduler(channels=channels, interval_hours=args.interval, accounts=selected_accounts).start_24_7_loop()
        return

    if args.mode == "webui":
        from .webui import run_webui
        run_webui(host=args.host, port=args.port)
        return


if __name__ == "__main__":
    main()
