# Doctor Workflow Manual

## Purpose
This manual explains doctor-facing system rules for schedule management, appointment visibility, queue handling, and reporting access.

## Doctor Account Policy
- A doctor may log in using doctor ID, doctor UHID, or registered email.
- The initial doctor password is the registered mobile number until changed.
- Doctors should change the initial password after first login.
- A doctor may access only their own doctor scope, appointments, queue, and reports.

## Availability and Slot Management Policy
- Doctor availability must be set for a valid weekday date.
- Availability windows must have a valid start time, end time, and approved slot duration.
- Duplicate availability for the same doctor and date is not allowed.
- Auto-generated slots are created from the doctor's default work hours and consultation duration.
- Lunch-break slots are blocked by business rules and cannot be booked.

## Appointment Scope Policy
- A doctor may view appointments assigned only to that doctor account.
- Doctors may inspect appointment details but should not edit unrelated doctor records.
- Rescheduling must remain within the same doctor scope under system policy.

## Queue Management Policy
- Emergency appointments must be prioritized above normal appointments.
- The doctor or authorized workflow may call the next patient from the queue.
- Queue states should move in a controlled flow: waiting, in-progress, completed, no-show, or cancelled.
- A doctor may mark an appointment completed after the consultation is finished.
- If a patient fails to appear, the appointment may be marked as no-show.

## Clinical Documentation and AI Safety Policy
- The AI assistant may help explain workflows, summarize rules, and suggest general routing.
- The AI assistant must not replace professional medical judgment.
- Doctors remain responsible for all clinical decisions.
- AI-generated summaries must be validated by the doctor before use in clinical communication.

## Reporting Policy
- Doctors may access report summaries limited to their own reporting scope.
- Reports reflect appointment counts, completion counts, cancellations, no-shows, utilization, and queue activity.
- Future-dated reports are not valid operational reports.

## Operational Escalation Policy
- System outages, schedule generation issues, and queue inconsistencies should be escalated to admin.
- If appointment or queue data appears inconsistent, the doctor should avoid manual assumptions and notify admin support.
