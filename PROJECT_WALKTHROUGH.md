# DPAMS — Full Project Walkthrough

**Doctor-Patient Appointment Management System**
FastAPI + Streamlit | PostgreSQL + MongoDB | Groq LLM + Gemini RAG

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Server Startup Flow](#2-server-startup-flow)
3. [Authentication & RBAC](#3-authentication--rbac)
4. [Patient Registration](#4-patient-registration)
5. [Doctor Registration & Slot Auto-Generation](#5-doctor-registration--slot-auto-generation)
6. [Appointment Booking (Thread-Safe)](#6-appointment-booking-thread-safe)
7. [Cancel & Reschedule](#7-cancel--reschedule)
8. [Nurse Registration & Triage](#8-nurse-registration--triage)
9. [Prescriptions](#9-prescriptions)
10. [Queue Management](#10-queue-management)
11. [Reports & Data Science Analytics](#11-reports--data-science-analytics)
12. [Audit Logs](#12-audit-logs)
13. [LLM Features — Detailed](#13-llm-features--detailed)
    - 13.1 [Symptom Explainer](#131-symptom-explainer)
    - 13.2 [Report Summary (Admin)](#132-report-summary-admin)
    - 13.3 [Health Summary (Patient)](#133-health-summary-patient)
    - 13.4 [Patient Chat with RAG](#134-patient-chat-with-rag)
    - 13.5 [Knowledge Reindex](#135-knowledge-reindex)
    - 13.6 [Agent Chat (Agentic AI)](#136-agent-chat-agentic-ai)
14. [Google Suite Integration](#14-google-suite-integration)
15. [Database Layer](#15-database-layer)
16. [Streamlit Frontend Flows](#16-streamlit-frontend-flows)
17. [Key Files Reference](#17-key-files-reference)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                  Streamlit Frontend                      │
│               streamlit_app.py                          │
│   HTTP calls to FastAPI via requests library            │
└────────────────────┬────────────────────────────────────┘
                     │  HTTP / REST
┌────────────────────▼────────────────────────────────────┐
│                  FastAPI Backend                         │
│            features/core/app.py                         │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ /auth    │ │/patients │ │/doctors  │ │/appts    │  │
│  │ /triage  │ │/prescr.. │ │/reports  │ │/llm      │  │
│  │ /queue   │ │/schedule │ │/gsuite   │ │/nurses   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │         BookingService (Central Orchestrator)     │  │
│  │    features/shared/services/booking_service.py   │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────┬──────────────┬───────────────┬───────────┘
              │              │               │
    ┌─────────▼──┐  ┌────────▼──┐  ┌────────▼──────────┐
    │ PostgreSQL │  │  MongoDB  │  │  Groq LLM API     │
    │(InMemory   │  │(InMemory  │  │  Gemini Embeddings│
    │ fallback)  │  │ fallback) │  │  pgvector RAG     │
    └────────────┘  └───────────┘  └───────────────────┘
```

**Roles:** SYSTEM | ADMIN | DOCTOR | PATIENT | NURSE | FRONT_DESK

**Feature slice structure:** Every feature lives in `features/<name>/` containing `router.py`, `service.py`, `contracts.py`.

---

## 2. Server Startup Flow

**Entry:** `uvicorn features.core.app:app --reload`

**File:** `features/core/app.py` → `lifespan()` async context manager

```
uvicorn starts
    └─ lifespan() runs
          ├─ PostgresManager()          → connects to Postgres (or falls back to InMemoryStore)
          ├─ MongoManager()             → connects to MongoDB (or falls back to InMemoryStore)
          ├─ ScheduleManager(db)        → slot query + auto-generation layer
          ├─ QueueManager(db, mongo)    → priority queue manager
          ├─ BookingService(db, mongo, schedule, queue)  → central service
          ├─ AuthService(db)            → login + JWT
          │
          ├─ Auto-regenerate weekly slots
          │     └─ list_doctors() → for each doctor:
          │           └─ schedule.auto_regenerate_weekly_slots(doctor)
          │                 → creates slots for next 7 weekdays if missing
          │
          └─ Start Google Forms background sync (if GOOGLE_FORMS_SPREADSHEET_ID set)
                └─ runs in background thread, syncs every 5 min
```

**Health Check:** `GET /health`
Returns status of: Postgres, MongoDB, LLM (Groq key present), RAG (all config), G-Suite.

---

## 3. Authentication & RBAC

### Login Flow

```
POST /auth/login
  Body: { identifier, password, role }
  │
  └─ features/auth/router.py → AuthModuleService.login()
        └─ features/shared/services/auth_service.py
              ├─ Check hardcoded admin/front_desk credentials (from config)
              ├─ OR look up doctor/patient/nurse by email or UHID in Postgres
              ├─ Verify bcrypt-hashed password
              └─ Create JWT token:
                    {
                      user_id, username, role, display_name,
                      linked_patient_id, linked_doctor_id,
                      exp: now + JWT_EXPIRE_MIN (default 60 min)
                    }
  Returns: { access_token, token_type: "bearer", user }
```

### Every Subsequent Request

```
Any protected endpoint
  └─ Depends(get_current_user)
        └─ features/core/dependencies.py → get_current_user()
              ├─ Extract Bearer token from Authorization header
              ├─ Decode JWT with JWT_SECRET
              ├─ Validate expiry
              └─ Return user dict (role, user_id, linked_patient_id, etc.)
```

### Role Enforcement

```python
# Hard role block:
Depends(require_roles(Role.ADMIN))         # only admin
Depends(require_roles(Role.ADMIN, Role.DOCTOR))  # admin or doctor

# Scope check (can-you-see-this-record):
Depends(ensure_patient_scope)   # patient can only see own record
Depends(ensure_doctor_scope)    # doctor can only see own schedule
Depends(ensure_appointment_scope)  # RBAC on individual appointments
```

---

## 4. Patient Registration

```
POST /patients
  Body: { full_name, email, mobile, date_of_birth, gender, blood_group, address }
  Allowed roles: ADMIN, PATIENT, NURSE, FRONT_DESK
  │
  └─ features/patients/router.py
        └─ features/patients/service.py → PatientModuleService.register_patient()
              └─ features/shared/services/booking_service.py → register_patient()
                    │
                    ├─ [1] Check if email already exists in Postgres
                    │       IF exists:
                    │         update full_name, increment visit_count
                    │         return existing record (idempotent)
                    │
                    ├─ [2] Validate input via Patient model
                    │       features/shared/models/patient.py
                    │       Checks: name length, email format, mobile 10-digit, gender/blood_group enum
                    │
                    ├─ [3] Generate UHID
                    │       Format: HMS-PAT-YYYYMMDD-XXXXXX (uppercase hex)
                    │
                    ├─ [4] Hash password (bcrypt from mobile number)
                    │
                    ├─ [5] Upsert to Postgres patients table
                    │       ON CONFLICT (email) DO UPDATE (F4 — race condition safe)
                    │
                    ├─ [6] Send registration email (non-blocking thread)
                    │       → features/gsuite/gmail_service.py
                    │         send_registration_success(email, {...})
                    │
                    └─ [7] log_action decorator logs to MongoDB audit trail
                            event="patient_registered", actor=current_user_id
```

**Returns:** `{ patient_id, uhid, full_name, email, mobile, visit_count, ... }`

---

## 5. Doctor Registration & Slot Auto-Generation

```
POST /doctors
  Body: { full_name, email, mobile, specialization, max_patients_per_day,
          work_start_time, work_end_time, consultation_duration_minutes }
  Allowed roles: ADMIN
  │
  └─ features/doctors/router.py
        └─ features/doctors/service.py → DoctorModuleService.register_doctor()
              └─ booking_service.py → register_doctor()
                    │
                    ├─ [1] Check for existing doctor by email
                    │
                    ├─ [2] Validate via Doctor model
                    │       features/shared/models/doctor.py
                    │       Checks: specialization enum (10 valid values),
                    │               consultation_duration in [10,15,20,30] minutes
                    │
                    ├─ [3] Default work hours from config if not provided
                    │       e.g. Cardiology → 09:00–17:00
                    │
                    ├─ [4] Generate UHID: HMS-DOC-YYYYMMDD-XXXXXX
                    │
                    ├─ [5] Hash password from mobile number
                    │
                    ├─ [6] Upsert to Postgres doctors table
                    │
                    ├─ [7] Auto-generate slots for next 7 weekdays
                    │       └─ ScheduleManager.generate_weekly_slots(doctor)
                    │             for each weekday in next 7 days:
                    │               for each time window (work_start → work_end):
                    │                 skip lunch block (13:00–13:30, configured via LUNCH_START/LUNCH_END)
                    │                 create Slot object: { slot_id, doctor_id, date, start_time, end_time }
                    │                 upsert to Postgres slots table
                    │               end
                    │             end
                    │
                    ├─ [8] Send registration email
                    │
                    └─ [9] Audit log to MongoDB

Slot structure in Postgres:
  slot_id (UUID), doctor_id, date, start_time, end_time,
  is_booked (default false), is_blocked (default false)
```

### Getting Slots

```
GET /slots/{doctor_id}/{slot_date}
  └─ features/scheduling/router.py
        └─ ScheduleManager.get_available_slots(doctor_id, date)
              ├─ Query Postgres: slots WHERE doctor_id AND date AND NOT is_booked AND NOT is_blocked
              ├─ IF no slots found for that date:
              │     auto_regenerate → generate slots on-demand for that date
              └─ Returns list of available slots

GET /slots/{doctor_id}/{slot_date}/all      ← admin/doctor view (all slots incl. booked)
PATCH /slots/{slot_id}                      ← doctor blocks/unblocks a slot
```

---

## 6. Appointment Booking (Thread-Safe)

```
POST /appointments
  Body: { patient_id, doctor_id, slot_id, date, notes?, priority? }
  Allowed roles: PATIENT, FRONT_DESK, NURSE
  │
  └─ features/appointments/router.py
        ├─ RBAC: if role=PATIENT, patient can only book for own patient_id
        └─ features/appointments/service.py → AppointmentModuleService.book_appointment()
              └─ booking_service.py → book_appointment()
                    │
                    ├─ PRE-LOCK VALIDATIONS
                    │   ├─ Reject past dates (E9)
                    │   ├─ Reject weekends — must be Mon–Fri (E12)
                    │   ├─ Verify patient is active (R073)
                    │   └─ Verify doctor is active
                    │
                    ├─ ATOMIC SECTION  ← threading.Lock (F6)
                    │   ├─ Lock slot row in Postgres: SELECT FOR UPDATE
                    │   ├─ Validate slot.doctor_id == requested doctor_id
                    │   ├─ Validate slot.date == requested appointment_date
                    │   ├─ Reject if slot.is_booked == True  ← double-booking prevented (R071)
                    │   ├─ Reject if slot.is_blocked == True
                    │   ├─ Reject if slot falls in lunch block 13:00–13:30 (E8, server-enforced)
                    │   ├─ Mark slot as booked in Postgres
                    │   └─ INSERT appointment row in Postgres
                    │         { appointment_id, patient_id, doctor_id, slot_id,
                    │           date, start_time, end_time, status="booked",
                    │           priority, notes, booked_by, booked_at }
                    │
                    └─ POST-LOCK (non-critical, failures don't rollback booking)
                        ├─ store_analytics_snapshot() → MongoDB dpas_analytics_raw
                        ├─ Send confirmation email to patient + doctor (Gmail)
                        ├─ Create Google Calendar event
                        └─ log_action decorator → MongoDB audit trail

Returns: full AppointmentResponse with appointment_id, start_time, end_time, status
```

**Double-Booking Prevention (F6):**
Two concurrent requests for the same slot hit `threading.Lock`. The first gets the lock, checks, marks booked, and saves. The second sees `is_booked=True` and raises `ValueError("slot is not available")`.

---

## 7. Cancel & Reschedule

### Cancel

```
POST /appointments/{appointment_id}/cancel
  Body: { reason (min 10 chars), cancelled_by? }
  │
  └─ booking_service.cancel_appointment()
        ├─ Fetch appointment; verify status is "booked" or "rescheduled"
        ├─ Mark slot as unbooked (free for rebooking)
        ├─ Update appointment status → "cancelled"
        ├─ Invalidate schedule cache
        ├─ Remove from queue if enqueued
        ├─ Send cancellation email
        └─ Audit log
```

### Reschedule

```
POST /appointments/{appointment_id}/reschedule
  Body: { new_slot_id, new_date }
  │
  └─ booking_service.reschedule_appointment()
        ├─ Validate old appointment
        ├─ Enforce max reschedule limit (MAX_RESCHEDULES = 2 from config)
        ├─ Validate new slot (same checks as booking)
        ├─ Mark old slot → unbooked
        ├─ Mark new slot → booked
        ├─ Update appointment (new date, start_time, end_time, status="rescheduled")
        ├─ Update queue entry if patient is in queue
        ├─ Send reschedule confirmation email
        └─ Audit log
```

---

## 8. Nurse Registration & Triage

### Nurse Registration

```
POST /nurses
  Body: { full_name, email, mobile, ward?, shift? }
  Allowed roles: ADMIN
  │
  └─ booking_service.register_nurse()
        ├─ Validate via Nurse model (features/shared/models/nurse.py)
        ├─ Generate UHID: HMS-NRS-YYYYMMDD-XXXXXX
        ├─ Hash password from mobile
        ├─ Upsert to Postgres nurses table
        ├─ Send registration email
        └─ Audit log
```

### Triage (Recording Patient Vitals)

```
POST /triage
  Body: {
    patient_id, nurse_id, doctor_id, date,
    queue_type: "normal" | "emergency",
    appointment_id?,
    blood_pressure,      ← string "120/80"
    heart_rate,          ← integer bpm
    temperature,         ← float Celsius
    weight,              ← float kg
    oxygen_saturation,   ← float SpO2%
    symptoms, notes
  }
  Allowed roles: NURSE
  │
  └─ features/triage/router.py
        └─ booking_service.create_triage_entry()
              ├─ Validate patient, nurse, doctor exist
              ├─ If appointment_id provided:
              │     verify appointment date matches triage date
              │     verify appointment status is "booked" or "rescheduled"
              ├─ Validate vitals via Triage model
              │     features/shared/models/triage.py
              │     HR: 40–150, Temp: 35–42°C, SpO2: 85–100
              ├─ Save triage to Postgres triage table
              ├─ IF queue_type == "emergency":
              │     update appointment.priority → "emergency"
              │     QueueManager.enqueue(patient, priority=HIGH)
              │     MongoManager.enqueue_to_queue_state(...)
              └─ Audit log

GET /triage/patient/{patient_id}    ← history for a patient (RBAC)
GET /triage/date/{triage_date}      ← all triage for a date (nurse/doctor)
```

---

## 9. Prescriptions

```
POST /prescriptions
  Body: { appointment_id, diagnosis, medicines, advice?, follow_up_date? }
  Allowed roles: DOCTOR
  │
  └─ features/prescriptions/router.py
        └─ booking_service.create_prescription()
              ├─ Retrieve appointment by ID
              ├─ Verify appointment status is "booked" or "rescheduled"
              ├─ Auto-derive patient_id and doctor_id from appointment
              ├─ Validate follow_up_date is in the future
              ├─ Save to MongoDB dpas_prescriptions collection
              └─ Audit log

GET /prescriptions/patient/{patient_id}    ← patient's history (RBAC)
GET /prescriptions/doctor/{doctor_id}      ← doctor's issued prescriptions (RBAC)
```

---

## 10. Queue Management

```
GET /queue/{doctor_id}
  └─ features/queue/router.py
        └─ QueueManager.get_queue(doctor_id, date)
              ├─ Fetch queue entries from MongoDB dpas_queue_state
              ├─ Sort by: emergency first (heapq), then by appointment start_time
              └─ Return ordered list with queue_position, estimated_wait_min

Queue internally uses heapq (priority queue) keyed by:
  (-is_emergency, appointment_datetime)
  → emergencies always surface to top regardless of booking time
```

---

## 11. Reports & Data Science Analytics

### Daily Report

```
GET /reports/{report_date}?doctor_id=optional
  Allowed roles: ADMIN, DOCTOR (doctor auto-filters to own)
  │
  └─ features/reports/router.py
        └─ BookingService.get_report_data(date, doctor_id)
              ├─ Query appointments in Postgres for that date
              ├─ Aggregate: total, booked, completed, cancelled, no_show
              ├─ Group by specialization
              └─ Return dict with all metrics
```

### Data Science Visualization

```
GET /reports/analytics/visualize?days=30
  Allowed roles: ADMIN
  │
  └─ features/reports/router.py
        ├─ Calculate date range: today - days → today
        ├─ MongoManager.get_analytics_data(start, end)
        │     → fetches denormalized snapshots from dpas_analytics_raw
        └─ features/reports/visualizer.py → generate_visualization_report(records)
              │
              ├─ analyze_busiest_doctor(records)
              │     NumPy: appointment counts per doctor
              │     Returns: doctor_id, doctor_name, count, mean, std_dev
              │
              ├─ predict_peak_hours(records)
              │     NumPy histogram on start_time hours
              │     Returns: peak_hour, hour_distribution dict
              │
              ├─ generate_appointments_by_hour_chart(records)
              │     Seaborn bar chart; peak hour highlighted red
              │     Returns: base64 PNG string
              │
              ├─ generate_doctor_load_chart(records)
              │     Horizontal bar chart per doctor
              │     Returns: base64 PNG string
              │
              └─ generate_status_pie_chart(records)
                    Matplotlib pie chart (booked/completed/cancelled)
                    Returns: base64 PNG string

Final return:
  { busiest_doctor, peak_hours, hour_distribution,
    chart_by_hour (base64), chart_doctor_load (base64), chart_status_pie (base64) }
```

---

## 12. Audit Logs

Every mutating BookingService method is decorated with `@log_action`:

```python
# features/shared/services/booking_service.py

def log_action(action_name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            actor = kwargs.get("current_user", {}).get("user_id", "system")
            try:
                result = fn(self, *args, **kwargs)
                log_data = {"success": True}
                # Extract meaningful display fields from result:
                #   full_name, email, mobile, appointment_id, status, etc.
                self._mongo.log_audit(event=action_name, data=log_data, actor=actor)
                return result
            except Exception as exc:
                self._mongo.log_audit(event=f"{action_name}_failed",
                                      data={"error": str(exc)}, actor=actor)
                raise
```

**Reading Audit Logs:**

```
GET /reports/audit/logs?event=appointment_booked&limit=100
  Allowed roles: ADMIN
  │
  └─ MongoManager.get_audit_logs(event_filter, limit)
        → MongoDB dpas_audit_logs collection
        → Sorted by logged_at DESC
        → Returns: [ { event, actor, data, logged_at }, ... ]
```

The Streamlit UI's Audit Logs page fetches all logs then filters client-side using 6 controls:
Category → Event Type → Date From → Date To → Max Rows → Keyword in Data.

---

## 13. LLM Features — Detailed

All LLM features live in `features/llm/`. Two services handle them:

| Service | File | Responsibility |
|---------|------|----------------|
| `LLMService` | `features/llm/service.py` | Direct Groq API calls (symptom explainer, report summary, health summary, patient chat) |
| `AgentService` | `features/llm/service.py` | Tool-calling agentic AI (book appointments, search, reports) |
| `RoleKnowledgeBase` | `features/llm/rag.py` | pgvector semantic search over knowledge docs |

**LLM Backend:** Groq API → `llama-3.1-8b-instant`, temperature 0.3, max_tokens 600, timeout 60s.

**Injection:**
```python
# features/llm/service.py
def get_llm_service() -> LLMService:
    return LLMService(db=app_state.db, mongo=app_state.mongo, booking=app_state.booking)

def get_agent_service() -> AgentService:
    return AgentService(db=app_state.db, booking=app_state.booking)
```

---

### 13.1 Symptom Explainer

```
POST /llm/symptom-explainer
  Body: { symptoms: str, patient_age?: int, patient_gender?: str }
  Any authenticated role
  │
  └─ LLMService.problem_guidance(symptoms, patient_age, patient_gender)
        │
        ├─ [1] Fetch active doctors from DB → extract specializations + top 5 doctors
        │
        ├─ [2] Build context JSON:
        │         { symptoms, patient_age, patient_gender,
        │           available_specializations: [...],
        │           available_doctors: [ {doctor_id, full_name, specialization}, ... ] }
        │
        ├─ [3] LLM Call 1 → doctor_recommendation
        │         system: "Cautious hospital assistant. Use ONLY provided doctor roster.
        │                  Do not diagnose. Do not invent doctors. Say urgent symptoms need urgent care."
        │         user:   symptoms + context JSON
        │         → returns: which specialization(s) and doctor(s) to see
        │
        ├─ [4] LLM Call 2 → explanation
        │         → why those specializations match the symptoms
        │
        ├─ [5] LLM Call 3 → self_care_guidance
        │         → general low-risk self-care measures (hydration, rest, monitoring)
        │
        └─ [6] Assemble response:
                  {
                    symptoms,
                    suggested_specializations: [from DB, matching LLM output],
                    doctor_recommendation,
                    explanation,
                    suggested_doctors: [SuggestedDoctor objects from DB],
                    self_care_guidance,
                    safety_note: "This is guidance only. Consult a qualified doctor."
                  }
```

---

### 13.2 Report Summary (Admin)

```
POST /llm/report-summary
  Body: { report_date: date, doctor_id?: str }
  ADMIN role only
  │
  └─ LLMService.summarize_report(report_date, doctor_id)
        │
        ├─ [1] BookingService.get_report_data(report_date, doctor_id)
        │         → raw appointment metrics dict from Postgres
        │
        ├─ [2] LLM Call
        │         system: "You are a clinical data analyst. Summarize the daily report
        │                  in 4–6 plain-English sentences for a hospital admin."
        │         user:   JSON.dumps(report_data)
        │
        └─ Returns: { summary: str, report: dict }
```

---

### 13.3 Health Summary (Patient)

```
POST /llm/health-summary
  Body: { triage_records: list, prescriptions: list, patient_name?: str }
  Any authenticated role
  │
  └─ LLMService.summarize_health(triage_records, prescriptions, patient_name)
        │
        ├─ [1] Build context:
        │         { triage_vitals: [...], prescriptions: [...] }
        │
        ├─ [2] LLM Call
        │         system: "You are a caring clinical assistant.
        │                  Write a concise plain-English health summary
        │                  based ONLY on the provided vitals and prescription data.
        │                  Mention trends, list medications, do NOT diagnose or prescribe."
        │         user:   "Generate a personal health summary for {patient_name}
        │                  from the following records: {context JSON}"
        │
        └─ Returns: { summary: str }

Streamlit Usage (Patient Role):
  Streamlit fetches patient's triage and prescriptions → sends to this endpoint
  → displays natural language health overview in "Report Summary" tab
```

---

### 13.4 Patient Chat with RAG

```
POST /llm/patient-chat
  Body: { message: str (2–2000 chars) }
  Any authenticated role
  │
  └─ LLMService.patient_chat(current_user, message)
        │
        ├─ [1] Determine audience from JWT role:
        │         "patient" / "doctor" / "admin"
        │
        ├─ [2] RAG Retrieval → RoleKnowledgeBase.search(message, audience)
        │         │
        │         ├─ Call Gemini Embeddings API (taskType: RETRIEVAL_QUERY)
        │         │     POST https://generativelanguage.googleapis.com/...
        │         │     → get 768-dim query vector
        │         │
        │         ├─ pgvector similarity search:
        │         │     SELECT ... FROM rag_table
        │         │     WHERE audience = 'patient'
        │         │     ORDER BY embedding <=> query_vector   ← cosine distance
        │         │     LIMIT 4 (RAG_TOP_K)
        │         │
        │         └─ Returns top-4 RetrievedChunk objects with similarity scores
        │
        ├─ [3] Build context string:
        │         RoleKnowledgeBase.render_context(chunks)
        │         →  [Source 1] Title | path | chunk 2
        │              ... chunk content ...
        │            [Source 2] ...
        │
        ├─ [4] LLM Call
        │         system: "Hospital knowledge assistant.
        │                  Answer using ONLY the retrieved context.
        │                  Do not invent hospital rules or clinical guidance.
        │                  If context is insufficient, say so.
        │                  For emergencies, direct to urgent care."
        │         user:   message + "\n\nRetrieved Context:\n" + context_string
        │
        └─ Returns: { reply: str, sources: [KnowledgeSource, ...] }
                     sources contain: title, source_path, chunk_index, score
```

---

### 13.5 Knowledge Reindex

```
POST /llm/reindex-knowledge
  ADMIN role only
  │
  └─ LLMService.reindex_knowledge_documents()
        └─ RoleKnowledgeBase.index_documents(docs_dir="/knowledge_base/")
              │
              ├─ Scan /knowledge_base/*.md files
              │     admin_*.md  → audience="admin"
              │     doctor_*.md → audience="doctor"
              │     patient_*.md → audience="patient"
              │
              ├─ For each document:
              │     extract title from first # heading
              │     chunk content: 900-char windows with 120-char overlap
              │
              ├─ For each chunk:
              │     Call Gemini Embeddings API (taskType: RETRIEVAL_DOCUMENT)
              │     → get 768-dim embedding vector
              │     INSERT INTO rag_table ... ON CONFLICT (source_path, chunk_index) DO UPDATE
              │
              └─ Returns: { documents_indexed: N, chunks_indexed: M }
```

---

### 13.6 Agent Chat (Agentic AI)

This is the most complex LLM feature. It uses Groq's function-calling API so the LLM autonomously decides which tools to invoke and in what order.

```
POST /llm/agent-chat
  Body: { message: str, conversation_history: list[dict] }
  Any authenticated role
  │
  └─ AgentService.agent_chat(current_user, message, conversation_history)
```

#### Tool Registry (by Role)

| Tool | patient | admin | doctor | nurse/front_desk |
|------|---------|-------|--------|-----------------|
| search_doctors | yes | yes | yes | yes |
| search_knowledge_base | yes | yes | yes | yes |
| get_available_slots | yes | yes | yes | yes |
| book_appointment | yes | yes | — | yes |
| get_my_appointments | yes | yes | yes | yes |
| cancel_appointment | yes | yes | — | — |
| get_daily_report | — | yes | yes | — |
| get_all_appointments | — | yes | — | — |
| get_my_queue | — | — | yes | — |

#### Role-Specific System Prompts

**Patient:**
> You are assisting patient {name}. Help find doctors, check slots, book/view/cancel appointments.
> Before booking: search_doctors → get_available_slots → confirm with patient → book_appointment.
> Always confirm doctor name, date, time before booking.

**Doctor:**
> You are assisting Dr. {name}. Help with patient queue, schedule viewing, and lookups.

**Admin:**
> You are a hospital administrator assistant. Use get_daily_report for stats, get_all_appointments for listings.

#### Agent Loop

```
AgentService._run_agent_loop(messages, tools, current_user)
  │
  for iteration in range(6):   ← MAX_LOOP_ITERATIONS prevents infinite loops
    │
    ├─ [1] POST to Groq API with messages + tool definitions
    │         model: llama-3.1-8b-instant
    │         tools: list of OpenAI-format function schemas
    │
    ├─ [2] Parse response
    │         finish_reason: "tool_calls" | "stop"
    │
    ├─ [3] If finish_reason == "stop" OR no tool_calls:
    │         LLM is done → return final reply text
    │
    ├─ [4] For each tool_call in response:
    │         tool_name = tool_call.function.name
    │         args = json.loads(tool_call.function.arguments)
    │         tools_used.append(tool_name)
    │
    │         result = _execute_tool(tool_name, args, current_user)
    │         ↓
    │         append to messages:
    │           { role: "tool", tool_call_id: id, content: result_json }
    │
    └─ Loop continues → LLM sees tool results, may call more tools or return final answer
```

#### Tool Executors (what each tool actually does)

```
search_knowledge_base(query)
  → RoleKnowledgeBase.search(query, audience_from_role)
  → Returns: { knowledge: str, sources: [...] }

search_doctors(specialization?)
  → BookingService.list_doctors() filtered by specialization
  → Returns: { doctors: [...top 10], count }

get_available_slots(doctor_id, date)
  → date parsing: "today" → date.today(), "tomorrow" → +1 day
  → BookingService.get_available_slots(doctor_id, parsed_date)
  → Returns: { slots: [...top 12], count, date, doctor_id }

book_appointment(doctor_id, slot_id, date, patient_id?, notes?)
  → patient role: patient_id = own linked_patient_id (cannot book for others)
  → admin/staff: patient_id from args
  → BookingService.book_appointment(...)
  → Returns: { success, appointment_id, date, start_time, doctor_id, status }

get_my_appointments(date?)
  → patient: own appointments
  → doctor: own schedule for date (default today)
  → admin: all appointments for date
  → Returns: { appointments: [...top 15], count }

cancel_appointment(appointment_id, reason)
  → BookingService.cancel_appointment(...)
  → Returns: { success, appointment_id, status }

get_daily_report(date, doctor_id?)
  → BookingService.get_report_data(date, doctor_id)
  → Returns: full report metrics JSON

get_all_appointments(date?, doctor_id?)
  → admin only
  → BookingService.get_all_appointments(...)
  → Returns: { appointments: [...top 20], count }

get_my_queue(date?)
  → doctor only
  → BookingService.get_queue(linked_doctor_id, date or today)
  → Returns: { queue: [...top 15], count }
```

#### Example: Patient Books via Agent

```
User: "Book me an appointment with a cardiologist tomorrow"
  │
  Agent iteration 1:
    LLM → tool_call: search_doctors(specialization="Cardiology")
    Executor → BookingService.list_doctors() filtered
    Result: { doctors: [{doctor_id: "...", full_name: "Dr. Arjun Mehta", ...}] }
  │
  Agent iteration 2:
    LLM → tool_call: get_available_slots(doctor_id="...", date="2026-04-18")
    Executor → ScheduleManager.get_available_slots(...)
    Result: { slots: [{slot_id:"...", start_time:"09:00", ...}, ...] }
  │
  LLM → returns final text (no tool call):
    "I found Dr. Arjun Mehta (Cardiology) available tomorrow.
     Shall I book the 09:00–09:30 slot for you? Please confirm."
  │
  User: "Yes, go ahead"
  │
  Agent iteration 3:
    LLM → tool_call: book_appointment(doctor_id="...", slot_id="...", date="2026-04-18")
    Executor → BookingService.book_appointment(patient_id=current_user.linked_patient_id, ...)
    Result: { success: true, appointment_id: "...", date: "2026-04-18", start_time: "09:00" }
  │
  LLM → final reply:
    "Done! Your appointment with Dr. Arjun Mehta (Cardiology) is booked
     for April 18, 2026 at 09:00. Your appointment ID is ABC123."
```

---

## 14. Google Suite Integration

All G-Suite calls are non-blocking (wrapped in try/except, failures don't break core operations).

```
features/gsuite/
  ├─ gmail_service.py      → send_registration_success(), send_appointment_confirmation()
  ├─ calendar_service.py   → create_event(), cancel_event(), list_upcoming()
  ├─ drive_service.py      → upload_file(), list_files(), share_with_patient()
  ├─ forms_sync.py         → sync_form_responses() → registers patients from Google Forms
  └─ router.py             → exposes all above as REST endpoints

Authentication:
  Service account (GOOGLE_SERVICE_ACCOUNT_FILE) for Drive/Calendar/Gmail
  OR OAuth2 token (GOOGLE_TOKEN_FILE) for user-delegated access
```

**When booking completes:**
```
book_appointment() POST-LOCK:
  → gmail_service.send_appointment_confirmation(patient_email, doctor_email, apt_dict)
  → calendar_service.create_event(title, date, start_time, end_time, attendees)
       → returns calendar_event_id, calendar_event_link stored on appointment
```

**Google Forms Auto-Sync (background thread):**
```
Every 5 minutes:
  → fetch new rows from Google Sheets (Forms response sheet)
  → for each new row: booking_service.register_patient(full_name, email, mobile, ...)
  → marks row as processed
```

---

## 15. Database Layer

### PostgreSQL (Primary Transactional DB)

**File:** `features/shared/database/postgres.py`

**Tables:** patients, doctors, nurses, slots, appointments, triage_entries, roles_permissions

**Fallback:** If psycopg2 not installed or connection fails → all operations silently route to InMemoryStore. Flag visible in `/health` endpoint.

**Key patterns:**
- `ON CONFLICT (email) DO UPDATE` — idempotent upserts (F4)
- `SELECT FOR UPDATE` on slot row — DB-level lock for double-booking (F6)
- Schema auto-created on first connect via `_SCHEMA_SQL`

### MongoDB (Audit, Analytics, Prescriptions)

**File:** `features/shared/database/mongo.py`

**Collections:**

| Collection | Contents | Key Indexes |
|------------|----------|-------------|
| dpas_audit_logs | Every action with actor + data | event, logged_at |
| dpas_queue_state | Serialized patient queue | appointment_id (unique), doctor_id+date |
| dpas_analytics_raw | Denormalized appointment snapshots | date, doctor_id |
| dpas_prescriptions | Full prescription documents | patient_id+created_at, doctor_id |

### InMemoryStore (Fallback)

**File:** `features/shared/database/in_memory.py`

Thread-safe in-process dict store. **Data is lost on server restart.** Used when Postgres/Mongo are unavailable.

---

## 16. Streamlit Frontend Flows

**File:** `streamlit_app.py`

All API calls use `requests` library. Token stored in `st.session_state.token`.

### Login

```
Sidebar "Login" form
  → POST /auth/login
  → store token, role, user_id in st.session_state
  → re-render UI with role-appropriate tabs
```

### Role-Based Tab Visibility

| Tab | admin | doctor | patient | nurse | front_desk |
|-----|-------|--------|---------|-------|------------|
| Register Patient | yes | — | — | yes | yes |
| Register Doctor | yes | — | — | — | — |
| Register Nurse | yes | — | — | — | — |
| Book Appointment | yes | — | yes | yes | yes |
| My Appointments | yes | yes | yes | yes | yes |
| Triage | yes | — | — | yes | — |
| Prescriptions | yes | yes | yes | — | — |
| Report Summary | yes | — | yes | — | — |
| Analytics | yes | — | — | — | — |
| Audit Logs | yes | — | — | — | — |
| LLM Assistant | yes | yes | yes | yes | yes |
| Problem Guidance | yes | yes | yes | yes | yes |
| Agent Chat | yes | yes | yes | yes | yes |

### Patient Appointments Auto-Load

```
My Appointments tab (patient role):
  → On first load (not in session_state):
      GET /appointments?patient_id=linked_patient_id
      store in st.session_state.appointments
      render table
  → "Refresh" button re-fetches
  → Agent-booked appointments appear on next load/refresh
```

### Report Summary Tab

```
IF role == "admin":
  → POST /reports/{date}              → get hospital metrics
  → POST /llm/report-summary          → LLM summary of hospital data
  Display: summary text + metrics table

IF role == "patient":
  → GET /triage/patient/{patient_id}  → vitals history
  → GET /prescriptions/patient/{patient_id}  → medications
  → POST /llm/health-summary          → LLM personal health summary
  Display: natural language summary of own health

IF role in ("doctor", "nurse"):
  → Tab is hidden entirely (not rendered)
```

### Audit Logs Multi-Filter (Admin)

```
Fetch: GET /reports/audit/logs?limit=1000
  → store raw in st.session_state.audit_logs_raw

Client-side filtering via 6 controls (2 rows):
  Row 1: [Category dropdown] [Event Type dropdown] [Max Rows]
  Row 2: [Date From] [Date To] [Keyword in Data]

Category groups:  Patients | Doctors | Nurses | Appointments | Triage | Prescriptions | All
Event Type:       scoped to selected category (e.g. Appointments → booked/cancelled/rescheduled)

All filters applied client-side with AND logic
Display columns: logged_at | event | name | data (sensitive fields redacted)
```

---

## 17. Key Files Reference

| File | What it does |
|------|-------------|
| `config.py` | All settings — DB, JWT, LLM, G-Suite, hospital rules |
| `features/core/app.py` | FastAPI app, lifespan startup, all router registrations |
| `features/core/dependencies.py` | `app_state` singleton container, `get_current_user()`, `require_roles()`, scope checks |
| `features/shared/services/booking_service.py` | Central orchestrator for ALL data mutations. Register, book, cancel, reschedule, triage, prescriptions |
| `features/shared/services/schedule_manager.py` | Slot generation, slot queries, cache invalidation |
| `features/shared/services/queue_manager.py` | heapq priority queue, emergency surfacing, queue persistence |
| `features/shared/services/auth_service.py` | Login, JWT create/validate, password hashing |
| `features/llm/service.py` | `LLMService` (Groq calls) + `AgentService` (tool-calling agent loop) |
| `features/llm/rag.py` | `RoleKnowledgeBase` — pgvector indexing + cosine similarity search with Gemini embeddings |
| `features/llm/router.py` | All 6 LLM endpoints with role guards |
| `features/llm/contracts.py` | Pydantic request/response models for all LLM endpoints |
| `features/reports/visualizer.py` | NumPy/Pandas/Matplotlib/Seaborn analytics module |
| `features/shared/database/postgres.py` | PostgreSQL CRUD + InMemoryStore fallback |
| `features/shared/database/mongo.py` | MongoDB audit logs, queue state, analytics, prescriptions |
| `features/shared/database/in_memory.py` | Thread-safe in-process store (fallback + test store) |
| `features/gsuite/gmail_service.py` | Registration/booking confirmation emails |
| `features/gsuite/forms_sync.py` | Background Google Forms → patient registration sync |
| `streamlit_app.py` | Full frontend — login, all role-based tabs, API calls |
| `tests/test_services.py` | Unit/integration tests using InMemoryStore directly |
| `tests/conftest.py` | pytest fixtures — BookingService with InMemoryStore |

---

*Generated: 2026-04-17 | DPAMS Fractal Architecture*
