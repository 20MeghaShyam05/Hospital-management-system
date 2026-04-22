"""Seed appointments, triage records, and prescriptions via HTTP API.
Run with the FastAPI server already running: uvicorn features.core.app:app --reload
"""
import sys
import requests
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE  = "http://localhost:8000"
TOKEN = "eyJ1c2VyX2lkIjoiYWRtaW4iLCJ1c2VybmFtZSI6ImFkbWluIiwicm9sZSI6ImFkbWluIiwiZGlzcGxheV9uYW1lIjoiU3lzdGVtIEFkbWluIiwiZXhwIjoxNzc2NDA1NTA1fQ.NM0iZ9Z0N78J4EpsPReIEMCdSapLLyBQxOtko3lDYVA"
H     = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def get(path):
    r = requests.get(f"{BASE}{path}", headers=H, timeout=15)
    r.raise_for_status()
    return r.json()


def post(path, body):
    r = requests.post(f"{BASE}{path}", headers=H, json=body, timeout=15)
    if not r.ok:
        return None, r.status_code, r.text[:120]
    return r.json(), r.status_code, None


def next_weekday(offset: int) -> str:
    d = date.today() + timedelta(days=offset)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


# ── 1. Fetch existing data ─────────────────────────────────────────────────────
print("Connecting to API...")
try:
    doctors  = get("/doctors/")
    patients = get("/patients/")
    nurses   = get("/nurses/")
except Exception as e:
    print(f"ERROR: Cannot reach API at {BASE}\n  {e}")
    print("Start the server first:  uvicorn features.core.app:app --reload")
    sys.exit(1)

if not isinstance(doctors,  list): doctors  = doctors.get("doctors",  [])
if not isinstance(patients, list): patients = patients.get("patients", [])
if not isinstance(nurses,   list): nurses   = nurses.get("nurses",     [])

print(f"Doctors: {len(doctors)}  Patients: {len(patients)}  Nurses: {len(nurses)}")

if not doctors or not patients:
    print("ERROR: Need doctors and patients. Run seed_data.py first.")
    sys.exit(1)


# ── 2. Ensure slots exist for every doctor ─────────────────────────────────────
SLOT_TIMES = [
    ("09:00", "09:30"), ("09:30", "10:00"), ("10:00", "10:30"),
    ("10:30", "11:00"), ("11:00", "11:30"),
    ("14:00", "14:30"), ("14:30", "15:00"), ("15:00", "15:30"),
    ("15:30", "16:00"), ("16:00", "16:30"),
]

print("\nEnsuring slots...")
for doc in doctors[:10]:
    doc_id = doc.get("doctor_id") or doc.get("uhid") or doc.get("id")
    appt_date = next_weekday(1)
    try:
        slots = get(f"/slots/{doc_id}/{appt_date}")
        if isinstance(slots, list) and slots:
            print(f"  {doc.get('full_name','?')[:22]}: {len(slots)} slots OK")
            continue
    except Exception:
        slots = []

    added = 0
    for start, end in SLOT_TIMES:
        body = {
            "doctor_id": doc_id,
            "start_time": start,
            "end_time": end,
            "days_of_week": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        }
        r, _, _ = post("/slots", body)
        if r:
            added += 1
    print(f"  {doc.get('full_name','?')[:22]}: added {added} slots")


# ── 3. Book 10 appointments ────────────────────────────────────────────────────
print("\n--- Booking appointments ---")

plan = [(0,0),(1,1),(2,2),(3,3),(4,4),(5,5),(6,6),(7,7),(0,8),(1,9)]
booked = []

for i, (pat_idx, doc_idx) in enumerate(plan):
    patient = patients[pat_idx % len(patients)]
    doctor  = doctors[doc_idx % len(doctors)]
    pat_id  = patient.get("patient_id") or patient.get("uhid") or patient.get("id")
    doc_id  = doctor.get("doctor_id")  or doctor.get("uhid")  or doctor.get("id")
    appt_date = next_weekday(i + 1)

    # Fetch available slots
    try:
        slots = get(f"/slots/{doc_id}/{appt_date}")
        if not isinstance(slots, list): slots = []
    except Exception:
        slots = []

    avail = [s for s in slots if not s.get("is_booked", False)]
    if not avail and slots:
        avail = slots
    if not avail:
        print(f"SKIP  no slots for {doctor.get('full_name','?')[:20]} on {appt_date}")
        continue

    slot_id = (avail[0].get("slot_id") or avail[0].get("id"))
    body = {"patient_id": pat_id, "doctor_id": doc_id, "slot_id": slot_id, "date": appt_date}
    result, code, err = post("/appointments", body)
    if result:
        booked.append(result)
        aid = result.get("appointment_id", "?")
        print(f"OK    {patient.get('full_name','?'):22s} -> {doctor.get('full_name','?'):22s} | {appt_date} | {aid}")
    else:
        print(f"ERR   {patient.get('full_name','?'):22s}: HTTP {code}: {err}")

print(f"\nBooked {len(booked)} appointments.")


# ── 4. Triage records ─────────────────────────────────────────────────────────
print("\n--- Adding triage records ---")

nurse_id = nurses[0].get("nurse_id") or nurses[0].get("uhid") if nurses else None

triage_vitals = [
    {"blood_pressure": "130/85", "heart_rate": 78, "temperature": 37.0, "weight": 72.0, "oxygen_saturation": 97, "symptoms": "Chest discomfort on exertion"},
    {"blood_pressure": "118/76", "heart_rate": 88, "temperature": 37.3, "weight": 65.0, "oxygen_saturation": 98, "symptoms": "Persistent headache and dizziness"},
    {"blood_pressure": "142/92", "heart_rate": 82, "temperature": 37.0, "weight": 85.0, "oxygen_saturation": 96, "symptoms": "Knee pain and swelling"},
    {"blood_pressure": "110/70", "heart_rate": 92, "temperature": 37.9, "weight": 38.0, "oxygen_saturation": 98, "symptoms": "Fever and sore throat"},
    {"blood_pressure": "125/80", "heart_rate": 74, "temperature": 37.1, "weight": 60.0, "oxygen_saturation": 99, "symptoms": "Skin rash and itching"},
    {"blood_pressure": "120/78", "heart_rate": 80, "temperature": 37.0, "weight": 58.0, "oxygen_saturation": 98, "symptoms": "Lower abdominal pain"},
    {"blood_pressure": "115/72", "heart_rate": 76, "temperature": 36.8, "weight": 68.0, "oxygen_saturation": 99, "symptoms": "Anxiety and sleep disturbance"},
    {"blood_pressure": "128/82", "heart_rate": 70, "temperature": 36.9, "weight": 74.0, "oxygen_saturation": 97, "symptoms": "Blurry vision and eye strain"},
]

triage_records = []
for i, vitals in enumerate(triage_vitals):
    patient = patients[i % len(patients)]
    doctor  = doctors[i % len(doctors)]
    pat_id  = patient.get("patient_id") or patient.get("uhid") or patient.get("id")
    doc_id  = doctor.get("doctor_id")  or doctor.get("uhid")  or doctor.get("id")
    nrs_id  = nurse_id or doc_id  # fallback to doc if no nurses

    # Use booked appointment_id if available
    appt_id = booked[i]["appointment_id"] if i < len(booked) else None

    body = {
        "patient_id":       pat_id,
        "nurse_id":         nrs_id,
        "doctor_id":        doc_id,
        "date":             next_weekday(i + 1),
        "appointment_id":   appt_id,
        **vitals,
    }
    result, code, err = post("/triage", body)
    if result:
        triage_records.append(result)
        print(f"Triage  {patient.get('full_name','?'):25s} | {vitals['blood_pressure']} | {vitals['symptoms'][:30]}")
    else:
        print(f"Triage ERR {patient.get('full_name','?')}: HTTP {code}: {err}")

print(f"\nAdded {len(triage_records)} triage records.")


# ── 5. Prescriptions ──────────────────────────────────────────────────────────
print("\n--- Adding prescriptions ---")

rx_data = [
    {"diagnosis": "Hypertension Stage 1",
     "medicines": "Amlodipine 5mg - Once daily after food; Aspirin 75mg - Once daily",
     "advice": "Low-salt diet, 30 min walk daily. Recheck in 4 weeks."},
    {"diagnosis": "Migraine with aura",
     "medicines": "Sumatriptan 50mg - At onset, max 2 doses/24h; Propranolol 40mg - Once daily",
     "advice": "Avoid triggers (stress, caffeine). Keep headache diary."},
    {"diagnosis": "Osteoarthritis - right knee",
     "medicines": "Ibuprofen 400mg - Twice daily with meals; Pantoprazole 40mg - Once daily",
     "advice": "Ice pack 20 min 3x/day. Avoid stairs where possible."},
    {"diagnosis": "Acute tonsillitis",
     "medicines": "Amoxicillin 500mg - Thrice daily for 7 days; Paracetamol 500mg - As needed",
     "advice": "Complete the antibiotic course. Warm saline gargles 4x daily."},
    {"diagnosis": "Allergic dermatitis",
     "medicines": "Cetirizine 10mg - Once at night; Betamethasone cream 0.05% - Apply twice daily",
     "advice": "Avoid identified allergens. Moisturise skin after bathing."},
    {"diagnosis": "Dysmenorrhoea",
     "medicines": "Mefenamic Acid 500mg - Thrice daily with food; Iron 100mg - Once daily",
     "advice": "Heating pad on lower abdomen. Adequate hydration and rest."},
    {"diagnosis": "Generalised Anxiety Disorder",
     "medicines": "Sertraline 50mg - Once daily in morning; Clonazepam 0.5mg - At night as needed",
     "advice": "CBT sessions recommended. Avoid alcohol and caffeine."},
    {"diagnosis": "Dry eye syndrome",
     "medicines": "Carboxymethylcellulose 0.5% eye drops - 4x daily; Vitamin A supplement - Once daily",
     "advice": "Reduce screen time. Use 20-20-20 rule. Wear UV-protective glasses."},
]

rx_added = []
for i, rx in enumerate(rx_data):
    # Attach to a booked appointment if possible
    if i < len(booked):
        appt_id = booked[i]["appointment_id"]
    else:
        print(f"Rx SKIP  no appointment for index {i}")
        continue

    body = {"appointment_id": appt_id, **rx}
    result, code, err = post("/prescriptions", body)
    if result:
        rx_added.append(result)
        print(f"Rx  {rx['diagnosis'][:35]:35s} | appt {appt_id}")
    else:
        print(f"Rx ERR appt {appt_id}: HTTP {code}: {err}")

print(f"\nAdded {len(rx_added)} prescriptions.")
print("\nAll done! Summary:")
print(f"  Appointments : {len(booked)}")
print(f"  Triage       : {len(triage_records)}")
print(f"  Prescriptions: {len(rx_added)}")
