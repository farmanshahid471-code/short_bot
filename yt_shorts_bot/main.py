"""
main.py - Command-line interface and entry point for the YouTube Shorts 24/7 Automation Bot.
Supports scheduler daemon mode, single cycle run, single URL processing, and status inspection.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional
from tabulate import tabulate

from .config import logger, TARGET_CHANNELS, CYCLE_INTERVAL_HOURS, WEBUI_HOST, WEBUI_PORT, KEEP_LOCAL_SHORTS, KEEP_SHORTS_DIR, ACCOUNTS
from .models import StateDB
from .fetcher import YouTubeFetcher
from .hashtags import srt_to_text, save_metadata_sidecar
from .processor import VideoProcessor
from .storage import CloudStorageManager
from .uploader import YouTubeUploader
from .scheduler import ShortsBotScheduler


def print_status() -> None:
    """Displays current bot status, SQLite processed video database, and R2 usage."""
    from .config import ACCOUNTS, MAX_DAILY_UPLOADS
    db = StateDB()
    videos = db.get_all_processed_videos(limit=15)
    count_24h = db.get_uploads_in_last_24_hours()

    print("\n=== YOUTUBE SHORTS BOT STATUS REPORT ===")
    print(f"YouTube API Uploads in Last 24 Hours: {count_24h} / 10 limit\n")

    # Per-account quota overview
    for acc in ACCOUNTS:
        name = acc.get("name", "default")
        max_daily = int(acc.get("max_daily_uploads") or MAX_DAILY_UPLOADS)
        used = db.get_uploads_in_last_24_hours(account=name)
        status_mark = "✅" if acc.get("enabled", True) else "⏸"
        print(f"  {status_mark} Account '{name}': {used} / {max_daily} uploads in 24h")

    if not videos:
        print("\nNo processed videos recorded yet.")
    else:
        table = []
        for v in videos:
            table.append([
                v.get("account", ""),
                v.get("video_id", ""),
                v.get("title", "")[:30],
                f"{v.get('clip_start', 0):.1f}s-{v.get('clip_end', 0):.1f}s",
                v.get("status", ""),
                v.get("youtube_short_id", "-"),
                v.get("updated_at", "")[:16]
            ])
        headers = ["Account", "Video ID", "Title", "Clip Window", "Status", "Short ID", "Updated At"]
        print(tabulate(table, headers=headers, tablefmt="grid"))

    # R2 Usage
    storage = CloudStorageManager()
    total_bytes, objects = storage.get_bucket_usage()
    gb_used = total_bytes / (1024 ** 3)
    print(f"\nCloudflare R2 Bucket Usage: {gb_used:.3f} GB / 8.00 GB threshold ({len(objects)} clips stored)\n")


def process_single_url(url: str, count: int = 1, aspect: Optional[str] = None, fill: Optional[str] = None, logo_position: Optional[str] = None, like_subscribe: Optional[bool] = None, like_subscribe_text: Optional[str] = None, top_watermark_enabled: Optional[bool] = None, top_watermark_text: Optional[str] = None, account: Optional[dict] = None) -> None:
    """
    Test mode: processes a specific YouTube video URL through the entire pipeline.
    `count` = how many Shorts to make from this video (default 1 = the single
    best heatmap/energy window). With count > 1 it takes the top non-overlapping
    windows so you get several Shorts from one video.
    `aspect` = "3:4" (reference Short style) or "9:16" (classic). None = config default.
    `fill`   = "blur" (keep whole frame, blurred bg) or "crop" (center crop). None = config default.
    `logo_position` = corner to blur a logo/watermark ("top-right", "off", ...). None = config default.
    `account` = account dict (from accounts.json) whose credentials/style/quota to use.
    """
    from pathlib import Path as _Path

    if account is not None:
        acc_name = account.get("name", "default")
        aspect = aspect or account.get("aspect")
        fill = fill or account.get("fill")
        logo_position = logo_position or ("off" if not account.get("logo_remove") else account.get("logo_position"))
        max_daily = int(account.get("max_daily_uploads") or 10)
        # Per-account watermark: CLI flag wins; otherwise use the account's setting
        if like_subscribe is None and "watermark_enabled" in account:
            like_subscribe = bool(account.get("watermark_enabled"))
        if not like_subscribe_text and account.get("watermark"):
            like_subscribe_text = str(account.get("watermark")).strip() or None
        if top_watermark_enabled is None and "top_watermark_enabled" in account:
            top_watermark_enabled = bool(account.get("top_watermark_enabled"))
        if not top_watermark_text and account.get("top_watermark"):
            top_watermark_text = str(account.get("top_watermark")).strip() or None
        extra_hashtags = str(account.get("extra_hashtags") or "").strip() or ""
        logger.info(f"=== PROCESSING FOR ACCOUNT '{acc_name}' ===")
    else:
        acc_name = "default"
        max_daily = None
        extra_hashtags = ""

    # Top watermark resolution (runs ALWAYS, even without an account):
    #   None  = not specified -> fallback chain: account > .env TOP_WATERMARK_TEXT
    #   "..." = explicit text  -> use it
    #   ""    = explicit OFF   -> no watermark (empty stays empty, no account-name fallback)
    if top_watermark_text is None:
        from .config import TOP_WATERMARK_TEXT as _twt
        candidate = ""
        if account is not None:
            candidate = str(account.get("top_watermark") or "").strip()
        if not candidate:
            candidate = (_twt or "").strip()
        top_watermark_text = candidate or None

    logger.info(f"=== TESTING SINGLE URL PIPELINE FOR: {url} (shorts to make: {count}, aspect: {aspect}, fill: {fill}, logo: {logo_position}, account: {acc_name}) ===")
    fetcher = YouTubeFetcher()
    processor = VideoProcessor()
    storage = CloudStorageManager()
    if account is not None:
        uploader = YouTubeUploader(
            client_secret_file=_Path(account.get("client_secret") or ""),
            token_file=_Path(account.get("token") or ""),
            state_db=StateDB(),
        )
    else:
        uploader = YouTubeUploader()
    state_db = StateDB()

    if count <= 1:
        windows = [fetcher.extract_heatmap_and_select_window(url)]
        windows = [{
            "info": w[0], "start": w[2], "end": w[3],
        } for w in windows]
    else:
        top = fetcher.select_top_windows(url, count=count)
        # re-fetch full info once for id/title (select_top_windows returns only windows)
        ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True, **fetcher._cookies_opts(), **fetcher._ffmpeg_opt()}
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        windows = [{"info": info, "start": w["start"], "end": w["end"]} for w in top]

    made = 0
    for idx, w in enumerate(windows, start=1):
        info = w["info"]
        clip_start, clip_end = w["start"], w["end"]
        v_id = info.get("id") or "test_video"
        v_title = info.get("title") or "Test Video Title"
        peak_time = (clip_start + clip_end) / 2.0

        logger.info(f"--- Short {idx}/{len(windows)}: segment [{clip_start:.1f}s -> {clip_end:.1f}s] ---")

        # 1. Download ONLY segment
        raw_clip_path = fetcher.download_clip_section(url, clip_start, clip_end)

        # 2. Transcribe CPU + Crop 9:16 Vertical + Burn Subtitles
        srt_path = raw_clip_path.with_suffix(".srt")
        processed_short_path = processor.process_clip_to_short(
            raw_clip_path, srt_path=srt_path, aspect=aspect, fill=fill,
            logo_position=logo_position, like_subscribe=like_subscribe,
            like_subscribe_text=like_subscribe_text,
            top_watermark_enabled=top_watermark_enabled,
            top_watermark_text=top_watermark_text,
        )

        # 2b. Keep a permanent copy so the Short is easy to find later
        saved_dest = None
        try:
            if KEEP_LOCAL_SHORTS and processed_short_path and processed_short_path.exists():
                part_name = f"_part{idx}" if len(windows) > 1 else ""
                dest = KEEP_SHORTS_DIR / f"short_{v_id}{part_name}.mp4"
                import shutil
                shutil.copy2(processed_short_path, dest)
                saved_dest = dest
                logger.info(f"💾 Finished Short saved to: {dest}")
        except Exception as e:
            logger.warning(f"Could not keep local copy of Short: {e}")

        # 3. Upload R2
        r2_key = f"shorts/{v_id}_part{idx}_short.mp4"
        uploaded_key = storage.upload_file(processed_short_path, r2_key=r2_key)

        # 4. Upload YouTube
        transcript_text = srt_to_text(srt_path)
        short_id = uploader.upload_short(
            video_path=processed_short_path,
            original_video_id=v_id,
            original_title=v_title,
            original_url=url,
            channel_name="Test Channel",
            part_label=f"Part {idx}" if len(windows) > 1 else None,
            account=acc_name,
            account_max_daily=max_daily,
            info=info,
            transcript_text=transcript_text,
            extra_hashtags=extra_hashtags,
            title_prefix=(account or {}).get("title_prefix") if account is not None else None,
            title_hashtags=str((account or {}).get("title_hashtags") or "").strip(),
            smart_titles=(account or {}).get("smart_titles"),
            expected_channel=((account or {}).get("expected_channel") or "").strip() or None,
        )

        state_db.record_video_state(
            video_id=f"{v_id}_part{idx}", video_url=url, title=v_title,
            peak_time=peak_time, clip_start=clip_start, clip_end=clip_end,
            r2_key=uploaded_key or r2_key,
            youtube_short_id=short_id or "",
            status="UPLOADED_YOUTUBE" if short_id and short_id != "QUOTA_LIMIT_REACHED" else "UPLOADED_R2",
            account=acc_name,
        )

        logger.info(f"✅ Short {idx} complete! Processed Short saved locally at: {processed_short_path}")
        if short_id and short_id != "QUOTA_LIMIT_REACHED":
            logger.info(f"Uploaded to YouTube Short ID: {short_id}")
        made += 1

        # Save title + hashtags alongside the Short (works in dry-run too)
        try:
            meta = uploader.generate_short_metadata(
                original_title=v_title,
                original_url=url,
                channel_name="Test Channel",
                part_label=f"Part {idx}" if len(windows) > 1 else None,
                info=info,
                transcript_text=transcript_text,
                extra_hashtags=extra_hashtags,
            )
            sidecar_target = saved_dest if saved_dest else processed_short_path
            save_metadata_sidecar(
                sidecar_target, meta,
                source_url=url,
                short_id=short_id or "",
                account=acc_name,
            )
        except Exception as e:
            logger.warning(f"Could not save metadata sidecar: {e}")

        # Stop early if the 24h YouTube upload cap was hit (no point rendering more)
        if short_id == "QUOTA_LIMIT_REACHED":
            logger.warning(
                f"YouTube 24h upload cap reached after {idx} Short(s) - stopping. "
                "Short(s) already made are saved in finished_shorts/ and R2."
            )
            break

    logger.info(f"🎬 Done: {made} Short(s) created from {url}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="24/7 YouTube Shorts Automation Bot - Farm clips, transcribe CPU, crop 9:16, R2 & YouTube upload"
    )
    parser.add_argument(
        "--mode",
        choices=["scheduler", "once", "process-url", "status", "prune-r2", "test-yt-auth", "webui"],
        default="scheduler",
        help="Operation mode: 'scheduler' (run 24/7 daemon), 'once' (run single cycle), 'process-url' (test URL), 'status', 'webui' (browser control panel), etc."
    )
    parser.add_argument(
        "--url",
        type=str,
        help="YouTube video URL to process when using --mode process-url"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="How many Shorts to make from one video (default 1 = best moment only; use 3 for top 3 moments)"
    )
    parser.add_argument(
        "--aspect",
        type=str,
        default=None,
        help="Output aspect ratio: '3:4' (reference Short style, 1080x1440) or '9:16' (classic, 1080x1920)"
    )
    parser.add_argument(
        "--fill",
        type=str,
        default=None,
        help="How to fit the video: 'blur' (whole frame + blurred background, nothing cut) or 'crop' (center crop)"
    )
    parser.add_argument(
        "--logo",
        type=str,
        default=None,
        help="Blur a corner logo/watermark: 'top-left', 'top-right', 'bottom-left', 'bottom-right', or 'off'"
    )
    parser.add_argument(
        "--like-subscribe",
        type=str,
        default=None,
        help="Show 'LIKE & SUBSCRIBE' banner at bottom: 'on' or 'off'"
    )
    parser.add_argument(
        "--top-watermark",
        type=str,
        default=None,
        help="Light channel-name watermark at the top (pass text, or 'off' to disable)"
    )
    parser.add_argument(
        "--channels",
        type=str,
        help="Comma-separated target channel URLs/IDs to override default configuration"
    )
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Only run this account (name from accounts.json). If not set, all enabled accounts run."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=CYCLE_INTERVAL_HOURS,
        help="Interval in hours for scheduler cycles"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=WEBUI_HOST,
        help="Host to bind the web control panel to (default 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=WEBUI_PORT,
        help="Port for the web control panel (default 5000)"
    )

    args = parser.parse_args()

    channels = [c.strip() for c in args.channels.split(",") if c.strip()] if args.channels else TARGET_CHANNELS

    # Resolve which accounts to run
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

    if args.mode == "prune-r2":
        logger.info("Manually triggering R2 storage pruning...")
        storage = CloudStorageManager()
        deleted = storage.enforce_storage_limit()
        print(f"Pruning complete. Deleted {deleted} object(s).")
        return

    if args.mode == "test-yt-auth":
        logger.info("Testing YouTube Data API v3 OAuth2 credentials...")
        uploader = YouTubeUploader()
        service = uploader._get_authenticated_service()
        if service:
            print("✅ YouTube OAuth credentials valid and token is active!")
        else:
            print("⚠️ Running in dry-run mode or client_secret.json missing/invalid.")
        return

    if args.mode == "process-url":
        if not args.url:
            print("Error: --url is required when --mode is 'process-url'")
            sys.exit(1)
        target_account = selected_accounts[0] if selected_accounts else None
        ls = None
        if args.like_subscribe is not None:
            ls = args.like_subscribe.strip().lower() in ("on", "true", "1", "yes")
        tw = None
        if args.top_watermark is not None:
            if args.top_watermark.strip().lower() in ("off", "false", "0", "none"):
                tw = ""  # explicitly disabled
            else:
                tw = args.top_watermark.strip()
        process_single_url(
            args.url,
            count=max(1, min(5, args.count)),
            aspect=args.aspect, fill=args.fill, logo_position=args.logo,
            like_subscribe=ls,
            top_watermark_text=tw,
            account=target_account,
        )
        return

    if args.mode == "once":
        logger.info(f"Running a single farming & processing cycle (accounts: {[a.get('name') for a in selected_accounts]})...")
        scheduler = ShortsBotScheduler(channels=channels, interval_hours=args.interval, accounts=selected_accounts)
        scheduler.run_single_cycle()
        return

    if args.mode == "scheduler":
        scheduler = ShortsBotScheduler(channels=channels, interval_hours=args.interval, accounts=selected_accounts)
        scheduler.start_24_7_loop()
        return

    if args.mode == "webui":
        from .webui import run_webui
        run_webui(host=args.host, port=args.port)
        return


if __name__ == "__main__":
    main()
