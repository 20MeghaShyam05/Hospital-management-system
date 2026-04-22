# Admin G-Suite Integration and Nurse Management Guide

## Purpose
This guide covers Google Workspace integrations, nurse management, and front-desk role operations in the Doctor-Patient Appointment Management System.

## Nurse Registration and Management
- Only admins may register new nurses in the system.
- Nurse registration requires the nurse's full name, contact details, and role assignment.
- Registered nurses can be listed and retrieved by nurse ID.
- Nurses have access to: recording triage vitals, booking appointments, registering patients, viewing patient data, and viewing all patient lists.
- Nurses may not register doctors, manage schedules, or generate reports.

## Front-Desk Role
- The front-desk role is intended for reception staff who handle patient-facing operations.
- Front-desk staff may: register patients, book appointments on behalf of patients, and view patient records.
- Front-desk staff may not register doctors or nurses, manage slot availability, or generate reports.
- The default front-desk credentials are configured at system level and must be changed before going to production.

## Google Forms Sync
- The system can automatically sync patient appointment bookings submitted through a configured Google Form.
- The Google Form is linked via the GOOGLE_FORMS_SPREADSHEET_ID setting.
- When a form response is submitted, the system reads the patient details and attempts to book an appointment automatically.
- A background sync job runs at a configurable interval (default: every 300 seconds).
- Admins can manually trigger a sync from the G-Suite section or via the API endpoint POST /gsuite/forms/sync.
- Admins can view sync statistics at GET /gsuite/forms/stats.
- If GOOGLE_FORMS_SPREADSHEET_ID is not set, the sync is disabled and a log message is recorded at startup.

## Gmail Email Notifications
- The system can send emails via Gmail using the configured sender address (GMAIL_SENDER_EMAIL).
- Email sending requires OAuth2 Google credentials to be configured (credentials.json or token.json).
- Admins can trigger email sending via POST /gsuite/email/send with a recipient, subject, and body.
- Email notifications are non-blocking; if email sending fails, it does not interrupt the core booking workflow.

## Google Drive File Management
- The system uploads files to a configured Google Drive folder (GOOGLE_DRIVE_FOLDER_ID).
- Uploaded files are automatically shared with the patient's registered email address so they appear in "Shared with me".
- Admins can upload any file to Drive via POST /gsuite/drive/upload.
- Admins can save a patient record as a PDF to Drive via POST /gsuite/drive/patient-save.
- Existing Drive files can be listed via GET /gsuite/drive/files.
- If the Google Drive folder ID is not configured, uploads will fail with a configuration error.
- Drive connectivity can be verified via GET /gsuite/drive/ping.

## Google Calendar Integration
- The system can create calendar events for appointments via POST /gsuite/calendar/event.
- Calendar events are linked to the configured Google Calendar ID (default: "primary").
- Events can be cancelled via DELETE /gsuite/calendar/event/{event_id}.
- Upcoming calendar events can be listed via GET /gsuite/calendar/upcoming.
- Calendar integration requires valid Google OAuth2 credentials.

## G-Suite Configuration Requirements
- All G-Suite features require valid Google credentials (OAuth2 or service account).
- The credentials file path is set via GOOGLE_CREDENTIALS_FILE (default: credentials.json).
- The token file is set via GOOGLE_TOKEN_FILE (default: token.json).
- If credentials are missing or expired, G-Suite endpoints will fail gracefully without affecting core booking operations.
- Admins should re-authenticate when token expiry errors appear.

## G-Suite Health Check
- The /health endpoint reports gsuite_connected as true if GOOGLE_FORMS_SPREADSHEET_ID or GOOGLE_DRIVE_FOLDER_ID is configured.
- A true gsuite_connected status means the configuration values are present, not that authentication is valid.
- Run GET /gsuite/drive/ping to confirm live Drive connectivity.
