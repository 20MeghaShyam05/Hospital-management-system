from __future__ import annotations

import json as json_lib
import re
from datetime import date, time
from typing import Any, Optional

import altair as alt
import pandas as pd
import requests
import streamlit as st

from config import settings


st.set_page_config(
    page_title="MediFlow HMS",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Fraunces:wght@600;700&display=swap');

:root {
    --bg:           #f5f2ea;
    --surface:      #ffffff;
    --surface-tint: rgba(246, 250, 249, 0.95);
    --ink:          #14313a;
    --muted:        #6e8085;
    --line:         rgba(20, 49, 58, 0.10);
    --brand:        #1f7a78;
    --brand-deep:   #155e5c;
    --brand-soft:   #dff2ef;
    --accent:       #f28f6b;
    --accent-soft:  #ffe9df;
    --gold:         #f3c96a;
    --success:      #2ea87d;
    --danger:       #d86c5e;
    --shadow-xs:    0 2px 8px rgba(20,49,58,0.05);
    --shadow-sm:    0 8px 26px rgba(24,53,63,0.08);
    --shadow:       0 16px 42px rgba(24,53,63,0.10);
    --shadow-lg:    0 24px 60px rgba(24,53,63,0.12);
    --r-xs: 6px;  --r-sm: 12px;  --r: 16px;  --r-lg: 22px;  --r-xl: 28px;
}

*, *::before, *::after { box-sizing: border-box; }

.stApp {
    background:
        radial-gradient(circle at top left, rgba(242, 143, 107, 0.16), transparent 26%),
        radial-gradient(circle at top right, rgba(31, 122, 120, 0.15), transparent 24%),
        linear-gradient(180deg, #f8f4ed 0%, var(--bg) 100%);
    color: var(--ink);
    font-family: "Manrope", "Segoe UI", sans-serif;
}
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(15, 55, 63, 0.98) 0%, rgba(18, 70, 80, 0.98) 100%) !important;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    min-width: 18rem !important;
}
[data-testid="stSidebar"] * { color: #eef8f7 !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
    color: #eef8f7 !important;
    -webkit-text-fill-color: unset;
    font-family: "Manrope", "Segoe UI", sans-serif;
    font-weight: 800;
    font-size: 1.3rem;
}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] button,
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] select,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    font-family: "Manrope", "Segoe UI", sans-serif !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label {
    margin: 0.2rem 0;
    padding: 0.35rem 0.3rem;
    border-radius: var(--r-sm);
    transition: background 0.15s;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(255, 255, 255, 0.08);
}
[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.10) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: #eef8f7 !important;
    border-radius: var(--r-sm) !important;
    font-weight: 600 !important;
    transition: background 0.18s, transform 0.18s !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.18) !important;
    transform: translateY(-1px) !important;
}

.page-header {
    background: linear-gradient(135deg, rgba(255,255,255,0.90), rgba(249,253,252,0.90));
    border: 1px solid var(--line);
    border-left: 4px solid var(--brand);
    border-radius: 0 var(--r-lg) var(--r-lg) 0;
    padding: 1.3rem 1.6rem;
    margin-bottom: 1rem;
    box-shadow: var(--shadow-sm);
}
.section-title {
    font-family: "Fraunces", Georgia, serif;
    font-size: 1.3rem; color: var(--ink); margin-bottom: 0.2rem;
}
.section-copy {
    color: var(--muted); font-size: 0.92rem; margin-bottom: 0;
}

.metric-card {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 22px;
    padding: 1rem 1rem 0.95rem 1rem;
    box-shadow: var(--shadow-sm);
    transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.22s;
    cursor: default;
}
.metric-card:hover { transform: translateY(-4px); box-shadow: var(--shadow); }
.metric-label {
    color: var(--muted); font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700;
}
.metric-value {
    color: var(--ink); font-size: 1.8rem; line-height: 1.1;
    font-weight: 800; margin-top: 0.35rem;
}
.metric-subtle { color: var(--brand); font-size: 0.85rem; margin-top: 0.35rem; }

.hero-shell {
    background:
        radial-gradient(circle at 85% 10%, rgba(242, 143, 107, 0.18), transparent 22%),
        linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(249, 253, 252, 0.92));
    border: 1px solid var(--line);
    border-radius: 28px;
    padding: 1.6rem 1.8rem;
    box-shadow: var(--shadow-lg);
    margin-bottom: 1.1rem;
}
.hero-kicker {
    display: inline-block;
    background: var(--brand-soft);
    color: var(--brand);
    border-radius: 999px;
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.04em;
    padding: 0.35rem 0.7rem; margin-bottom: 0.8rem;
}
.hero-title {
    font-family: "Fraunces", Georgia, serif;
    font-size: 2.4rem; line-height: 1.05; margin: 0; color: var(--ink);
}
.hero-copy {
    color: var(--muted); font-size: 1rem; line-height: 1.6; margin-top: 0.8rem;
}
.hero-stat-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem; margin-top: 1.2rem;
}
.hero-stat {
    background: rgba(255, 255, 255, 0.78);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 0.9rem 1rem;
    transition: border-color 0.18s, background 0.18s;
}
.hero-stat:hover { border-color: var(--brand); background: var(--brand-soft); }
.hero-stat-label { color: var(--muted); font-size: 0.82rem; }
.hero-stat-value { color: var(--ink); font-size: 1.5rem; font-weight: 800; }

.stButton > button, .stDownloadButton > button {
    border-radius: 14px !important;
    border: 1px solid rgba(31, 122, 120, 0.18) !important;
    background: linear-gradient(135deg, #1f7a78, #226b8a) !important;
    color: #ffffff !important;
    padding: 0.55rem 1rem !important;
    font-weight: 700 !important;
    transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.22s !important;
    box-shadow: 0 4px 14px rgba(31,122,120,0.22) !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-2px) scale(1.02) !important;
    box-shadow: 0 8px 22px rgba(31,122,120,0.36) !important;
}
.stButton > button:active {
    transform: translateY(1px) scale(0.97) !important;
    box-shadow: 0 2px 6px rgba(31,122,120,0.18) !important;
}

.stForm {
    background: rgba(255,255,255,0.72);
    border-radius: 24px;
    border: 1px solid var(--line);
    padding: 0.6rem 0.5rem 0.2rem 0.5rem;
}
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div,
.stDateInput > div > div > input,
.stNumberInput > div > div > input {
    background: var(--surface-tint) !important;
    border: 1px solid rgba(31, 122, 120, 0.12) !important;
    border-radius: 12px !important;
    color: var(--ink) !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 3px rgba(31,122,120,0.12) !important;
    outline: none !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 0.4rem;
    background: rgba(255,255,255,0.5);
    border-radius: 12px;
    padding: 0.35rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    font-weight: 700;
    font-size: 0.85rem;
    color: var(--muted) !important;
    padding: 0.55rem 1rem;
    transition: background 0.17s, color 0.17s;
}
.stTabs [data-baseweb="tab"]:hover {
    background: rgba(31,122,120,0.07) !important;
    color: var(--brand) !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(31,122,120,0.14) !important;
    color: var(--brand) !important;
}

[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-sm);
}
.streamlit-expanderHeader {
    background: rgba(255,255,255,0.6) !important;
    border-radius: 12px !important;
    font-weight: 600;
    transition: background 0.17s !important;
}
.streamlit-expanderHeader:hover { background: var(--brand-soft) !important; }

.status-dot {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 6px;
}
.status-dot.online {
    background: var(--success);
    box-shadow: 0 0 0 3px rgba(46,168,125,0.22);
    animation: pulse-dot 2s ease-in-out infinite;
}
.status-dot.offline { background: var(--danger); }
@keyframes pulse-dot {
    0%, 100% { box-shadow: 0 0 0 3px rgba(46,168,125,0.22); }
    50%       { box-shadow: 0 0 0 7px rgba(46,168,125,0.0);  }
}

.pill {
    display: inline-block;
    padding: 0.3rem 0.7rem;
    border-radius: 999px;
    background: var(--accent-soft);
    color: #b85f42;
    font-size: 0.78rem;
    font-weight: 700;
}
.pill-brand { background: var(--brand-soft); color: var(--brand-deep); }
.pill-cyan  { background: var(--brand-soft); color: var(--brand-deep); }
.pill-green { background: #d9f2e6; color: #1a6642; }

.login-card {
    max-width: 560px;
    margin: 1rem auto 2rem auto;
    background: linear-gradient(135deg, rgba(255,255,255,0.88), rgba(249,253,252,0.9));
    border: 1px solid var(--line);
    border-radius: 24px;
    padding: 1.8rem 1.8rem 1.4rem;
    box-shadow: var(--shadow-lg);
}
.login-logo {
    font-family: "Fraunces", Georgia, serif;
    font-size: 2rem; font-weight: 700; text-align: center;
    color: var(--ink); margin-bottom: 0.35rem;
}
.login-subtitle {
    text-align: center; color: var(--muted); font-size: 0.92rem; margin-bottom: 0;
}

[data-testid="stMetric"] {
    background: rgba(255,255,255,0.78);
    border-radius: 16px; padding: 0.9rem 1rem;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-xs);
    transition: transform 0.2s;
}
[data-testid="stMetric"]:hover { transform: translateY(-3px); }

hr { border-color: var(--line) !important; }

.section-divider {
    display: flex; align-items: center; gap: 0.85rem;
    margin: 1.2rem 0 0.8rem; color: var(--muted);
    font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
}
.section-divider::before, .section-divider::after {
    content: ''; flex: 1; height: 1px; background: var(--line);
}

/* ── AI Assistant ──────────────────────────────────────── */
.ai-header {
    display: flex; align-items: center; gap: 0.65rem;
    margin-bottom: 0.25rem;
}
.ai-title {
    font-family: "Fraunces", serif; font-size: 1.55rem; font-weight: 700;
    color: var(--ink); line-height: 1.15;
}
.ai-role-badge {
    display: inline-flex; align-items: center;
    padding: 0.2rem 0.65rem; border-radius: 20px;
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; text-transform: capitalize;
    background: var(--brand-soft); color: var(--brand-deep);
    border: 1px solid rgba(31,122,120,0.22);
}
.ai-subtitle {
    color: var(--muted); font-size: 0.88rem; margin-bottom: 1.2rem;
}
.ai-section-label {
    font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--muted); margin-bottom: 0.5rem;
}
.ai-empty-state {
    text-align: center; padding: 2.5rem 1rem 2rem;
    color: var(--muted);
}
.ai-empty-icon { font-size: 2.4rem; margin-bottom: 0.6rem; }
.ai-empty-title {
    font-size: 1.05rem; font-weight: 700; color: var(--ink);
    margin-bottom: 0.3rem;
}
.ai-empty-copy { font-size: 0.85rem; line-height: 1.55; }
.tool-actions { margin-top: 0.35rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.tool-chip {
    display: inline-flex; align-items: center; gap: 0.25rem;
    padding: 0.18rem 0.55rem; border-radius: 20px;
    font-size: 0.7rem; font-weight: 600;
    background: var(--brand-soft); color: var(--brand-deep);
    border: 1px solid rgba(31,122,120,0.18);
}
.tool-chip::before { content: "✓ "; opacity: 0.7; }

/* make the sticky chat bar more prominent */
[data-testid="stChatInput"] > div {
    border: 2px solid var(--brand) !important;
    border-radius: var(--r-lg) !important;
    box-shadow: 0 4px 22px rgba(31,122,120,0.16) !important;
    background: #ffffff !important;
}
[data-testid="stChatInput"] textarea {
    font-size: 0.95rem !important;
    font-family: "Manrope", sans-serif !important;
    color: var(--ink) !important;
}
[data-testid="stChatInput"] button {
    color: var(--brand) !important;
}
/* quick prompt buttons */
.quick-prompt .stButton > button {
    background: #ffffff !important;
    border: 1.5px solid rgba(31,122,120,0.30) !important;
    color: var(--brand-deep) !important;
    border-radius: 20px !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    padding: 0.25rem 0.7rem !important;
    white-space: nowrap !important;
    transition: background 0.15s, border-color 0.15s !important;
}
.quick-prompt .stButton > button:hover {
    background: var(--brand-soft) !important;
    border-color: var(--brand) !important;
}
</style>
"""


st.markdown(THEME_CSS, unsafe_allow_html=True)


SPECIALIZATIONS = [
    "General Physician",
    "Cardiologist",
    "Dermatologist",
    "Neurologist",
    "Orthopedist",
    "Pediatrician",
    "Psychiatrist",
    "Gynecologist",
    "ENT Specialist",
    "Ophthalmologist",
]

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
GENDERS = ["Male", "Female", "Other"]
EARLIEST_DOB = date(1900, 1, 1)


def next_weekday(start: Optional[date] = None) -> date:
    d = start or date.today()
    while d.weekday() in (5, 6):
        d = d.fromordinal(d.toordinal() + 1)
    return d


def get_api_base_url() -> str:
    if "api_base_url" not in st.session_state:
        st.session_state.api_base_url = "http://127.0.0.1:8000"
    return st.session_state.api_base_url.rstrip("/")


def get_auth_headers() -> dict[str, str]:
    token = st.session_state.get("auth_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def api_request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
    timeout: int = 20,
) -> tuple[bool, Any]:
    url = f"{get_api_base_url()}{path}"
    try:
        response = requests.request(
            method,
            url,
            params=params,
            json=json,
            timeout=timeout,
            headers=get_auth_headers(),
        )
    except requests.RequestException as exc:
        return False, f"API connection failed: {exc}"

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if response.ok:
        return True, payload

    if isinstance(payload, dict) and payload.get("detail"):
        detail = payload["detail"]
        if (
            response.status_code in {401, 403}
            and st.session_state.get("auth_token")
            and isinstance(detail, str)
            and "authentication token" in detail.lower()
        ):
            st.session_state.pop("auth_token", None)
            st.session_state.pop("current_user", None)
            set_auth_notice("Your session expired. Please sign in again.")
            st.rerun()
        return False, detail
    return False, payload or f"HTTP {response.status_code}"


def load_health() -> dict[str, Any]:
    ok, payload = api_request("GET", "/health")
    return payload if ok and isinstance(payload, dict) else {"status": "offline", "postgres": False, "mongo": False}


def load_patients(active_only: bool = True) -> list[dict[str, Any]]:
    ok, payload = api_request("GET", "/patients", params={"active_only": active_only})
    return load_collection_result(ok, payload, "patients")


def load_doctors(active_only: bool = True) -> list[dict[str, Any]]:
    ok, payload = api_request("GET", "/doctors", params={"active_only": active_only})
    return load_collection_result(ok, payload, "doctors")


def load_collection_result(ok: bool, payload: Any, label: str) -> list[dict[str, Any]]:
    if ok and isinstance(payload, list):
        return payload
    if ok:
        st.warning(f"The {label} API returned an unexpected response shape.")
    else:
        st.error(f"Could not load {label}: {payload}")
    return []


def current_user() -> dict[str, Any]:
    return st.session_state.get("current_user", {})


def current_role() -> str:
    return current_user().get("role", "")


def load_session_patients() -> list[dict[str, Any]]:
    if current_role() in {"admin", "nurse", "front_desk"}:
        return load_patients()
    if current_role() == "patient":
        patient_id = current_user().get("linked_patient_id")
        ok, payload = api_request("GET", f"/patients/{patient_id}")
        return [payload] if ok and isinstance(payload, dict) else []
    return []


def set_auth_screen(screen: str) -> None:
    st.session_state.auth_screen = screen


def auth_screen() -> str:
    return st.session_state.get("auth_screen", "login")


def set_auth_notice(message: str) -> None:
    st.session_state.auth_notice = message


def pop_auth_notice() -> Optional[str]:
    return st.session_state.pop("auth_notice", None)


def google_forms_url() -> str:
    return settings.GOOGLE_FORMS_URL.strip()


def render_patient_registration_access(*, context: str) -> None:
    form_url = google_forms_url()
    if form_url:
        st.link_button("Book an Appointment", form_url, use_container_width=True)
        if context == "login":
            st.caption("Complete the Google Form to register and book an appointment. MediFlow will sync the response automatically.")
        else:
            st.caption("Use the live Google Form to register and book appointments, then sync responses into MediFlow.")
    else:
        st.info("Google Forms URL is not configured yet. Add `GOOGLE_FORMS_URL` in `.env` to enable direct form access.")


def render_forms_sync_controls(*, context: str) -> None:
    st.subheader("Forms Sync")
    render_patient_registration_access(context=context)
    if st.button("Sync Google Form Responses", use_container_width=True, key=f"{context}_forms_sync"):
        ok, result = api_request("POST", "/gsuite/forms/sync")
        if ok:
            booked = result.get("appointments_booked", 0)
            failed = result.get("appointments_failed", 0)
            apt_note = f" · {booked} appointment(s) booked" if booked else ""
            apt_note += f" · {failed} booking(s) failed" if failed else ""
            st.success(
                f"Sync complete: {result.get('new', 0)} new patient(s), "
                f"{result.get('skipped', 0)} skipped{apt_note}"
            )
            for err in result.get("errors", []):
                st.warning(err)
            st.rerun()
        else:
            st.error(result)


def render_patient_intake_booking(doctors: list[dict[str, Any]], *, context: str) -> None:
    if not doctors:
        st.info("No doctors are available for appointment booking yet.")
        return

    doctor_map = doctor_lookup_map(doctors)
    prefix = f"{context}_intake"
    with st.form(f"{prefix}_patient_form"):
        st.markdown("#### Patient Details")
        full_name = st.text_input("Full Name", key=f"{prefix}_name")
        email = st.text_input("Email", key=f"{prefix}_email")
        mobile = st.text_input("Mobile", key=f"{prefix}_mobile")
        col1, col2 = st.columns(2)
        with col1:
            date_of_birth = st.date_input("Date of Birth", value=date(1995, 1, 1), min_value=EARLIEST_DOB, max_value=date.today(), key=f"{prefix}_dob")
            gender = st.selectbox("Gender", GENDERS, key=f"{prefix}_gender")
        with col2:
            blood_group = st.selectbox("Blood Group", [""] + BLOOD_GROUPS, key=f"{prefix}_blood")
            address = st.text_area("Address", height=70, key=f"{prefix}_address")
        st.markdown("#### Appointment")
        doctor_label = st.selectbox("Doctor", list(doctor_map.keys()), key=f"{prefix}_doctor")
        appointment_date = st.date_input("Appointment Date", min_value=date.today(), value=next_weekday(), key=f"{prefix}_date")
        problem = st.text_area("Problem / Reason for Visit", height=90, key=f"{prefix}_problem")
        submitted = st.form_submit_button("Find Slots", use_container_width=True)

    selected_doctor = doctor_map[doctor_label]
    slot_state_key = f"{prefix}_slots"
    if submitted:
        ok, result = api_request("GET", f"/slots/{selected_doctor['uhid']}/{appointment_date.isoformat()}")
        if ok:
            st.session_state[slot_state_key] = result
        else:
            st.error(result)

    slots = [
        slot for slot in st.session_state.get(slot_state_key, [])
        if slot.get("doctor_id") == selected_doctor["doctor_id"]
        and slot.get("date") == appointment_date.isoformat()
        and not slot.get("is_blocked")
        and not slot.get("is_booked")
    ]
    slot_options = {
        slot.get("label") or f"{slot['start_time']} - {slot['end_time']}": slot["slot_id"]
        for slot in slots
    }
    if slot_options:
        selected_slot = st.selectbox("Available Slots", list(slot_options.keys()), key=f"{prefix}_slot")
        if st.button("Register & Book Appointment", use_container_width=True, key=f"{prefix}_book"):
            patient_payload = {
                "full_name": full_name.strip(),
                "email": email.strip().lower(),
                "mobile": mobile.strip(),
                "date_of_birth": date_of_birth.isoformat(),
                "gender": gender,
                "blood_group": blood_group or None,
                "address": address.strip() or None,
                "registered_by": current_role() or "self_service",
            }
            ok, patient = api_request("POST", "/patients", json=patient_payload)
            if not ok:
                st.error(patient)
                return
            ok, appointment = api_request(
                "POST",
                "/appointments",
                json={
                    "patient_id": patient["uhid"],
                    "doctor_id": selected_doctor["uhid"],
                    "slot_id": slot_options[selected_slot],
                    "date": appointment_date.isoformat(),
                    "notes": problem.strip() or None,
                    "priority": "normal",
                },
            )
            if ok:
                st.success(
                    f"Appointment booked for {patient['full_name']} with Dr. {selected_doctor['full_name']} on {appointment_date} at {appointment['start_time']}."
                )
                st.session_state.last_appointment_id = appointment["appointment_id"]
            else:
                st.error(appointment)
    elif submitted:
        st.info("No available slots for the selected doctor and date.")


def render_patient_registration_form(*, context: str) -> None:
    prefix = f"{context}_registration"
    with st.form(f"{prefix}_patient_form", clear_on_submit=True):
        st.markdown("#### Patient Details")
        full_name = st.text_input("Full Name", key=f"{prefix}_name")
        email = st.text_input("Email", key=f"{prefix}_email")
        mobile = st.text_input("Mobile", key=f"{prefix}_mobile")
        col1, col2 = st.columns(2)
        with col1:
            date_of_birth = st.date_input("Date of Birth", value=date(1995, 1, 1), min_value=EARLIEST_DOB, max_value=date.today(), key=f"{prefix}_dob")
            gender = st.selectbox("Gender", GENDERS, key=f"{prefix}_gender")
        with col2:
            blood_group = st.selectbox("Blood Group", [""] + BLOOD_GROUPS, key=f"{prefix}_blood")
            address = st.text_area("Address", height=70, key=f"{prefix}_address")
        submitted = st.form_submit_button("Register Patient", use_container_width=True)

    if submitted:
        patient_payload = {
            "full_name": full_name.strip(),
            "email": email.strip().lower(),
            "mobile": mobile.strip(),
            "date_of_birth": date_of_birth.isoformat(),
            "gender": gender,
            "blood_group": blood_group or None,
            "address": address.strip() or None,
            "registered_by": current_role() or "self_service",
        }
        ok, patient = api_request("POST", "/patients", json=patient_payload)
        if ok:
            st.success(f"Patient registered: {patient['full_name']}")
            st.rerun()
        else:
            st.error(patient)


def render_login() -> None:
    st.markdown('<div class="login-card"><div class="login-logo">MediFlow HMS</div><div class="login-subtitle">Sign in to access the clinical workspace</div></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        notice = pop_auth_notice()
        if notice:
            st.success(notice)
        with st.form("login_form"):
            role = st.selectbox("Role", ["admin", "front_desk", "doctor", "patient", "nurse"])
            identifier_help = {
                "admin": "Use username: admin",
                "front_desk": "Use username: frontdesk",
                "doctor": "Use your registered email",
                "patient": "Use your registered email",
                "nurse": "Use your registered email",
            }
            st.caption(identifier_help[role])
            identifier = st.text_input("Identifier")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign In", use_container_width=True)
            if submit:
                ok, result = api_request(
                    "POST",
                    "/auth/login",
                    json={"identifier": identifier.strip(), "password": password, "role": role},
                )
                if ok:
                    st.session_state.auth_token = result["access_token"]
                    st.session_state.current_user = result["user"]
                    st.rerun()
                else:
                    st.error(result)
        st.caption("Default admin: admin / admin123 · Front desk: frontdesk / frontdesk123 · Staff and patients use mobile as password.")
        st.markdown("---")
        st.subheader("Patient Registration")
        render_patient_registration_access(context="login")


def load_report(report_date: date, doctor_id: Optional[str] = None) -> dict[str, Any]:
    params = {"doctor_id": doctor_id} if doctor_id else None
    ok, payload = api_request("GET", f"/reports/{report_date.isoformat()}", params=params)
    return payload if ok and isinstance(payload, dict) else {}


def load_audit_logs(event: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if event:
        params["event"] = event
    ok, payload = api_request("GET", "/reports/audit/logs", params=params)
    return payload if ok and isinstance(payload, list) else []


def load_appointments_for_view(
    appointment_date: Optional[date] = None,
    doctor_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if appointment_date:
        params["date_filter"] = appointment_date.isoformat()
    if doctor_id:
        params["doctor_id"] = doctor_id
    ok, payload = api_request("GET", "/appointments", params=params or None)
    return payload if ok and isinstance(payload, list) else []


def appointment_display_label(row: dict[str, Any]) -> str:
    doctor_name = row.get("doctor_name") or "Doctor"
    patient_name = row.get("patient_name") or "Patient"
    return f"{row.get('date')} | {row.get('start_time')} | {patient_name} with Dr. {doctor_name}"


def llm_enabled() -> bool:
    ok, payload = api_request("GET", "/health")
    return bool(ok and payload)


def safe_frame(records: list[dict[str, Any]], columns: Optional[list[str]] = None) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=columns or [])
    frame = pd.DataFrame(records)
    if columns:
        for column in columns:
            if column not in frame.columns:
                frame[column] = None
        frame = frame[columns]
    return frame


def build_identity_index(records: list[dict[str, Any]], primary_key: str, *, alternate_key: Optional[str] = None) -> dict[str, str]:
    index: dict[str, str] = {}
    for record in records:
        name = str(record.get("full_name", "")).strip()
        for key in (primary_key, alternate_key):
            if key and record.get(key):
                index[str(record[key])] = name
    return index


def resolve_entity_name(
    entity_type: str,
    identifier: Any,
    *,
    index: Optional[dict[str, str]] = None,
    endpoint: Optional[str] = None,
) -> str:
    if identifier is None:
        return ""

    lookup_value = str(identifier).strip()
    if not lookup_value:
        return ""

    if index and lookup_value in index:
        return index[lookup_value]

    cache = st.session_state.setdefault("entity_name_cache", {}).setdefault(entity_type, {})
    if lookup_value in cache:
        return cache[lookup_value]

    if endpoint:
        ok, payload = api_request("GET", f"{endpoint}/{lookup_value}")
        if ok and isinstance(payload, dict):
            name = str(payload.get("full_name", "")).strip()
            if name:
                cache[lookup_value] = name
                for key in ("patient_id", "doctor_id", "nurse_id", "uhid"):
                    if payload.get(key):
                        cache[str(payload[key])] = name
                return name

    return ""


def enrich_appointment_rows(
    rows: list[dict[str, Any]],
    *,
    patient_index: dict[str, str],
    doctor_index: dict[str, str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["patient_name"] = resolve_entity_name(
            "patient",
            row.get("patient_id"),
            index=patient_index,
            endpoint="/patients",
        )
        item["doctor_name"] = resolve_entity_name(
            "doctor",
            row.get("doctor_id"),
            index=doctor_index,
            endpoint="/doctors",
        )
        enriched.append(item)
    return enriched


def enrich_triage_rows(
    rows: list[dict[str, Any]],
    *,
    patient_index: dict[str, str],
    doctor_index: dict[str, str],
    nurse_index: dict[str, str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["patient_name"] = resolve_entity_name(
            "patient",
            row.get("patient_id"),
            index=patient_index,
            endpoint="/patients",
        )
        item["doctor_name"] = resolve_entity_name(
            "doctor",
            row.get("doctor_id"),
            index=doctor_index,
            endpoint="/doctors",
        )
        item["nurse_name"] = resolve_entity_name(
            "nurse",
            row.get("nurse_id"),
            index=nurse_index,
            endpoint="/nurses",
        )
        enriched.append(item)
    return enriched


def enrich_queue_rows(
    rows: list[dict[str, Any]],
    *,
    patient_index: dict[str, str],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["patient_name"] = resolve_entity_name(
            "patient",
            row.get("patient_id"),
            index=patient_index,
            endpoint="/patients",
        )
        enriched.append(item)
    return enriched


def doctor_lookup_map(doctors: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        f"{doc['full_name']}  |  {doc.get('specialization', 'Doctor')}": doc
        for doc in doctors
    }


def patient_lookup_map(patients: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        f"{pat['full_name']}  |  {pat.get('mobile', pat.get('email', 'Patient'))}": pat
        for pat in patients
    }


def parse_time_value(value: Any, fallback: str) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        return time.fromisoformat(value)
    return time.fromisoformat(fallback)


def render_metric_card(label: str, value: Any, subtle: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-subtle">{subtle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero(health: dict[str, Any], patients: list[dict[str, Any]], doctors: list[dict[str, Any]], today_report: dict[str, Any]) -> None:
    pg_on = health.get("postgres", False)
    mg_on = health.get("mongo", False)
    pg_dot = "online" if pg_on else "offline"
    mg_dot = "online" if mg_on else "offline"
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="hero-kicker">Operations Cockpit</div>
            <h1 class="hero-title">Real-time patient flow, scheduling &amp; queue control.</h1>
            <div class="hero-copy">
                Your unified clinical workspace — registrations, appointments, triage,
                live queues, and AI-powered insights from a single dashboard.
            </div>
            <div class="hero-stat-grid">
                <div class="hero-stat">
                    <div class="hero-stat-label">Patients</div>
                    <div class="hero-stat-value">{len(patients)}</div>
                </div>
                <div class="hero-stat">
                    <div class="hero-stat-label">Doctors</div>
                    <div class="hero-stat-value">{len(doctors)}</div>
                </div>
                <div class="hero-stat">
                    <div class="hero-stat-label">Booked Today</div>
                    <div class="hero-stat-value">{today_report.get("total_appointments", 0)}</div>
                </div>
            </div>
            <div style="display:flex; gap:0.6rem; flex-wrap:wrap; margin-top:1.2rem; align-items:center;">
                <span class="pill pill-brand"><span class="status-dot {pg_dot}"></span>Postgres</span>
                <span class="pill pill-cyan"><span class="status-dot {mg_dot}"></span>MongoDB</span>
                <span class="pill pill-green">FastAPI + Streamlit</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_controls() -> str:
    with st.sidebar:
        st.markdown("## MediFlow HMS")
        st.caption("Clinical operations dashboard")
        user = current_user()
        if user:
            role_label = user.get("role", "unknown").upper()
            display = user.get("display_name", user.get("user_id", "User"))
            st.markdown(f"**{display}**")
            st.caption(role_label)
        st.markdown("---")
        if st.button("Refresh", use_container_width=True):
            st.rerun()
        st.markdown("---")
        role = current_role()
        page_options = {
            "admin":      ["Overview", "Patients", "Doctors", "Nurses", "Appointments", "Scheduling", "Reports", "Audit Logs", "AI Assistant"],
            "front_desk": ["Overview", "Patients", "Appointments", "Nurse Assignments", "AI Assistant"],
            "doctor":     ["Overview", "Appointments", "Scheduling", "Queue", "Prescriptions", "AI Assistant"],
            "patient":    ["Overview", "Appointments", "Doctors", "Triage", "Prescriptions", "AI Assistant"],
            "nurse":      ["Overview", "Patients", "Appointments", "Triage", "Nurse Assignments", "AI Assistant"],
        }.get(role, ["Overview"])
        page = st.radio("Navigate", page_options, label_visibility="collapsed")
        st.markdown("---")
        if user:
            with st.expander("Change Password"):
                current_password = st.text_input("Current Password", type="password", key="sidebar_current_password")
                new_password = st.text_input("New Password", type="password", key="sidebar_new_password")
                if st.button("Update Password", use_container_width=True):
                    ok, result = api_request(
                        "POST",
                        "/auth/change-password",
                        json={"current_password": current_password, "new_password": new_password},
                    )
                    if ok:
                        st.success("Password updated.")
                    else:
                        st.error(result)
        if user and st.button("Sign Out", use_container_width=True):
            for key in ("auth_token", "current_user", "appointment_payload", "last_appointment_id"):
                st.session_state.pop(key, None)
            set_auth_screen("login")
            st.rerun()
    return page


def render_save_to_drive(records: list[dict], record_type: str, label_maker, id_key: str, key_prefix: str) -> None:
    with st.expander("Save to Google Drive as PDF"):
        options = {label_maker(r): r for r in records}
        if not options:
            st.info("No records available to save.")
            return
        selected = st.selectbox(f"Select {record_type.capitalize()} Record", list(options.keys()), key=f"{key_prefix}_select")
        if st.button("Generate & Save to Drive", key=f"{key_prefix}_btn", use_container_width=True):
            with st.spinner("Generating PDF and uploading..."):
                r_id = options[selected][id_key]
                ok, result = api_request("POST", "/gsuite/drive/patient-save", json={"record_type": record_type, "record_id": r_id})
                if ok:
                    st.success("PDF saved to Google Drive successfully!")
                    if isinstance(result, dict):
                        web_link = result.get("webViewLink") or ""
                        file_id = result.get("id") or ""
                        if not web_link and file_id:
                            web_link = f"https://drive.google.com/file/d/{file_id}/view"
                        if web_link:
                            st.markdown(f"**[📂 Open PDF in Google Drive]({web_link})**")
                    st.info(
                        "The file has been shared with your registered email address. "
                        "Check **Shared with me** in Google Drive if you cannot find it directly."
                    )
                else:
                    st.error(f"Failed to save: {result}")

def render_overview(patients: list[dict[str, Any]], doctors: list[dict[str, Any]], health: dict[str, Any]) -> None:
    today = date.today()
    report = load_report(today)
    if current_role() == "patient":
        patient_id = current_user().get("linked_patient_id")
        st.markdown('<div class="page-header"><div class="section-title">My Care History</div><div class="section-copy">Appointments, vitals, and prescriptions recorded for your visits.</div></div>', unsafe_allow_html=True)
        ok_appt, appointments = api_request("GET", "/appointments")
        ok_triage, triage_rows = api_request("GET", f"/triage/patient/{patient_id}")
        ok_rx, prescriptions = api_request("GET", f"/prescriptions/patient/{patient_id}")
        tab1, tab2, tab3 = st.tabs(["Appointments", "Triage Results", "Prescriptions"])
        with tab1:
            if ok_appt and appointments:
                enriched = enrich_appointment_rows(appointments, patient_index={}, doctor_index=build_identity_index(doctors, "doctor_id", alternate_key="uhid"))
                st.dataframe(safe_frame(enriched, ["doctor_name", "date", "start_time", "status", "notes"]), use_container_width=True, hide_index=True)
            else:
                st.info("No appointment history yet.")
        with tab2:
            if ok_triage and triage_rows:
                st.dataframe(safe_frame(triage_rows, ["date", "queue_type", "blood_pressure", "heart_rate", "temperature", "oxygen_saturation", "symptoms", "notes"]), use_container_width=True, hide_index=True)
                render_save_to_drive(
                    triage_rows, 
                    "triage", 
                    lambda r: f"{r.get('date')} - Queue: {r.get('queue_type')}",
                    "triage_id",
                    "triage_overview_drive"
                )
            else:
                st.info("No triage records yet.")
        with tab3:
            if ok_rx and prescriptions:
                st.dataframe(safe_frame(prescriptions, ["created_at", "doctor_name", "doctor_specialization", "diagnosis", "medicines", "advice", "follow_up_date"]), use_container_width=True, hide_index=True)
                render_save_to_drive(
                    prescriptions,
                    "prescription",
                    lambda r: f"{r.get('diagnosis')} (Dr. {r.get('doctor_name')}) - {r.get('created_at', '')[:10]}",
                    "prescription_id",
                    "rx_overview_drive"
                )
            else:
                st.info("No prescriptions yet.")
        return
    render_hero(health, patients, doctors, report)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Total Patients", len(patients), "Active registry")
    with c2:
        render_metric_card("Total Doctors", len(doctors), "Clinical network")
    with c3:
        render_metric_card("Completed Today", report.get("total_completed", 0), "Daily throughput")
    with c4:
        render_metric_card("Cancellation Rate", f"{report.get('cancellation_rate_pct', 0)}%", "Operational leakage")

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown('<div class="section-title">Recent Registry</div><div class="section-copy">Latest patients and doctors.</div>', unsafe_allow_html=True)
        tabs = st.tabs(["Patients", "Doctors"])
        with tabs[0]:
            patient_df = safe_frame(
                patients,
                ["full_name", "mobile", "email", "visit_type", "registration_date"],
            ).tail(10)
            st.dataframe(patient_df, use_container_width=True, hide_index=True)
        with tabs[1]:
            doctor_df = safe_frame(
                doctors,
                ["full_name", "specialization", "work_start_time", "work_end_time"],
            ).tail(10)
            st.dataframe(doctor_df, use_container_width=True, hide_index=True)

    with right:
        st.markdown('<div class="section-title">Daily Pulse</div><div class="section-copy">Quick operational snapshot for today.</div>', unsafe_allow_html=True)
        st.metric("Booked", report.get("total_appointments", 0))
        st.metric("No Shows", report.get("total_no_shows", 0))
        st.metric("Slot Utilization", f"{report.get('slot_utilization_pct', 0)}%")
        busiest = report.get("busiest_doctor_name") or "Not enough data"
        st.info(f"Busiest doctor today: {busiest}")


def render_nurse_assignment() -> None:
    """Front desk: assign a nurse to a booked appointment for today."""
    st.subheader("Nurse Assignments")
    ok_nurses, nurses_data = api_request("GET", "/nurses")
    nurses = nurses_data if ok_nurses and isinstance(nurses_data, list) else []
    if not nurses:
        st.info("No nurses registered yet.")
        return

    nurse_map = {n["full_name"]: n for n in nurses}

    ok_apts, apts = api_request("GET", f"/appointments/nurse-assignments/{date.today().isoformat()}")
    if not ok_apts or not isinstance(apts, list) or not apts:
        st.info("No booked appointments for today.")
        return

    ok_patients, patients_data = api_request("GET", "/patients")
    ok_doctors, doctors_data = api_request("GET", "/doctors")
    patient_map = {p["patient_id"]: p["full_name"] for p in (patients_data if ok_patients and isinstance(patients_data, list) else [])}
    doctor_map = {d["doctor_id"]: d["full_name"] for d in (doctors_data if ok_doctors and isinstance(doctors_data, list) else [])}

    for apt in apts:
        apt_id = apt["appointment_id"]
        patient_name = patient_map.get(apt["patient_id"], apt["patient_id"])
        doctor_name = doctor_map.get(apt["doctor_id"], apt["doctor_id"])
        assigned_nurse_id = apt.get("assigned_nurse_id")
        assigned_label = next((n["full_name"] for n in nurses if n["nurse_id"] == assigned_nurse_id), None)

        with st.expander(
            f"{patient_name} — Dr. {doctor_name} at {apt['start_time']}"
            + (f" | Nurse: {assigned_label}" if assigned_label else " | Unassigned"),
            expanded=not bool(assigned_label),
        ):
            selected_nurse = st.selectbox(
                "Assign nurse",
                list(nurse_map.keys()),
                index=list(nurse_map.keys()).index(assigned_label) if assigned_label in nurse_map else 0,
                key=f"assign_nurse_{apt_id}",
            )
            btn_label = "Reassign Nurse" if assigned_label else "Assign Nurse"
            endpoint = "reassign-nurse" if assigned_label else "assign-nurse"
            if st.button(btn_label, key=f"assign_btn_{apt_id}"):
                ok, result = api_request(
                    "POST",
                    f"/appointments/{apt_id}/{endpoint}",
                    json={"nurse_id": nurse_map[selected_nurse]["nurse_id"]},
                )
                if ok:
                    st.success(f"Nurse {selected_nurse} assigned to {patient_name}.")
                    st.rerun()
                else:
                    st.error(result)


def render_nurse_assignments_page() -> None:
    """Dedicated page: front desk assigns nurses; nurses reassign their patients."""
    role = current_role()
    st.markdown(
        '<div class="page-header">'
        '<div class="section-title">Nurse Assignments</div>'
        '<div class="section-copy">'
        'Front desk: assign a nurse to each booked appointment. '
        'Nurses: reassign your patients to a colleague if unavailable.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    ok_nurses, nurses_data = api_request("GET", "/nurses")
    nurses = nurses_data if ok_nurses and isinstance(nurses_data, list) else []
    if not nurses:
        st.info("No nurses are registered yet.")
        return

    ok_apts, apts_raw = api_request("GET", f"/appointments/nurse-assignments/{date.today().isoformat()}")
    apts = apts_raw if ok_apts and isinstance(apts_raw, list) else []

    ok_p, pd_raw = api_request("GET", "/patients")
    ok_d, dd_raw = api_request("GET", "/doctors")
    patient_map = {p["patient_id"]: p["full_name"] for p in (pd_raw if ok_p and isinstance(pd_raw, list) else [])}
    doctor_map  = {d["doctor_id"]: d["full_name"] for d in (dd_raw if ok_d and isinstance(dd_raw, list) else [])}
    nurse_map   = {n["full_name"]: n for n in nurses}
    nurse_id_map = {n["nurse_id"]: n["full_name"] for n in nurses}

    if not apts:
        st.info("No booked appointments for today.")
        return

    if role == "front_desk":
        st.subheader(f"Today's appointments — {date.today().strftime('%d %b %Y')}")
        for apt in apts:
            apt_id = apt["appointment_id"]
            patient_name  = patient_map.get(apt["patient_id"], apt["patient_id"])
            doctor_name   = doctor_map.get(apt["doctor_id"], apt["doctor_id"])
            assigned_id   = apt.get("assigned_nurse_id")
            assigned_name = nurse_id_map.get(assigned_id) if assigned_id else None

            with st.expander(
                f"{apt.get('start_time', '')}  |  {patient_name}  →  Dr. {doctor_name}"
                + (f"  ✅ Nurse: {assigned_name}" if assigned_name else "  ⚠ Unassigned"),
                expanded=not bool(assigned_name),
            ):
                selected = st.selectbox(
                    "Select nurse",
                    list(nurse_map.keys()),
                    index=list(nurse_map.keys()).index(assigned_name) if assigned_name in nurse_map else 0,
                    key=f"fd_assign_{apt_id}",
                )
                btn_label = "Reassign Nurse" if assigned_name else "Assign Nurse"
                endpoint  = "reassign-nurse" if assigned_name else "assign-nurse"
                if st.button(btn_label, key=f"fd_assign_btn_{apt_id}", use_container_width=True):
                    ok_r, res = api_request(
                        "POST",
                        f"/appointments/{apt_id}/{endpoint}",
                        json={"nurse_id": nurse_map[selected]["nurse_id"]},
                    )
                    if ok_r:
                        st.success(f"Nurse {selected} assigned to {patient_name}.")
                        st.rerun()
                    else:
                        st.error(res)

    elif role == "nurse":
        my_nurse_id = current_user().get("linked_nurse_id")
        my_apts = [a for a in apts if a.get("assigned_nurse_id") == my_nurse_id]
        other_nurses = {n["full_name"]: n for n in nurses if n["nurse_id"] != my_nurse_id}

        if not my_apts:
            st.info("You have no patients assigned to you today.")
            return

        st.subheader("Your assigned patients — reassign if unavailable")
        if not other_nurses:
            st.warning("No other nurses available to reassign to.")
            return

        for apt in my_apts:
            apt_id       = apt["appointment_id"]
            patient_name = patient_map.get(apt["patient_id"], apt["patient_id"])
            doctor_name  = doctor_map.get(apt["doctor_id"], apt["doctor_id"])
            with st.expander(
                f"{apt.get('start_time', '')}  |  {patient_name}  →  Dr. {doctor_name}",
                expanded=True,
            ):
                target = st.selectbox(
                    "Reassign to nurse",
                    list(other_nurses.keys()),
                    key=f"nurse_reassign_{apt_id}",
                )
                if st.button(f"Reassign to {target}", key=f"nurse_reassign_btn_{apt_id}", use_container_width=True):
                    ok_r, res = api_request(
                        "POST",
                        f"/appointments/{apt_id}/reassign-nurse",
                        json={"nurse_id": other_nurses[target]["nurse_id"]},
                    )
                    if ok_r:
                        st.success(f"{patient_name} reassigned to {target}.")
                        st.rerun()
                    else:
                        st.error(res)


def render_patients(patients: list[dict[str, Any]]) -> None:
    role = current_role()
    st.markdown('<div class="page-header"><div class="section-title">Patient Registry</div><div class="section-copy">Search registered patients and handle patient intake without exposing internal IDs.</div></div>', unsafe_allow_html=True)
    left, right = st.columns([1, 1.2])

    with left:
        if role == "front_desk":
            st.subheader("Patient Intake")
            render_patient_intake_booking(load_doctors(), context=f"{role}_patients")
            st.markdown("---")
            render_forms_sync_controls(context=f"{role}_patients")
        elif role == "nurse":
            st.subheader("Patient Registration")
            render_patient_registration_form(context=f"{role}_patients")
            st.markdown("---")
            render_forms_sync_controls(context=f"{role}_patients")
        elif role == "admin":
            render_forms_sync_controls(context="admin")

    with right:
        search = st.text_input("Search registry")
        patient_df = safe_frame(
            patients,
            ["full_name", "mobile", "email", "gender", "visit_count", "visit_type", "registration_date"],
        )
        if search:
            mask = patient_df.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False))
            patient_df = patient_df[mask.any(axis=1)]
        st.dataframe(patient_df, use_container_width=True, hide_index=True)


def render_doctors(doctors: list[dict[str, Any]]) -> None:
    role = current_role()
    st.markdown('<div class="page-header"><div class="section-title">Doctor Network</div><div class="section-copy">View available doctors by date, specialization, and working hours.</div></div>', unsafe_allow_html=True)
    if role != "admin":
        view_date = st.date_input("Available On", min_value=date.today(), value=next_weekday(), key="doctor_availability_date")
        spec_filter = st.selectbox("Specialization", ["All"] + SPECIALIZATIONS, key="doctor_specialization_filter")
        rows = []
        for doctor in doctors:
            if spec_filter != "All" and doctor.get("specialization") != spec_filter:
                continue
            ok, slots = api_request("GET", f"/slots/{doctor['uhid']}/{view_date.isoformat()}")
            available = len(slots) if ok and isinstance(slots, list) else 0
            rows.append({
                "Doctor": doctor.get("full_name"),
                "Specialization": doctor.get("specialization"),
                "Work Hours": f"{doctor.get('work_start_time')} - {doctor.get('work_end_time')}",
                "Available Slots": available,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        return

    left, right = st.columns([1, 1.2])

    with left:
        with st.form("doctor_registration_form", clear_on_submit=True):
            st.subheader("Register Doctor")
            full_name = st.text_input("Doctor Name")
            email = st.text_input("Doctor Email")
            mobile = st.text_input("Doctor Mobile")
            specialization = st.selectbox("Specialization", SPECIALIZATIONS)
            max_patients = st.number_input("Max Patients Per Day", min_value=1, max_value=100, value=20)
            work_start = st.time_input("Work Start Time", value=time(9, 0))
            work_end = st.time_input("Work End Time", value=time(17, 0))
            consult = st.selectbox("Consultation Duration", [10, 15, 20, 30], index=1)
            submit = st.form_submit_button("Create Doctor", use_container_width=True)

            if submit:
                payload = {
                    "full_name": full_name,
                    "email": email,
                    "mobile": mobile,
                    "specialization": specialization,
                    "max_patients_per_day": int(max_patients),
                    "work_start_time": work_start.isoformat(),
                    "work_end_time": work_end.isoformat(),
                    "consultation_duration_minutes": consult,
                }
                ok, result = api_request("POST", "/doctors", json=payload)
                if ok:
                    st.success(f"Doctor created: {result['full_name']}")
                    st.rerun()
                else:
                    st.error(result)

        st.markdown("---")
        st.info("Smart symptom-to-doctor guidance now lives in the AI Assistant page, where recommendations are generated from the active doctor roster.")

    with right:
        st.markdown("#### Active Doctors")
        doctor_df = safe_frame(
            doctors,
            [
                "full_name",
                "specialization",
                "work_start_time",
                "work_end_time",
                "consultation_duration_minutes",
            ],
        )
        st.dataframe(doctor_df, use_container_width=True, hide_index=True)


def render_scheduling(doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Scheduling Studio</div><div class="section-copy">Slots are auto-generated from each doctor\'s fixed work hours. Inspect generated slots below.</div></div>', unsafe_allow_html=True)
    if not doctors:
        st.warning("Register at least one doctor before inspecting slots.")
        return

    doctor_map = doctor_lookup_map(doctors)
    role = current_role()
    doctor_labels = list(doctor_map.keys())
    if role == "doctor":
        doctor_labels = [
            label for label, doc in doctor_map.items()
            if doc["doctor_id"] == current_user().get("linked_doctor_id")
        ]
    selected_label = st.selectbox("Doctor", doctor_labels)
    selected_doctor = doctor_map[selected_label]

    st.info(
        f"Doctor work hours: {selected_doctor.get('work_start_time', '09:00')} – "
        f"{selected_doctor.get('work_end_time', '17:00')} | "
        f"Consultation: {selected_doctor.get('consultation_duration_minutes', 15)} min | "
        f"Slots are auto-generated for each weekday."
    )

    slot_date = st.date_input("Inspect Slot Date", value=next_weekday(), key="slot_date")
    endpoint = f"/slots/{selected_doctor['uhid']}/{slot_date.isoformat()}/all" if role in {"admin", "doctor"} else f"/slots/{selected_doctor['uhid']}/{slot_date.isoformat()}"
    if st.button("Load Slots", use_container_width=True):
        ok, result = api_request("GET", endpoint)
        if ok:
            st.session_state.schedule_slots = result
        else:
            st.error(result)
    schedule_slots = [
        slot for slot in st.session_state.get("schedule_slots", [])
        if slot.get("doctor_id") == selected_doctor["doctor_id"]
        and slot.get("date") == slot_date.isoformat()
    ]
    if schedule_slots:
        slot_df = safe_frame(schedule_slots, ["label", "start_time", "end_time", "is_booked", "is_blocked"])
        st.dataframe(slot_df, use_container_width=True, hide_index=True)
        if role == "doctor":
            editable = {
                f"{slot.get('label') or slot['start_time']} ({'booked' if slot.get('is_booked') else 'blocked' if slot.get('is_blocked') else 'open'})": slot
                for slot in schedule_slots
                if not slot.get("is_lunch_break")
            }
            slot_label = st.selectbox("Slot to Update", list(editable.keys()))
            selected_slot = editable[slot_label]
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Block Slot", use_container_width=True, disabled=selected_slot.get("is_booked")):
                    ok, result = api_request("PATCH", f"/slots/{selected_slot['slot_id']}", json={"is_blocked": True})
                    if ok:
                        st.success("Slot blocked.")
                    else:
                        st.error(result)
            with col_b:
                if st.button("Unblock Slot", use_container_width=True):
                    ok, result = api_request("PATCH", f"/slots/{selected_slot['slot_id']}", json={"is_blocked": False})
                    if ok:
                        st.success("Slot reopened.")
                    else:
                        st.error(result)
    elif st.session_state.get("schedule_slots") is not None:
        st.info("No slots found for this doctor on that date. Slots auto-generate for weekdays only.")


def render_patient_appointment_management(
    appointment_rows: list[dict[str, Any]],
    *,
    doctor_index: dict[str, str],
) -> None:
    st.markdown("---")
    st.markdown("#### Manage My Appointments")
    active_rows = [
        row for row in appointment_rows
        if row.get("status") in {"booked", "rescheduled"}
    ]
    if not active_rows:
        st.info("No active appointments are available to manage.")
        return

    enriched_rows = enrich_appointment_rows(active_rows, patient_index={}, doctor_index=doctor_index)
    appointment_options = {
        appointment_display_label(row): row
        for row in enriched_rows
    }
    selected_label = st.selectbox("Appointment", list(appointment_options.keys()), key="patient_manage_appointment")
    selected_appointment = appointment_options[selected_label]

    action = st.radio("Action", ["Cancel", "Reschedule"], horizontal=True, key="patient_manage_action")
    if action == "Cancel":
        reason = st.text_area("Cancellation Reason", height=90, key="patient_cancel_reason")
        if st.button("Cancel Appointment", use_container_width=True, key="patient_cancel_appointment"):
            if len(reason.strip()) < 10:
                st.warning("Enter a cancellation reason with at least 10 characters.")
                return
            ok, result = api_request(
                "POST",
                f"/appointments/{selected_appointment['appointment_id']}/cancel",
                json={"reason": reason.strip(), "cancelled_by": current_user().get("display_name", "patient")},
            )
            if ok:
                st.success("Appointment cancelled.")
                st.session_state.pop("appointment_rows", None)
            else:
                st.error(result)
        return

    new_date = st.date_input("New Appointment Date", min_value=date.today(), value=next_weekday(), key="patient_reschedule_date")
    if st.button("Load Available Slots", use_container_width=True, key="patient_load_reschedule_slots"):
        ok, result = api_request("GET", f"/slots/{selected_appointment['doctor_id']}/{new_date.isoformat()}")
        if ok:
            st.session_state.patient_reschedule_slots = result
        else:
            st.error(result)

    slots = [
        slot for slot in st.session_state.get("patient_reschedule_slots", [])
        if slot.get("doctor_id") == selected_appointment["doctor_id"]
        and slot.get("date") == new_date.isoformat()
    ]
    slot_options = {
        slot.get("label") or f"{slot['start_time']} - {slot['end_time']}": slot
        for slot in slots
    }
    if not slot_options:
        st.info("Load available slots for the new date.")
        return

    slot_label = st.selectbox("New Slot", list(slot_options.keys()), key="patient_new_slot")
    if st.button("Reschedule Appointment", use_container_width=True, key="patient_reschedule_appointment"):
        ok, result = api_request(
            "POST",
            f"/appointments/{selected_appointment['appointment_id']}/reschedule",
            json={"new_slot_id": slot_options[slot_label]["slot_id"], "new_date": new_date.isoformat()},
        )
        if ok:
            st.success("Appointment rescheduled.")
            st.session_state.pop("appointment_rows", None)
            st.session_state.pop("patient_reschedule_slots", None)
        else:
            st.error(result)


def render_appointments(patients: list[dict[str, Any]], doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Appointments</div><div class="section-copy">Load appointment lists and keep booking actions in their own front-desk section.</div></div>', unsafe_allow_html=True)
    if (current_role() != "doctor" and not patients) or not doctors:
        st.warning("You need at least one patient and one doctor before booking appointments.")
        return

    role = current_role()
    user = current_user()
    patient_map = patient_lookup_map(patients)
    doctor_map = doctor_lookup_map(doctors)
    patient_index = build_identity_index(patients, "patient_id", alternate_key="uhid")
    doctor_index = build_identity_index(doctors, "doctor_id", alternate_key="uhid")
    browse_left, browse_right = st.columns([1, 1])

    with browse_left:
        st.markdown("#### Appointment Browser")
        browse_mode = "Single Doctor" if role == "doctor" else st.radio(
            "View Scope",
            ["All Doctors", "Single Doctor"],
            horizontal=True,
            key="appointment_browse_mode",
        )
        filter_by_date = st.checkbox("Filter by date", value=True, key="appointment_filter_by_date")
        browse_date = st.date_input("Browse Date", value=date.today(), key="appointment_browse_date", disabled=not filter_by_date)
        browse_doctor_id = None
        if role == "doctor":
            browse_mode = "Single Doctor"
            browse_doctor_id = user.get("linked_doctor_id")
            st.caption("Showing only your appointments.")
        elif browse_mode == "Single Doctor":
            browse_doctor_label = st.selectbox("Browse Doctor", list(doctor_map.keys()), key="appointment_browse_doctor")
            browse_doctor_id = doctor_map[browse_doctor_label]["uhid"]
        # For patients, auto-load so agent-booked appointments always appear
        if role == "patient" and "appointment_rows" not in st.session_state:
            st.session_state.appointment_rows = load_appointments_for_view()
        if st.button("Refresh Appointments" if role == "patient" else "Load Appointment List", use_container_width=True):
            st.session_state.appointment_rows = load_appointments_for_view(
                browse_date if filter_by_date else None,
                browse_doctor_id,
            )

    with browse_right:
        rows = st.session_state.get("appointment_rows", [])
        if rows:
            appointment_rows = enrich_appointment_rows(rows, patient_index=patient_index, doctor_index=doctor_index)
            appointment_df = safe_frame(
                appointment_rows,
                [
                    "patient_name",
                    "doctor_name",
                    "date",
                    "start_time",
                    "end_time",
                    "status",
                    "priority",
                    "reschedule_count",
                ],
            )
            st.dataframe(appointment_df, use_container_width=True, hide_index=True)
        else:
            st.info("Load a date range above to inspect doctor-wise or all-doctor appointments.")

    if role == "patient":
        render_patient_appointment_management(rows, doctor_index=doctor_index)
        return

    if role not in {"front_desk", "nurse"}:
        return

    st.markdown("---")
    book_col, _ = st.columns([1.1, 0.9])

    with book_col:
        st.markdown("#### Appointment Booking")
        patient_labels = list(patient_map.keys())
        patient_label = st.selectbox("Patient", patient_labels)
        doctor_label = st.selectbox("Doctor", list(doctor_map.keys()))
        appt_date = st.date_input("Appointment Date", min_value=date.today(), value=next_weekday(), key="appt_date")
        notes = st.text_area("Clinical Notes", height=90)

        if st.button("Load Available Slots", use_container_width=True):
            selected_doctor = doctor_map[doctor_label]
            ok, result = api_request("GET", f"/slots/{selected_doctor['uhid']}/{appt_date.isoformat()}")
            if ok:
                st.session_state.booking_slots = result
            else:
                st.error(result)

        slots = [
            slot for slot in st.session_state.get("booking_slots", [])
            if slot.get("doctor_id") == doctor_map[doctor_label]["doctor_id"]
            and slot.get("date") == appt_date.isoformat()
        ]
        slot_options = {
            slot.get("label") or f"{slot['start_time']} - {slot['end_time']}": slot["slot_id"]
            for slot in slots
        }

        if slot_options:
            selected_slot_label = st.selectbox("Select Slot", list(slot_options.keys()))
            if st.button("Book Appointment", use_container_width=True):
                selected_patient = patient_map[patient_label]
                selected_doctor = doctor_map[doctor_label]
                payload = {
                    "patient_id": selected_patient["uhid"],
                    "doctor_id": selected_doctor["uhid"],
                    "slot_id": slot_options[selected_slot_label],
                    "date": appt_date.isoformat(),
                    "notes": notes or None,
                    "priority": "normal",
                }
                ok, result = api_request("POST", "/appointments", json=payload)
                if ok:
                    st.success(
                        f"Appointment booked for {selected_patient['full_name']} with Dr. {selected_doctor['full_name']}."
                    )
                    st.session_state.last_appointment_id = result["appointment_id"]
                    st.session_state.appointment_payload = enrich_appointment_rows(
                        [result],
                        patient_index=patient_index,
                        doctor_index=doctor_index,
                    )[0]
                else:
                    st.error(result)


def render_queue(doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Queue Control</div><div class="section-copy">Monitor the day queue, call the next patient, and mark completion or no-show events.</div></div>', unsafe_allow_html=True)
    if not doctors:
        st.warning("Register doctors first to use queue operations.")
        return

    doctor_map = doctor_lookup_map(doctors)
    patients = load_session_patients()
    patient_index = build_identity_index(patients, "patient_id", alternate_key="uhid")
    doctor_labels = list(doctor_map.keys())
    if current_role() == "doctor":
        doctor_labels = [
            label for label, doc in doctor_map.items()
            if doc["doctor_id"] == current_user().get("linked_doctor_id")
        ]
    doctor_label = st.selectbox("Doctor Queue", doctor_labels)
    doctor = doctor_map[doctor_label]
    queue_date = st.date_input("Queue Date", value=date.today(), key="queue_date")

    top_left, top_right = st.columns([1.1, 0.9])
    with top_left:
        if st.button("Load Queue", use_container_width=True):
            ok, result = api_request("GET", f"/queue/{doctor['uhid']}/{queue_date.isoformat()}")
            if ok:
                st.session_state.queue_rows = result
                in_progress = next((row for row in result if row.get("status") == "in-progress"), None)
                first_row = result[0] if result else None
                selected = in_progress or first_row
                st.session_state.queue_appointment_id = selected["appointment_id"] if selected else ""
            else:
                st.error(result)

        queue_rows = st.session_state.get("queue_rows", [])
        if queue_rows:
            queue_display_rows = enrich_queue_rows(queue_rows, patient_index=patient_index)
            st.dataframe(
                safe_frame(
                    queue_display_rows,
                    ["queue_position", "patient_name", "status", "is_emergency", "added_at"],
                ),
                use_container_width=True,
                hide_index=True,
            )

    with top_right:
        ok, summary = api_request("GET", f"/queue/{doctor['uhid']}/{queue_date.isoformat()}/summary")
        if ok:
            c1, c2 = st.columns(2)
            c1.metric("Total", summary["total"])
            c2.metric("Emergency", summary["emergency"])
            c3, c4 = st.columns(2)
            c3.metric("Waiting", summary["waiting"])
            c4.metric("In Progress", summary["in_progress"])

    action_col1, action_col2, action_col3 = st.columns(3)
    with action_col1:
        if st.button("Call Next Patient", use_container_width=True):
            ok, result = api_request("POST", f"/queue/{doctor['uhid']}/next", params={"queue_date": queue_date.isoformat()})
            if ok:
                patient_name = resolve_entity_name(
                    "patient",
                    result.get("patient_id"),
                    index=patient_index,
                    endpoint="/patients",
                )
                serving_label = patient_name or "Selected patient"
                st.success(f"Now serving: {serving_label}")
                st.session_state.queue_appointment_id = result["appointment_id"]
            else:
                st.error(result)

    queue_rows = st.session_state.get("queue_rows", [])
    in_progress = next((row for row in queue_rows if row.get("status") == "in-progress"), None)
    if in_progress and st.session_state.get("queue_appointment_id") != in_progress["appointment_id"]:
        st.session_state.queue_appointment_id = in_progress["appointment_id"]

    actionable_rows = [
        row for row in enrich_queue_rows(queue_rows, patient_index=patient_index)
        if row.get("status") in {"waiting", "in-progress"}
    ]
    queue_options = {
        f"{row.get('queue_position')} | {row.get('patient_name') or 'Patient'} | {row.get('status')}": row
        for row in actionable_rows
    }
    selected_queue_row = None
    if queue_options:
        selected_queue_label = st.selectbox("Queue Patient", list(queue_options.keys()))
        selected_queue_row = queue_options[selected_queue_label]
        st.session_state.queue_appointment_id = selected_queue_row["appointment_id"]
    appointment_id = st.session_state.get("queue_appointment_id", "")
    with action_col2:
        if st.button("Mark Completed", use_container_width=True):
            if not appointment_id.strip():
                st.error("Load the queue and select a patient before marking completion.")
            else:
                ok, result = api_request("POST", f"/queue/{doctor['uhid']}/{appointment_id}/complete")
                if ok:
                    st.success("Appointment marked completed.")
                else:
                    st.error(result)
    with action_col3:
        if st.button("Mark No Show", use_container_width=True):
            if not appointment_id.strip():
                st.error("Load the queue and select a patient before marking no-show.")
            else:
                ok, result = api_request("POST", f"/queue/{doctor['uhid']}/{appointment_id}/no-show")
                if ok:
                    st.success("Patient marked no-show.")
                else:
                    st.error(result)


def render_prescriptions(doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Prescriptions</div><div class="section-copy">Create prescriptions after completed visits and view patient medication history.</div></div>', unsafe_allow_html=True)
    role = current_role()
    if role == "patient":
        patient_id = current_user().get("linked_patient_id")
        ok, rows = api_request("GET", f"/prescriptions/patient/{patient_id}")
        if ok and rows:
            st.dataframe(
                safe_frame(rows, ["created_at", "doctor_name", "doctor_specialization", "diagnosis", "medicines", "advice", "follow_up_date"]),
                use_container_width=True,
                hide_index=True,
            )
            render_save_to_drive(
                rows,
                "prescription",
                lambda r: f"{r.get('diagnosis')} (Dr. {r.get('doctor_name')}) - {r.get('created_at', '')[:10]}",
                "prescription_id",
                "rx_page_drive"
            )
        else:
            st.info("No prescriptions are available yet.")
        return

    if role != "doctor":
        st.info("Prescription creation is available to doctors after completing an appointment.")
        return

    doctor_id = current_user().get("linked_doctor_id")
    appointment_date = st.date_input("Completed Appointment Date", value=date.today(), max_value=date.today(), key="rx_date")
    if st.button("Load Completed Appointments", use_container_width=True):
        rows = load_appointments_for_view(appointment_date, doctor_id)
        st.session_state.rx_completed_rows = [row for row in rows if row.get("status") == "completed"]

    patient_index = build_identity_index(load_session_patients(), "patient_id", alternate_key="uhid")
    doctor_index = build_identity_index(doctors, "doctor_id", alternate_key="uhid")
    completed_rows = enrich_appointment_rows(
        st.session_state.get("rx_completed_rows", []),
        patient_index=patient_index,
        doctor_index=doctor_index,
    )
    options = {
        f"{row.get('patient_name') or 'Patient'} | {row.get('start_time')}": row
        for row in completed_rows
    }
    if not options:
        st.info("Load completed appointments to create a prescription.")
        return

    selected = st.selectbox("Patient Visit", list(options.keys()))
    with st.form("prescription_form", clear_on_submit=True):
        diagnosis = st.text_area("Diagnosis", height=90)
        medicines = st.text_area("Medicines", height=120)
        advice = st.text_area("Advice", height=90)
        needs_follow_up = st.checkbox("Follow-up needed")
        follow_up = st.date_input("Follow-up Date", value=next_weekday(), min_value=date.today())
        if st.form_submit_button("Save Prescription", use_container_width=True):
            payload = {
                "appointment_id": options[selected]["appointment_id"],
                "diagnosis": diagnosis,
                "medicines": medicines,
                "advice": advice or None,
                "follow_up_date": follow_up.isoformat() if needs_follow_up else None,
            }
            ok, result = api_request("POST", "/prescriptions", json=payload)
            if ok:
                st.success("Prescription saved.")
            else:
                st.error(result)

    ok, rows = api_request("GET", f"/prescriptions/doctor/{doctor_id}")
    if ok and rows:
        st.markdown("#### Recent Prescriptions")
        st.dataframe(
            safe_frame(rows, ["created_at", "patient_name", "diagnosis", "medicines", "follow_up_date"]),
            use_container_width=True,
            hide_index=True,
        )


def render_reports(doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Reporting</div><div class="section-copy">Generate daily reporting views with clean executive summaries and operational charts.</div></div>', unsafe_allow_html=True)
    doctor_map = doctor_lookup_map(doctors)
    options = ["All Doctors"] + list(doctor_map.keys())
    if current_role() == "doctor":
        options = [
            label for label, doc in doctor_map.items()
            if doc["doctor_id"] == current_user().get("linked_doctor_id")
        ]
    selected = st.selectbox("Doctor Filter", options)
    selected_doctor = None if selected == "All Doctors" else doctor_map[selected]["uhid"]
    report_date = st.date_input("Report Date", value=date.today(), max_value=date.today())

    report = load_report(report_date, selected_doctor)
    if not report:
        st.warning("No report data available for the selected filters.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Appointments", report.get("total_appointments", 0))
    c2.metric("Completed", report.get("total_completed", 0))
    c3.metric("Cancelled", report.get("total_cancelled", 0))
    c4.metric("No Shows", report.get("total_no_shows", 0))

    left, right = st.columns([1, 1])
    with left:
        summary_rows = [
            {"Metric": "Busiest Doctor", "Value": report.get("busiest_doctor_name") or "N/A"},
            {"Metric": "Peak Hour", "Value": report.get("peak_hour_label") or "N/A"},
            {"Metric": "Slot Utilization", "Value": f"{report.get('slot_utilization_pct', 0)}%"},
            {"Metric": "Cancellation Rate", "Value": f"{report.get('cancellation_rate_pct', 0)}%"},
        ]
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    with right:
        chart_frame = pd.DataFrame(
            [
                {"Metric": "Completed", "Count": report.get("total_completed", 0)},
                {"Metric": "Cancelled", "Count": report.get("total_cancelled", 0)},
                {"Metric": "No Show", "Count": report.get("total_no_shows", 0)},
            ]
        )
        chart = (
            alt.Chart(chart_frame)
            .mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8)
            .encode(
                x=alt.X("Metric:N", sort=None),
                y=alt.Y("Count:Q"),
                color=alt.Color("Metric:N", scale=alt.Scale(range=["#6366f1", "#f43f5e", "#f59e0b"]), legend=None),
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)


_AUDIT_CATEGORY_MAP: dict[str, list[str]] = {
    "Registration":   ["patient_registered", "doctor_registered", "nurse_registered"],
    "Appointments":   ["appointment_booked", "appointment_cancelled", "appointment_rescheduled"],
    "Clinical":       ["triage_recorded"],
    "Failures":       [
        "patient_registered_failed", "doctor_registered_failed", "nurse_registered_failed",
        "appointment_booked_failed", "appointment_cancelled_failed", "appointment_rescheduled_failed",
        "triage_recorded_failed",
    ],
}
_ALL_KNOWN_EVENTS: list[str] = [e for events in _AUDIT_CATEGORY_MAP.values() for e in events]


def render_audit_logs() -> None:
    st.markdown(
        '<div class="page-header">'
        '<div class="section-title">Audit Logs</div>'
        '<div class="section-copy">Filter by category, event type, date range, or any combination to inspect system activity.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    if current_role() != "admin":
        st.warning("Audit logs are available only to admins.")
        return

    # ── Row 1: Category + Event Type + Rows ──────────────────────────────────
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        category_options = ["All Categories"] + list(_AUDIT_CATEGORY_MAP.keys())
        selected_category = st.selectbox("Category", category_options)

    with col2:
        if selected_category == "All Categories":
            event_pool = ["All Events"] + _ALL_KNOWN_EVENTS
        else:
            event_pool = ["All Events"] + _AUDIT_CATEGORY_MAP[selected_category]
        selected_event = st.selectbox("Event Type", event_pool)

    with col3:
        limit = st.number_input("Max Rows to Fetch", min_value=10, max_value=1000, value=500, step=50)

    # ── Row 2: Date From + Date To + Status keyword ───────────────────────────
    col4, col5, col6 = st.columns([1, 1, 1])
    with col4:
        from datetime import date as _date, timedelta as _td
        date_from = st.date_input("Date From", value=_date.today() - _td(days=7))
    with col5:
        date_to = st.date_input("Date To", value=_date.today())
    with col6:
        keyword = st.text_input("Keyword in Data", placeholder="e.g. john@example.com")

    # ── Load ──────────────────────────────────────────────────────────────────
    if st.button("Load Audit Logs", use_container_width=True):
        api_event = None if selected_event == "All Events" else selected_event
        st.session_state.audit_logs_raw = load_audit_logs(api_event, int(limit))

    raw_rows: list[dict] = st.session_state.get("audit_logs_raw", [])
    if not raw_rows:
        st.info("Set your filters above and click **Load Audit Logs**.")
        return

    # ── Client-side filtering ─────────────────────────────────────────────────
    filtered = raw_rows

    # Category filter (if no specific event selected)
    if selected_category != "All Categories" and selected_event == "All Events":
        allowed = set(_AUDIT_CATEGORY_MAP[selected_category])
        filtered = [r for r in filtered if r.get("event") in allowed]

    # Date range filter
    def _row_date(r: dict):
        ts = r.get("logged_at", "")
        try:
            return pd.to_datetime(ts).date()
        except Exception:
            return None

    filtered = [r for r in filtered if (d := _row_date(r)) is not None and date_from <= d <= date_to]

    # Keyword filter
    if keyword.strip():
        kw = keyword.strip().lower()
        def _matches(r: dict) -> bool:
            return kw in json_lib.dumps(r, ensure_ascii=False).lower()
        filtered = [r for r in filtered if _matches(r)]

    # ── Summary badges ────────────────────────────────────────────────────────
    total = len(filtered)
    event_counts: dict[str, int] = {}
    for r in filtered:
        ev = r.get("event", "unknown")
        event_counts[ev] = event_counts.get(ev, 0) + 1

    st.markdown(f"**{total} log entries** match your filters.")
    if event_counts:
        badge_html = " &nbsp;".join(
            f'<span style="background:#1f7a78;color:#fff;padding:2px 8px;border-radius:10px;font-size:0.78rem;">'
            f'{ev} ({cnt})</span>'
            for ev, cnt in sorted(event_counts.items(), key=lambda x: -x[1])
        )
        st.markdown(badge_html, unsafe_allow_html=True)

    if not filtered:
        st.warning("No logs match the selected filters.")
        return

    # ── Redact sensitive IDs ──────────────────────────────────────────────────
    sensitive_keys = {"appointment_id", "patient_id", "doctor_id", "nurse_id", "slot_id", "uhid"}

    def redact_ids(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[hidden]" if key in sensitive_keys or key.endswith("_id") else redact_ids(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact_ids(item) for item in value]
        if isinstance(value, str):
            value = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "[hidden]", value)
            value = re.sub(r"\bHMS-[A-Z]+-\d{8}-[A-F0-9]{6}\b", "[hidden]", value)
            return value
        return value

    display_rows = []
    for row in filtered:
        item = dict(row)
        data = item.get("data") or {}

        # Who performed the action
        actor_val = item.get("actor") or "system"

        # Who/what the action was performed on
        subject_val = ""
        if isinstance(data, dict):
            subject_val = (
                data.get("name") or
                data.get("full_name") or
                data.get("patient_name") or
                data.get("doctor_name") or
                data.get("nurse_name") or ""
            )
            # Append email if present for extra context
            email_val = data.get("email", "")
            if email_val and email_val not in subject_val:
                subject_val = f"{subject_val} <{email_val}>" if subject_val else email_val

        # Build a short human-readable details string from key fields
        detail_parts = []
        if isinstance(data, dict):
            for key, label in [
                ("specialization", "spec"),
                ("date", "date"),
                ("start_time", "time"),
                ("status", "status"),
                ("priority", "priority"),
                ("mobile", "mobile"),
                ("error", "error"),
            ]:
                val = data.get(key)
                if val:
                    detail_parts.append(f"{label}: {val}")
        details_val = "  |  ".join(detail_parts)

        display_rows.append({
            "logged_at":    item.get("logged_at", ""),
            "event":        item.get("event", ""),
            "performed_by": actor_val,
            "subject":      subject_val,
            "details":      details_val,
        })

    st.dataframe(
        safe_frame(display_rows, ["logged_at", "event", "performed_by", "subject", "details"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "logged_at":    st.column_config.TextColumn("Timestamp", width="medium"),
            "event":        st.column_config.TextColumn("Event", width="medium"),
            "performed_by": st.column_config.TextColumn("Performed By", width="medium"),
            "subject":      st.column_config.TextColumn("Subject", width="medium"),
            "details":      st.column_config.TextColumn("Details", width="large"),
        },
    )


# ---------------------------------------------------------------------------
# AI Assistant — multi-tab LLM tools
# ---------------------------------------------------------------------------

_AGENT_HISTORY_KEY = "agent_chat_history"

_TOOL_LABELS: dict[str, str] = {
    "search_doctors":           "Searched doctors",
    "get_available_slots":      "Fetched available slots",
    "book_appointment":         "Booked appointment",
    "reschedule_appointment":   "Rescheduled appointment",
    "get_my_appointments":      "Retrieved appointments",
    "cancel_appointment":       "Cancelled appointment",
    "get_daily_report":         "Pulled daily report",
    "get_all_appointments":     "Listed all appointments",
    "get_my_queue":             "Fetched patient queue",
    "search_knowledge_base":    "Searched knowledge base",
    "get_symptom_guidance":     "Analysed symptoms",
    "get_report_summary":       "Generated hospital report",
    "get_my_health_summary":    "Generated health summary",
    "search_patient":           "Searched patient records",
    "get_patient_appointments": "Fetched patient appointments",
    "suggest_medication":       "Generated medication suggestions",
}


def render_ai_assistant(doctors: list[dict[str, Any]]) -> None:
    health = load_health()
    role = current_role()

    st.markdown(
        '<div class="page-header">'
        '<div class="section-title">AI Assistant</div>'
        '<div class="section-copy">'
        'Book, cancel, or reschedule appointments · Symptom guidance · Medication suggestions · '
        'Patient lookups · Reports · Speaks Hindi, Telugu, Tamil and more.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not health.get("llm_configured"):
        st.error(
            "**GROQ_API_KEY is not set.** Add it to your `.env` file and restart the server.",
            icon="🔑",
        )
        return

    if role == "admin":
        if st.button("Reindex Knowledge Base", key="reindex_kb"):
            ok, result = api_request("POST", "/llm/reindex-knowledge", timeout=120)
            if ok:
                st.success(f"Indexed {result.get('documents_indexed', 0)} docs · {result.get('chunks_indexed', 0)} chunks.")
            else:
                st.error(result)

    if _AGENT_HISTORY_KEY not in st.session_state:
        st.session_state[_AGENT_HISTORY_KEY] = []

    history: list[dict] = st.session_state[_AGENT_HISTORY_KEY]

    col_title, col_clear = st.columns([5, 1])
    with col_clear:
        if history and st.button("Clear chat", key="agent_clear", use_container_width=True):
            st.session_state[_AGENT_HISTORY_KEY] = []
            st.rerun()

    if not history:
        hints = {
            "patient":    "Try: 'Book me an appointment with a cardiologist tomorrow' · 'I have fever, which doctor?' · 'Naku doctor kavali' · 'Mujhe bukhar hai'",
            "admin":      "Try: 'Generate today's report' · 'Find apurupa's last appointment' · 'List all doctors' · 'Apurupa ki appointment kab thi'",
            "doctor":     "Try: 'Show my queue for today' · 'Suggest medication for hypertension' · 'Patient has chest pain, which specialist?'",
            "nurse":      "Try: 'Book appointment for patient P001' · 'Suggest medication for fever' · 'Find ravi's appointments'",
            "front_desk": "Try: 'Check available slots for tomorrow' · 'Find apurupa's details' · 'Book appointment for patient'",
        }
        st.info(hints.get(role, "Ask me anything about the hospital system."), icon="💬")
    else:
        for msg in history:
            msg_role = msg.get("role", "")
            msg_content = msg.get("content") or ""
            if msg_role == "user" and msg_content:
                with st.chat_message("user"):
                    st.markdown(msg_content)
            elif msg_role == "assistant" and msg_content:
                with st.chat_message("assistant"):
                    st.markdown(msg_content)

    prompt = st.chat_input(
        "Ask anything — book, cancel, reschedule, symptoms, medications, reports, patient lookup…",
        key="agent_chat_input",
    )
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.spinner("Thinking…"):
            ok, result = api_request(
                "POST",
                "/llm/agent-chat",
                json={"message": prompt, "conversation_history": history},
                timeout=90,
            )
        if ok:
            reply = result.get("reply", "")
            tools_used: list[str] = result.get("tools_used", [])
            with st.chat_message("assistant"):
                st.markdown(reply)
                if tools_used:
                    labels = [_TOOL_LABELS.get(t, t) for t in tools_used]
                    chips = "".join(f'<span class="tool-chip">{lbl}</span>' for lbl in labels)
                    st.markdown(f'<div class="tool-actions">{chips}</div>', unsafe_allow_html=True)
            st.session_state[_AGENT_HISTORY_KEY] = result.get("updated_history", [])
            st.rerun()
        else:
            st.error(str(result))


def load_nurses() -> list[dict[str, Any]]:
    ok, payload = api_request("GET", "/nurses")
    return load_collection_result(ok, payload, "nurses")


def render_nurses() -> None:
    st.markdown('<div class="page-header"><div class="section-title">Nurse Registry</div><div class="section-copy">Register and manage nursing staff who perform patient triage and queue assignment.</div></div>', unsafe_allow_html=True)
    left, right = st.columns([1, 1.2])

    with left:
        with st.form("nurse_registration_form", clear_on_submit=True):
            st.subheader("Register Nurse")
            full_name = st.text_input("Full Name")
            email = st.text_input("Email")
            mobile = st.text_input("Mobile")
            submit = st.form_submit_button("Create Nurse", use_container_width=True)
            if submit:
                payload = {
                    "full_name": full_name,
                    "email": email,
                    "mobile": mobile,
                }
                ok, result = api_request("POST", "/nurses", json=payload)
                if ok:
                    st.success(f"Nurse created: {result['full_name']}")
                    st.rerun()
                else:
                    st.error(result)

    with right:
        nurses = load_nurses()
        st.markdown("#### Active Nurses")
        nurse_df = safe_frame(
            nurses,
            ["full_name", "email", "mobile"],
        )
        st.dataframe(nurse_df, use_container_width=True, hide_index=True)


def render_triage(doctors: list[dict[str, Any]]) -> None:
    st.markdown('<div class="page-header"><div class="section-title">Patient Triage</div><div class="section-copy">Record vitals and assign patients to normal or emergency queue before their appointment.</div></div>', unsafe_allow_html=True)
    if current_role() == "admin":
        st.warning("Triage is handled by nurses. Admin users can review operations from reports and appointment views.")
        return
    if current_role() == "patient":
        patient_id = current_user().get("linked_patient_id")
        ok, rows = api_request("GET", f"/triage/patient/{patient_id}")
        if ok and rows:
            st.dataframe(
                safe_frame(rows, ["date", "queue_type", "blood_pressure", "heart_rate", "temperature", "weight", "oxygen_saturation", "symptoms", "notes", "created_at"]),
                use_container_width=True,
                hide_index=True,
            )
            render_save_to_drive(
                rows, 
                "triage", 
                lambda r: f"{r.get('date')} - Queue: {r.get('queue_type')}",
                "triage_id",
                "triage_page_drive"
            )
        else:
            st.info("No triage results are available yet.")
        return
    if not doctors:
        st.warning("No doctors registered yet.")
        return

    nurses = load_nurses()
    patients = load_session_patients() if current_role() in {"admin", "nurse", "patient"} else []
    if not nurses:
        st.warning("No nurses registered yet. Register a nurse first.")
        return

    patient_index = build_identity_index(patients, "patient_id", alternate_key="uhid")
    nurse_index = build_identity_index(nurses, "nurse_id", alternate_key="uhid")
    doctor_index = build_identity_index(doctors, "doctor_id", alternate_key="uhid")
    left, right = st.columns([1.1, 0.9])
    with left:
        triage_date = st.date_input("Appointment Date", value=date.today(), key="triage_date")
        if st.button("Load Appointments for Vitals", use_container_width=True):
            st.session_state.triage_appointments = load_appointments_for_view(triage_date)
        appointment_rows = st.session_state.get("triage_appointments", [])
        appointment_rows = [row for row in appointment_rows if row.get("status") in {"booked", "rescheduled"}]
        appointment_options = {}
        for row in enrich_appointment_rows(appointment_rows, patient_index=patient_index, doctor_index=doctor_index):
            label = f"{row.get('start_time')} | {row.get('patient_name') or 'Patient'} with Dr. {row.get('doctor_name') or 'Doctor'}"
            appointment_options[label] = row
        if not appointment_options:
            st.info("Load today's active appointments before recording vitals.")

        with st.form("triage_form", clear_on_submit=True):
            st.subheader("Record Vitals")
            appointment_label = st.selectbox("Appointment", list(appointment_options.keys()) or ["No active appointments"])
            nurse_map = {n["full_name"]: n for n in nurses}
            if current_role() == "nurse":
                nurse_map = {
                    label: nurse for label, nurse in nurse_map.items()
                    if nurse["nurse_id"] == current_user().get("linked_nurse_id")
                } or nurse_map
            nurse_label = st.selectbox("Nurse", list(nurse_map.keys()))

            queue_type = st.selectbox("Queue Assignment", ["normal", "emergency"])
            skip_vitals = st.checkbox(
                "Skip vitals — add to queue immediately (vitals can be recorded later)",
                value=False,
            )

            col1, col2 = st.columns(2)
            with col1:
                blood_pressure = st.text_input("Blood Pressure", placeholder="120/80", disabled=skip_vitals)
                heart_rate = st.number_input("Heart Rate (bpm)", min_value=20, max_value=300, value=72, disabled=skip_vitals)
                temperature = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, value=37.0, step=0.1, disabled=skip_vitals)
            with col2:
                weight = st.number_input("Weight (kg)", min_value=0.5, max_value=500.0, value=70.0, step=0.1, disabled=skip_vitals)
                oxygen_saturation = st.number_input("SpO2 (%)", min_value=0.0, max_value=100.0, value=98.0, step=0.1, disabled=skip_vitals)

            symptoms = st.text_area("Symptoms", height=80)
            notes = st.text_area("Nurse Notes", height=80)

            submit = st.form_submit_button("Record Triage", use_container_width=True)
            if submit:
                if appointment_label not in appointment_options:
                    st.error("Select an active appointment first.")
                    return
                selected_appointment = appointment_options[appointment_label]
                selected_nurse = nurse_map[nurse_label]
                payload = {
                    "patient_id": selected_appointment["patient_id"],
                    "nurse_id": selected_nurse["uhid"],
                    "doctor_id": selected_appointment["doctor_id"],
                    "date": triage_date.isoformat(),
                    "queue_type": queue_type,
                    "appointment_id": selected_appointment["appointment_id"],
                    "blood_pressure": None if skip_vitals else (blood_pressure or None),
                    "heart_rate": None if skip_vitals else int(heart_rate),
                    "temperature": None if skip_vitals else float(temperature),
                    "weight": None if skip_vitals else float(weight),
                    "oxygen_saturation": None if skip_vitals else float(oxygen_saturation),
                    "symptoms": symptoms or None,
                    "notes": notes or None,
                }
                ok, result = api_request("POST", "/triage", json=payload)
                if ok:
                    patient_name = resolve_entity_name(
                        "patient",
                        result.get("patient_id"),
                        index=patient_index,
                        endpoint="/patients",
                    )
                    vitals_note = " (vitals skipped — record later)" if skip_vitals else ""
                    st.success(
                        "Triage recorded: "
                        f"Patient: {patient_name or 'Patient'} | "
                        f"Queue: {result['queue_type'].upper()}{vitals_note}"
                    )
                else:
                    st.error(result)

    with right:
        st.markdown("#### Today's Triage Records")
        ok, triage_rows = api_request("GET", f"/triage/date/{date.today().isoformat()}")
        if ok and triage_rows:
            triage_display_rows = enrich_triage_rows(
                triage_rows,
                patient_index=patient_index,
                doctor_index=doctor_index,
                nurse_index=nurse_index,
            )
            triage_df = safe_frame(
                triage_display_rows,
                [
                    "patient_name",
                    "nurse_name",
                    "doctor_name",
                    "queue_type",
                    "blood_pressure",
                    "heart_rate",
                    "temperature",
                    "created_at",
                ],
            )
            st.dataframe(triage_df, use_container_width=True, hide_index=True)
        else:
            st.info("No triage records for today yet.")

        st.markdown("---")
        st.markdown("#### Patient Triage History")
        patient_map = patient_lookup_map(patients)
        patient_label = st.selectbox("Patient", list(patient_map.keys()) or ["No patients available"], key="triage_lookup_patient")
        if st.button("Fetch History", use_container_width=True):
            if patient_label in patient_map:
                ok, result = api_request("GET", f"/triage/patient/{patient_map[patient_label]['uhid']}")
                if ok and result:
                    triage_history_rows = enrich_triage_rows(
                        result,
                        patient_index=patient_index,
                        doctor_index=doctor_index,
                        nurse_index=nurse_index,
                    )
                    hist_df = safe_frame(
                        triage_history_rows,
                        [
                            "patient_name",
                            "doctor_name",
                            "nurse_name",
                            "date",
                            "queue_type",
                            "blood_pressure",
                            "heart_rate",
                            "temperature",
                            "symptoms",
                        ],
                    )
                    st.dataframe(hist_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No triage history found.")


def render_gsuite() -> None:
    st.markdown('<div class="page-header"><div class="section-title">G-Suite Integration</div><div class="section-copy">Google Forms sync, Gmail notifications, Drive documents, and Calendar events.</div></div>', unsafe_allow_html=True)

    tabs = st.tabs(["Forms Sync", "Gmail", "Drive", "Calendar"])

    # ---- Forms Sync Tab ----
    with tabs[0]:
        st.subheader("Google Forms → Patient Registration")
        st.caption("Form responses are automatically synced every 5 minutes. You can also trigger a manual sync.")
        render_patient_registration_access(context="admin")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("🔄 Sync Now", use_container_width=True):
                ok, result = api_request("POST", "/gsuite/forms/sync")
                if ok:
                    st.success(
                        f"Sync complete: {result.get('new', 0)} new, "
                        f"{result.get('skipped', 0)} skipped"
                    )
                    if result.get("errors"):
                        for err in result["errors"]:
                            st.warning(err)
                else:
                    st.error(result)
        with col2:
            ok, stats = api_request("GET", "/gsuite/forms/stats")
            if ok and stats:
                st.metric("Total Synced", stats.get("total_new", 0))
                st.metric("Total Skipped", stats.get("total_skipped", 0))
                if stats.get("last_sync"):
                    st.caption(f"Last sync: {stats['last_sync']}")

    # ---- Gmail Tab ----
    with tabs[1]:
        st.subheader("Send Email via Gmail")
        st.caption("Emails are automatically sent on booking/cancellation/reschedule. Use this to send ad-hoc emails.")
        with st.form("gmail_form", clear_on_submit=True):
            to_email = st.text_input("To")
            subject = st.text_input("Subject")
            body = st.text_area("Body (HTML supported)", height=150)
            if st.form_submit_button("Send Email", use_container_width=True):
                ok, result = api_request("POST", "/gsuite/email/send", json={
                    "to": to_email, "subject": subject, "body_html": body,
                })
                if ok and result.get("success"):
                    st.success("Email sent.")
                else:
                    st.error(result if isinstance(result, str) else result.get("error", "Send failed"))

    # ---- Drive Tab ----
    with tabs[2]:
        st.subheader("Google Drive Documents")
        left, right = st.columns([1, 1.2])
        with left:
            st.markdown("**Upload Document**")
            uploaded = st.file_uploader("Choose a file", type=["pdf", "png", "jpg", "docx", "csv"])
            patient_folder = st.text_input("Patient Folder")
            if st.button("⬆️ Upload to Drive", use_container_width=True) and uploaded:
                files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}
                params = {"patient_id": patient_folder} if patient_folder else {}
                ok, result = api_request("POST", "/gsuite/drive/upload", files=files, params=params)
                if ok:
                    st.success(f"Uploaded: {result.get('name', '')}")
                    link = result.get("webViewLink", "")
                    if link:
                        st.markdown(f"[Open in Drive]({link})")
                else:
                    st.error(result)
        with right:
            st.markdown("**Browse Files**")
            search_patient = st.text_input("Filter by Patient Folder", key="drive_search")
            if st.button("📂 List Files", use_container_width=True):
                params = {"patient_id": search_patient} if search_patient else {}
                ok, files = api_request("GET", "/gsuite/drive/files", params=params)
                if ok and files:
                    drive_df = safe_frame(files, ["name", "mimeType", "createdTime", "webViewLink"])
                    st.dataframe(drive_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No files found.")

    # ---- Calendar Tab ----
    with tabs[3]:
        st.subheader("Google Calendar Events")
        st.caption("Calendar events are auto-created when appointments are booked.")
        if st.button("Load Upcoming Events", use_container_width=True):
            ok, events = api_request("GET", "/gsuite/calendar/upcoming")
            if ok and events:
                for ev in events:
                    with st.expander(f"{ev.get('summary', 'Event')} — {ev.get('start', '')}"):
                        st.write(f"**Start:** {ev.get('start', '')}")
                        st.write(f"**End:** {ev.get('end', '')}")
                        if ev.get("attendees"):
                            st.write(f"**Attendees:** {', '.join(ev['attendees'])}")
                        link = ev.get("link", "")
                        if link:
                            st.markdown(f"[Open in Calendar]({link})")
            elif ok:
                st.info("No upcoming events.")
            else:
                st.error(events)


def main() -> None:
    if not st.session_state.get("auth_token"):
        render_login()
        return

    page = sidebar_controls()
    health = load_health()
    patients = load_session_patients()
    doctors = load_doctors()

    if page == "Overview":
        render_overview(patients, doctors, health)
    elif page == "Patients":
        render_patients(patients)
    elif page == "Doctors":
        render_doctors(doctors)
    elif page == "Nurses":
        render_nurses()
    elif page == "Scheduling":
        render_scheduling(doctors)
    elif page == "Appointments":
        render_appointments(patients, doctors)
    elif page == "Queue":
        render_queue(doctors)
    elif page == "Nurse Assignments":
        render_nurse_assignments_page()
    elif page == "Triage":
        render_triage(doctors)
    elif page == "Prescriptions":
        render_prescriptions(doctors)
    elif page == "Reports":
        render_reports(doctors)
    elif page == "Audit Logs":
        render_audit_logs()
    elif page == "AI Assistant":
        render_ai_assistant(doctors)
    elif page == "G-Suite":
        render_gsuite()



if __name__ == "__main__":
    main()
