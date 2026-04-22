# Admin Reports, Audit Logs, and System Limits Guide

## Purpose
This guide explains daily reports, audit logs, UHID identifiers, and the fixed operational limits built into the Doctor-Patient Appointment Management System.

## Daily Reports
- A daily report is generated for a specific calendar date via GET /reports/{report_date}.
- Reports are only valid for past or current dates. Future-dated reports are not allowed.
- Admins receive a full-scope report across all doctors.
- Doctors receive a report scoped to their own appointments only.
- Report metrics include:
  - Total appointments scheduled
  - Completed appointments
  - Cancelled appointments
  - No-show appointments
  - Slot utilization rate
  - Queue activity summary

## AI-Assisted Report Summaries
- The LLM assistant can generate a natural-language summary of a daily report.
- The summary is grounded in the actual report data and does not invent metrics.
- AI-generated summaries are advisory and should be reviewed by the admin or doctor before acting on them.

## Audit Logs
- The system maintains an audit log of significant operational actions.
- Audit logs can be retrieved via GET /reports/audit/logs.
- Only admins may access audit logs.
- Audit entries record who performed what action, on which resource, and at what time.
- Audit logs should be reviewed if data inconsistencies or unauthorized changes are suspected.

## UHID (Unique Hospital Identifier)
- Every patient and doctor registered in the system is assigned a UHID at registration.
- The UHID is a unique, system-generated identifier that serves as the preferred hospital-facing ID for the patient or doctor.
- Patients and doctors may log in using their UHID, internal ID, or registered email address.
- The UHID should be used when referencing a patient or doctor in clinical or administrative communications.
- If a patient or doctor loses their ID, the UHID is the most reliable identifier to look up their record.

## Slot and Scheduling Limits
- Valid slot durations are: 10, 15, 20, or 30 minutes only. No other durations are accepted.
- The default slot duration if not otherwise configured is 15 minutes.
- Default working hours if not otherwise configured are 09:00 to 17:00.
- The lunch break is blocked from 13:00 to 13:30 every day. Slots in this window cannot be booked.
- Weekends (Saturday and Sunday) are not valid appointment days. Weekend bookings are rejected.
- Past-date appointments are not allowed.
- When a new doctor is registered, the system auto-generates available slots for the next 7 weekdays.
- If a doctor has no manually set availability, the system uses the specialization-level default work hours.

## Reschedule Limits
- A patient is allowed a maximum of 2 reschedules per appointment.
- After 2 reschedules, no further rescheduling is permitted for that appointment.
- If a patient needs to change their appointment beyond the limit, they must cancel and book a new appointment.

## Slot Search Window
- When looking for the next available slot for a doctor, the system searches up to 14 days ahead.
- If no available slot is found within 14 days, the system reports that no slot is available.

## Specialization Consultation Durations
- Each medical specialization has a default consultation duration:
  - General Physician: 10 minutes
  - Cardiologist: 20 minutes
  - Dermatologist: 15 minutes
  - Neurologist: 20 minutes
  - Orthopedist: 15 minutes
  - Pediatrician: 15 minutes
  - Psychiatrist: 30 minutes
  - Gynecologist: 20 minutes
  - ENT Specialist: 15 minutes
  - Ophthalmologist: 15 minutes
- Individual doctors can override these defaults with their own work start and end times.

## Specialization Default Work Hours
- Each specialization has default work hours if a doctor has not set custom hours:
  - General Physician: 09:00–17:00
  - Cardiologist: 09:00–16:00
  - Dermatologist: 10:00–17:00
  - Neurologist: 09:00–16:00
  - Orthopedist: 08:00–15:00
  - Pediatrician: 09:00–17:00
  - Psychiatrist: 10:00–18:00
  - Gynecologist: 09:00–16:00
  - ENT Specialist: 09:00–16:00
  - Ophthalmologist: 09:00–16:00

## JWT and Session Policy
- User sessions are issued as JWT tokens with a default expiry of 60 minutes.
- After expiry, the user must log in again to obtain a new token.
- In production, the JWT_SECRET must be changed from the default placeholder value. The system will refuse to start in production mode if the secret is not set.

## Health Check
- The system exposes a GET /health endpoint.
- It reports connectivity status for Postgres, MongoDB, LLM (Groq), RAG (pgvector), and G-Suite.
- Use /health to verify the system is fully operational before processing patients.
