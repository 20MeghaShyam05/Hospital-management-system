# =============================================================================
# config.py
# Central settings — read by database layer, services, and adapters
# =============================================================================
# Override any value by setting an environment variable before launch:
#   export POSTGRES_HOST=prod-db.hospital.local
#   python main.py
# =============================================================================

import os
from pathlib import Path


def _load_local_env() -> None:
    """Load simple KEY=VALUE pairs from the repo .env file into os.environ."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


_load_local_env()


class Settings:
    # -------------------------------------------------------------------------
    # PostgreSQL
    # -------------------------------------------------------------------------
    POSTGRES_HOST:     str = os.getenv("POSTGRES_HOST",     "")
    POSTGRES_PORT:     int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB:       str = os.getenv("POSTGRES_DB",       "")
    POSTGRES_USER:     str = os.getenv("POSTGRES_USER",     "")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

    # -------------------------------------------------------------------------
    # MongoDB
    # -------------------------------------------------------------------------
    MONGO_URI: str = os.getenv(
        "MONGO_URI",
        "",
    )
    MONGO_DB:  str = os.getenv("MONGO_DB",  "")

    # -------------------------------------------------------------------------
    # Hospital business rules
    # -------------------------------------------------------------------------
    LUNCH_START:           str = "13:00"
    LUNCH_END:             str = "13:30"
    DEFAULT_SLOT_DURATION: int = 15        # minutes
    DEFAULT_START_TIME:    str = "09:00"
    DEFAULT_END_TIME:      str = "17:00"
    MAX_RESCHEDULES:       int = 2
    NEXT_SLOT_SEARCH_DAYS: int = 14        # how far ahead find_next_slot looks
    AUTO_GENERATE_SLOTS_DAYS: int = 7      # auto-gen slots for next N weekdays on registration

    # -------------------------------------------------------------------------
    # Specialization-based consultation times (minutes per session)
    # Each specialization has a clinically appropriate consultation duration.
    # Doctors can override individually via work_start_time / work_end_time.
    # -------------------------------------------------------------------------
    SPECIALIZATION_CONSULTATION_MINUTES: dict = {
        "General Physician": 10,
        "Cardiologist":      20,
        "Dermatologist":     15,
        "Neurologist":       20,
        "Orthopedist":       15,
        "Pediatrician":      15,
        "Psychiatrist":      30,
        "Gynecologist":      20,
        "ENT Specialist":    15,
        "Ophthalmologist":   15,
    }

    # -------------------------------------------------------------------------
    # Per-specialization default work hours (can be overridden per doctor)
    # -------------------------------------------------------------------------
    SPECIALIZATION_WORK_HOURS: dict = {
        "General Physician": {"start": "09:00", "end": "17:00"},
        "Cardiologist":      {"start": "09:00", "end": "16:00"},
        "Dermatologist":     {"start": "10:00", "end": "17:00"},
        "Neurologist":       {"start": "09:00", "end": "16:00"},
        "Orthopedist":       {"start": "08:00", "end": "15:00"},
        "Pediatrician":      {"start": "09:00", "end": "17:00"},
        "Psychiatrist":      {"start": "10:00", "end": "18:00"},
        "Gynecologist":      {"start": "09:00", "end": "16:00"},
        "ENT Specialist":    {"start": "09:00", "end": "16:00"},
        "Ophthalmologist":   {"start": "09:00", "end": "16:00"},
    }

    # -------------------------------------------------------------------------
    # Notifications (used by adapters/gmail.py)
    # -------------------------------------------------------------------------
    NOTIFICATION_EMAIL: str = os.getenv("NOTIFICATION_EMAIL", "")

    # -------------------------------------------------------------------------
    # G-Suite Integration
    # -------------------------------------------------------------------------
    GOOGLE_CREDENTIALS_FILE:     str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_TOKEN_FILE:           str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    GOOGLE_SERVICE_ACCOUNT_FILE: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

    # Google Forms → Sheets sync
    GOOGLE_FORMS_URL:            str = os.getenv("GOOGLE_FORMS_URL", "")
    GOOGLE_FORMS_SPREADSHEET_ID: str = os.getenv("GOOGLE_FORMS_SPREADSHEET_ID", "")
    GOOGLE_FORMS_SHEET_NAME:     str = os.getenv("GOOGLE_FORMS_SHEET_NAME", "Form Responses 1")
    GOOGLE_FORMS_SYNC_INTERVAL:  int = int(os.getenv("GOOGLE_FORMS_SYNC_INTERVAL", "300"))  # seconds

    # Google Drive
    GOOGLE_DRIVE_FOLDER_ID: str = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

    # Google Calendar
    GOOGLE_CALENDAR_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")

    # Gmail sender
    GMAIL_SENDER_EMAIL: str = os.getenv("GMAIL_SENDER_EMAIL", "")

    # -------------------------------------------------------------------------
    # LLM — Groq (free, Llama 3)
    # -------------------------------------------------------------------------
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL:   str = os.getenv("GROQ_MODEL",   "llama-3.1-8b-instant")

    # -------------------------------------------------------------------------
    # RAG / Knowledge Base — embeddings via Gemini (free)
    # -------------------------------------------------------------------------
    GEMINI_API_KEY:        str = os.getenv("GEMINI_API_KEY", "")
    RAG_POSTGRES_HOST:     str = os.getenv("RAG_POSTGRES_HOST", "")
    RAG_POSTGRES_PORT:     int = int(os.getenv("RAG_POSTGRES_PORT", "5432"))
    RAG_POSTGRES_DB:       str = os.getenv("RAG_POSTGRES_DB", "")
    RAG_POSTGRES_USER:     str = os.getenv("RAG_POSTGRES_USER", "")
    RAG_POSTGRES_PASSWORD: str = os.getenv("RAG_POSTGRES_PASSWORD", "")
    RAG_POSTGRES_SSLMODE:  str = os.getenv("RAG_POSTGRES_SSLMODE", "prefer")
    RAG_TABLE:             str = os.getenv("RAG_TABLE", "knowledge_chunks")
    RAG_DOCS_DIR:          str = os.getenv("RAG_DOCS_DIR", "knowledge_base")
    RAG_EMBED_MODEL:       str = os.getenv("RAG_EMBED_MODEL", "models/gemini-embedding-001")
    RAG_EMBED_DIM:         int = int(os.getenv("RAG_EMBED_DIM", "768"))
    RAG_TOP_K:             int = int(os.getenv("RAG_TOP_K", "4"))

    # -------------------------------------------------------------------------
    # App
    # -------------------------------------------------------------------------
    APP_ENV:   str = os.getenv("APP_ENV",   "development")   # development | production
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # -------------------------------------------------------------------------
    # RBAC / Auth
    # -------------------------------------------------------------------------
    JWT_SECRET:     str = os.getenv("JWT_SECRET",     "")
    JWT_ALGORITHM:  str = os.getenv("JWT_ALGORITHM",  "HS256")
    JWT_EXPIRE_MIN: int = int(os.getenv("JWT_EXPIRE_MIN", "60"))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    FRONT_DESK_USERNAME: str = os.getenv("FRONT_DESK_USERNAME", "")
    FRONT_DESK_PASSWORD: str = os.getenv("FRONT_DESK_PASSWORD", "")


    def validate(self) -> None:
        """Fail fast at startup if critical settings are misconfigured."""
        import os
        errors = []
        if self.JWT_SECRET in ("", "change-me-in-production") and self.APP_ENV == "production":
            errors.append("JWT_SECRET must be set in production.")
        if not (1 <= self.POSTGRES_PORT <= 65535):
            errors.append(f"POSTGRES_PORT invalid: {self.POSTGRES_PORT}")
        if self.JWT_EXPIRE_MIN < 1:
            errors.append(f"JWT_EXPIRE_MIN must be >= 1, got {self.JWT_EXPIRE_MIN}")
        if self.DEFAULT_SLOT_DURATION not in (10, 15, 20, 30):
            errors.append(f"DEFAULT_SLOT_DURATION must be one of 10/15/20/30.")
        # Validate all specialization consultation times
        for spec, mins in self.SPECIALIZATION_CONSULTATION_MINUTES.items():
            if mins not in (10, 15, 20, 30):
                errors.append(f"Consultation time for {spec} must be one of 10/15/20/30, got {mins}.")
        if errors:
            raise EnvironmentError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

settings = Settings()
settings.validate()   
