"""
models.py - SQLite Database manager for idempotency, state persistence, and
per-account YouTube 24h upload quota tracking (multi-account support).
"""
import sqlite3
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from .config import DB_PATH, logger


class StateDB:
    """
    Manages SQLite database state so the bot never re-processes videos and
    strictly enforces each account's 10 upload/24h API quota, across reboots.

    Every record is scoped to an `account` name, so multiple YouTube channels
    can run side by side with independent quotas and processed-video tracking.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    def init_db(self) -> None:
        """Initialize tables with per-account columns, migrating old DBs."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # ---- processed_videos ----
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='processed_videos'")
            has_old = cursor.fetchone() is not None

            if has_old:
                cols = [r["name"] for r in cursor.execute("PRAGMA table_info(processed_videos)")]
                if "account" not in cols:
                    logger.info("Migrating processed_videos table for multi-account support...")
                    # Rebuild table: add account column and make (video_id, account) unique
                    cursor.execute("""
                        CREATE TABLE processed_videos_new (
                            video_id TEXT NOT NULL,
                            account TEXT NOT NULL DEFAULT '',
                            video_url TEXT,
                            channel_id TEXT,
                            title TEXT,
                            peak_time REAL,
                            clip_start REAL,
                            clip_end REAL,
                            r2_key TEXT,
                            youtube_short_id TEXT,
                            status TEXT,
                            error_msg TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (video_id, account)
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO processed_videos_new (
                            video_id, account, video_url, channel_id, title, peak_time,
                            clip_start, clip_end, r2_key, youtube_short_id,
                            status, error_msg, created_at, updated_at
                        ) SELECT video_id, '', video_url, channel_id, title, peak_time,
                            clip_start, clip_end, r2_key, youtube_short_id,
                            status, error_msg, created_at, updated_at
                        FROM processed_videos
                    """)
                    cursor.execute("DROP TABLE processed_videos")
                    cursor.execute("ALTER TABLE processed_videos_new RENAME TO processed_videos")
                    conn.commit()
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_videos (
                        video_id TEXT NOT NULL,
                        account TEXT NOT NULL DEFAULT '',
                        video_url TEXT,
                        channel_id TEXT,
                        title TEXT,
                        peak_time REAL,
                        clip_start REAL,
                        clip_end REAL,
                        r2_key TEXT,
                        youtube_short_id TEXT,
                        status TEXT,
                        error_msg TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (video_id, account)
                    )
                """)

            # ---- daily_uploads ----
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_uploads'")
            has_old_up = cursor.fetchone() is not None
            if has_old_up:
                cols = [r["name"] for r in cursor.execute("PRAGMA table_info(daily_uploads)")]
                if "account" not in cols:
                    logger.info("Migrating daily_uploads table for multi-account support...")
                    cursor.execute("""
                        CREATE TABLE daily_uploads_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            video_id TEXT,
                            account TEXT NOT NULL DEFAULT '',
                            youtube_short_id TEXT,
                            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cursor.execute("""
                        INSERT INTO daily_uploads_new (video_id, account, youtube_short_id, uploaded_at)
                        SELECT video_id, '', youtube_short_id, uploaded_at FROM daily_uploads
                    """)
                    cursor.execute("DROP TABLE daily_uploads")
                    cursor.execute("ALTER TABLE daily_uploads_new RENAME TO daily_uploads")
                    conn.commit()
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS daily_uploads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        video_id TEXT,
                        account TEXT NOT NULL DEFAULT '',
                        youtube_short_id TEXT,
                        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

            conn.commit()
        logger.debug(f"StateDB initialized at {self.db_path}")

    # ------------------------------------------------------------------
    def is_video_processed(self, video_id: str, account: str = "") -> bool:
        """Check if a video ID has already been processed for this account."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status FROM processed_videos
                WHERE video_id = ? AND account = ?
                  AND status IN ('UPLOADED_R2', 'UPLOADED_YOUTUBE', 'PROCESSED', 'PROCESSED_MULTI')
            """, (video_id, account))
            return cursor.fetchone() is not None

    def get_video_state(self, video_id: str, account: str = "") -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM processed_videos WHERE video_id = ? AND account = ?",
                (video_id, account),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def record_video_state(
        self,
        video_id: str,
        video_url: str = "",
        channel_id: str = "",
        title: str = "",
        peak_time: float = 0.0,
        clip_start: float = 0.0,
        clip_end: float = 0.0,
        r2_key: str = "",
        youtube_short_id: str = "",
        status: str = "FETCHED",
        error_msg: str = "",
        account: str = ""
    ) -> None:
        """Insert or update a video's processing status, scoped to an account."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO processed_videos (
                    video_id, account, video_url, channel_id, title, peak_time,
                    clip_start, clip_end, r2_key, youtube_short_id,
                    status, error_msg, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, account) DO UPDATE SET
                    video_url=excluded.video_url,
                    channel_id=excluded.channel_id,
                    title=excluded.title,
                    peak_time=excluded.peak_time,
                    clip_start=excluded.clip_start,
                    clip_end=excluded.clip_end,
                    r2_key=coalesce(nullif(excluded.r2_key, ''), processed_videos.r2_key),
                    youtube_short_id=coalesce(nullif(excluded.youtube_short_id, ''), processed_videos.youtube_short_id),
                    status=excluded.status,
                    error_msg=excluded.error_msg,
                    updated_at=excluded.updated_at
            """, (
                video_id, account, video_url, channel_id, title, peak_time,
                clip_start, clip_end, r2_key, youtube_short_id,
                status, error_msg, now, now
            ))
            conn.commit()
        logger.debug(f"Recorded state for {account}/{video_id}: status={status}")

    def get_last_upload_time(self, account: str = "") -> Optional[datetime.datetime]:
        """Returns the timestamp of the most recent upload for an account (or None)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT uploaded_at FROM daily_uploads
                WHERE account = ?
                ORDER BY uploaded_at DESC LIMIT 1
            """, (account,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                return datetime.datetime.fromisoformat(row["uploaded_at"])
            except Exception:
                return None

    def get_uploads_in_last_24_hours(self, account: str = "") -> int:
        """Count YouTube uploads in the last 24h for ONE account."""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        cutoff_iso = cutoff.isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM daily_uploads
                WHERE uploaded_at >= ? AND account = ?
            """, (cutoff_iso, account))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def can_upload_today(self, max_daily_uploads: int = 10, account: str = "") -> Tuple[bool, int]:
        """Check upload quota for ONE account. Returns (can_upload, remaining_slots)."""
        count_24h = self.get_uploads_in_last_24_hours(account=account)
        remaining = max(0, max_daily_uploads - count_24h)
        return remaining > 0, remaining

    def record_upload(self, video_id: str, youtube_short_id: str, account: str = "") -> None:
        """Log a successful upload for one account and update its processed state."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_uploads (video_id, account, youtube_short_id, uploaded_at)
                VALUES (?, ?, ?, ?)
            """, (video_id, account, youtube_short_id, now_iso))
            cursor.execute("""
                UPDATE processed_videos
                SET youtube_short_id = ?, status = 'UPLOADED_YOUTUBE', updated_at = ?
                WHERE video_id = ? AND account = ?
            """, (youtube_short_id, now_iso, video_id, account))
            conn.commit()
        logger.info(f"Recorded YouTube upload for {account}/{video_id} -> Short ID: {youtube_short_id}")

    def get_all_processed_videos(self, limit: int = 50, account: str = "") -> List[Dict[str, Any]]:
        """Retrieve recent processed videos (optionally for one account)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if account:
                cursor.execute("""
                    SELECT * FROM processed_videos
                    WHERE account = ?
                    ORDER BY updated_at DESC LIMIT ?
                """, (account, limit))
            else:
                cursor.execute("""
                    SELECT * FROM processed_videos
                    ORDER BY updated_at DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def list_accounts_in_db(self) -> List[str]:
        """Distinct account names seen in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT account FROM processed_videos WHERE account != ''")
            return [r["account"] for r in cursor.fetchall()]
