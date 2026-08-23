"""
storage.py - Cloudflare R2 (S3-compatible) integration, storage monitoring,
8 GB threshold enforcement (auto-deleting oldest clips), and local disk cleanup.
"""
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
    R2_ENDPOINT_URL,
    R2_MAX_BUCKET_BYTES,
    logger,
)


class CloudStorageManager:
    """
    Manages video clip storage in Cloudflare R2 (S3-compatible API).
    Monitors total storage usage and automatically deletes the oldest objects
    when bucket usage hits the 8 GB threshold (staying safely below 10 GB free tier).
    Also cleans up local files immediately after upload to conserve server disk space.
    """
    _dry_run_warned = False  # log the dry-run warning only once per process

    def __init__(
        self,
        access_key_id: str = R2_ACCESS_KEY_ID,
        secret_access_key: str = R2_SECRET_ACCESS_KEY,
        endpoint_url: str = R2_ENDPOINT_URL,
        bucket_name: str = R2_BUCKET_NAME,
        max_bucket_bytes: int = R2_MAX_BUCKET_BYTES
    ):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.bucket_name = bucket_name
        self.max_bucket_bytes = max_bucket_bytes
        self.client = self._init_s3_client()

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        """True if the value is empty or still a template placeholder from .env.example."""
        if not value or not str(value).strip():
            return True
        v = str(value).lower()
        return any(marker in v for marker in ("your_", "changeme", "replace_me", "your-cloudflare"))

    def _init_s3_client(self):
        """Initialize boto3 S3 client for Cloudflare R2."""
        if (
            self._is_placeholder(self.access_key_id)
            or self._is_placeholder(self.secret_access_key)
            or self._is_placeholder(self.endpoint_url)
        ):
            if not CloudStorageManager._dry_run_warned:
                logger.warning(
                    "Cloudflare R2 credentials not fully configured (missing or still "
                    "template placeholders). Storage operations will run in DRY-RUN mode."
                )
                CloudStorageManager._dry_run_warned = True
            return None

        try:
            client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto"
            )
            logger.debug(f"Connected to Cloudflare R2 bucket: {self.bucket_name}")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize R2 S3 client: {e}")
            return None

    def get_bucket_usage(self) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Calculates total bytes stored in the bucket and returns all object metadata
        sorted by LastModified ascending (oldest first).
        
        Returns:
            (total_bytes: int, sorted_objects: list)
        """
        if not self.client:
            logger.debug("R2 client not available; returning 0 bucket usage.")
            return 0, []

        total_bytes = 0
        objects = []

        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name):
                for obj in page.get("Contents", []):
                    size = obj.get("Size", 0)
                    total_bytes += size
                    objects.append({
                        "Key": obj["Key"],
                        "Size": size,
                        "LastModified": obj["LastModified"]
                    })
        except Exception as e:
            logger.error(f"Error listing R2 bucket {self.bucket_name}: {e}")
            return 0, []

        # Sort oldest first
        objects.sort(key=lambda x: x["LastModified"])

        gb_used = total_bytes / (1024 ** 3)
        gb_max = self.max_bucket_bytes / (1024 ** 3)
        logger.info(
            f"Current R2 Bucket Usage: {gb_used:.3f} GB / {gb_max:.2f} GB threshold "
            f"({len(objects)} stored clips)"
        )

        return total_bytes, objects

    def enforce_storage_limit(self) -> int:
        """
        Monitors bucket usage against the 8 GB threshold.
        If total storage >= 8 GB, automatically deletes the oldest objects in the bucket
        until total storage is safely below threshold (e.g. 7.5 GB).
        
        Returns number of deleted objects.
        """
        total_bytes, objects = self.get_bucket_usage()
        if total_bytes < self.max_bucket_bytes:
            return 0

        logger.warning(
            f"R2 bucket usage ({total_bytes / (1024**3):.2f} GB) exceeded threshold "
            f"({self.max_bucket_bytes / (1024**3):.2f} GB). Starting automatic pruning of oldest clips..."
        )

        deleted_count = 0
        target_bytes = int(self.max_bucket_bytes * 0.92)  # Prune down to 92% of threshold

        for obj in objects:
            if total_bytes <= target_bytes:
                break
            key = obj["Key"]
            size = obj["Size"]
            logger.info(f"Deleting oldest R2 clip '{key}' ({size / (1024**2):.2f} MB)...")
            try:
                self.client.delete_object(Bucket=self.bucket_name, Key=key)
                total_bytes -= size
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete R2 object '{key}': {e}")

        logger.info(
            f"Storage pruning completed. Deleted {deleted_count} old clips. "
            f"New bucket usage: {total_bytes / (1024**3):.2f} GB."
        )
        return deleted_count

    def upload_file(self, file_path: Path, r2_key: Optional[str] = None) -> Optional[str]:
        """
        Uploads a processed clip to Cloudflare R2 after enforcing storage limits.
        Returns the object Key if successful.
        """
        if not file_path.exists():
            logger.error(f"Cannot upload missing file: {file_path}")
            return None

        if r2_key is None:
            r2_key = f"shorts/{file_path.name}"

        # First, ensure we don't cross the 8 GB threshold
        self.enforce_storage_limit()

        if not self.client:
            logger.info(f"[DRY-RUN] Simulated R2 upload of {file_path.name} -> key: {r2_key}")
            return r2_key

        logger.info(f"Uploading {file_path.name} to R2 bucket '{self.bucket_name}' under key '{r2_key}'...")
        try:
            self.client.upload_file(
                Filename=str(file_path),
                Bucket=self.bucket_name,
                Key=r2_key,
                ExtraArgs={"ContentType": "video/mp4"}
            )
            logger.info(f"Successfully uploaded {file_path.name} to R2 ({r2_key})")
            return r2_key
        except Exception as e:
            logger.error(f"Failed to upload {file_path.name} to R2: {e}")
            return None

    @staticmethod
    def cleanup_local_files(*file_paths: Optional[Path]) -> None:
        """
        Deletes local temporary video and subtitle files immediately after R2/YouTube upload
        to save disk space on the headless server.
        """
        for fp in file_paths:
            if fp and isinstance(fp, Path) and fp.exists():
                try:
                    fp.unlink()
                    logger.debug(f"Deleted local temporary file: {fp.name}")
                except Exception as e:
                    logger.warning(f"Could not delete local file {fp}: {e}")
