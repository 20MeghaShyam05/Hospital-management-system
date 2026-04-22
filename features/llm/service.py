from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, timedelta
from typing import Optional

import requests
from requests import HTTPError, RequestException
from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.llm.rag import RoleKnowledgeBase
from features.shared.services.booking_service import BookingService

logger = logging.getLogger(__name__)


class LLMService:
    """Groq-backed assistant layer (Llama 3 via Groq's free API)."""

    def __init__(self, booking: BookingService) -> None:
        self._booking = booking
        self._api_key = os.environ.get("GROQ_API_KEY")
        self._model = os.environ.get("GROQ_MODEL", "llama3-8b-8192")
        self._rag = RoleKnowledgeBase()

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _require_key(self) -> None:
        if not self.enabled:
            raise ValueError("GROQ_API_KEY is not configured for the LLM service.")

    @staticmethod
    def _parse_retry_after(exc: HTTPError) -> float:
        """Extract wait seconds from a 429 response (header or body)."""
        try:
            retry_after = exc.response.headers.get("retry-after") or exc.response.headers.get("Retry-After")
            if retry_after:
                return float(retry_after) + 0.5
        except Exception:
            pass
        try:
            msg = exc.response.json().get("error", {}).get("message", "")
            match = re.search(r"try again in ([\d.]+)s", msg)
            if match:
                return float(match.group(1)) + 0.5
        except Exception:
            pass
        return 20.0

    def _post_groq(self, payload: dict, timeout: int = 60) -> dict:
        """POST to Groq with up to 3 retries on 429 rate-limit errors."""
        self._require_key()
        for attempt in range(2):
            try:
                resp = requests.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429 and attempt < 1:
                    wait = min(self._parse_retry_after(exc), 20.0)
                    logger.warning("Groq rate limit hit — waiting %.1fs before retry", wait)
                    time.sleep(wait)
                    continue
                detail = ""
                try:
                    detail = exc.response.json().get("error", {}).get("message", "")
                except Exception:
                    pass
                if not detail and exc.response is not None:
                    detail = f"Groq request failed with HTTP {exc.response.status_code}."
                raise ValueError(
                    detail or "Groq request failed. Check the API key, model name, and network access."
                ) from exc
            except RequestException as exc:
                raise ValueError(
                    "Could not reach the Groq API. Check your internet connection or proxy settings."
                ) from exc
        raise ValueError("Groq rate limit: all retries exhausted. Please wait a moment and try again.")

    def _generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Call Groq's OpenAI-compatible Chat Completions endpoint (free tier)."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 400,
        }
        result = self._post_groq(payload)
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("The LLM did not return any response choices.")
        text = choices[0].get("message", {}).get("content", "").strip()
        if not text:
            raise ValueError("The LLM returned an empty response.")
        return text

    @staticmethod
    def _doctor_cards(doctors: list[dict]) -> list[dict]:
        return [
            {
                "doctor_id": doctor["doctor_id"],
                "uhid": doctor.get("uhid"),
                "full_name": doctor["full_name"],
                "specialization": doctor["specialization"],
            }
            for doctor in doctors[:5]
        ]

    def _active_doctor_cards(self) -> list[dict]:
        return self._doctor_cards(self._booking.list_doctors(active_only=True))

    def problem_guidance(
        self,
        symptoms: str,
        patient_age: Optional[int] = None,
        patient_gender: Optional[str] = None,
    ) -> dict:
        doctor_cards = self._active_doctor_cards()
        specialization_order = []
        for doctor in doctor_cards:
            spec = doctor["specialization"]
            if spec not in specialization_order:
                specialization_order.append(spec)
        context = {
            "symptoms": symptoms,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "available_specializations": specialization_order,
            "available_doctors": doctor_cards,
        }
        doctor_recommendation = self._generate_text(
            system_prompt=(
                "You are a cautious hospital assistant. "
                "Recommend which doctor specializations and available doctors from the provided roster may fit the symptoms using only the provided context. "
                "Do not diagnose, do not invent doctors, do not invent departments, and do not claim certainty. "
                "If the roster is insufficient, say that clearly. Tell the user this is guidance and urgent symptoms need urgent care."
            ),
            user_prompt=(
                "Use only this JSON context. "
                "If you are unsure, say 'I do not have enough information from the provided roster.' "
                "Write a short recommendation in plain English and mention only specializations and doctors present in the roster.\n"
                f"{json.dumps(context, indent=2)}"
            ),
        )
        explanation = self._generate_text(
            system_prompt=(
                "You are a cautious hospital assistant. "
                "Explain the reasoning behind the doctor recommendation using only the provided context. "
                "Do not diagnose and do not invent facts or doctors."
            ),
            user_prompt=(
                "Use only this JSON context and briefly explain why the suggested specialization or doctors may be relevant. "
                "If the available roster is insufficient, say that clearly.\n"
                f"{json.dumps(context, indent=2)}"
            ),
        )
        self_care_guidance = self._generate_text(
            system_prompt=(
                "You are a cautious hospital assistant. "
                "Give only general low-risk self-care guidance for symptoms. "
                "Do not diagnose, do not prescribe medicines, do not give dosages, and do not replace professional care. "
                "Mention escalation signs if symptoms sound urgent."
            ),
            user_prompt=(
                "Provide short, general self-care guidance for this patient description. "
                "Keep it safe and conservative. If the situation may need urgent attention, say so clearly.\n"
                f"{json.dumps(context, indent=2)}"
            ),
        )
        return {
            "symptoms": symptoms,
            "suggested_specializations": specialization_order,
            "doctor_recommendation": doctor_recommendation,
            "explanation": explanation,
            "suggested_doctors": doctor_cards,
            "self_care_guidance": self_care_guidance,
            "safety_note": (
                "This is an assistant suggestion, not a diagnosis. "
                "For chest pain, breathing difficulty, stroke symptoms, heavy bleeding, or severe distress, seek urgent medical care immediately."
            ),
        }

    def summarize_report(self, report_date: date, doctor_id: Optional[str] = None) -> dict:
        report = self._booking.get_report_data(report_date, doctor_id=doctor_id)
        summary = self._generate_text(
            system_prompt=(
                "You are a hospital operations analyst. "
                "Summarize report metrics in 4-6 concise sentences for admins. "
                "Highlight operational takeaways without inventing facts."
            ),
            user_prompt=f"Summarize this report JSON:\n{json.dumps(report, indent=2, default=str)}",
        )
        return {"summary": summary, "report": report}

    def summarize_health(
        self,
        triage_records: list[dict],
        prescriptions: list[dict],
        patient_name: Optional[str] = None,
    ) -> dict:
        """Generate a personal health summary from vitals and prescription history."""
        name_clause = f" for {patient_name}" if patient_name else ""
        context = {
            "triage_vitals": triage_records,
            "prescriptions": prescriptions,
        }
        summary = self._generate_text(
            system_prompt=(
                "You are a caring clinical assistant reviewing a patient's health records. "
                "Write a concise, plain-English health summary based ONLY on the provided vitals "
                "and prescription data. Mention trends in vitals (blood pressure, heart rate, "
                "temperature, oxygen saturation), current medications, and any follow-up notes. "
                "Do NOT invent data. If records are empty, say so clearly. "
                "Do NOT provide diagnoses or treatment recommendations."
            ),
            user_prompt=(
                f"Generate a personal health summary{name_clause} from the following records:\n"
                f"{json.dumps(context, indent=2, default=str)}"
            ),
        )
        return {"summary": summary}

    @staticmethod
    def _audience_for_role(role: str) -> str:
        if role == "doctor":
            return "doctor"
        if role == "patient":
            return "patient"
        return "admin"

    def patient_chat(self, current_user: dict, message: str) -> dict:
        role = current_user.get("role", "user")
        linked_patient_id = current_user.get("linked_patient_id")
        linked_doctor_id = current_user.get("linked_doctor_id")
        audience = self._audience_for_role(role)
        retrieved_chunks = self._rag.search(message, audience)
        context = {
            "role": role,
            "linked_patient_id": linked_patient_id,
            "linked_doctor_id": linked_doctor_id,
            "retrieved_knowledge": self._rag.render_context(retrieved_chunks),
        }
        reply = self._generate_text(
            system_prompt=(
                "You are a hospital role-aware knowledge assistant. "
                "Answer using the retrieved hospital policy, business rule, and process documents whenever available. "
                "Do not invent hospital rules, workflows, permissions, or clinical guidance. "
                "If the retrieved context is insufficient, say so clearly. "
                "Do not diagnose or prescribe treatment. "
                "For medical emergencies, instruct the user to contact urgent care immediately."
            ),
            user_prompt=(
                "Use this user context and retrieved knowledge to answer the message helpfully.\n"
                f"Context: {json.dumps(context)}\n"
                f"Message: {message}"
            ),
        )
        return {
            "reply": reply,
            "sources": [
                {
                    "title": chunk.title,
                    "source_path": chunk.source_path,
                    "chunk_index": chunk.chunk_index,
                    "score": round(chunk.score, 4),
                }
                for chunk in retrieved_chunks
            ],
        }

    def reindex_knowledge_documents(self) -> dict:
        return self._rag.index_documents()

def get_llm_service(booking: BookingService = Depends(get_booking_service)) -> LLMService:
    return LLMService(booking)


# =============================================================================
# AgentService — agentic AI assistant with tool calling (A2A design)
# =============================================================================

class AgentService:
    """Agentic AI assistant that executes real HMS actions via Groq tool calling.

    Architecture (A2A):
      Orchestrator agent receives the user message and decides which tool to call.
      Tool executors are scoped sub-agents that call BookingService / RAG directly.
      The loop continues until the LLM returns a plain-text final answer.
    """

    _MAX_LOOP_ITERATIONS = 3

    def __init__(self, booking: BookingService) -> None:
        self._booking = booking
        self._api_key = os.environ.get("GROQ_API_KEY")
        self._model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
        self._rag = RoleKnowledgeBase()
        self._llm = LLMService(booking)  # for symptom guidance, report & health summary tools

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _require_key(self) -> None:
        if not self.enabled:
            raise ValueError("GROQ_API_KEY is not configured for the LLM service.")

    # ------------------------------------------------------------------
    # Date parsing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_str: str) -> date:
        s = date_str.strip().lower()
        today = date.today()
        if s in ("today", "now"):
            return today
        if s == "tomorrow":
            return today + timedelta(days=1)
        return date.fromisoformat(date_str.strip())

    # ------------------------------------------------------------------
    # Role-scoped tool definitions (Groq / OpenAI function-calling format)
    # ------------------------------------------------------------------

    @staticmethod
    def _tools_for_role(role: str, rag_enabled: bool = False) -> list[dict]:
        search_doctors = {
            "type": "function",
            "function": {
                "name": "search_doctors",
                "description": (
                    "Search for active doctors in the hospital. "
                    "Optionally filter by medical specialization. "
                    "Returns doctor IDs, names, and specializations."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "specialization": {
                            "type": "string",
                            "description": (
                                "Optional specialization filter, e.g. 'Cardiologist', "
                                "'General Physician', 'Dermatologist'. "
                                "Leave blank to list all active doctors."
                            ),
                        }
                    },
                    "required": [],
                },
            },
        }

        get_available_slots = {
            "type": "function",
            "function": {
                "name": "get_available_slots",
                "description": "Get available (unbooked) appointment slots for a specific doctor on a given date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doctor_id": {
                            "type": "string",
                            "description": "The doctor's ID or UHID (from search_doctors).",
                        },
                        "date": {
                            "type": "string",
                            "description": "Date in YYYY-MM-DD format, or 'today' or 'tomorrow'.",
                        },
                    },
                    "required": ["doctor_id", "date"],
                },
            },
        }

        book_appointment = {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": (
                    "Book an appointment. "
                    "Call get_available_slots first to obtain a valid slot_id. "
                    "Once you have doctor_id, slot_id, and appointment_date, call this immediately — "
                    "do not ask for further confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "doctor_id": {
                            "type": "string",
                            "description": "Doctor's ID (from search_doctors).",
                        },
                        "slot_id": {
                            "type": "string",
                            "description": "Slot ID from get_available_slots.",
                        },
                        "appointment_date": {
                            "type": "string",
                            "description": "Appointment date in YYYY-MM-DD format.",
                        },
                        "patient_id": {
                            "type": "string",
                            "description": "Patient ID — required when booking on behalf of a patient (nurse/front_desk). Omit for patient self-booking.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional notes or reason for visit.",
                        },
                    },
                    "required": ["doctor_id", "slot_id", "appointment_date"],
                },
            },
        }

        reschedule_appointment = {
            "type": "function",
            "function": {
                "name": "reschedule_appointment",
                "description": (
                    "Reschedule an existing appointment to a new slot. "
                    "Call get_available_slots first to pick the new slot_id. "
                    "Once you have the new slot_id and date, call this immediately."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {
                            "type": "string",
                            "description": "The appointment ID to reschedule (from get_my_appointments).",
                        },
                        "new_slot_id": {
                            "type": "string",
                            "description": "New slot ID from get_available_slots.",
                        },
                        "new_date": {
                            "type": "string",
                            "description": "New appointment date in YYYY-MM-DD format.",
                        },
                    },
                    "required": ["appointment_id", "new_slot_id", "new_date"],
                },
            },
        }

        get_my_appointments = {
            "type": "function",
            "function": {
                "name": "get_my_appointments",
                "description": "Get all appointments for the current user (patient's appointments or doctor's schedule).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Optional date filter (YYYY-MM-DD, 'today', 'tomorrow'). For doctors only.",
                        }
                    },
                    "required": [],
                },
            },
        }

        cancel_appointment = {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": "Cancel an existing appointment by appointment ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {
                            "type": "string",
                            "description": "The appointment ID to cancel.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for cancellation (at least 10 characters).",
                        },
                    },
                    "required": ["appointment_id", "reason"],
                },
            },
        }

        get_daily_report = {
            "type": "function",
            "function": {
                "name": "get_daily_report",
                "description": "Get appointment metrics and statistics for a specific date (admin/doctor use).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Report date in YYYY-MM-DD format or 'today'.",
                        },
                        "doctor_id": {
                            "type": "string",
                            "description": "Optional: filter report to a specific doctor's ID.",
                        },
                    },
                    "required": ["date"],
                },
            },
        }

        get_all_appointments = {
            "type": "function",
            "function": {
                "name": "get_all_appointments",
                "description": "Get all appointments across all patients and doctors (admin use). Optionally filter by date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Optional date filter in YYYY-MM-DD format or 'today'.",
                        }
                    },
                    "required": [],
                },
            },
        }

        get_my_queue = {
            "type": "function",
            "function": {
                "name": "get_my_queue",
                "description": "Get the current doctor's patient queue for a specific date.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Date in YYYY-MM-DD format or 'today' (defaults to today).",
                        }
                    },
                    "required": [],
                },
            },
        }

        search_knowledge = {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": (
                    "Search the hospital knowledge base for policies, procedures, "
                    "system usage guides, and operational rules. "
                    "Use this when the user asks a question about hospital policy, "
                    "how something works, or what the rules are."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The question or topic to look up.",
                        }
                    },
                    "required": ["query"],
                },
            },
        }

        get_symptom_guidance = {
            "type": "function",
            "function": {
                "name": "get_symptom_guidance",
                "description": (
                    "Get doctor recommendations and self-care advice based on symptoms or health complaints. "
                    "Use whenever the user describes any medical symptom, body pain, illness, discomfort, "
                    "or asks which doctor/specialist to see. Also handles misspelt symptoms and symptoms "
                    "described in any language."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symptoms": {
                            "type": "string",
                            "description": "Description of symptoms or health complaints (any language, spelling errors are fine).",
                        }
                    },
                    "required": ["symptoms"],
                },
            },
        }

        get_report_summary = {
            "type": "function",
            "function": {
                "name": "get_report_summary",
                "description": (
                    "Generate a natural-language narrative summary of hospital appointment data for a date. "
                    "Use when admin asks for a hospital summary, operations report, daily statistics, "
                    "or an overview of how the hospital performed on a given day."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Report date in YYYY-MM-DD format or 'today'.",
                        },
                        "doctor_id": {
                            "type": "string",
                            "description": "Optional: filter report to a specific doctor.",
                        },
                    },
                    "required": ["date"],
                },
            },
        }

        get_my_health_summary = {
            "type": "function",
            "function": {
                "name": "get_my_health_summary",
                "description": (
                    "Generate a personal health summary from the patient's triage vitals and prescriptions. "
                    "Use when patient asks about their own health, current medications, vitals history, "
                    "health overview, or recent medical records."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

        suggest_medication = {
            "type": "function",
            "function": {
                "name": "suggest_medication",
                "description": (
                    "Suggest possible medications or treatments for a given diagnosis or set of symptoms. "
                    "Use when a doctor or nurse asks about medication options, dosage guidance, or treatment plans. "
                    "Always includes safety disclaimers. Does not replace clinical judgement."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symptoms_or_diagnosis": {
                            "type": "string",
                            "description": "The symptoms, condition, or diagnosis to get medication suggestions for.",
                        },
                        "patient_age": {
                            "type": "integer",
                            "description": "Optional patient age in years for age-appropriate suggestions.",
                        },
                    },
                    "required": ["symptoms_or_diagnosis"],
                },
            },
        }

        search_patient = {
            "type": "function",
            "function": {
                "name": "search_patient",
                "description": (
                    "Search for a patient by name (partial match). "
                    "Use when someone asks about a specific patient by name, e.g. 'find apurupa' or 'search for ravi's appointments'. "
                    "Returns patient ID, name, mobile, and email."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Patient name or partial name to search for.",
                        }
                    },
                    "required": ["name"],
                },
            },
        }

        get_patient_appointments = {
            "type": "function",
            "function": {
                "name": "get_patient_appointments",
                "description": (
                    "Get all appointments for a specific patient by their patient ID. "
                    "Use after search_patient to get a specific patient's appointment history."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The patient's ID (from search_patient).",
                        }
                    },
                    "required": ["patient_id"],
                },
            },
        }

        # Base set available to all roles (knowledge search only when RAG is configured)
        base = [search_doctors, get_available_slots, get_symptom_guidance]
        if rag_enabled:
            base.append(search_knowledge)

        if role == "patient":
            return base + [
                book_appointment, reschedule_appointment,
                get_my_appointments, cancel_appointment, get_my_health_summary,
            ]
        elif role == "admin":
            return base + [
                book_appointment, reschedule_appointment,
                get_my_appointments, cancel_appointment,
                get_daily_report, get_all_appointments, get_report_summary,
                search_patient, get_patient_appointments,
            ]
        elif role == "doctor":
            return base + [get_my_appointments, get_my_queue, suggest_medication]
        elif role == "nurse":
            return base + [
                book_appointment, reschedule_appointment,
                get_my_appointments, cancel_appointment,
                suggest_medication, search_patient, get_patient_appointments,
            ]
        elif role == "front_desk":
            return base + [
                book_appointment, reschedule_appointment,
                get_my_appointments, cancel_appointment,
                search_patient, get_patient_appointments,
            ]
        return base

    # ------------------------------------------------------------------
    # System prompt per role
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt(role: str, current_user: dict) -> str:
        today = date.today().isoformat()
        base = (
            f"You are a helpful hospital assistant for the MediFlow HMS. "
            f"Today's date is {today}. "
            "You have access to tools to perform real actions in the hospital system. "
            "Use tools to fetch real data — never invent IDs, names, or slot times. "
            "For medical emergencies, immediately direct the user to seek urgent care. "
            "Be concise and professional.\n\n"

            "LANGUAGE AND TRANSLITERATION UNDERSTANDING:\n"
            "- Accept input in any language or script and respond in the same language the user writes in.\n"
            "- Understand transliterated Indian languages written in English letters:\n"
            "  Telugu examples: 'naku doctor kavali' = I need a doctor; 'appointment book cheyyandi' = please book appointment; "
            "  'cancel cheyyandi' = please cancel; 'slots chupandi' = show slots; 'naaku jwaram ga undi' = I have fever; "
            "  'neeru mingu' = drink water (self care); 'medicines cheppandi' = tell me medicines.\n"
            "  Hindi examples: 'doctor chahiye' = need a doctor; 'appointment book karo' = book appointment; "
            "  'cancel karo' = cancel; 'mujhe bukhar hai' = I have fever; 'slots dikhao' = show slots; "
            "  'report chahiye' = need report; 'dawai batao' = tell medicine.\n"
            "  Tamil examples: 'doctor venum' = need doctor; 'appointment pottu' = book appointment.\n"
            "- Tolerate spelling mistakes and typos. "
            "Examples: 'apoint'→appointment; 'docter'→doctor; 'symtoms'→symptoms; 'cancell'→cancel; 'medcine'→medication.\n"
            "- Recognise shorthand: 'BP'→blood pressure; 'HR'→heart rate; 'checkup'→appointment; "
            "'slot'→appointment slot; 'report'→hospital report; 'history'→past appointments.\n"
            "- When a patient or staff asks about a specific person by name (e.g. 'apurupa ki appointment', "
            "'ravi ka last visit'), call search_patient with that name first, then fetch their appointments.\n"
            "- If a phrase is ambiguous, pick the most medically relevant meaning and proceed without asking.\n"
        )
        name = current_user.get("full_name", "")
        if role == "patient":
            return base + (
                f"\nYou are assisting patient {name}. "
                "Help them:\n"
                "- Symptoms / which doctor → call get_symptom_guidance; also give self-care advice.\n"
                "- Book appointment → search_doctors → get_available_slots → book_appointment immediately.\n"
                "- Reschedule → get_my_appointments to find appointment_id → get_available_slots → reschedule_appointment.\n"
                "- Cancel → get_my_appointments to find appointment_id → cancel_appointment.\n"
                "- Health summary → get_my_health_summary.\n"
                "IMPORTANT: Once you have all required IDs, call the tool immediately — never ask 'shall I proceed?'."
            )
        elif role == "admin":
            return base + (
                "\nYou are assisting a hospital administrator. "
                "Help with:\n"
                "- Hospital report / today's summary → get_report_summary.\n"
                "- All appointments → get_all_appointments; raw stats → get_daily_report.\n"
                "- Find a specific patient by name → search_patient, then get_patient_appointments.\n"
                "- Questions like 'apurupa's last appointment', 'ravi ka appointment kab tha' → "
                "search_patient with the name, then get_patient_appointments and find the relevant one.\n"
                "- List doctors → search_doctors.\n"
                "When admin asks about any named patient, always call search_patient first."
            )
        elif role == "doctor":
            return base + (
                f"\nYou are assisting Dr. {name}. "
                "Help with:\n"
                "- Today's patient queue → get_my_queue.\n"
                "- Appointment schedule → get_my_appointments.\n"
                "- Symptom guidance for a patient → get_symptom_guidance.\n"
                "- Medication or treatment suggestions → suggest_medication. "
                "Always include clinical disclaimers and remind that final prescription is the doctor's decision.\n"
                "When asked about medicines, dosage, or treatment for a condition, call suggest_medication immediately."
            )
        elif role == "nurse":
            return base + (
                f"\nYou are assisting nurse {name}. "
                "Help with:\n"
                "- Booking for a patient → search_doctors → get_available_slots → book_appointment with patient_id.\n"
                "- Rescheduling / cancelling on behalf of a patient → get_my_appointments → reschedule or cancel.\n"
                "- Medication suggestions for symptoms → suggest_medication (include disclaimer).\n"
                "- Find a patient by name → search_patient, then get_patient_appointments.\n"
                "Once you have all required IDs, act immediately — never ask 'shall I proceed?'."
            )
        elif role == "front_desk":
            return base + (
                "\nYou are assisting front-desk staff. "
                "Help with:\n"
                "- Book for a patient → search_doctors → get_available_slots → book_appointment with patient_id.\n"
                "- Reschedule / cancel on behalf of a patient → get_my_appointments → act.\n"
                "- Find a patient by name → search_patient, then get_patient_appointments.\n"
                "- Questions about a specific patient's history → search_patient first, then get_patient_appointments.\n"
                "Once you have all required IDs, act immediately."
            )
        return base

    # ------------------------------------------------------------------
    # Tool executor (sub-agent dispatch)
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name: str, arguments: dict, current_user: dict) -> str:
        """Execute a named tool and return the result as a JSON string."""
        role = current_user.get("role", "")
        patient_id = current_user.get("linked_patient_id")
        doctor_id = current_user.get("linked_doctor_id")
        audience = "patient" if role == "patient" else ("doctor" if role == "doctor" else "admin")

        try:
            # ---- Knowledge search (RAG sub-agent) -----
            if tool_name == "search_knowledge_base":
                query = arguments.get("query", "")
                chunks = self._rag.search(query, audience)
                knowledge = self._rag.render_context(chunks)
                return json.dumps({
                    "knowledge": knowledge,
                    "sources": [{"title": c.title, "path": c.source_path} for c in chunks],
                })

            # ---- Doctor search -----
            elif tool_name == "search_doctors":
                spec_filter = arguments.get("specialization", "").strip().lower()
                doctors = self._booking.list_doctors(active_only=True)
                if spec_filter:
                    doctors = [
                        d for d in doctors
                        if spec_filter in d.get("specialization", "").lower()
                    ]
                cards = [
                    {
                        "doctor_id": d["doctor_id"],
                        "uhid": d.get("uhid", ""),
                        "full_name": d["full_name"],
                        "specialization": d["specialization"],
                    }
                    for d in doctors[:10]
                ]
                return json.dumps({"doctors": cards, "count": len(cards)})

            # ---- Available slots -----
            elif tool_name == "get_available_slots":
                doc_id = arguments["doctor_id"]
                slot_date = self._parse_date(arguments["date"])
                slots = self._booking.get_available_slots(doc_id, slot_date)
                result = [
                    {
                        "slot_id": s["slot_id"],
                        "start_time": str(s["start_time"]),
                        "end_time": str(s["end_time"]),
                        "label": s.get("label", ""),
                    }
                    for s in slots[:12]
                ]
                return json.dumps({
                    "slots": result,
                    "count": len(result),
                    "date": str(slot_date),
                    "doctor_id": doc_id,
                })

            # ---- Book appointment -----
            elif tool_name == "book_appointment":
                # Resolve patient ID
                if role == "patient":
                    if not patient_id:
                        return json.dumps({"error": "Your patient ID is not linked to this session."})
                    booking_patient_id = patient_id
                else:
                    booking_patient_id = arguments.get("patient_id") or patient_id
                    if not booking_patient_id:
                        return json.dumps({"error": "patient_id is required when booking on behalf of a patient."})

                apt_date = self._parse_date(arguments["appointment_date"])
                saved = self._booking.book_appointment(
                    patient_id=booking_patient_id,
                    doctor_id=arguments["doctor_id"],
                    slot_id=arguments["slot_id"],
                    appointment_date=apt_date,
                    notes=arguments.get("notes"),
                    booked_by=current_user.get("user_id"),
                    current_user=current_user,
                )
                return json.dumps({
                    "success": True,
                    "appointment_id": saved["appointment_id"],
                    "date": str(saved["date"]),
                    "start_time": str(saved["start_time"]),
                    "end_time": str(saved["end_time"]),
                    "doctor_id": saved["doctor_id"],
                    "status": saved["status"],
                }, default=str)

            # ---- Get appointments -----
            elif tool_name == "get_my_appointments":
                date_arg = arguments.get("date")
                if role == "patient":
                    if not patient_id:
                        return json.dumps({"error": "Patient ID not found."})
                    apts = self._booking.get_patient_appointments(patient_id)
                elif role == "doctor":
                    if not doctor_id:
                        return json.dumps({"error": "Doctor ID not found."})
                    filter_date = self._parse_date(date_arg) if date_arg else date.today()
                    apts = self._booking.get_doctor_appointments(doctor_id, filter_date)
                else:
                    filter_date = self._parse_date(date_arg) if date_arg else None
                    apts = self._booking.get_all_appointments(for_date=filter_date)

                result = [
                    {
                        "appointment_id": a["appointment_id"],
                        "date": str(a["date"]),
                        "start_time": str(a["start_time"]),
                        "status": a["status"],
                        "doctor_id": a.get("doctor_id", ""),
                        "patient_id": a.get("patient_id", ""),
                    }
                    for a in apts[:15]
                ]
                return json.dumps({"appointments": result, "count": len(result)})

            # ---- Reschedule appointment -----
            elif tool_name == "reschedule_appointment":
                new_date = self._parse_date(arguments["new_date"])
                saved = self._booking.reschedule_appointment(
                    appointment_id=arguments["appointment_id"],
                    new_slot_id=arguments["new_slot_id"],
                    new_date=new_date,
                    current_user=current_user,
                )
                return json.dumps({
                    "success": True,
                    "appointment_id": saved["appointment_id"],
                    "new_date": str(saved["date"]),
                    "new_start_time": str(saved["start_time"]),
                    "new_end_time": str(saved["end_time"]),
                    "status": saved["status"],
                }, default=str)

            # ---- Cancel appointment -----
            elif tool_name == "cancel_appointment":
                apt_id = arguments["appointment_id"]
                reason = arguments.get("reason", "Cancelled via assistant")
                saved = self._booking.cancel_appointment(
                    appointment_id=apt_id,
                    reason=reason,
                    cancelled_by=current_user.get("user_id"),
                    current_user=current_user,
                )
                return json.dumps({
                    "success": True,
                    "appointment_id": apt_id,
                    "status": saved.get("status"),
                })

            # ---- Daily report (admin/doctor) -----
            elif tool_name == "get_daily_report":
                report_date = self._parse_date(arguments["date"])
                doc_filter = arguments.get("doctor_id")
                if role == "doctor" and not doc_filter:
                    doc_filter = doctor_id
                report = self._booking.get_report_data(report_date, doctor_id=doc_filter)
                return json.dumps(report, default=str)

            # ---- All appointments (admin) -----
            elif tool_name == "get_all_appointments":
                date_arg = arguments.get("date")
                filter_date = self._parse_date(date_arg) if date_arg else None
                apts = self._booking.get_all_appointments(for_date=filter_date)
                result = [
                    {
                        "appointment_id": a["appointment_id"],
                        "date": str(a["date"]),
                        "start_time": str(a["start_time"]),
                        "status": a["status"],
                        "doctor_id": a.get("doctor_id", ""),
                        "patient_id": a.get("patient_id", ""),
                    }
                    for a in apts[:20]
                ]
                return json.dumps({"appointments": result, "count": len(result)})

            # ---- Doctor queue -----
            elif tool_name == "get_my_queue":
                if not doctor_id:
                    return json.dumps({"error": "Doctor ID not found in session."})
                date_arg = arguments.get("date", "today")
                queue_date = self._parse_date(date_arg)
                queue = self._booking.get_queue(doctor_id, queue_date)
                return json.dumps({"queue": queue[:15], "count": len(queue)}, default=str)

            # ---- Symptom guidance (all roles) -----
            elif tool_name == "get_symptom_guidance":
                symptoms = arguments.get("symptoms", "").strip()
                if not symptoms:
                    return json.dumps({"error": "No symptoms provided."})
                guidance = self._llm.problem_guidance(symptoms)
                return json.dumps({
                    "doctor_recommendation": guidance.get("doctor_recommendation", ""),
                    "explanation":           guidance.get("explanation", ""),
                    "self_care_guidance":    guidance.get("self_care_guidance", ""),
                    "suggested_doctors":     guidance.get("suggested_doctors", []),
                    "safety_note":           guidance.get("safety_note", ""),
                }, default=str)

            # ---- Hospital report summary (admin only) -----
            elif tool_name == "get_report_summary":
                report_date = self._parse_date(arguments.get("date", "today"))
                doc_filter = arguments.get("doctor_id")
                result = self._llm.summarize_report(report_date, doctor_id=doc_filter)
                return json.dumps({
                    "summary": result.get("summary", ""),
                    "date":    str(report_date),
                }, default=str)

            # ---- Personal health summary (patient only) -----
            elif tool_name == "get_my_health_summary":
                if not patient_id:
                    return json.dumps({"error": "Patient ID not found in your session."})
                triage_records = self._booking.get_triage_entries(patient_id)
                prescriptions  = self._booking.get_patient_prescriptions(patient_id)
                patient_data   = self._booking.get_patient(patient_id)
                patient_name   = patient_data.get("full_name") if patient_data else None
                result = self._llm.summarize_health(triage_records, prescriptions, patient_name)
                return json.dumps({"summary": result.get("summary", "")}, default=str)

            # ---- Search patient by name -----
            elif tool_name == "search_patient":
                name_query = arguments.get("name", "").strip().lower()
                patients = self._booking.list_patients(active_only=False)
                matches = [
                    p for p in patients
                    if name_query in p.get("full_name", "").lower()
                ]
                cards = [
                    {
                        "patient_id": p["patient_id"],
                        "full_name": p["full_name"],
                        "mobile": p.get("mobile", ""),
                        "email": p.get("email", ""),
                    }
                    for p in matches[:10]
                ]
                return json.dumps({"patients": cards, "count": len(cards)})

            # ---- Get appointments for a specific patient (admin/nurse/front_desk) -----
            elif tool_name == "get_patient_appointments":
                target_patient_id = arguments.get("patient_id", "").strip()
                if not target_patient_id:
                    return json.dumps({"error": "patient_id is required."})
                apts = self._booking.get_patient_appointments(target_patient_id)
                result = [
                    {
                        "appointment_id": a["appointment_id"],
                        "date": str(a["date"]),
                        "start_time": str(a["start_time"]),
                        "status": a["status"],
                        "doctor_id": a.get("doctor_id", ""),
                        "notes": a.get("notes", ""),
                    }
                    for a in sorted(apts, key=lambda x: str(x.get("date", "")), reverse=True)[:15]
                ]
                return json.dumps({"appointments": result, "count": len(result)})

            # ---- Medication suggestion (doctor/nurse) -----
            elif tool_name == "suggest_medication":
                symptoms_or_diagnosis = arguments.get("symptoms_or_diagnosis", "").strip()
                patient_age = arguments.get("patient_age")
                if not symptoms_or_diagnosis:
                    return json.dumps({"error": "symptoms_or_diagnosis is required."})
                age_note = f" Patient age: {patient_age} years." if patient_age else ""
                suggestion = self._llm._generate_text(
                    system_prompt=(
                        "You are a clinical pharmacology reference assistant helping a doctor or nurse. "
                        "Suggest commonly used medications and general treatment approaches for the given condition or symptoms. "
                        "Include drug class, common examples, typical dosage range, and important contraindications. "
                        "ALWAYS add: 'This is reference information only. Final prescription must be decided by the treating physician based on full clinical assessment.' "
                        "Do NOT recommend specific branded drugs as the only option. Do NOT replace clinical judgment."
                    ),
                    user_prompt=(
                        f"Suggest medications and treatment approach for: {symptoms_or_diagnosis}.{age_note} "
                        "Include: drug class, common generic names, dosage range, contraindications, and monitoring parameters."
                    ),
                )
                return json.dumps({
                    "suggestion": suggestion,
                    "disclaimer": "This is reference information only. Final prescription must be decided by the treating physician.",
                })

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as exc:
            logger.warning("Tool execution error [%s]: %s", tool_name, exc)
            return json.dumps({"error": str(exc)})

    # ------------------------------------------------------------------
    # Safe history trimming
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_trim_history(history: list[dict], max_messages: int) -> list[dict]:
        """Return at most max_messages tail messages without splitting tool-call sequences.

        A tool-call sequence is: [assistant msg with tool_calls] + [N tool result msgs].
        Slicing in the middle of such a sequence causes Groq to reject the request with
        an "orphaned tool result" error. This method always cuts at a clean boundary.
        """
        if len(history) <= max_messages:
            return history

        # Walk backwards from the desired cut point until we land on a safe boundary.
        # A safe start is either a "user" message or an "assistant" message without tool_calls.
        candidate = history[-max_messages:]
        for i, msg in enumerate(candidate):
            msg_role = msg.get("role", "")
            if msg_role == "user":
                return candidate[i:]
            if msg_role == "assistant" and not msg.get("tool_calls"):
                return candidate[i:]
            # "tool" messages and assistant-with-tool_calls at the cut point — skip forward
        # Fallback: return as-is (better than nothing)
        return candidate

    # ------------------------------------------------------------------
    # Text-based tool call parser (fallback for models like Cerebras llama3.1-8b
    # that output tool calls as JSON text instead of structured tool_calls)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text_tool_calls(content: str) -> list[dict]:
        """Parse tool calls embedded as JSON objects in plain text content.

        Handles two formats the model may emit:
          {"type": "function", "name": "fn", "arguments": {...}}
          {"name": "fn", "arguments": {...}}
        Returns a list in the same shape as the OpenAI tool_calls structure.
        """
        import re, uuid
        results = []
        for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*\}', content, re.DOTALL):
            raw = match.group(0)
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = obj.get("name")
            args = obj.get("arguments") or obj.get("parameters") or {}
            if not name:
                continue
            results.append({
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args),
                },
            })
        return results

    # ------------------------------------------------------------------
    # Groq API call with tools
    # ------------------------------------------------------------------

    def _call_groq(self, messages: list[dict], tools: list[dict]) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 600,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return self._llm._post_groq(payload)

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    def _run_agent_loop(
        self,
        messages: list[dict],
        tools: list[dict],
        current_user: dict,
    ) -> tuple[str, list[dict], list[str]]:
        """Orchestrator loop: call LLM → execute tool calls → repeat until done.

        Returns:
            (final_reply_text, updated_message_list, list_of_tool_names_called)
        """
        tools_used: list[str] = []

        for _ in range(self._MAX_LOOP_ITERATIONS):
            payload = self._call_groq(messages, tools)
            choices = payload.get("choices", [])
            if not choices:
                raise ValueError("LLM returned no response choices.")

            choice = choices[0]
            assistant_msg = choice["message"]
            finish_reason = choice.get("finish_reason", "stop")

            # Append assistant message to history
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls") or []

            # Cerebras llama3.1-8b outputs tool calls as JSON text in content
            # instead of structured tool_calls. Parse and normalise them.
            if not tool_calls:
                tool_calls = self._extract_text_tool_calls(assistant_msg.get("content") or "")
                if tool_calls:
                    # Clear the raw JSON from content so it isn't shown to the user
                    messages[-1]["content"] = None

            # Treat as final answer when: no tool calls, or token limit hit.
            if not tool_calls or finish_reason == "length":
                reply = (assistant_msg.get("content") or "").strip() or "I have completed your request."
                # Ensure the assistant message in history has visible content for the UI
                messages[-1]["content"] = reply
                return reply, messages, tools_used

            # Execute every tool call and append results
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args_raw = tc["function"].get("arguments", "{}")
                try:
                    fn_args = json.loads(fn_args_raw)
                except json.JSONDecodeError:
                    fn_args = {}

                tools_used.append(fn_name)
                tool_result = self._execute_tool(fn_name, fn_args, current_user)

                # Keep tool results short to stay within TPM limits
                if len(tool_result) > 1200:
                    tool_result = tool_result[:1200] + "…[truncated]"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

        # Safety exit after max iterations
        last_content = "I have processed your request."
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("content"):
                last_content = m["content"]
                break
        # Ensure last assistant message has visible content for the UI
        for m in reversed(messages):
            if m.get("role") == "assistant":
                m["content"] = last_content
                break
        return last_content, messages, tools_used

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def agent_chat(
        self,
        current_user: dict,
        message: str,
        conversation_history: list[dict],
    ) -> dict:
        """Run the agentic chat loop and return reply + updated history.

        Args:
            current_user:         JWT-decoded user dict (role, linked_patient_id, etc.)
            message:              The new user message.
            conversation_history: Full prior history (including tool messages).
                                  Stored and returned for client-side persistence.
        Returns:
            {reply, updated_history, tools_used, sources}
        """
        role = current_user.get("role", "")
        tools = self._tools_for_role(role, rag_enabled=self._rag.enabled)
        system_prompt = self._system_prompt(role, current_user)

        # Trim history to stay within token budget, but never split a
        # tool-call sequence (assistant-with-tool_calls + tool results must stay together).
        trimmed = self._safe_trim_history(conversation_history, max_messages=6)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(trimmed)
        messages.append({"role": "user", "content": message})

        reply, updated_messages, tools_used = self._run_agent_loop(messages, tools, current_user)

        # Strip system message and sanitize for JSON serialization
        persisted = []
        for m in updated_messages:
            if m.get("role") == "system":
                continue
            try:
                safe = json.loads(json.dumps(m, default=str))
                persisted.append(safe)
            except Exception:
                persisted.append({"role": m.get("role", "assistant"), "content": str(m.get("content", ""))})

        return {
            "reply": reply,
            "updated_history": persisted,
            "tools_used": tools_used,
            "sources": [],
        }


def get_agent_service(booking: BookingService = Depends(get_booking_service)) -> AgentService:
    return AgentService(booking)
