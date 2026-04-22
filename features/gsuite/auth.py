# =============================================================================
# features/gsuite/auth.py
# Google API credential builders — OAuth2 (user) and Service Account (server)
# =============================================================================
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

_PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


@contextmanager
def _without_proxy_env():
    """Temporarily clear proxy env vars for Google API auth/network calls."""
    previous = {key: os.environ.pop(key, None) for key in _PROXY_ENV_KEYS}
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value


def get_oauth_credentials():
    """Get OAuth2 credentials with interactive login on first use.

    Caches the token to disk so subsequent calls are non-interactive.
    Returns None if credentials file is missing.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError:
        logger.warning("google-auth packages not installed — G-Suite disabled")
        return None

    creds_file = settings.GOOGLE_CREDENTIALS_FILE
    token_file = settings.GOOGLE_TOKEN_FILE

    if not os.path.exists(creds_file):
        logger.warning(f"Google credentials file not found: {creds_file}")
        return None

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        with _without_proxy_env():
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
                creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def get_service_account_credentials():
    """Get service account credentials for server-to-server calls (Forms/Sheets).

    Returns None if service account file is missing.
    """
    try:
        from google.oauth2 import service_account
    except ImportError:
        logger.warning("google-auth packages not installed — G-Suite disabled")
        return None

    sa_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    if not os.path.exists(sa_file):
        logger.warning(f"Service account file not found: {sa_file}")
        return None

    return service_account.Credentials.from_service_account_file(
        sa_file, scopes=SCOPES,
    )


def build_service(api: str, version: str, use_service_account: bool = False):
    """Build a Google API service client.

    Args:
        api: API name (e.g. 'gmail', 'drive', 'calendar', 'sheets')
        version: API version (e.g. 'v1', 'v3', 'v4')
        use_service_account: If True, use service account; otherwise OAuth2.

    Returns the service object or None if credentials are unavailable.
    """
    try:
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2
    except ImportError:
        logger.warning("google-api-python-client not installed — G-Suite disabled")
        return None

    creds = get_service_account_credentials() if use_service_account else get_oauth_credentials()
    if not creds:
        return None

    with _without_proxy_env():
        http = AuthorizedHttp(creds, http=httplib2.Http())
        return build(api, version, http=http)
