# =============================================================================
# database/postgres.py
# PostgresManager — primary persistent store
# =============================================================================
# Responsibility
# --------------
# All CRUD for: patients, doctors, nurses, slots, appointments,
#               triage, roles_permissions.
# Falls back to InMemoryStore transparently when PostgreSQL is unreachable (F2).
#
# Failure case coverage (from failure_and_edge_cases.docx)
# ---------------------------------------------------------
# F2  — PG down → is_connected=False → all ops route to _memory
# F4  — concurrent registration: ON CONFLICT (email) DO UPDATE (atomic upsert)
# F6  — double booking race: SELECT FOR UPDATE advisory lock on slot row
# E1  — same email different name: ON CONFLICT updates full_name
# E6  — negative max_patients: API-level guard added in Doctor model; PG
#        CONSTRAINT also enforced in DDL
# E7  — doctor email conflict: ON CONFLICT updates specialization silently
#
# Connection pooling
# ------------------
# Uses psycopg2's built-in connection (no external pool lib needed for this
# scale). Each PostgresManager instance holds ONE connection. Services should
# share a single PostgresManager instance (injected via config.py).
# =============================================================================

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Optional

from features.shared.database.in_memory import InMemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — psycopg2 may not be installed in every environment
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras      # RealDictCursor
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    logger.warning(
        "psycopg2 not installed. PostgresManager will run in memory-only mode. "
        "Install with: pip install psycopg2-binary"
    )


# ---------------------------------------------------------------------------
# DDL — run once on first connect to create tables if missing
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """

CREATE TABLE IF NOT EXISTS patients (
    patient_id        VARCHAR(36) NOT NULL PRIMARY KEY,
    uhid              VARCHAR(32) UNIQUE,

    full_name         VARCHAR(100) NOT NULL,
    email             VARCHAR(254) NOT NULL UNIQUE,    -- RFC 5321 max
    mobile            CHAR(10)     NOT NULL,           -- always 10 digits after normalisation
    date_of_birth     DATE,
    gender            VARCHAR(10),                     -- Male/Female/Other
    blood_group       VARCHAR(3),                      -- A+/AB-/O+ etc. max 3 chars
    address           VARCHAR(300),
    registration_date DATE         NOT NULL DEFAULT CURRENT_DATE,
    registered_by     VARCHAR(20),                     -- session user_id
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    visit_count       INTEGER      NOT NULL DEFAULT 0 CHECK (visit_count >= 0),
    visit_type        VARCHAR(20)  NOT NULL DEFAULT 'first_visit',
    password_hash     VARCHAR(255),
    password_changed_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patients_email  ON patients(email);
CREATE INDEX IF NOT EXISTS idx_patients_mobile ON patients(mobile);
CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_uhid ON patients(uhid);

-- ============================================================
-- DOCTORS
-- ============================================================
CREATE TABLE IF NOT EXISTS doctors (
    doctor_id            VARCHAR(36)  NOT NULL PRIMARY KEY,
    uhid                 VARCHAR(32) UNIQUE,

    full_name            VARCHAR(100) NOT NULL,
    email                VARCHAR(254) NOT NULL UNIQUE,
    mobile               CHAR(10)     NOT NULL,
    specialization       VARCHAR(50)  NOT NULL,
    max_patients_per_day SMALLINT     NOT NULL DEFAULT 20
        CHECK (max_patients_per_day BETWEEN 1 AND 100),
    work_start_time      TIME         NOT NULL DEFAULT TIME '09:00',
    work_end_time        TIME         NOT NULL DEFAULT TIME '17:00',
    consultation_duration_minutes SMALLINT NOT NULL DEFAULT 15
        CHECK (consultation_duration_minutes IN (10, 15, 20, 30)),
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    password_hash        VARCHAR(255),
    password_changed_at  TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doctors_email ON doctors(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doctors_uhid ON doctors(uhid);

-- ============================================================
-- NURSES
-- ============================================================
CREATE TABLE IF NOT EXISTS nurses (
    nurse_id          VARCHAR(36) NOT NULL PRIMARY KEY,
    uhid              VARCHAR(32) UNIQUE,

    full_name         VARCHAR(100) NOT NULL,
    email             VARCHAR(254) NOT NULL UNIQUE,
    mobile            CHAR(10)     NOT NULL,
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    password_hash     VARCHAR(255),
    password_changed_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nurses_email ON nurses(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nurses_uhid ON nurses(uhid);

-- ============================================================
-- APPOINTMENT SLOTS (no longer linked to availabilities)
-- ============================================================
CREATE TABLE IF NOT EXISTS appointment_slots (
    slot_id           VARCHAR(36) NOT NULL PRIMARY KEY,
    doctor_id         VARCHAR(36) NOT NULL REFERENCES doctors(doctor_id) ON DELETE RESTRICT,

    date             DATE        NOT NULL,
    start_time       TIME        NOT NULL,
    end_time         TIME        NOT NULL,
    is_lunch_break   BOOLEAN     NOT NULL DEFAULT FALSE,
    is_booked        BOOLEAN     NOT NULL DEFAULT FALSE,
    is_blocked       BOOLEAN     NOT NULL DEFAULT FALSE,

    CONSTRAINT chk_slot_times CHECK (end_time > start_time)
    ,
    CONSTRAINT uq_slot_doctor_date_start UNIQUE (doctor_id, date, start_time)
);

CREATE INDEX IF NOT EXISTS idx_slots_doctor_date ON appointment_slots(doctor_id, date);
CREATE INDEX IF NOT EXISTS idx_slots_available
    ON appointment_slots(doctor_id, date)
    WHERE is_booked = FALSE AND is_blocked = FALSE AND is_lunch_break = FALSE;

-- ============================================================
-- APPOINTMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id   VARCHAR(36) NOT NULL PRIMARY KEY,
    patient_id       VARCHAR(36) NOT NULL REFERENCES patients(patient_id) ON DELETE RESTRICT,
    doctor_id        VARCHAR(36) NOT NULL REFERENCES doctors(doctor_id) ON DELETE RESTRICT,
    slot_id          VARCHAR(36) NOT NULL REFERENCES appointment_slots(slot_id) ON DELETE RESTRICT,

    date             DATE        NOT NULL,
    start_time       TIME        NOT NULL,
    end_time         TIME        NOT NULL,

    -- Enum-constrained status and priority
    status           VARCHAR(15) NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked','completed','cancelled','no-show','rescheduled')),
    priority         VARCHAR(10) NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('normal','emergency')),

    notes            VARCHAR(500),
    booked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    booked_by        VARCHAR(20),

    cancellation_reason VARCHAR(300),
    cancelled_by     VARCHAR(20),
    cancelled_at     TIMESTAMPTZ,

    reschedule_count SMALLINT    NOT NULL DEFAULT 0
        CHECK (reschedule_count BETWEEN 0 AND 2),
    calendar_event_id   VARCHAR(255),
    calendar_event_link TEXT,

    CONSTRAINT chk_apt_times CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_apts_doctor_date    ON appointments(doctor_id, date);
CREATE INDEX IF NOT EXISTS idx_apts_patient        ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_apts_status         ON appointments(status);


-- ============================================================
-- TRIAGE
-- ============================================================
CREATE TABLE IF NOT EXISTS triage (
    triage_id         VARCHAR(36) NOT NULL PRIMARY KEY,
    patient_id        VARCHAR(36) NOT NULL REFERENCES patients(patient_id) ON DELETE RESTRICT,
    nurse_id          VARCHAR(36) NOT NULL REFERENCES nurses(nurse_id) ON DELETE RESTRICT,
    doctor_id         VARCHAR(36) NOT NULL REFERENCES doctors(doctor_id) ON DELETE RESTRICT,
    appointment_id    VARCHAR(36) REFERENCES appointments(appointment_id) ON DELETE SET NULL,

    date              DATE        NOT NULL,
    blood_pressure    VARCHAR(20),
    heart_rate        SMALLINT,
    temperature       NUMERIC(4,1),
    weight            NUMERIC(5,1),
    oxygen_saturation NUMERIC(4,1),
    symptoms          VARCHAR(500),
    queue_type        VARCHAR(10) NOT NULL DEFAULT 'normal'
        CHECK (queue_type IN ('normal','emergency')),
    notes             VARCHAR(500),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_patient ON triage(patient_id);
CREATE INDEX IF NOT EXISTS idx_triage_nurse   ON triage(nurse_id);
CREATE INDEX IF NOT EXISTS idx_triage_date    ON triage(date);

-- ============================================================
-- ROLES & PERMISSIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS roles_permissions (
    id               SERIAL PRIMARY KEY,
    role_name        VARCHAR(20) NOT NULL,
    permission_key   VARCHAR(50) NOT NULL,
    is_allowed       BOOLEAN     NOT NULL DEFAULT TRUE,
    description      VARCHAR(200),

    UNIQUE (role_name, permission_key)
);

-- Seed default permissions
INSERT INTO roles_permissions (role_name, permission_key, is_allowed, description) VALUES
    ('admin', 'register_patient', TRUE, 'Register new patients'),
    ('admin', 'register_doctor', TRUE, 'Register new doctors'),
    ('admin', 'register_nurse', TRUE, 'Register new nurses'),
    ('admin', 'set_availability', TRUE, 'Set doctor availability'),
    ('admin', 'book_appointment', TRUE, 'Book appointments'),
    ('admin', 'cancel_appointment', TRUE, 'Cancel appointments'),
    ('admin', 'reschedule', TRUE, 'Reschedule appointments'),

    ('admin', 'perform_triage', TRUE, 'Perform patient triage'),
    ('admin', 'view_triage', TRUE, 'View triage records'),
    ('admin', 'generate_report', TRUE, 'Generate reports'),
    ('admin', 'view_patient_data', TRUE, 'View patient data'),
    ('admin', 'view_all_patients', TRUE, 'View all patients'),
    ('admin', 'view_nurses', TRUE, 'View nurse list'),
    ('doctor', 'cancel_appointment', TRUE, 'Cancel own appointments'),

    ('doctor', 'view_triage', TRUE, 'View triage records for own patients'),
    ('doctor', 'generate_report', TRUE, 'Generate reports'),
    ('doctor', 'view_patient_data', TRUE, 'View own patient data'),
    ('doctor', 'view_nurses', TRUE, 'View nurse list'),
    ('doctor', 'set_availability', TRUE, 'Set own availability'),
    ('patient', 'register_patient', TRUE, 'Self-register'),
    ('patient', 'book_appointment', TRUE, 'Book own appointments'),
    ('patient', 'cancel_appointment', TRUE, 'Cancel own appointments'),
    ('patient', 'reschedule', TRUE, 'Reschedule own appointments'),
    ('patient', 'view_patient_data', TRUE, 'View own data'),
    ('nurse', 'perform_triage', TRUE, 'Record patient vitals and assign queue'),
    ('nurse', 'view_triage', TRUE, 'View triage records'),

    ('nurse', 'view_patient_data', TRUE, 'View patient data for triage'),
    ('system', 'set_availability', TRUE, 'Automated availability management'),

    ('system', 'generate_report', TRUE, 'Automated report generation')
ON CONFLICT (role_name, permission_key) DO NOTHING;

-- ============================================================
"""


class PostgresManager:
    """Primary persistent store backed by PostgreSQL.

    Falls back to InMemoryStore on every operation when PG is unavailable.

    Usage
    -----
    >>> from database import get_store
    >>> db = get_store()          # reads config.py
    >>> db.upsert_patient({...})
    """

    def __init__(self, config: dict | None = None) -> None:
        from config import settings  # lazy import to avoid circular deps

        cfg = config or {
            "host":     settings.POSTGRES_HOST,
            "port":     settings.POSTGRES_PORT,
            "dbname":   settings.POSTGRES_DB,
            "user":     settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
        }
        self._cfg  = cfg
        self._conn = None
        self._memory = InMemoryStore()   # always available (F2)
        self._last_failed_connect: float = 0.0   # epoch seconds of last failed attempt
        self._connect_cooldown: float = 60.0     # seconds to wait before retrying after failure
        self._connect()

    # =========================================================================
    # Connection management
    # =========================================================================

    def _connect(self) -> None:
        if not _PSYCOPG2_AVAILABLE:
            logger.info("PostgresManager: running in memory-only mode (psycopg2 absent).")
            return
        try:
            self._conn = psycopg2.connect(**self._cfg, connect_timeout=5)
            self._conn.autocommit = False
            self._ensure_schema()
            self._last_failed_connect = 0.0
            logger.info("PostgresManager: connected to PostgreSQL.")
        except Exception as exc:
            logger.warning(f"PostgresManager: cannot connect to PostgreSQL ({exc}). Using in-memory fallback.")
            self._conn = None
            self._last_failed_connect = time.monotonic()

    def _ensure_schema(self) -> None:
        """Run DDL once — idempotent CREATE TABLE IF NOT EXISTS."""
        with self._conn.cursor() as cur:
            # Abort DDL immediately if any table is locked by another session
            # rather than blocking startup indefinitely.
            cur.execute("SET lock_timeout = '8s'")
            cur.execute("SET statement_timeout = '30s'")
            cur.execute(_SCHEMA_SQL)
            cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255);")
            cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS calendar_event_link TEXT;")
            cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS assigned_nurse_id VARCHAR(36);")
        self._conn.commit()
        with self._conn.cursor() as cur:
            cur.execute("SET lock_timeout = '0'")
            cur.execute("SET statement_timeout = '0'")
        self._conn.commit()

    def _reconnect_if_needed(self) -> None:
        """Attempt reconnect on a broken connection, with a cooldown to avoid
        hammering an unavailable DB on every request (which would hang each
        caller for up to 13 s and cause Streamlit timeouts)."""
        if self._conn is None:
            elapsed = time.monotonic() - self._last_failed_connect
            if elapsed < self._connect_cooldown:
                return  # still in cooldown — stay in memory-only mode
            self._connect()
            return
        try:
            self._conn.cursor().execute("SELECT 1")
        except Exception:
            self._conn = None
            self._last_failed_connect = time.monotonic()
            self._connect()

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def _cursor(self):
        """Return a RealDictCursor for dict-style row access."""
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    @staticmethod
    def _get_scalar(row: Optional[dict], key: str, default: Any = 0) -> Any:
        """Read a scalar value from a RealDictCursor row safely."""
        if not row:
            return default
        return row.get(key, default)

    # =========================================================================
    # PATIENTS
    # =========================================================================

    def upsert_patient(self, patient_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.upsert_patient(patient_dict)
        try:
            sql = """
            INSERT INTO patients
                (patient_id, uhid, full_name, email, mobile, date_of_birth, gender,
                 blood_group, address, registration_date, registered_by,
                 is_active, visit_count, visit_type, password_hash, password_changed_at, created_at)
            VALUES
                (%(patient_id)s, %(uhid)s, %(full_name)s, %(email)s, %(mobile)s,
                 %(date_of_birth)s, %(gender)s, %(blood_group)s, %(address)s,
                 %(registration_date)s, %(registered_by)s,
                 %(is_active)s, %(visit_count)s, %(visit_type)s, %(password_hash)s, %(password_changed_at)s, %(created_at)s)
            ON CONFLICT (email) DO UPDATE SET
                uhid        = COALESCE(patients.uhid, EXCLUDED.uhid),
                full_name   = EXCLUDED.full_name,
                mobile      = EXCLUDED.mobile,
                visit_count = EXCLUDED.visit_count,
                visit_type  = EXCLUDED.visit_type
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, patient_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"upsert_patient PG error: {exc}. Falling back to memory.")
            return self._memory.upsert_patient(patient_dict)

    def get_patient_by_id(self, patient_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_patient_by_id(patient_id)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE patient_id = %s", (patient_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_patient_by_id PG error: {exc}")
            return self._memory.get_patient_by_id(patient_id)

    def get_patient_by_email(self, email: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_patient_by_email(email)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE email = %s AND is_active = TRUE", (email.lower(),))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_patient_by_email PG error: {exc}")
            return self._memory.get_patient_by_email(email)

    def get_patient_by_uhid(self, uhid: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_patient_by_uhid(uhid)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE uhid = %s AND is_active = TRUE", (uhid,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_patient_by_uhid PG error: {exc}")
            return self._memory.get_patient_by_uhid(uhid)

    def get_patient_by_mobile(self, mobile: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_patient_by_mobile(mobile)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE mobile = %s AND is_active = TRUE", (mobile,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_patient_by_mobile PG error: {exc}")
            return self._memory.get_patient_by_mobile(mobile)

    def list_patients(self, active_only: bool = True) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.list_patients(active_only)
        try:
            sql = "SELECT * FROM patients"
            if active_only:
                sql += " WHERE is_active = TRUE"
            sql += " ORDER BY full_name"
            with self._cursor() as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"list_patients PG error: {exc}")
            return self._memory.list_patients(active_only)

    # =========================================================================
    # DOCTORS
    # =========================================================================

    def upsert_doctor(self, doctor_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.upsert_doctor(doctor_dict)
        try:
            sql = """
            INSERT INTO doctors
                (doctor_id, uhid, full_name, email, mobile, specialization,
                 max_patients_per_day, work_start_time,
                 work_end_time, consultation_duration_minutes, is_active,
                 password_hash, password_changed_at, created_at)
            VALUES
                (%(doctor_id)s, %(uhid)s, %(full_name)s, %(email)s, %(mobile)s,
                 %(specialization)s, %(max_patients_per_day)s,
                 %(work_start_time)s, %(work_end_time)s, %(consultation_duration_minutes)s,
                 %(is_active)s, %(password_hash)s, %(password_changed_at)s, %(created_at)s)
            ON CONFLICT (email) DO UPDATE SET
                uhid                 = COALESCE(doctors.uhid, EXCLUDED.uhid),
                full_name            = EXCLUDED.full_name,
                specialization       = EXCLUDED.specialization,
                max_patients_per_day = EXCLUDED.max_patients_per_day,
                work_start_time      = EXCLUDED.work_start_time,
                work_end_time        = EXCLUDED.work_end_time,
                consultation_duration_minutes = EXCLUDED.consultation_duration_minutes
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, doctor_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"upsert_doctor PG error: {exc}. Falling back to memory.")
            return self._memory.upsert_doctor(doctor_dict)

    def get_doctor_by_id(self, doctor_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_doctor_by_id(doctor_id)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM doctors WHERE doctor_id = %s", (doctor_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_doctor_by_id PG error: {exc}")
            return self._memory.get_doctor_by_id(doctor_id)

    def get_doctor_by_email(self, email: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_doctor_by_email(email)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM doctors WHERE email = %s", (email.lower(),))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_doctor_by_email PG error: {exc}")
            return self._memory.get_doctor_by_email(email)

    def get_doctor_by_uhid(self, uhid: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_doctor_by_uhid(uhid)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM doctors WHERE uhid = %s", (uhid,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_doctor_by_uhid PG error: {exc}")
            return self._memory.get_doctor_by_uhid(uhid)

    def list_doctors(self, active_only: bool = True) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.list_doctors(active_only)
        try:
            sql = "SELECT * FROM doctors"
            if active_only:
                sql += " WHERE is_active = TRUE"
            sql += " ORDER BY full_name"
            with self._cursor() as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"list_doctors PG error: {exc}")
            return self._memory.list_doctors(active_only)

    def update_patient_password(self, patient_id: str, password_hash: str, password_changed_at: str) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_patient_password(patient_id, password_hash, password_changed_at)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE patients SET password_hash=%s, password_changed_at=%s WHERE patient_id=%s",
                    (password_hash, password_changed_at, patient_id),
                )
                updated = cur.rowcount > 0
            self._conn.commit()
            return updated
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_patient_password PG error: {exc}")
            return self._memory.update_patient_password(patient_id, password_hash, password_changed_at)

    def update_doctor_password(self, doctor_id: str, password_hash: str, password_changed_at: str) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_doctor_password(doctor_id, password_hash, password_changed_at)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE doctors SET password_hash=%s, password_changed_at=%s WHERE doctor_id=%s",
                    (password_hash, password_changed_at, doctor_id),
                )
                updated = cur.rowcount > 0
            self._conn.commit()
            return updated
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_doctor_password PG error: {exc}")
            return self._memory.update_doctor_password(doctor_id, password_hash, password_changed_at)

    # =========================================================================
    # NURSES
    # =========================================================================

    def upsert_nurse(self, nurse_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.upsert_nurse(nurse_dict)
        try:
            sql = """
            INSERT INTO nurses
                (nurse_id, uhid, full_name, email, mobile, is_active,
                 password_hash, password_changed_at, created_at)
            VALUES
                (%(nurse_id)s, %(uhid)s, %(full_name)s, %(email)s, %(mobile)s,
                 %(is_active)s, %(password_hash)s, %(password_changed_at)s, %(created_at)s)
            ON CONFLICT (email) DO UPDATE SET
                uhid      = COALESCE(nurses.uhid, EXCLUDED.uhid),
                full_name = EXCLUDED.full_name,
                mobile    = EXCLUDED.mobile
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, nurse_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"upsert_nurse PG error: {exc}. Falling back to memory.")
            return self._memory.upsert_nurse(nurse_dict)

    def get_nurse_by_id(self, nurse_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_nurse_by_id(nurse_id)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM nurses WHERE nurse_id = %s", (nurse_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_nurse_by_id PG error: {exc}")
            return self._memory.get_nurse_by_id(nurse_id)

    def get_nurse_by_email(self, email: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_nurse_by_email(email)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM nurses WHERE email = %s", (email.lower(),))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_nurse_by_email PG error: {exc}")
            return self._memory.get_nurse_by_email(email)

    def get_nurse_by_uhid(self, uhid: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_nurse_by_uhid(uhid)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM nurses WHERE uhid = %s", (uhid,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_nurse_by_uhid PG error: {exc}")
            return self._memory.get_nurse_by_uhid(uhid)

    def list_nurses(self, active_only: bool = True) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.list_nurses(active_only)
        try:
            sql = "SELECT * FROM nurses"
            if active_only:
                sql += " WHERE is_active = TRUE"
            sql += " ORDER BY full_name"
            with self._cursor() as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"list_nurses PG error: {exc}")
            return self._memory.list_nurses(active_only)

    def update_nurse_password(self, nurse_id: str, password_hash: str, password_changed_at: str) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_nurse_password(nurse_id, password_hash, password_changed_at)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE nurses SET password_hash=%s, password_changed_at=%s WHERE nurse_id=%s",
                    (password_hash, password_changed_at, nurse_id),
                )
                updated = cur.rowcount > 0
            self._conn.commit()
            return updated
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_nurse_password PG error: {exc}")
            return self._memory.update_nurse_password(nurse_id, password_hash, password_changed_at)

    # =========================================================================
    # SLOTS
    # =========================================================================

    def save_slots(self, slot_dicts: list[dict]) -> int:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.save_slots(slot_dicts)
        try:
            sql = """
            INSERT INTO appointment_slots
                (slot_id, doctor_id, date, start_time,
                 end_time, is_lunch_break, is_booked, is_blocked)
            VALUES
                (%(slot_id)s, %(doctor_id)s, %(date)s,
                 %(start_time)s, %(end_time)s, %(is_lunch_break)s,
                 %(is_booked)s, %(is_blocked)s)
            ON CONFLICT (slot_id) DO NOTHING;
            """
            with self._cursor() as cur:
                psycopg2.extras.execute_batch(cur, sql, slot_dicts)
            self._conn.commit()
            return len(slot_dicts)
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"save_slots PG error: {exc}")
            return self._memory.save_slots(slot_dicts)

    def get_slot(self, slot_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_slot(slot_id)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM appointment_slots WHERE slot_id=%s", (slot_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_slot PG error: {exc}")
            return self._memory.get_slot(slot_id)

    def get_available_slots(self, doctor_id: str, date_str: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_available_slots(doctor_id, date_str)
        try:
            sql = """
            SELECT * FROM appointment_slots
            WHERE doctor_id=%s AND date=%s
              AND is_booked=FALSE AND is_blocked=FALSE AND is_lunch_break=FALSE
            ORDER BY start_time;
            """
            with self._cursor() as cur:
                cur.execute(sql, (doctor_id, date_str))
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_available_slots PG error: {exc}")
            return self._memory.get_available_slots(doctor_id, date_str)

    def get_all_slots_for_doctor_date(self, doctor_id: str, date_str: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_all_slots_for_doctor_date(doctor_id, date_str)
        try:
            sql = """
            SELECT * FROM appointment_slots
            WHERE doctor_id=%s AND date=%s
            ORDER BY start_time;
            """
            with self._cursor() as cur:
                cur.execute(sql, (doctor_id, date_str))
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_all_slots_for_doctor_date PG error: {exc}")
            return self._memory.get_all_slots_for_doctor_date(doctor_id, date_str)

    def update_slot_booked(self, slot_id: str, is_booked: bool) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_slot_booked(slot_id, is_booked)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE appointment_slots SET is_booked=%s WHERE slot_id=%s",
                    (is_booked, slot_id)
                )
                updated = cur.rowcount > 0
            self._conn.commit()
            return updated
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_slot_booked PG error: {exc}")
            return self._memory.update_slot_booked(slot_id, is_booked)

    def update_slot_blocked(self, slot_id: str, is_blocked: bool) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_slot_blocked(slot_id, is_blocked)
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    UPDATE appointment_slots
                       SET is_blocked=%s
                     WHERE slot_id=%s
                       AND (is_booked=FALSE OR %s=FALSE)
                    """,
                    (is_blocked, slot_id, is_blocked),
                )
                updated = cur.rowcount > 0
            self._conn.commit()
            return updated
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_slot_blocked PG error: {exc}")
            return self._memory.update_slot_blocked(slot_id, is_blocked)

    def lock_slot_for_update(self, slot_id: str) -> Optional[dict]:
        """SELECT FOR UPDATE — prevents F6 double-booking race condition."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_slot(slot_id)
        try:
            self._conn.rollback()
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM appointment_slots
                    WHERE slot_id=%s
                      AND is_booked=FALSE AND is_blocked=FALSE
                    FOR UPDATE;
                    """,
                    (slot_id,)
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"lock_slot_for_update PG error: {exc}")
            return None

    def find_next_available_slot(self, doctor_id: str, after_date_str: str, max_days: int = 14) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.find_next_available_slot(doctor_id, after_date_str, max_days)
        try:
            from datetime import date as date_type, timedelta
            start = date_type.fromisoformat(after_date_str) + timedelta(days=1)
            end   = start + timedelta(days=max_days)
            sql = """
            SELECT * FROM appointment_slots
            WHERE doctor_id=%s
              AND date > %s AND date <= %s
              AND is_booked=FALSE AND is_blocked=FALSE AND is_lunch_break=FALSE
              AND EXTRACT(DOW FROM date) NOT IN (0, 6)  -- skip weekends (E12)
            ORDER BY date, start_time
            LIMIT 1;
            """
            with self._cursor() as cur:
                cur.execute(sql, (doctor_id, after_date_str, end.isoformat()))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"find_next_available_slot PG error: {exc}")
            return self._memory.find_next_available_slot(doctor_id, after_date_str, max_days)

    def has_slots_for_doctor_date(self, doctor_id: str, date_str: str) -> bool:
        """Check if any slots exist for a doctor on a date (for auto-generation check)."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.has_slots_for_doctor_date(doctor_id, date_str)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM appointment_slots WHERE doctor_id=%s AND date=%s) AS has_slots",
                    (doctor_id, date_str)
                )
                row = cur.fetchone()
                return bool(row and row.get("has_slots", False))
        except Exception as exc:
            logger.error(f"has_slots_for_doctor_date PG error: {exc}")
            return self._memory.has_slots_for_doctor_date(doctor_id, date_str)

    # =========================================================================
    # APPOINTMENTS
    # =========================================================================

    def save_appointment(self, apt_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.save_appointment(apt_dict)
        try:
            sql = """
            INSERT INTO appointments
                (appointment_id, patient_id, doctor_id, slot_id, date,
                 start_time, end_time, status, priority, notes,
                 booked_at, booked_by, reschedule_count, calendar_event_id,
                 calendar_event_link)
            VALUES
                (%(appointment_id)s, %(patient_id)s, %(doctor_id)s,
                 %(slot_id)s, %(date)s, %(start_time)s, %(end_time)s,
                 %(status)s, %(priority)s, %(notes)s,
                 %(booked_at)s, %(booked_by)s, %(reschedule_count)s,
                 %(calendar_event_id)s, %(calendar_event_link)s)
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, apt_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"save_appointment PG error: {exc}")
            return self._memory.save_appointment(apt_dict)

    def update_appointment(self, apt_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.update_appointment(apt_dict)
        try:
            sql = """
            UPDATE appointments SET
                slot_id             = %(slot_id)s,
                date                = %(date)s,
                start_time          = %(start_time)s,
                end_time            = %(end_time)s,
                status              = %(status)s,
                cancellation_reason = %(cancellation_reason)s,
                cancelled_by        = %(cancelled_by)s,
                cancelled_at        = %(cancelled_at)s,
                reschedule_count    = %(reschedule_count)s,
                calendar_event_id   = %(calendar_event_id)s,
                calendar_event_link = %(calendar_event_link)s
            WHERE appointment_id = %(appointment_id)s
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, apt_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"update_appointment PG error: {exc}")
            return self._memory.update_appointment(apt_dict)

    def get_appointment(self, appointment_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_appointment(appointment_id)
        try:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM appointments WHERE appointment_id=%s", (appointment_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as exc:
            logger.error(f"get_appointment PG error: {exc}")
            return self._memory.get_appointment(appointment_id)

    def get_appointments_for_patient(self, patient_id: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_appointments_for_patient(patient_id)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT * FROM appointments WHERE patient_id=%s ORDER BY date, start_time",
                    (patient_id,)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_appointments_for_patient PG error: {exc}")
            return self._memory.get_appointments_for_patient(patient_id)

    def get_appointments_for_doctor_date(
        self, doctor_id: str, date_str: str, status_filter: list[str] | None = None
    ) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_appointments_for_doctor_date(doctor_id, date_str, status_filter)
        try:
            sql = "SELECT * FROM appointments WHERE doctor_id=%s AND date=%s"
            params: list = [doctor_id, date_str]
            if status_filter:
                placeholders = ",".join(["%s"] * len(status_filter))
                sql += f" AND status IN ({placeholders})"
                params.extend(status_filter)
            sql += " ORDER BY start_time"
            with self._cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_appointments_for_doctor_date PG error: {exc}")
            return self._memory.get_appointments_for_doctor_date(doctor_id, date_str, status_filter)

    def assign_nurse_to_appointment(self, appointment_id: str, nurse_id: str) -> Optional[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.assign_nurse_to_appointment(appointment_id, nurse_id)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE appointments SET assigned_nurse_id=%s WHERE appointment_id=%s RETURNING *",
                    (nurse_id, appointment_id),
                )
                row = cur.fetchone()
            self._conn.commit()
            return dict(row) if row else None
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"assign_nurse_to_appointment PG error: {exc}")
            return self._memory.assign_nurse_to_appointment(appointment_id, nurse_id)

    def get_appointments_for_date(self, date_str: str, status_filter: list[str] | None = None) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_appointments_for_date(date_str, status_filter)
        try:
            sql = "SELECT * FROM appointments WHERE date=%s"
            params: list = [date_str]
            if status_filter:
                placeholders = ",".join(["%s"] * len(status_filter))
                sql += f" AND status IN ({placeholders})"
                params.extend(status_filter)
            sql += " ORDER BY start_time"
            with self._cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_appointments_for_date PG error: {exc}")
            return self._memory.get_appointments_for_date(date_str, status_filter)

    def count_booked_appointments(self, doctor_id: str, date_str: str) -> int:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.count_booked_appointments(doctor_id, date_str)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS total FROM appointments WHERE doctor_id=%s AND date=%s AND status='booked'",
                    (doctor_id, date_str)
                )
                row = cur.fetchone()
                return int(self._get_scalar(row, "total", 0))
        except Exception as exc:
            logger.error(f"count_booked_appointments PG error: {exc}")
            return self._memory.count_booked_appointments(doctor_id, date_str)

    def check_slot_conflict(self, slot_id: str) -> bool:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.check_slot_conflict(slot_id)
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS total FROM appointments
                    WHERE slot_id=%s AND status NOT IN ('cancelled','completed','no-show')
                    """,
                    (slot_id,)
                )
                row = cur.fetchone()
                return int(self._get_scalar(row, "total", 0)) > 0
        except Exception as exc:
            logger.error(f"check_slot_conflict PG error: {exc}")
            return self._memory.check_slot_conflict(slot_id)

    def get_all_appointments(
        self,
        date_str: str | None = None,
        doctor_id: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_all_appointments(date_str, doctor_id, status_filter)
        try:
            conditions, params = [], []
            if date_str:
                conditions.append("date=%s"); params.append(date_str)
            if doctor_id:
                conditions.append("doctor_id=%s"); params.append(doctor_id)
            if status_filter:
                placeholders = ",".join(["%s"] * len(status_filter))
                conditions.append(f"status IN ({placeholders})")
                params.extend(status_filter)
            sql = "SELECT * FROM appointments"
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY date, start_time"
            with self._cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_all_appointments PG error: {exc}")
            return self._memory.get_all_appointments(date_str, doctor_id, status_filter)


    # =========================================================================
    # TRIAGE
    # =========================================================================

    def save_triage(self, triage_dict: dict) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.save_triage(triage_dict)
        try:
            sql = """
            INSERT INTO triage
                (triage_id, patient_id, nurse_id, doctor_id, appointment_id,
                 date, blood_pressure, heart_rate, temperature, weight,
                 oxygen_saturation, symptoms, queue_type, notes, created_at)
            VALUES
                (%(triage_id)s, %(patient_id)s, %(nurse_id)s, %(doctor_id)s,
                 %(appointment_id)s, %(date)s, %(blood_pressure)s, %(heart_rate)s,
                 %(temperature)s, %(weight)s, %(oxygen_saturation)s, %(symptoms)s,
                 %(queue_type)s, %(notes)s, %(created_at)s)
            RETURNING *;
            """
            with self._cursor() as cur:
                cur.execute(sql, triage_dict)
                row = dict(cur.fetchone())
            self._conn.commit()
            return row
        except Exception as exc:
            self._conn.rollback()
            logger.error(f"save_triage PG error: {exc}")
            return self._memory.save_triage(triage_dict)

    def get_triage_for_patient(self, patient_id: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_triage_for_patient(patient_id)
        try:
            with self._cursor() as cur:
                cur.execute(
                    "SELECT * FROM triage WHERE patient_id=%s ORDER BY created_at DESC",
                    (patient_id,)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_triage_for_patient PG error: {exc}")
            return self._memory.get_triage_for_patient(patient_id)

    def get_triage_for_date(self, date_str: str, doctor_id: str | None = None) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_triage_for_date(date_str, doctor_id)
        try:
            sql = "SELECT * FROM triage WHERE date=%s"
            params: list = [date_str]
            if doctor_id:
                sql += " AND doctor_id=%s"
                params.append(doctor_id)
            sql += " ORDER BY created_at DESC"
            with self._cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_triage_for_date PG error: {exc}")
            return self._memory.get_triage_for_date(date_str, doctor_id)

    # =========================================================================
    # ROLES & PERMISSIONS
    # =========================================================================

    def get_roles_permissions(self, role_name: str | None = None) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_roles_permissions(role_name)
        try:
            sql = "SELECT * FROM roles_permissions"
            params: list = []
            if role_name:
                sql += " WHERE role_name=%s"
                params.append(role_name)
            sql += " ORDER BY role_name, permission_key"
            with self._cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            logger.error(f"get_roles_permissions PG error: {exc}")
            return self._memory.get_roles_permissions(role_name)

    # =========================================================================
    # REPORTING (GO8)
    # =========================================================================

    def get_report_data(self, date_str: str, doctor_id: str | None = None) -> dict:
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_report_data(date_str, doctor_id)
        try:
            filter_clause = "AND doctor_id=%s" if doctor_id else ""
            params_base   = [date_str, doctor_id] if doctor_id else [date_str]

            with self._cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS total FROM appointments WHERE date=%s {filter_clause}", params_base)
                total = int(self._get_scalar(cur.fetchone(), "total", 0))
                cur.execute(f"SELECT COUNT(*) AS total FROM appointments WHERE date=%s AND status='completed' {filter_clause}", params_base)
                completed = int(self._get_scalar(cur.fetchone(), "total", 0))
                cur.execute(f"SELECT COUNT(*) AS total FROM appointments WHERE date=%s AND status='cancelled' {filter_clause}", params_base)
                cancelled = int(self._get_scalar(cur.fetchone(), "total", 0))
                cur.execute(f"SELECT COUNT(*) AS total FROM appointments WHERE date=%s AND status='no-show' {filter_clause}", params_base)
                no_show = int(self._get_scalar(cur.fetchone(), "total", 0))

                cur.execute(f"""
                    SELECT doctor_id, COUNT(*) AS cnt FROM appointments
                    WHERE date=%s AND status='completed' {filter_clause}
                    GROUP BY doctor_id ORDER BY cnt DESC LIMIT 1
                """, params_base)
                busiest_row = cur.fetchone()
                busiest_doctor_id = busiest_row["doctor_id"] if busiest_row else None

                cur.execute(f"""
                    SELECT EXTRACT(HOUR FROM start_time)::int AS hr, COUNT(*) AS cnt
                    FROM appointments WHERE date=%s {filter_clause}
                    GROUP BY hr ORDER BY cnt DESC LIMIT 1
                """, params_base)
                peak_row  = cur.fetchone()
                peak_hour = peak_row["hr"] if peak_row else None

                cur.execute(f"""
                    SELECT COUNT(*) AS total FROM appointment_slots
                    WHERE date=%s AND is_blocked=FALSE
                    {('AND doctor_id=%s' if doctor_id else '')}
                """, params_base)
                total_slots = int(self._get_scalar(cur.fetchone(), "total", 0))

            return {
                "date":               date_str,
                "doctor_id_filter":   doctor_id,
                "total_appointments": total,
                "total_completed":    completed,
                "total_cancelled":    cancelled,
                "total_no_shows":     no_show,
                "busiest_doctor_id":  busiest_doctor_id,
                "peak_hour":          peak_hour,
                "slot_utilization_pct": round((completed / total_slots * 100), 1) if total_slots else 0,
                "cancellation_rate_pct": round((cancelled / total * 100), 1) if total else 0,
            }
        except Exception as exc:
            logger.error(f"get_report_data PG error: {exc}")
            return self._memory.get_report_data(date_str, doctor_id)

    # =========================================================================
    # Audit log fallback (mirrors InMemoryStore interface)
    # =========================================================================

    def log_audit(self, event: str, data: dict) -> None:
        """Delegate audit logging to InMemoryStore (Mongo handles real logs)."""
        self._memory.log_audit(event, data)

    def __repr__(self) -> str:
        mode = "PostgreSQL" if self.is_connected else "InMemory(fallback)"
        return f"PostgresManager(mode={mode})"
