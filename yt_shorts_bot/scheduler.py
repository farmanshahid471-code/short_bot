"""
scheduler.py - 24/7 continuous automation scheduler using APScheduler / schedule,
orchestrating target selection, heatmap analysis, section download, CPU transcription,
vertical cropping, R2 storage pruning, and YouTube Shorts uploading for MULTIPLE accounts.
"""
import time
import signal
import sys
import shutil
import threading
from pathlib import Path
from typing import Optional, List
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import (
    TARGET_CHANNELS,
    CYCLE_INTERVAL_HOURS,
    SHORTS_PER_VIDEO,
    SELECTION_ORDER,
    DELETE_AFTER_UPLOAD,
    DELETE_R2_AFTER_UPLOAD,
    TOP_WATERMARK_ENABLED,
    TOP_WATERMARK_TEXT,
    KEEP_LOCAL_SHORTS,
    KEEP_SHORTS_DIR,
    ACCOUNTS,
    logger,
)
from .models import StateDB
from .fetcher import YouTubeFetcher
from .processor import VideoProcessor
from .storage import CloudStorageManager
from .uploader import YouTubeUploader
from .hashtags import srt_to_text, save_metadata_sidecar


class ShortsBotScheduler:
    """
    Continuous 24/7 automation engine for farming YouTube clips,
    processing vertical Shorts, managing R2 storage, and uploading to YouTube
    across one or many accounts (each with its own channels, credentials,
    style settings, and daily quota).
    """
    def __init__(
        self,
        channels: Optional[List[str]] = None,
        interval_hours: int = CYCLE_INTERVAL_HOURS,
        accounts: Optional[List[dict]] = None,
    ):
        self.interval_hours = interval_hours
        if accounts is not None:
            self.accounts = accounts
        else:
            # Re-read accounts.json fresh so accounts added/edited from the
            # control panel apply IMMEDIATELY (no panel restart needed).
            try:
                from .config import _load_accounts
                self.accounts = _load_accounts()
            except Exception:
                self.accounts = ACCOUNTS
        # Backwards-compatible: if caller passes channels directly, build one account
        if channels is not None and len(self.accounts) == 1 and self.accounts[0]["name"] == "default":
            self.accounts[0]["target_channels"] = channels
        self.state_db = StateDB()
        self.processor = VideoProcessor()
        self.storage = CloudStorageManager()
        self.scheduler = BlockingScheduler()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Register graceful SIGINT/SIGTERM shutdown handlers (main thread only)."""
        if threading.current_thread() is not threading.main_thread():
            return

        def handle_shutdown(signum, frame):
            logger.info("Received termination signal. Shutting down 24/7 Shorts bot gracefully...")
            try:
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

    # ------------------------------------------------------------------
    def run_single_cycle(self, accounts: Optional[List[dict]] = None) -> int:
        """
        Runs one complete farming and processing cycle for all enabled accounts.
        Returns the number of videos successfully processed and uploaded.
        """
        accounts = accounts if accounts is not None else self.accounts
        logger.info("=== STARTING 24/7 SHORTS BOT FARMING & PROCESSING CYCLE ===")
        total_made = 0

        for account in accounts:
            if not account.get("enabled", True):
                logger.info(f"Skipping disabled account: {account.get('name')}")
                continue
            try:
                total_made += self._run_cycle_for_account(account)
            except Exception as e:
                logger.error(f"Cycle failed for account '{account.get('name')}': {e}")

        logger.info(f"=== COMPLETED CYCLE: Processed {total_made} new Short(s) across all accounts ===")
        return total_made

    # ------------------------------------------------------------------
    def _run_cycle_for_account(self, account: dict) -> int:
        """Runs a full cycle for ONE account (its channels, style, quota, creds)."""
        name = account.get("name", "default")
        channels = account.get("target_channels") or TARGET_CHANNELS
        max_daily = int(account.get("max_daily_uploads") or 10)
        aspect = account.get("aspect")
        fill = account.get("fill")
        shorts_per_video = int(account.get("shorts_per_video") or SHORTS_PER_VIDEO)
        min_gap_min = int(account.get("min_minutes_between_uploads") or 0)
        del_after = account.get("delete_after_upload", DELETE_AFTER_UPLOAD)
        del_r2 = account.get("delete_r2_after_upload", DELETE_R2_AFTER_UPLOAD)
        # Clip bot: subtitles ON by default. Per-account override available.
        subtitles_enabled = account.get("subtitles_enabled", True)
        expected_channel = (account.get("expected_channel") or "").strip() or None
        if expected_channel:
            logger.info(f"[{name}] Channel safety lock: uploads verified against '{expected_channel}'.")

        # Per-account watermark ("LIKE & SUBSCRIBE" banner + top channel watermark)
        wm_enabled = account.get("watermark_enabled")
        wm_text = (account.get("watermark") or "").strip() or None
        top_wm_enabled = account.get("top_watermark_enabled")
        # Empty top watermark text = NO top watermark (explicit empty stays off,
        # matching the config docs "leave empty to disable"). No auto fallback
        # to the account name - if you want your channel name there, type it.
        top_wm_text = (account.get("top_watermark") or TOP_WATERMARK_TEXT or "").strip() or None
        if wm_text or top_wm_text:
            logger.info(
                f"[{name}] Watermarks: bottom='{wm_text}' top='{top_wm_text}' "
                f"(enabled bottom={wm_enabled if wm_enabled is not None else 'default'}, "
                f"top={top_wm_enabled if top_wm_enabled is not None else 'default'})"
            )

        logger.info(f"--- Account: {name} | channels: {channels} | max uploads/day: {max_daily} ---")

        fetcher = YouTubeFetcher(channels=channels)
        from .uploader import resolve_credentials
        cs, tk = resolve_credentials(account)
        uploader = YouTubeUploader(
            client_secret_file=cs,
            token_file=tk,
            state_db=self.state_db,
        )

        can_upload, remaining = self.state_db.can_upload_today(max_daily_uploads=max_daily, account=name)
        logger.info(f"[{name}] YouTube 24h upload quota: {remaining} slots remaining.")

        processed_count = 0
        for channel_url in channels:
            if not can_upload:
                logger.warning(f"[{name}] Daily upload cap reached - stopping this account's cycle.")
                break

            logger.info(f"[{name}] Checking target channel: {channel_url}")
            try:
                recent_videos = fetcher.fetch_channel_recent_videos(channel_url)
            except Exception as e:
                logger.error(f"[{name}] Failed to fetch channel list for {channel_url}: {e}")
                continue

            # Apply selection order (per-account override > global setting)
            order = (account.get("selection_order") or SELECTION_ORDER).strip().lower()
            if order == "oldest":
                recent_videos = list(reversed(recent_videos))
                logger.info(f"[{name}] Selection order: oldest first ({len(recent_videos)} candidates)")
            elif order == "random":
                import random as _rnd
                _rnd.shuffle(recent_videos)
                logger.info(f"[{name}] Selection order: random ({len(recent_videos)} candidates)")
            else:
                logger.info(f"[{name}] Selection order: newest first ({len(recent_videos)} candidates)")

            for video_meta in recent_videos:
                v_id = video_meta["video_id"]
                v_url = video_meta["url"]
                v_title = video_meta["title"]

                if self.state_db.is_video_processed(v_id, account=name):
                    logger.debug(f"[{name}] Skipping already processed video: '{v_title}' ({v_id})")
                    continue

                # ---- pacing: respect min-minutes-between-uploads ----
                if min_gap_min > 0:
                    last_up = self.state_db.get_last_upload_time(account=name)
                    if last_up is not None:
                        from datetime import datetime, timezone
                        elapsed = (datetime.now(timezone.utc) - last_up).total_seconds() / 60.0
                        if elapsed < min_gap_min:
                            wait_s = int((min_gap_min - elapsed) * 60) + 1
                            logger.info(f"[{name}] Waiting {wait_s}s to respect {min_gap_min} min between uploads...")
                            time.sleep(wait_s)

                logger.info(f"[{name}] --> Processing new target video: '{v_title}' ({v_url})")

                # Step 1: pick window(s) - best heatmap/energy moment, or top N
                try:
                    if shorts_per_video > 1:
                        top_windows = fetcher.select_top_windows(v_url, count=shorts_per_video)
                        windows = [
                            {"start": w["start"], "end": w["end"], "score": w.get("score", 0.0)}
                            for w in top_windows
                        ]
                        logger.info(f"[{name}] Making {len(windows)} Short(s) from the top moments of '{v_title}'")
                    else:
                        info, peak_time, clip_start, clip_end = fetcher.extract_heatmap_and_select_window(v_url)
                        windows = [{"start": clip_start, "end": clip_end, "score": peak_time}]
                except Exception as e:
                    logger.error(f"[{name}] Heatmap/energy analysis failed for {v_url}: {e}")
                    self.state_db.record_video_state(
                        video_id=v_id, video_url=v_url, title=v_title,
                        status="FAILED", error_msg=str(e), account=name,
                    )
                    continue

                made = self._process_video_windows(
                    v_id, v_url, v_title, channel_url, windows,
                    account=name, max_daily=max_daily,
                    uploader=uploader, aspect=aspect, fill=fill,
                    like_subscribe=(None if wm_enabled is None else bool(wm_enabled)),
                    like_subscribe_text=wm_text,
                    top_watermark_enabled=(None if top_wm_enabled is None else bool(top_wm_enabled)),
                    top_watermark_text=top_wm_text,
                    extra_hashtags=str(account.get("extra_hashtags") or "").strip(),
                    title_prefix=account.get("title_prefix"),
                    title_hashtags=str(account.get("title_hashtags") or "").strip(),
                    smart_titles=account.get("smart_titles"),
                    delete_after_upload=del_after,
                    delete_r2_after_upload=del_r2,
                    subtitles_enabled=subtitles_enabled,
                    expected_channel=expected_channel,
                )
                processed_count += made
                can_upload, remaining = self.state_db.can_upload_today(
                    max_daily_uploads=max_daily, account=name
                )

                # One new video per channel per cycle to pace uploads naturally
                break

        logger.info(f"[{name}] Account cycle done: {processed_count} Short(s).")
        return processed_count

    # ------------------------------------------------------------------
    def _process_video_windows(
        self,
        v_id: str,
        v_url: str,
        v_title: str,
        channel_url: str,
        windows: List[dict],
        account: str = "",
        max_daily: int = 10,
        uploader: Optional[YouTubeUploader] = None,
        aspect: Optional[str] = None,
        fill: Optional[str] = None,
        like_subscribe: Optional[bool] = None,
        like_subscribe_text: Optional[str] = None,
        top_watermark_enabled: Optional[bool] = None,
        top_watermark_text: Optional[str] = None,
        extra_hashtags: str = "",
        title_prefix: Optional[str] = None,
        title_hashtags: str = "",
        smart_titles: Optional[bool] = None,
        delete_after_upload: Optional[bool] = None,
        delete_r2_after_upload: Optional[bool] = None,
        subtitles_enabled: Optional[bool] = None,
        expected_channel: Optional[str] = None,
    ) -> int:
        """
        Downloads, processes, and uploads one Short per window for a single video,
        for ONE account. Stops early if the account's daily quota is reached.
        """
        if uploader is None:
            uploader = YouTubeUploader(state_db=self.state_db)

        made = 0
        total = len(windows)

        for idx, win in enumerate(windows, start=1):
            clip_start, clip_end = float(win["start"]), float(win["end"])
            peak_time = (clip_start + clip_end) / 2.0
            part_label = f"Part {idx}" if total > 1 else None
            db_video_id = f"{v_id}_part{idx}" if total > 1 else v_id

            logger.info(f"[{account}] --- Short {idx}/{total}: segment [{clip_start:.1f}s -> {clip_end:.1f}s] ---")

            # Step 2: Download ONLY the selected segment
            raw_clip_path = None
            try:
                raw_clip_path = self._download_window(v_url, clip_start, clip_end)
            except Exception as e:
                logger.error(f"[{account}] Clip section download failed for {v_url}: {e}")
                self.state_db.record_video_state(
                    video_id=db_video_id, video_url=v_url, title=v_title,
                    peak_time=peak_time, clip_start=clip_start, clip_end=clip_end,
                    status="FAILED", error_msg=str(e), account=account,
                )
                continue

            # Step 3: Transcribe + crop + subtitles + BGM
            processed_short_path = None
            srt_path = None
            try:
                srt_path = Path(raw_clip_path).with_suffix(".srt")
                processed_short_path = self.processor.process_clip_to_short(
                    raw_clip_path, srt_path=srt_path, aspect=aspect, fill=fill,
                    like_subscribe=like_subscribe, like_subscribe_text=like_subscribe_text,
                    top_watermark_enabled=top_watermark_enabled,
                    top_watermark_text=top_watermark_text,
                    subtitles=subtitles_enabled,
                )
            except Exception as e:
                logger.error(f"[{account}] Video processing/subtitles failed for {v_id}: {e}")
                self.state_db.record_video_state(
                    video_id=db_video_id, video_url=v_url, title=v_title,
                    peak_time=peak_time, clip_start=clip_start, clip_end=clip_end,
                    status="FAILED", error_msg=str(e), account=account,
                )
                self.storage.cleanup_local_files(raw_clip_path, srt_path)
                continue

            # Step 4: Upload to Cloudflare R2 (enforcing 8 GB limit)
            r2_key = f"shorts/{account}/{db_video_id}_short.mp4"
            try:
                uploaded_key = self.storage.upload_file(processed_short_path, r2_key=r2_key)
                if uploaded_key:
                    r2_key = uploaded_key
            except Exception as e:
                logger.error(f"[{account}] R2 upload failed for {v_id}: {e}")

            # Record state as R2 uploaded
            self.state_db.record_video_state(
                video_id=db_video_id, video_url=v_url, channel_id=channel_url,
                title=v_title, peak_time=peak_time,
                clip_start=clip_start, clip_end=clip_end,
                r2_key=r2_key, status="UPLOADED_R2", account=account,
            )

            # Step 5: Upload to YouTube (this account's quota)
            quota_hit = False
            try:
                transcript_text = srt_to_text(srt_path)
                short_id = uploader.upload_short(
                    video_path=processed_short_path,
                    original_video_id=db_video_id,
                    original_title=v_title,
                    original_url=v_url,
                    channel_name=channel_url,
                    part_label=part_label,
                    account=account,
                    account_max_daily=max_daily,
                    info={"title": v_title},
                    transcript_text=transcript_text,
                    extra_hashtags=extra_hashtags,
                    title_prefix=title_prefix,
                    title_hashtags=title_hashtags,
                    smart_titles=smart_titles,
                    expected_channel=expected_channel,
                )
                if short_id == "QUOTA_LIMIT_REACHED":
                    logger.warning(f"[{account}] Upload cap reached - saved in R2, queued for next window.")
                    quota_hit = True
                elif short_id:
                    logger.info(f"[{account}] SUCCESS! Created YouTube Short {short_id} from {v_id}")
                    made += 1
            except Exception as e:
                logger.error(f"[{account}] YouTube upload failed for {v_id}: {e}")

            # Step 6: Keep a local copy (optional), then clean up working files
            self._keep_local_copy(processed_short_path, db_video_id, account)

            # Save title + hashtags alongside the Short (works in dry-run too)
            try:
                meta = uploader.generate_short_metadata(
                    original_title=v_title,
                    original_url=v_url,
                    channel_name=channel_url,
                    part_label=part_label,
                    info={"title": v_title},
                    transcript_text=transcript_text,
                    extra_hashtags=extra_hashtags,
                )
                saved_copy = KEEP_SHORTS_DIR / f"{account}_short_{db_video_id}.mp4"
                sidecar_target = saved_copy if saved_copy.exists() else processed_short_path
                save_metadata_sidecar(
                    sidecar_target, meta,
                    source_url=v_url,
                    short_id=short_id or "",
                    account=account,
                )
            except Exception as e:
                logger.warning(f"Could not save metadata sidecar: {e}")

            # Delete-after-upload: remove the local copy + sidecar once posted
            if short_id and short_id != "QUOTA_LIMIT_REACHED" and delete_after_upload:
                local_copy = KEEP_SHORTS_DIR / f"{account}_short_{db_video_id}.mp4"
                for fp in (local_copy, local_copy.with_suffix(".txt")):
                    try:
                        if Path(fp).exists():
                            Path(fp).unlink()
                            logger.info(f"[{account}] 🗑️ Deleted local copy after upload: {fp}")
                    except Exception as e:
                        logger.warning(f"[{account}] Could not delete {fp}: {e}")
            if short_id and short_id != "QUOTA_LIMIT_REACHED" and delete_r2_after_upload and r2_key and self.storage.client:
                try:
                    self.storage.client.delete_object(Bucket=self.storage.bucket_name, Key=r2_key)
                    logger.info(f"[{account}] 🗑️ Deleted R2 backup after upload: {r2_key}")
                except Exception as e:
                    logger.warning(f"[{account}] Could not delete R2 object {r2_key}: {e}")

            self.storage.cleanup_local_files(raw_clip_path, processed_short_path, srt_path)

            if quota_hit:
                break

        # Mark the base video as processed for this account (multi-shorts case)
        if total > 1:
            self.state_db.record_video_state(
                video_id=v_id, video_url=v_url, channel_id=channel_url,
                title=v_title,
                clip_start=float(windows[0]["start"]),
                clip_end=float(windows[-1]["end"]),
                status="PROCESSED_MULTI", account=account,
            )

        return made

    def _download_window(self, v_url: str, clip_start: float, clip_end: float) -> Path:
        """Small helper so _process_video_windows uses the shared fetcher download."""
        return YouTubeFetcher().download_clip_section(v_url, clip_start, clip_end)

    # ------------------------------------------------------------------
    def _keep_local_copy(self, processed_short_path, v_id: str, account: str = "") -> None:
        try:
            if not KEEP_LOCAL_SHORTS:
                return
            if not processed_short_path or not Path(processed_short_path).exists():
                return
            dest = KEEP_SHORTS_DIR / f"{account}_short_{v_id}.mp4"
            shutil.copy2(processed_short_path, dest)
            logger.info(f"Saved local copy of finished Short: {dest}")
        except Exception as e:
            logger.warning(f"Could not keep local copy of Short {v_id}: {e}")

    # ------------------------------------------------------------------
    def start_24_7_loop(self) -> None:
        logger.info(
            f"Starting 24/7 YouTube Shorts Automation Bot daemon "
            f"(Interval: every {self.interval_hours} hour(s), "
            f"{len(self.accounts)} account(s))..."
        )
        try:
            self.run_single_cycle()
        except Exception as e:
            logger.error(f"Exception during initial startup cycle: {e}")

        self.scheduler.add_job(
            self.run_single_cycle,
            trigger=IntervalTrigger(hours=self.interval_hours),
            id="yt_shorts_farming_job",
            name="YouTube Shorts Clip Farming & Upload Cycle",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600
        )
        logger.info("Scheduler running 24/7. Press Ctrl+C to stop.")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped by user.")

    def stop(self) -> None:
        """Stops the 24/7 scheduler loop (used by the web control panel)."""
        try:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info("Scheduler stopped by web control panel.")
            else:
                logger.info("Scheduler was not running.")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
