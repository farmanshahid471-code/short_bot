"""
uploader.py - YouTube Data API v3 integration for uploading Shorts,
automatic catchy title/description/tag generation, and strict 10-upload/24h quota enforcement.
"""
import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from .config import (
    YOUTUBE_CLIENT_SECRET_FILE,
    YOUTUBE_TOKEN_FILE,
    YOUTUBE_API_SERVICE_NAME,
    YOUTUBE_API_VERSION,
    YOUTUBE_SCOPES,
    MAX_DAILY_UPLOADS,
    logger,
)
from .models import StateDB


class YouTubeUploader:
    """
    Handles OAuth 2.0 authentication and resumable uploads to YouTube via Data API v3.
    Automatically generates SEO-optimized Shorts titles, descriptions, and tags.
    Strictly enforces the 10 upload/24h channel limit.
    """
    def __init__(
        self,
        client_secret_file: Path = YOUTUBE_CLIENT_SECRET_FILE,
        token_file: Path = YOUTUBE_TOKEN_FILE,
        state_db: Optional[StateDB] = None
    ):
        self.client_secret_file = client_secret_file
        self.token_file = token_file
        self.state_db = state_db if state_db else StateDB()
        self.youtube_service: Optional[Resource] = None

    @staticmethod
    def _run_auth_flow(flow) -> Credentials:
        """
        Runs the OAuth local-server flow BUT logs the authorization URL first,
        so if the browser tab does not open automatically you can copy the URL
        into Chrome manually. Also opens the browser when possible.
        """
        import socket
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import urlparse, parse_qs

        # Pick a free localhost port
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        flow.redirect_uri = f"http://localhost:{port}/"
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent select_account",  # ALWAYS show the Google account chooser
        )
        logger.info("🔐 Opening browser for Google login...")
        logger.info("   If a browser tab did NOT open, copy this URL into Chrome manually:")
        logger.info(f"   {auth_url}")
        try:
            webbrowser.open(auth_url)
        except Exception as e:
            logger.warning(f"   Could not auto-open the browser ({e}). Open the URL above manually.")

        result: dict = {}

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                params = parse_qs(urlparse(self.path).query)
                result["code"] = params.get("code", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    ("<html><body><h3 style='font-family:sans-serif'>"
                     "&#9989; Auth successful! "
                     "You can close this tab and go back to the bot panel.</h3></body></html>")
                    .encode("utf-8")
                )

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", port), _Handler)
        server.timeout = 300
        try:
            while not result.get("code"):
                server.handle_request()
        except Exception:
            pass
        finally:
            server.server_close()

        code = result.get("code")
        if not code:
            raise RuntimeError(
                "OAuth flow timed out - no authorization code received. "
                "Run Connect again and complete the login in the browser."
            )
        flow.fetch_token(code=code)
        return flow.credentials

    def _get_authenticated_service(self) -> Optional[Resource]:
        """
        Authenticates with YouTube Data API v3 using OAuth2.
        Loads existing token.json or initiates InstalledAppFlow if interactive.
        """
        if self.youtube_service:
            return self.youtube_service

        logger.info(f"🔑 Auth for this tab uses token file: {self.token_file}")
        creds = None
        if self.token_file.is_file():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_file), YOUTUBE_SCOPES)
            except Exception as e:
                logger.warning(f"Could not read existing OAuth token {self.token_file}: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube OAuth token...")
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.error(f"Failed to refresh OAuth token: {e}")
                    creds = None
            
            if not creds:
                if not self.client_secret_file.is_file():
                    logger.warning(
                        f"YouTube OAuth client_secret file '{self.client_secret_file}' not found. "
                        "YouTube uploads will run in DRY-RUN mode."
                    )
                    return None
                logger.info("Starting OAuth authorization flow...")
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.client_secret_file), YOUTUBE_SCOPES
                    )
                    creds = self._run_auth_flow(flow)
                except Exception as e:
                    logger.error(f"OAuth flow failed: {e}")
                    return None

            # Save token for next runs
            try:
                with open(self.token_file, "w", encoding="utf-8") as token_fp:
                    token_fp.write(creds.to_json())
                logger.info(f"Saved new OAuth token to {self.token_file}")
            except Exception as e:
                logger.warning(f"Could not write OAuth token to {self.token_file}: {e}")

        try:
            self.youtube_service = build(
                YOUTUBE_API_SERVICE_NAME,
                YOUTUBE_API_VERSION,
                credentials=creds,
                cache_discovery=False
            )
            logger.info("Connected to YouTube Data API v3 successfully.")
            return self.youtube_service
        except Exception as e:
            logger.error(f"Failed to build YouTube service client: {e}")
            return None

    @staticmethod
    def _verify_channel(service, expected: str) -> tuple:
        """
        Checks that the authenticated Google account actually owns the channel
        this tab EXPECTS to upload to. Returns (ok: bool, actual_titles: str).
        A token belongs to ONE Google account; that account can only upload to
        its own channel(s) - so if the login is for the wrong account, this
        catches it BEFORE a video goes to the wrong channel.
        """
        try:
            resp = service.channels().list(part="snippet", mine=True).execute()
            items = resp.get("items") or []
            titles = [str(i.get("snippet", {}).get("title", "")) for i in items]
            actual = ", ".join(t for t in titles if t) or "(no channel)"
            exp = str(expected or "").strip().lower()
            for t in titles:
                tl = t.strip().lower()
                if tl and (tl == exp or exp in tl or tl in exp):
                    return True, actual
            return False, actual
        except Exception as e:
            logger.warning(f"Channel safety check could not run ({e}) - allowing upload.")
            return True, ""

    @staticmethod
    def generate_short_metadata(
        original_title: str,
        original_url: str = "",
        channel_name: str = "",
        part_label: Optional[str] = None,
        info: Optional[Dict[str, Any]] = None,
        transcript_text: str = "",
        extra_hashtags: str = "",
        title_prefix: Optional[str] = None,
        title_hashtags: str = "",
        smart_titles: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Builds the Short title (prefix + video title + the user's Title Hashtags),
        description, and tags. Smart titles (when enabled) adds content tags to
        the description from the video's metadata + CPU transcription - free.
        """
        from .hashtags import build_hashtags, make_catchy_title, make_description

        if info is None:
            info = {"title": original_title}

        catchy_title = make_catchy_title(
            info=info,
            transcript_text=transcript_text,
            extra_hashtags=extra_hashtags,
            part_label=part_label or "",
            title_prefix=title_prefix,
            title_hashtags=title_hashtags,
            smart_titles=smart_titles,
        )
        final_tags = build_hashtags(
            info=info,
            transcript_text=transcript_text,
            extra_hashtags=extra_hashtags,
            smart_titles=smart_titles,
            title_hashtags=title_hashtags,
        )
        description = make_description(original_title, original_url, final_tags)

        # YouTube API tags field: max 500 bytes total - cap length.
        tags = [t.lstrip("#") for t in final_tags]
        if channel_name:
            # Only a CLEAN channel name/handle may become a tag - NEVER the
            # source channel URL (invisible junk in the API + reveals the source).
            ch = str(channel_name).strip()
            ch = ch.split("/")[-1].lstrip("@").strip()  # last path segment, no @
            if ch and not ch.lower().startswith("http") and len(ch) <= 40:
                tags.append(ch)
        # dedupe + trim to stay under the byte limit
        seen, capped = set(), []
        for t in tags:
            t = t.strip()
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                capped.append(t)
            if len(",".join(capped)) > 480:
                break
        tags = capped

        return {
            "title": catchy_title,
            "description": description,
            "tags": tags,
            "categoryId": "24",  # Entertainment category
        }

    def upload_short(
        self,
        video_path: Path,
        original_video_id: str,
        original_title: str,
        original_url: str = "",
        channel_name: str = "",
        part_label: Optional[str] = None,
        account: str = "",
        account_max_daily: Optional[int] = None,
        info: Optional[Dict[str, Any]] = None,
        transcript_text: str = "",
        extra_hashtags: str = "",
        title_prefix: Optional[str] = None,
        title_hashtags: str = "",
        smart_titles: Optional[bool] = None,
        expected_channel: Optional[str] = None
    ) -> Optional[str]:
        """
        Uploads the processed vertical video as a YouTube Short to the channel
        owned by `account`. Enforces that account's upload quota (default 10/24h).
        If `expected_channel` is set, the upload is BLOCKED when the connected
        Google login's channel does not match it (wrong-channel protection).

        Returns the new YouTube Short video ID if successful, or None.
        """
        max_daily = account_max_daily if account_max_daily else MAX_DAILY_UPLOADS

        # 1. Enforce this account's upload quota
        can_upload, remaining_slots = self.state_db.can_upload_today(
            max_daily_uploads=max_daily, account=account
        )
        if not can_upload:
            logger.warning(
                f"Upload cap ({max_daily}/24h) reached for account '{account}'! "
                f"Skipping YouTube upload for '{original_title}'. Video is safely saved in R2 "
                f"and will be queued for the next 24h upload window."
            )
            return "QUOTA_LIMIT_REACHED"

        logger.info(f"YouTube 24h upload quota check passed for '{account}' ({remaining_slots} slots remaining today).")

        service = self._get_authenticated_service()

        # ---- CHANNEL SAFETY LOCK ----
        # Never upload to the wrong channel: if the tab declares which channel
        # it should post to, verify the connected login really owns it.
        if service and expected_channel:
            ch_ok, actual = self._verify_channel(service, expected_channel)
            if not ch_ok:
                logger.error(
                    f"🚫 CHANNEL SAFETY LOCK for account '{account}': this Google login "
                    f"belongs to channel(s) '{actual}', but this tab expects "
                    f"'{expected_channel}'. Upload BLOCKED - connect this tab with the "
                    f"Google account that owns '{expected_channel}'."
                )
                return None

        metadata = self.generate_short_metadata(
            original_title=original_title,
            original_url=original_url,
            channel_name=channel_name,
            part_label=part_label,
            info=info,
            transcript_text=transcript_text,
            extra_hashtags=extra_hashtags,
            title_prefix=title_prefix,
            title_hashtags=title_hashtags,
            smart_titles=smart_titles,
        )

        if not service:
            logger.info(
                f"[DRY-RUN] Simulated YouTube Short upload:\n"
                f"  Title: {metadata['title']}\n"
                f"  File : {video_path.name}"
            )
            # In dry-run mode, return a synthetic ID so pipeline testing works
            mock_id = f"mock_short_{original_video_id}"
            self.state_db.record_upload(original_video_id, mock_id, account=account)
            return mock_id

        logger.info(f"Uploading '{metadata['title']}' to YouTube Shorts...")

        body = {
            "snippet": {
                "title": metadata["title"],
                "description": metadata["description"],
                "tags": metadata["tags"],
                "categoryId": metadata["categoryId"],
            },
            "status": {
                "privacyStatus": "public",  # Can be set to 'unlisted' or 'public'
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024 * 5  # 5 MB chunks
        )

        try:
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.info(f"YouTube upload progress: {int(status.progress() * 100)}%")

            short_id = response.get("id")
            logger.info(f"YouTube Short upload complete! Video ID: {short_id}")
            logger.info(f"Watch live at: https://www.youtube.com/shorts/{short_id}")

            self.state_db.record_upload(original_video_id, short_id, account=account)
            return short_id

        except HttpError as e:
            if e.resp.status in [403, 429]:
                logger.error(
                    f"YouTube API quota/rate-limit error ({e.resp.status}): {e.content}. "
                    "Bot will pause uploads and resume in the next cycle."
                )
                return "QUOTA_LIMIT_REACHED"
            logger.error(f"YouTube API HttpError during upload: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error uploading to YouTube: {e}")
            return None


def resolve_credentials(acc):
    """
    Returns (client_secret_path, token_path) for an account dict.

    THE WRONG-CHANNEL BUG (v6.2): accounts created without a token path used to
    fall back to the bot-ROOT token.json - which belongs to whichever channel
    was connected LAST (e.g. Simpson Pimp). Every new tab silently connected to
    that channel. Rules now:
      - named account (multi-account mode): token ALWAYS resolves to
        accounts/<name>/token.json. Missing file = fresh Google login for THIS
        account, never the root token.
      - client_secret: the account's own file when it exists; falls back to the
        bot-root client_secret.json otherwise - that IS safe (a client secret is
        not channel-bound; the login decides which channel gets connected).
      - only the legacy single-account mode (no accounts.json / no name) uses
        the bot-root token.json.
    """
    from .config import BASE_DIR, YOUTUBE_CLIENT_SECRET_FILE, YOUTUBE_TOKEN_FILE
    if not acc:
        return YOUTUBE_CLIENT_SECRET_FILE, YOUTUBE_TOKEN_FILE

    name = str(acc.get("name") or "").strip()
    per_acc_dir = BASE_DIR / "accounts" / name.lower() if name else None
    per_acc_cs = per_acc_dir / "client_secret.json" if per_acc_dir else None
    per_acc_tk = per_acc_dir / "token.json" if per_acc_dir else None

    # client secret: own file > per-account path (even if missing, so the next
    # Connect stores it there) > bot root (safe fallback)
    raw_cs = str(acc.get("client_secret") or "").strip()
    if raw_cs:
        p = Path(raw_cs)
        p = p if p.is_absolute() else BASE_DIR / p
        cs = p
    elif per_acc_cs is not None:
        cs = per_acc_cs
    else:
        cs = YOUTUBE_CLIENT_SECRET_FILE

    # token: own file > per-account path (MISSING is fine - triggers fresh
    # login) > bot root ONLY for unnamed/legacy accounts.
    raw_tk = str(acc.get("token") or "").strip()
    if raw_tk:
        p = Path(raw_tk)
        p = p if p.is_absolute() else BASE_DIR / p
        tk = p
    elif per_acc_tk is not None:
        tk = per_acc_tk
    else:
        tk = YOUTUBE_TOKEN_FILE

    return cs, tk
