# =============================================================================
# features/gsuite/gmail_service.py
# Send transactional emails via Gmail API (appointment confirmations, etc.)
# Sends from: meghashyam2005@gmail.com (OAuth2 authenticated user)
# =============================================================================
from __future__ import annotations

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from features.gsuite.auth import build_service

logger = logging.getLogger(__name__)


class GmailService:
    """Send transactional emails via the Gmail API."""

    def __init__(self):
        self._service = build_service("gmail", "v1")
        if not self._service:
            logger.warning("Gmail service unavailable — emails will be skipped")

    @property
    def is_available(self) -> bool:
        return self._service is not None

    def send_email(
        self, to: str, subject: str, body_html: str, from_name: str = "MediFlow HMS"
    ) -> Optional[dict]:
        """Send an HTML email via Gmail API.

        Returns the Gmail message dict or None on failure.
        """
        if not self._service:
            logger.warning(f"Gmail unavailable — skipping email to {to}")
            return None

        try:
            message = MIMEMultipart("alternative")
            message["to"] = to
            message["subject"] = subject
            message["from"] = from_name
            message.attach(MIMEText(body_html, "html"))

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = self._service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            logger.info(f"Email sent to {to}: message_id={result.get('id')}")
            return result
        except Exception as exc:
            logger.error(f"Failed to send email to {to}: {exc}")
            return None

    # =========================================================================
    # Convenience methods for standard hospital notifications
    # =========================================================================

    def send_appointment_confirmation(self, patient_email: str, details: dict) -> Optional[dict]:
        """Send appointment booking confirmation."""
        subject = f"✅ Appointment Confirmed — Dr. {details.get('doctor_name', 'N/A')}"
        body = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #1f7a78, #226b8a); padding: 24px; border-radius: 16px 16px 0 0;">
                <h1 style="color: #fff; margin: 0; font-size: 1.4rem;">⚕ MediFlow HMS</h1>
                <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Appointment Confirmation</p>
            </div>
            <div style="background: #fff; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 16px 16px;">
                <p>Dear <strong>{details.get('patient_name', 'Patient')}</strong>,</p>
                <p>Your appointment has been successfully booked:</p>
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                    <tr><td style="padding: 8px; color: #6b7280;">Doctor</td><td style="padding: 8px;"><strong>Dr. {details.get('doctor_name', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Date</td><td style="padding: 8px;"><strong>{details.get('date', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Time</td><td style="padding: 8px;"><strong>{details.get('time', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Queue Position</td><td style="padding: 8px;"><strong>{details.get('queue_position', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Appointment ID</td><td style="padding: 8px; font-family: monospace;">{details.get('appointment_id', 'N/A')}</td></tr>
                </table>
                <p style="color: #6b7280; font-size: 0.9rem;">Please arrive 15 minutes early for triage and vitals check.</p>
            </div>
        </div>
        """
        return self.send_email(patient_email, subject, body)

    def send_cancellation_notice(self, patient_email: str, details: dict) -> Optional[dict]:
        """Send appointment cancellation notice."""
        subject = f"❌ Appointment Cancelled — {details.get('date', '')}"
        body = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #dc2626; padding: 24px; border-radius: 16px 16px 0 0;">
                <h1 style="color: #fff; margin: 0; font-size: 1.4rem;">⚕ MediFlow HMS</h1>
                <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Appointment Cancellation</p>
            </div>
            <div style="background: #fff; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 16px 16px;">
                <p>Dear <strong>{details.get('patient_name', 'Patient')}</strong>,</p>
                <p>Your appointment has been cancelled:</p>
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                    <tr><td style="padding: 8px; color: #6b7280;">Doctor</td><td style="padding: 8px;">Dr. {details.get('doctor_name', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Date</td><td style="padding: 8px;">{details.get('date', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Reason</td><td style="padding: 8px;">{details.get('reason', 'Not specified')}</td></tr>
                </table>
                <p style="color: #6b7280; font-size: 0.9rem;">Please contact the front desk if you need to rebook.</p>
            </div>
        </div>
        """
        return self.send_email(patient_email, subject, body)

    def send_reschedule_notice(self, patient_email: str, details: dict) -> Optional[dict]:
        """Send appointment reschedule notice."""
        subject = f"🔄 Appointment Rescheduled — Dr. {details.get('doctor_name', 'N/A')}"
        body = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #f59e0b; padding: 24px; border-radius: 16px 16px 0 0;">
                <h1 style="color: #fff; margin: 0; font-size: 1.4rem;">⚕ MediFlow HMS</h1>
                <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Appointment Rescheduled</p>
            </div>
            <div style="background: #fff; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 16px 16px;">
                <p>Dear <strong>{details.get('patient_name', 'Patient')}</strong>,</p>
                <p>Your appointment has been rescheduled:</p>
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                    <tr><td style="padding: 8px; color: #6b7280;">Doctor</td><td style="padding: 8px;">Dr. {details.get('doctor_name', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">New Date</td><td style="padding: 8px;"><strong>{details.get('new_date', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">New Time</td><td style="padding: 8px;"><strong>{details.get('new_time', 'N/A')}</strong></td></tr>
                </table>
            </div>
        </div>
        """
        return self.send_email(patient_email, subject, body)

    def send_registration_success(self, recipient_email: str, details: dict) -> Optional[dict]:
        """Send role registration success notice after the record is stored."""
        role_label = details.get("role_label", "User")
        subject = f"✅ {role_label} Registration Successful — MediFlow HMS"
        body = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #1f7a78, #226b8a); padding: 24px; border-radius: 16px 16px 0 0;">
                <h1 style="color: #fff; margin: 0; font-size: 1.4rem;">⚕ MediFlow HMS</h1>
                <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Registration Successful</p>
            </div>
            <div style="background: #fff; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 16px 16px;">
                <p>Dear <strong>{details.get('full_name', 'User')}</strong>,</p>
                <p>Your {role_label.lower()} registration has been successfully completed and stored in MediFlow HMS.</p>
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                    <tr><td style="padding: 8px; color: #6b7280;">Name</td><td style="padding: 8px;"><strong>{details.get('full_name', 'N/A')}</strong></td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Email</td><td style="padding: 8px;">{details.get('email', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">Mobile</td><td style="padding: 8px;">{details.get('mobile', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">System ID</td><td style="padding: 8px; font-family: monospace;">{details.get('entity_id', 'N/A')}</td></tr>
                    <tr><td style="padding: 8px; color: #6b7280;">UHID</td><td style="padding: 8px; font-family: monospace;">{details.get('uhid', 'N/A')}</td></tr>
                </table>
                <p style="color: #6b7280; font-size: 0.9rem;">Initial password: your registered mobile number. Please change it after your first sign-in.</p>
            </div>
        </div>
        """
        return self.send_email(recipient_email, subject, body)


# Module-level singleton (lazy)
_gmail: Optional[GmailService] = None


def get_gmail() -> GmailService:
    """Get or create the Gmail service singleton."""
    global _gmail
    if _gmail is None:
        _gmail = GmailService()
    return _gmail
