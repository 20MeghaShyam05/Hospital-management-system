# =============================================================================
# database/mongo.py
# MongoManager — audit log, queue persistence, and analytics store
# =============================================================================
# Role in the architecture
# ------------------------
# MongoDB is NOT the primary store for transactional data (that's Postgres).
# It handles three specific jobs:
#
#   1. AUDIT TRAIL  — every booking/cancel/reschedule action is logged as a
#                     document: {event, actor, payload, timestamp}
#   2. QUEUE STATE  — persists the in-memory queue to Mongo so QueueManager
#                     can reload after a restart (F9 mitigation from failure doc)
#   3. ANALYTICS    — raw appointment documents for Pandas/NumPy processing
#                     (Step 7 Data Science component)
#
# Failure case coverage (from failure_and_edge_cases.docx)
# ---------------------------------------------------------
# F3  — Mongo down → all ops fall back to InMemoryStore.audit_logs
#        Patient registration succeeds; audit entry goes to RAM instead.
# F9  — Queue lost on restart: persist queue state to Mongo on every
#        enqueue/dequeue; reload on startup.
#
# Collections
# -----------
# dpas_audit_logs     — append-only event log
# dpas_queue_state    — one doc per (doctor_id, date, appointment_id)
# dpas_analytics_raw  — denormalised appointment snapshots for DS layer
# =============================================================================

from __future__ import annotations

import logging
import time as time_module
from datetime import datetime
from typing import Any, Optional

from features.shared.database.in_memory import InMemoryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — pymongo may not be installed
# ---------------------------------------------------------------------------
try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    _PYMONGO_AVAILABLE = True
except ImportError:
    _PYMONGO_AVAILABLE = False
    logger.warning(
        "pymongo not installed. MongoManager will run in memory-only mode. "
        "Install with: pip install pymongo"
    )

# Collection names
_COL_AUDIT     = "dpas_audit_logs"
_COL_QUEUE     = "dpas_queue_state"
_COL_ANALYTICS = "dpas_analytics_raw"
_COL_PRESCRIPTIONS = "dpas_prescriptions"


class MongoManager:
    """Audit log, queue persistence, and analytics store backed by MongoDB.

    Falls back to InMemoryStore when MongoDB is unreachable (F3).

    Usage
    -----
    >>> from database import get_mongo
    >>> mongo = get_mongo()
    >>> mongo.log_audit("appointment_booked", {"appointment_id": "APT-...", ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        from config import settings  # lazy import

        cfg = {
            "uri":    settings.MONGO_URI,
            "db":     settings.MONGO_DB,
        }
        if config:
            cfg.update(config)
        self._uri     = cfg["uri"]
        self._db_name = cfg["db"]
        self._client = None
        self._db     = None
        self._memory = InMemoryStore()   # fallback (F3)
        self._prescriptions_memory: list[dict] = []
        self._reconnect_cooldown_until = 0.0
        self._connect()

    # =========================================================================
    # Connection management
    # =========================================================================

    def _connect(self) -> None:
        if not _PYMONGO_AVAILABLE:
            logger.info("MongoManager: running in memory-only mode (pymongo absent).")
            return
        try:
            self._client = MongoClient(
                self._uri,
                serverSelectionTimeoutMS=3000,   # fast fail (3 s)
                connectTimeoutMS=3000,
            )
            # Force a round-trip to confirm the server is reachable
            self._client.admin.command("ping")
            self._db = self._client[self._db_name]
            self._ensure_indexes()
            logger.info(f"MongoManager: connected to MongoDB db='{self._db_name}'.")
        except Exception as exc:
            logger.warning(f"MongoManager: cannot reach MongoDB ({exc}). Using in-memory fallback.")
            self._client = None
            self._db     = None
            self._reconnect_cooldown_until = time_module.monotonic() + 30

    def _ensure_indexes(self) -> None:
        """Create indexes once — idempotent."""
        # Audit: search by event type and timestamp
        self._db[_COL_AUDIT].create_index(
            [("event", ASCENDING), ("logged_at", DESCENDING)],
            background=True
        )
        # Queue: fast lookup by appointment_id
        self._db[_COL_QUEUE].create_index(
            [("appointment_id", ASCENDING)],
            unique=True,
            background=True
        )
        self._db[_COL_QUEUE].create_index(
            [("doctor_id", ASCENDING), ("date", ASCENDING)],
            background=True
        )
        # Analytics: date + doctor for DS aggregations
        self._db[_COL_ANALYTICS].create_index(
            [("date", ASCENDING), ("doctor_id", ASCENDING)],
            background=True
        )
        self._db[_COL_PRESCRIPTIONS].create_index(
            [("patient_id", ASCENDING), ("created_at", DESCENDING)],
            background=True,
        )
        self._db[_COL_PRESCRIPTIONS].create_index(
            [("doctor_id", ASCENDING), ("created_at", DESCENDING)],
            background=True,
        )

    def _reconnect_if_needed(self) -> None:
        if time_module.monotonic() < self._reconnect_cooldown_until:
            return
        if self._client is None:
            self._connect()
            return
        try:
            self._client.admin.command("ping")
        except Exception:
            self._client = None
            self._db     = None
            self._reconnect_cooldown_until = time_module.monotonic() + 30
            self._connect()

    def update_queue_position(self, appointment_id: str, queue_position: int) -> None:
        """Persist queue position changes used after dequeue/cancel reorder."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return
        try:
            self._db[_COL_QUEUE].update_one(
                {"appointment_id": appointment_id},
                {"$set": {"queue_position": queue_position, "updated_at": datetime.now().isoformat()}},
            )
        except Exception as exc:
            logger.error(f"update_queue_position Mongo error: {exc}")

    @property
    def is_connected(self) -> bool:
        return self._db is not None

    # =========================================================================
    # AUDIT LOG  (F3 mitigation — primary job of Mongo in this system)
    # =========================================================================

    def log_audit(
        self,
        event: str,
        data: dict,
        actor: Optional[str] = None,
    ) -> None:
        """Append an audit entry.

        Parameters
        ----------
        event : str  e.g. "patient_registered", "appointment_booked", "slot_cancelled"
        data  : dict payload (appointment_id, patient_id, etc.)
        actor : str  session user ID who triggered the action
        """
        self._reconnect_if_needed()
        doc = {
            "event":     event,
            "actor":     actor,
            "data":      data,
            "logged_at": datetime.now().isoformat(),
        }
        if not self.is_connected:
            # F3 — graceful fallback: store in RAM, not a hard failure
            self._memory.log_audit(event, data, actor=actor)
            logger.debug(f"Audit (memory fallback): {event}")
            return
        try:
            self._db[_COL_AUDIT].insert_one(doc)
        except Exception as exc:
            logger.error(f"log_audit Mongo error: {exc}. Falling back to memory.")
            self._memory.log_audit(event, data, actor=actor)

    def get_audit_logs(
        self,
        event_filter: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Retrieve recent audit entries."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return self._memory.get_audit_logs(event_filter)
        try:
            query = {"event": event_filter} if event_filter else {}
            cursor = (
                self._db[_COL_AUDIT]
                .find(query, {"_id": 0})
                .sort("logged_at", DESCENDING)
                .limit(limit)
            )
            return list(cursor)
        except Exception as exc:
            logger.error(f"get_audit_logs Mongo error: {exc}")
            return self._memory.get_audit_logs(event_filter)

    # =========================================================================
    # QUEUE STATE PERSISTENCE  (F9 mitigation)
    # =========================================================================

    def persist_queue_entry(self, queue_dict: dict) -> None:
        """Upsert one queue entry so the queue survives a process restart."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return   # best-effort; in-memory queue is the source of truth
        try:
            self._db[_COL_QUEUE].replace_one(
                {"appointment_id": queue_dict["appointment_id"]},
                queue_dict,
                upsert=True,
            )
        except Exception as exc:
            logger.error(f"persist_queue_entry Mongo error: {exc}")

    def load_queue_for_doctor_date(self, doctor_id: str, date_str: str) -> list[dict]:
        """Reload persisted queue entries on startup (F9)."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return []
        try:
            cursor = self._db[_COL_QUEUE].find(
                {"doctor_id": doctor_id, "date": date_str, "status": {"$in": ["waiting", "in-progress"]}},
                {"_id": 0},
            ).sort([("is_emergency", DESCENDING), ("queue_position", ASCENDING)])
            return list(cursor)
        except Exception as exc:
            logger.error(f"load_queue_for_doctor_date Mongo error: {exc}")
            return []

    def remove_queue_entry(self, appointment_id: str) -> None:
        """Delete queue entry when appointment is completed/cancelled."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return
        try:
            self._db[_COL_QUEUE].delete_one({"appointment_id": appointment_id})
        except Exception as exc:
            logger.error(f"remove_queue_entry Mongo error: {exc}")

    def update_queue_status(self, appointment_id: str, new_status: str) -> None:
        """Update queue entry status in Mongo (mirrors QueueManager state)."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return
        try:
            self._db[_COL_QUEUE].update_one(
                {"appointment_id": appointment_id},
                {"$set": {"status": new_status, "updated_at": datetime.now().isoformat()}},
            )
        except Exception as exc:
            logger.error(f"update_queue_status Mongo error: {exc}")

    # =========================================================================
    # ANALYTICS RAW STORE  (Step 7 Data Science layer)
    # =========================================================================

    def store_analytics_snapshot(self, appointment_dict: dict) -> None:
        """Push a denormalised appointment doc to the analytics collection.

        Called by BookingService after every status change so the DS layer
        always has fresh data without joining tables.
        """
        self._reconnect_if_needed()
        if not self.is_connected:
            return
        try:
            doc = {**appointment_dict, "snapshot_at": datetime.now().isoformat()}
            self._db[_COL_ANALYTICS].replace_one(
                {"appointment_id": appointment_dict["appointment_id"]},
                doc,
                upsert=True,
            )
        except Exception as exc:
            logger.error(f"store_analytics_snapshot Mongo error: {exc}")

    def get_analytics_for_date_range(
        self,
        start_date: str,
        end_date: str,
        doctor_id: Optional[str] = None,
    ) -> list[dict]:
        """Fetch denormalised appointment docs for Pandas/NumPy processing."""
        self._reconnect_if_needed()
        if not self.is_connected:
            logger.warning("get_analytics_for_date_range: Mongo unavailable, returning empty.")
            return []
        try:
            query: dict[str, Any] = {"date": {"$gte": start_date, "$lte": end_date}}
            if doctor_id:
                query["doctor_id"] = doctor_id
            return list(
                self._db[_COL_ANALYTICS].find(query, {"_id": 0})
            )
        except Exception as exc:
            logger.error(f"get_analytics_for_date_range Mongo error: {exc}")
            return []

    def get_peak_hours_data(self, date_str: str) -> list[dict]:
        """Aggregate appointment counts by start hour for peak-hour prediction."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return []
        try:
            pipeline = [
                {"$match": {"date": date_str}},
                {"$group": {
                    "_id": {"$substr": ["$start_time", 0, 2]},   # "HH" from "HH:MM:SS"
                    "count": {"$sum": 1},
                }},
                {"$sort": {"count": -1}},
            ]
            return list(self._db[_COL_ANALYTICS].aggregate(pipeline))
        except Exception as exc:
            logger.error(f"get_peak_hours_data Mongo error: {exc}")
            return []

    def get_busiest_doctors(self, date_str: str, top_n: int = 5) -> list[dict]:
        """Rank doctors by completed appointment count (GO8 NF5)."""
        self._reconnect_if_needed()
        if not self.is_connected:
            return []
        try:
            pipeline = [
                {"$match": {"date": date_str, "status": "completed"}},
                {"$group": {"_id": "$doctor_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": top_n},
            ]
            return list(self._db[_COL_ANALYTICS].aggregate(pipeline))
        except Exception as exc:
            logger.error(f"get_busiest_doctors Mongo error: {exc}")
            return []

    # =========================================================================
    # PRESCRIPTIONS
    # =========================================================================

    def save_prescription(self, prescription: dict) -> dict:
        self._reconnect_if_needed()
        doc = dict(prescription)
        if not self.is_connected:
            self._prescriptions_memory = [
                item for item in self._prescriptions_memory
                if item.get("prescription_id") != doc["prescription_id"]
            ]
            self._prescriptions_memory.append(doc)
            return dict(doc)
        try:
            self._db[_COL_PRESCRIPTIONS].replace_one(
                {"prescription_id": doc["prescription_id"]},
                doc,
                upsert=True,
            )
            return dict(doc)
        except Exception as exc:
            logger.error(f"save_prescription Mongo error: {exc}. Falling back to memory.")
            self._prescriptions_memory.append(doc)
            return dict(doc)

    def get_prescriptions_for_patient(self, patient_id: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return [dict(item) for item in self._prescriptions_memory if item.get("patient_id") == patient_id]
        try:
            return list(
                self._db[_COL_PRESCRIPTIONS]
                .find({"patient_id": patient_id}, {"_id": 0})
                .sort("created_at", DESCENDING)
            )
        except Exception as exc:
            logger.error(f"get_prescriptions_for_patient Mongo error: {exc}")
            return [dict(item) for item in self._prescriptions_memory if item.get("patient_id") == patient_id]

    def get_prescriptions_for_doctor(self, doctor_id: str) -> list[dict]:
        self._reconnect_if_needed()
        if not self.is_connected:
            return [dict(item) for item in self._prescriptions_memory if item.get("doctor_id") == doctor_id]
        try:
            return list(
                self._db[_COL_PRESCRIPTIONS]
                .find({"doctor_id": doctor_id}, {"_id": 0})
                .sort("created_at", DESCENDING)
            )
        except Exception as exc:
            logger.error(f"get_prescriptions_for_doctor Mongo error: {exc}")
            return [dict(item) for item in self._prescriptions_memory if item.get("doctor_id") == doctor_id]

    # =========================================================================
    # Misc
    # =========================================================================

    def close(self) -> None:
        """Close the MongoDB connection cleanly (called on app shutdown)."""
        if self._client:
            self._client.close()
            self._client = None
            self._db     = None

    def __repr__(self) -> str:
        mode = f"MongoDB(db={self._db_name})" if self.is_connected else "InMemory(fallback)"
        return f"MongoManager(mode={mode})"
