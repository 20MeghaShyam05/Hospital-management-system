# =============================================================================
# features/gsuite/drive_service.py
# Upload, download, and list patient documents on Google Drive
# =============================================================================
from __future__ import annotations

import io
import logging
from typing import Optional

from config import settings
from features.gsuite.auth import build_service

logger = logging.getLogger(__name__)


class DriveService:
    """Manage patient documents on Google Drive."""

    def __init__(self):
        self._service = build_service("drive", "v3")
        self._folder_id = settings.GOOGLE_DRIVE_FOLDER_ID
        if not self._service:
            logger.warning("Google Drive service unavailable")

    @property
    def is_available(self) -> bool:
        return self._service is not None and bool(self._folder_id)

    def upload_file(
        self,
        file_content: bytes,
        filename: str,
        mime_type: str = "application/pdf",
        subfolder: Optional[str] = None,
    ) -> Optional[dict]:
        """Upload a file to the MediFlow Drive folder.

        Args:
            file_content: Raw file bytes.
            filename: Name for the uploaded file.
            mime_type: MIME type of the file.
            subfolder: If provided, creates/reuses a subfolder (e.g. patient ID).

        Returns dict with {id, name, webViewLink} or None on failure.
        """
        if not self.is_available:
            logger.warning("Drive unavailable — skipping upload")
            return None

        try:
            from googleapiclient.http import MediaIoBaseUpload

            folder_id = self._folder_id
            if subfolder:
                folder_id = self._ensure_subfolder(subfolder)

            metadata = {"name": filename, "parents": [folder_id]}
            media = MediaIoBaseUpload(
                io.BytesIO(file_content), mimetype=mime_type, resumable=True
            )

            file = self._service.files().create(
                body=metadata, media_body=media, fields="id, name, webViewLink"
            ).execute()

            logger.info(f"Uploaded to Drive: {file['name']} ({file['id']})")
            return file
        except Exception as exc:
            logger.error(f"Drive upload failed: {exc}")
            return None

    def download_file(self, file_id: str) -> Optional[bytes]:
        """Download a file from Drive by its file ID."""
        if not self._service:
            return None
        try:
            from googleapiclient.http import MediaIoBaseDownload

            request = self._service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buffer.getvalue()
        except Exception as exc:
            logger.error(f"Drive download failed ({file_id}): {exc}")
            return None

    def list_files(self, patient_id: Optional[str] = None) -> list[dict]:
        """List files in the MediFlow Drive folder.

        If patient_id is given, searches inside that patient's subfolder.
        """
        if not self.is_available:
            return []

        try:
            folder = self._folder_id
            if patient_id:
                # Look for subfolder named after patient_id
                sub = self._find_subfolder(patient_id)
                if sub:
                    folder = sub

            query = f"'{folder}' in parents and trashed = false"
            results = self._service.files().list(
                q=query,
                fields="files(id, name, mimeType, webViewLink, createdTime, size)",
                orderBy="createdTime desc",
                pageSize=50,
                spaces="drive",
                corpora="user",
            ).execute()
            return results.get("files", [])
        except Exception as exc:
            logger.error(f"Drive list failed: {exc}")
            return []

    def _ensure_subfolder(self, name: str) -> str:
        """Create a subfolder if it doesn't exist; return its ID."""
        existing = self._find_subfolder(name)
        if existing:
            return existing

        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [self._folder_id],
        }
        folder = self._service.files().create(body=metadata, fields="id").execute()
        logger.info(f"Created Drive subfolder: {name} ({folder['id']})")
        return folder["id"]

    def share_file(self, file_id: str, email: str, role: str = "reader") -> bool:
        """Share a Drive file with a specific user by email.

        Args:
            file_id: The Drive file ID to share.
            email: The recipient's Google account email.
            role: Permission role — 'reader', 'commenter', or 'writer'.

        Returns True on success, False on failure.
        """
        if not self._service:
            return False
        try:
            self._service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
            ).execute()
            logger.info(f"Shared Drive file {file_id} with {email} as {role}")
            return True
        except Exception as exc:
            logger.error(f"Drive share failed ({file_id} → {email}): {exc}")
            return False

    def _find_subfolder(self, name: str) -> Optional[str]:
        """Find a subfolder by name; return its ID or None."""
        query = (
            f"name='{name}' and '{self._folder_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        results = self._service.files().list(
            q=query,
            fields="files(id)",
            spaces="drive",
            corpora="user",
        ).execute()
        files = results.get("files", [])
        return files[0]["id"] if files else None


# Module-level singleton (lazy)
_drive: Optional[DriveService] = None


def get_drive() -> DriveService:
    """Get or create the Drive service singleton."""
    global _drive
    if _drive is None:
        _drive = DriveService()
    return _drive


def reset_drive() -> None:
    """Reset the Drive service singleton (forces re-initialisation on next call)."""
    global _drive
    _drive = None
