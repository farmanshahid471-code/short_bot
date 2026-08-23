"""
scheduler.py - 24/7 loop for the REPOST bot: scans channels, downloads their
Shorts, prepares them, uploads to YOUR channel(s) - MULTIPLE accounts supported.
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
    MAX_SHORTS_PER_CHANNEL_CYCLE,
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
from .fetcher import ShortsFetcher
from .reprocessor import ShortReprocessor
from .storage import CloudStorageManager
from .uploader import YouTubeUploader


class ShortsRepostScheduler:
    """24/7 engine that reposts Shorts to one or many of your channels."""

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
        if channels is not None and len(self.accounts) == 1 and self.accounts[0]["name"] == "default":
            self.accounts[0]["target_channels"] = channels
        self.state_db = StateDB()
        self.storage = CloudStorageManager()
        self.scheduler = BlockingScheduler()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def handle_shutdown(signum, frame):
            logger.info("Received termination signal. Shutting down gracefully...")
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
        """One full scan-and-repost cycle across all enabled accounts."""
        accounts = accounts if accounts is not None else self.accounts
        logger.info("=== STARTING SHORTS REPOST CYCLE ===")
        uploaded_count = 0

        for account in accounts:
            if not account.get("enabled", True):
                logger.info(f"Skipping disabled account: {account.get('name')}")
                continue
            try:
                uploaded_count += self._run_cycle_for_account(account)
            except Exception as e:
                logger.error(f"Cycle failed for account '{account.get('name')}': {e}")

        logger.info(f"=== CYCLE COMPLETE: uploaded {uploaded_count} Short(s) across all accounts ===")
        return uploaded_count

    # ------------------------------------------------------------------
    def _run_cycle_for_account(self, account: dict) -> int:
        name = account.get("name", "default")
        channels = account.get("target_channels") or TARGET_CHANNELS
        max_daily = int(account.get("max_daily_uploads") or 10)
        process_mode = account.get("process_mode") or "copy"
        aspect = account.get("aspect") or "auto"   # auto = like the original video
        fill = account.get("fill") or "crop"
        # Repost render mode: subtitles OFF by default (source Shorts already
        # have captions baked in) - watermarks only. Per-account override.
        subtitles_enabled = account.get("subtitles_enabled", False)
        expected_channel = (account.get("expected_channel") or "").strip() or None
        if expected_channel:
            logger.info(f"[{name}] Channel safety lock: uploads verified against '{expected_channel}'.")

        # Per-account watermarks (bottom banner + top channel watermark)
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

        # IMPORTANT: watermarks are ONLY burned in "render" mode. In "copy" mode
        # the original Short is re-encoded as-is, so NO watermark is applied.
        if (wm_text or top_wm_text) and str(process_mode) != "render":
            logger.warning(
                f"[{name}] ⚠️ Watermarks are configured ('{wm_text or top_wm_text}') but process_mode is "
                f"'{process_mode}' (copy = original as-is). Switch this account to 'render' mode "
                f"in Settings -> Source to apply watermarks + subtitles."
            )

        logger.info(f"--- Account: {name} | channels: {channels} | max uploads/day: {max_daily} | mode: {process_mode} ---")

        fetcher = ShortsFetcher(channels=channels)
        reprocessor = ShortReprocessor()
        from .uploader import resolve_credentials
        cs, tk = resolve_credentials(account)
        uploader = YouTubeUploader(
            client_secret_file=cs,
            token_file=tk,
            state_db=self.state_db,
        )

        can_upload, remaining = self.state_db.can_upload_today(max_daily_uploads=max_daily, account=name)
        logger.info(f"[{name}] YouTube 24h upload quota: {remaining} slots remaining.")

        uploaded_count = 0
        for channel_url in channels:
            if not can_upload:
                logger.warning(f"[{name}] Daily upload cap reached - stopping this account's cycle.")
                break

            logger.info(f"[{name}] Checking channel: {channel_url}")
            try:
                shorts = fetcher.fetch_channel_recent_shorts(channel_url)
            except Exception as e:
                logger.error(f"[{name}] Failed to scan {channel_url}: {e}")
                continue

            # Apply selection order (per-account override > global setting)
            order = (account.get("selection_order") or SELECTION_ORDER).strip().lower()
            if order == "oldest":
                shorts = list(reversed(shorts))
                logger.info(f"[{name}] Selection order: oldest first ({len(shorts)} candidates)")
            elif order == "random":
                import random as _rnd
                _rnd.shuffle(shorts)
                logger.info(f"[{name}] Selection order: random ({len(shorts)} candidates)")
            else:
                logger.info(f"[{name}] Selection order: newest first ({len(shorts)} candidates)")

            done_this_channel = 0
            max_per_chan = int(account.get("max_shorts_per_channel_cycle") or MAX_SHORTS_PER_CHANNEL_CYCLE)
            min_gap_min = int(account.get("min_minutes_between_uploads") or 0)
            for short in shorts:
                if not can_upload or done_this_channel >= max_per_chan:
                    break
                v_id = short["video_id"]
                v_url = short["url"]
                v_title = short["title"]

                if self.state_db.is_video_processed(v_id, account=name):
                    logger.debug(f"[{name}] Skipping already-reposted Short: {v_title} ({v_id})")
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

                logger.info(f"[{name}] --> Reposting Short: '{v_title}' ({v_url})")
                try:
                    uploaded = self._process_one(
                        v_id, v_url, v_title, channel_url,
                        account=name, max_daily=max_daily,
                        fetcher=fetcher, reprocessor=reprocessor, uploader=uploader,
                        like_subscribe=(None if wm_enabled is None else bool(wm_enabled)),
                        like_subscribe_text=wm_text,
                        top_watermark_enabled=(None if top_wm_enabled is None else bool(top_wm_enabled)),
                        top_watermark_text=top_wm_text,
                        extra_hashtags=str(account.get("extra_hashtags") or "").strip(),
                        title_prefix=account.get("title_prefix"),
                        title_hashtags=str(account.get("title_hashtags") or "").strip(),
                        smart_titles=account.get("smart_titles"),
                        delete_after_upload=account.get("delete_after_upload", DELETE_AFTER_UPLOAD),
                        delete_r2_after_upload=account.get("delete_r2_after_upload", DELETE_R2_AFTER_UPLOAD),
                        process_mode=process_mode,
                        subtitles_enabled=subtitles_enabled,
                        expected_channel=expected_channel,
                        aspect=aspect,
                        fill=fill,
                    )
                    if uploaded:
                        uploaded_count += 1
                        done_this_channel += 1
                except Exception as e:
                    logger.error(f"[{name}] Failed to repost {v_url}: {e}")
                    self.state_db.record_video_state(
                        video_id=v_id, video_url=v_url, title=v_title,
                        status="FAILED", error_msg=str(e), account=name,
                    )

                can_upload, remaining = self.state_db.can_upload_today(
                    max_daily_uploads=max_daily, account=name
                )

        logger.info(f"[{name}] Account cycle done: {uploaded_count} Short(s).")
        return uploaded_count

    # ------------------------------------------------------------------
    def _process_one(
        self, v_id, v_url, v_title, channel_url,
        account: str = "", max_daily: int = 10,
        fetcher=None, reprocessor=None, uploader=None,
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
        process_mode: Optional[str] = None,
        subtitles_enabled: Optional[bool] = None,
        expected_channel: Optional[str] = None,
        aspect: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> bool:
        """Download -> prepare -> keep copy -> R2 -> YouTube. Returns True if uploaded."""
        if fetcher is None:
            fetcher = ShortsFetcher()
        if reprocessor is None:
            reprocessor = ShortReprocessor()
        if uploader is None:
            uploader = YouTubeUploader(state_db=self.state_db)

        raw_path = fetcher.download_short(v_url)
        final_path = reprocessor.process_short(
            raw_path,
            like_subscribe=like_subscribe,
            like_subscribe_text=like_subscribe_text,
            top_watermark_enabled=top_watermark_enabled,
            top_watermark_text=top_watermark_text,
            mode=process_mode,
            subtitles=subtitles_enabled,
            aspect=aspect,
            fill=fill,
        )

        if KEEP_LOCAL_SHORTS and final_path.exists():
            dest = KEEP_SHORTS_DIR / f"{account}_repost_{v_id}.mp4"
            try:
                shutil.copy2(final_path, dest)
                logger.info(f"[{account}] 💾 Saved local copy: {dest}")
            except Exception as e:
                logger.warning(f"[{account}] Could not keep local copy: {e}")

        r2_key = f"reposts/{account}/{v_id}.mp4"
        try:
            uploaded_key = self.storage.upload_file(final_path, r2_key=r2_key)
            if uploaded_key:
                r2_key = uploaded_key
        except Exception as e:
            logger.error(f"[{account}] R2 upload failed for {v_id}: {e}")

        # Fetch full metadata for content-aware hashtags (title/desc/tags/category)
        info = {"title": v_title}
        try:
            if fetcher is not None:
                info = fetcher.get_short_info(v_url)
        except Exception as e:
            logger.debug(f"[{account}] Could not fetch full metadata for {v_id}: {e}")

        short_id = uploader.upload_short(
            video_path=final_path,
            original_video_id=v_id,
            original_title=v_title,
            original_url=v_url,
            channel_name=channel_url,
            account=account,
            account_max_daily=max_daily,
            info=info,
            transcript_text="",
            extra_hashtags=extra_hashtags,
            title_prefix=title_prefix,
            title_hashtags=title_hashtags,
            smart_titles=smart_titles,
            expected_channel=expected_channel,
        )

        status = "UPLOADED_YOUTUBE" if short_id and short_id != "QUOTA_LIMIT_REACHED" else "UPLOADED_R2"
        self.state_db.record_video_state(
            video_id=v_id, video_url=v_url, channel_id=channel_url,
            title=v_title, r2_key=r2_key,
            youtube_short_id=short_id or "",
            status=status, account=account,
        )

        # Save title + hashtags alongside the Short (works in dry-run too)
        try:
            meta = uploader.generate_short_metadata(
                original_title=v_title,
                original_url=v_url,
                channel_name=channel_url,
                info=info,
                transcript_text="",
                extra_hashtags=extra_hashtags,
            )
            from .hashtags import save_metadata_sidecar
            sidecar_target = KEEP_SHORTS_DIR / f"{account}_repost_{v_id}.mp4"
            if not sidecar_target.exists():
                sidecar_target = final_path
            save_metadata_sidecar(
                sidecar_target, meta,
                source_url=v_url,
                short_id=short_id or "",
                account=account,
            )
        except Exception as e:
            logger.warning(f"[{account}] Could not save metadata sidecar: {e}")

        try:
            for p in (raw_path, final_path):
                if p and Path(p).exists():
                    Path(p).unlink()
        except Exception:
            pass

        if short_id == "QUOTA_LIMIT_REACHED":
            logger.warning(f"[{account}] YouTube 24h cap reached - queued for next window (saved in R2 + finished_shorts/).")
            return False
        if short_id:
            logger.info(f"[{account}] SUCCESS! Reposted '{v_title}' -> {short_id}")

            # ---- delete-after-upload ----
            if delete_after_upload:
                local_copy = KEEP_SHORTS_DIR / f"{account}_repost_{v_id}.mp4"
                for fp in (local_copy, local_copy.with_suffix(".txt")):
                    try:
                        if Path(fp).exists():
                            Path(fp).unlink()
                            logger.info(f"[{account}] 🗑️ Deleted local copy after upload: {fp}")
                    except Exception as e:
                        logger.warning(f"[{account}] Could not delete {fp}: {e}")
            if delete_r2_after_upload and uploaded_key and self.storage.client:
                try:
                    self.storage.client.delete_object(Bucket=self.storage.bucket_name, Key=uploaded_key)
                    logger.info(f"[{account}] 🗑️ Deleted R2 backup after upload: {uploaded_key}")
                except Exception as e:
                    logger.warning(f"[{account}] Could not delete R2 object {uploaded_key}: {e}")
            return True
        return False

    # ------------------------------------------------------------------
    def start_24_7_loop(self) -> None:
        logger.info(
            f"Starting 24/7 Shorts REPOST bot (every {self.interval_hours} hour(s), "
            f"{len(self.accounts)} account(s))..."
        )
        try:
            self.run_single_cycle()
        except Exception as e:
            logger.error(f"Initial cycle failed: {e}")

        self.scheduler.add_job(
            self.run_single_cycle,
            trigger=IntervalTrigger(hours=self.interval_hours),
            id="shorts_repost_job",
            name="Shorts Repost Cycle",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("Scheduler running 24/7. Press Ctrl+C to stop.")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")

    def stop(self) -> None:
        try:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                logger.info("Scheduler stopped by web control panel.")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
