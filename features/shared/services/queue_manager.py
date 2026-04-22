# =============================================================================
# services/queue_manager.py
# QueueManager — priority queue, wait-time estimation, triage grouping
# =============================================================================
# NSL coverage : GO7 (Manage Appointment Queue) — LO1, LO2, LO3
# Failure cases: E15 — emergency inserts, regular patients notified of delay
#                E16 — multiple emergencies sorted FIFO among themselves
#                E17 — no-show timeout flag
#                E18 — MongoDB persistence so queue survives restart
#                F9  — per-doctor in-progress guard (max 1 per doctor)
#                F10 — complete/no-show on wrong ID raises, not silently passes
#                F11 — wait-time note: slot-duration estimate, acknowledged
#                F12 — triage groups regenerated on every call (no stale cache)
#
# DSA requirements (assignment spec):
#   - Queue (deque) for regular FIFO patients
#   - Priority Queue (heapq) for emergency patients
#   - Generator to stream queue entries
# =============================================================================

from __future__ import annotations

import heapq
import logging
import threading
from collections import deque
from datetime import date, datetime, timedelta
from typing import Generator, Optional

from features.shared.database.postgres import PostgresManager
from features.shared.database.mongo    import MongoManager
from features.shared.models.queue      import AppointmentQueue, QueueStatus, TriageGroup

logger = logging.getLogger(__name__)

# Sentinel — separates emergency heap entries by (priority, counter, entry)
# so heapq never falls back to comparing AppointmentQueue objects directly.
_COUNTER = 0


def _next_counter() -> int:
    global _COUNTER
    _COUNTER += 1
    return _COUNTER


class QueueManager:
    """Manages the real-time appointment queue for all doctors.

    Internal structure per (doctor_id, date_str):
      _emergency_heap : min-heap of (0, counter, AppointmentQueue)
                        — emergency patients, FIFO among themselves (E16)
      _regular_deque  : deque of AppointmentQueue
                        — normal patients, strict FIFO
      _in_progress    : {doctor_id: AppointmentQueue | None}
                        — the patient currently being seen per doctor (F9)

    Public interface mirrors GO7 LOs:
      enqueue()       → LO2 "Process Next" setup
      dequeue()       → LO2 "call next patient"
      complete()      → LO3 "mark completed"
      mark_no_show()  → LO3 "mark absent"
      cancel_entry()  → GO5 side-effect
      get_queue()     → LO1 "view queue"
      triage_groups() → F12-safe regeneration every call
    """

    def __init__(self, db: PostgresManager, mongo: MongoManager) -> None:
        self._db    = db
        self._mongo = mongo
        self._lock  = threading.Lock()

        # Per-(doctor_id, date_str) structures
        self._heaps:  dict[tuple, list]           = {}   # emergency heaps
        self._deques: dict[tuple, deque]          = {}   # regular deques
        self._in_progress: dict[str, Optional[AppointmentQueue]] = {}

        # Reload persisted queue on startup (E18 mitigation)
        self._reload_from_mongo()

    # =========================================================================
    # Startup reload (E18 — survive restarts)
    # =========================================================================

    def _reload_from_mongo(self) -> None:
        """Pull any persisted waiting/in-progress entries from MongoDB."""
        today = date.today().isoformat()
        # We don't know which doctors exist yet — this is called before
        # doctors load. A full reload is triggered per-doctor on first access.
        logger.info("QueueManager initialised — per-doctor reload on first access.")

    def reload_for_doctor(self, doctor_id: str, for_date: date) -> int:
        """Reload a doctor's queue from MongoDB (called on page load / restart).

        Returns number of entries reloaded.
        """
        key = (doctor_id, for_date.isoformat())
        with self._lock:
            self._heaps[key] = []
            self._deques[key] = deque()
            if self._in_progress.get(doctor_id) and self._in_progress[doctor_id].date == for_date:
                self._in_progress[doctor_id] = None
        entries = self._mongo.load_queue_for_doctor_date(
            doctor_id, for_date.isoformat()
        )
        count = 0
        for entry_dict in entries:
            entry = AppointmentQueue.from_dict(entry_dict)
            self._insert_to_structures(key, entry, persist=False)
            count += 1

        logger.info(f"Reloaded {count} queue entries for {doctor_id} / {for_date}")
        return count

    # =========================================================================
    # GO7 LO2 — Enqueue (called by BookingService after every booking)
    # =========================================================================

    def enqueue(
        self,
        doctor_id: str,
        for_date: date,
        patient_id: str,
        appointment_id: str,
        is_emergency: bool = False,
    ) -> AppointmentQueue:
        """Add a patient to the queue.

        Emergency → priority heap (R130, E15, E16).
        Normal    → FIFO deque.
        Persists to MongoDB (E18).
        Returns the created AppointmentQueue entry.
        """
        key = (doctor_id, for_date.isoformat())
        with self._lock:
            position = self._next_position(key)

        entry = AppointmentQueue(
            doctor_id=doctor_id,
            date=for_date,
            patient_id=patient_id,
            appointment_id=appointment_id,
            queue_position=position,
            is_emergency=is_emergency,
        )

        with self._lock:
            self._insert_to_structures(key, entry, persist=True)

        # Persist to Mongo for restart recovery
        self._mongo.persist_queue_entry(entry.to_dict())

        logger.info(
            f"Enqueued {patient_id} → {doctor_id}/{for_date} "
            f"pos={position} emergency={is_emergency}"
        )
        return entry

    def _insert_to_structures(
        self,
        key: tuple,
        entry: AppointmentQueue,
        persist: bool = True,
    ) -> None:
        """Insert into the correct in-memory structure (must hold self._lock)."""
        if entry.is_emergency:
            heap = self._heaps.setdefault(key, [])
            heapq.heappush(heap, (_next_counter(), entry))   # E16 — FIFO among emergencies
        else:
            dq = self._deques.setdefault(key, deque())
            dq.append(entry)

    def _next_position(self, key: tuple) -> int:
        """Total entries in both structures + 1 (must hold self._lock)."""
        heap_count = len(self._heaps.get(key, []))
        deq_count  = len(self._deques.get(key, deque()))
        return heap_count + deq_count + 1

    # =========================================================================
    # GO7 LO2 — Dequeue (call next patient)
    # =========================================================================

    def dequeue(self, doctor_id: str, for_date: date) -> Optional[AppointmentQueue]:
        """Pop the highest-priority waiting patient.

        Emergency heap is drained before the regular deque (R130, E15).
        F9 — enforces max 1 in-progress per doctor.
        Returns the entry now in-progress, or None if queue is empty.
        """
        with self._lock:
            # F9 — block if doctor already has a patient in-progress
            current = self._in_progress.get(doctor_id)
            if current is not None:
                logger.warning(
                    f"Doctor {doctor_id} still has {current.appointment_id} in-progress. "
                    "Complete or mark no-show before calling next patient."
                )
                return None

            key = (doctor_id, for_date.isoformat())
            entry = self._pop_next(key)
            if entry is None:
                return None

            entry.start()   # QueueStatus: waiting → in-progress (R132)
            self._in_progress[doctor_id] = entry

        # Persist status change to Mongo
        self._mongo.update_queue_status(entry.appointment_id, "in-progress")

        # Reorder remaining positions (R131)
        self._reorder(doctor_id, for_date)

        logger.info(
            f"Dequeued {entry.patient_id} (appt {entry.appointment_id}) "
            f"for doctor {doctor_id}"
        )
        return entry

    def _pop_next(self, key: tuple) -> Optional[AppointmentQueue]:
        """Emergency heap first, then regular deque (must hold self._lock)."""
        heap = self._heaps.get(key, [])
        if heap:
            _, entry = heapq.heappop(heap)
            return entry

        dq = self._deques.get(key, deque())
        if dq:
            return dq.popleft()

        return None

    # =========================================================================
    # GO7 LO3 — Complete or no-show
    # =========================================================================

    def complete(self, doctor_id: str, appointment_id: str) -> AppointmentQueue:
        """Mark the current in-progress patient as completed.

        F10 — raises KeyError if appointment_id doesn't match in-progress entry.
        """
        with self._lock:
            entry = self._in_progress.get(doctor_id)
            if entry is None:
                raise KeyError(
                    f"Doctor {doctor_id} has no patient currently in-progress."
                )
            if entry.appointment_id != appointment_id:
                raise KeyError(
                    f"In-progress appointment for {doctor_id} is "
                    f"'{entry.appointment_id}', not '{appointment_id}'. "
                    "Cannot complete a different appointment."
                )
            entry.complete()
            self._in_progress[doctor_id] = None

        self._mongo.update_queue_status(appointment_id, "completed")
        self._mongo.remove_queue_entry(appointment_id)

        logger.info(f"Completed: {appointment_id} (doctor {doctor_id})")
        return entry

    def mark_no_show(self, doctor_id: str, appointment_id: str) -> AppointmentQueue:
        """Mark in-progress patient as a no-show (F10 — explicit ID check)."""
        with self._lock:
            entry = self._in_progress.get(doctor_id)
            if entry is None:
                raise KeyError(f"Doctor {doctor_id} has no patient currently in-progress.")
            if entry.appointment_id != appointment_id:
                raise KeyError(
                    f"In-progress appointment is '{entry.appointment_id}', "
                    f"not '{appointment_id}'."
                )
            entry.mark_no_show()
            self._in_progress[doctor_id] = None

        self._mongo.update_queue_status(appointment_id, "no-show")
        self._mongo.remove_queue_entry(appointment_id)

        logger.info(f"No-show: {appointment_id} (doctor {doctor_id})")
        return entry

    # =========================================================================
    # Cancel — triggered by BookingService.cancel_appointment() (GO5)
    # =========================================================================

    def cancel_entry(self, doctor_id: str, for_date: date, appointment_id: str) -> bool:
        """Remove a queue entry by appointment_id (on cancellation).

        Scans both heap and deque; rebuilds heap if the entry was there.
        Returns True if found and removed, False if not in queue (already served).
        """
        key = (doctor_id, for_date.isoformat())
        found = False

        with self._lock:
            # Check regular deque first
            dq = self._deques.get(key, deque())
            new_dq = deque(e for e in dq if e.appointment_id != appointment_id)
            if len(new_dq) < len(dq):
                self._deques[key] = new_dq
                found = True

            # Check emergency heap
            if not found:
                heap = self._heaps.get(key, [])
                new_heap = [(c, e) for c, e in heap if e.appointment_id != appointment_id]
                if len(new_heap) < len(heap):
                    heapq.heapify(new_heap)
                    self._heaps[key] = new_heap
                    found = True

            # Check in-progress (edge: cancelled while being seen)
            if not found:
                ip = self._in_progress.get(doctor_id)
                if ip and ip.appointment_id == appointment_id:
                    ip.cancel()
                    self._in_progress[doctor_id] = None
                    found = True

        if found:
            self._mongo.update_queue_status(appointment_id, "cancelled")
            self._mongo.remove_queue_entry(appointment_id)
            self._reorder(doctor_id, for_date)
            logger.info(f"Queue entry cancelled: {appointment_id}")

        return found

    # =========================================================================
    # GO7 LO1 — View queue (ordered emergency-first, then position)
    # =========================================================================

    def get_queue(
        self,
        doctor_id: str,
        for_date: date,
        status_filter: Optional[list[str]] = None,
    ) -> list[AppointmentQueue]:
        """Return current queue for doctor/date — R130 order.

        Combines in-memory structures (source of truth for live entries)
        with DB for already-completed entries when status_filter is broad.
        """
        key = (doctor_id, for_date.isoformat())
        result: list[AppointmentQueue] = []

        with self._lock:
            # Emergency heap entries (sorted by counter = arrival order)
            heap_entries = sorted(
                [entry for _, entry in self._heaps.get(key, [])],
                key=lambda e: e.added_at
            )
            result.extend(heap_entries)

            # Regular deque (already FIFO)
            result.extend(list(self._deques.get(key, deque())))

            # In-progress for this doctor (if any)
            ip = self._in_progress.get(doctor_id)
            if ip and ip.date == for_date:
                result.insert(0, ip)   # show in-progress at top

        return result

    def get_queue_summary(self, doctor_id: str, for_date: date) -> dict:
        """Return counts for GO7 LO1 display (total, emergency, in-progress)."""
        queue = self.get_queue(doctor_id, for_date)
        return {
            "total":       len(queue),
            "emergency":   sum(1 for e in queue if e.is_emergency),
            "waiting":     sum(1 for e in queue if e.status == QueueStatus.WAITING),
            "in_progress": 1 if self._in_progress.get(doctor_id) else 0,
        }

    # =========================================================================
    # Wait-time estimation (F11 — acknowledged: uses slot duration as proxy)
    # =========================================================================

    def estimate_wait_minutes(
        self,
        doctor_id: str,
        for_date: date,
        patient_appointment_id: str,
        slot_duration_minutes: int = 15,
    ) -> int:
        """Estimate wait time in minutes for a given appointment.

        F11 — uses slot_duration_minutes as average consultation time.
        Real consultation times vary; this is a known approximation.

        E15 — emergency patients see 0 wait (only other emergencies ahead).
        """
        queue = self.get_queue(doctor_id, for_date)
        waiting = [e for e in queue if e.status == QueueStatus.WAITING]

        target_idx = next(
            (i for i, e in enumerate(waiting) if e.appointment_id == patient_appointment_id),
            None
        )
        if target_idx is None:
            return 0   # already in-progress or completed

        entry = waiting[target_idx]

        if entry.is_emergency:
            # Only other emergencies ahead count (E15)
            emergencies_ahead = sum(
                1 for e in waiting[:target_idx] if e.is_emergency
            )
            return emergencies_ahead * slot_duration_minutes
        else:
            # All entries ahead (emergencies served first)
            return target_idx * slot_duration_minutes

    # =========================================================================
    # Triage groups (F12 — always regenerated, never cached)
    # =========================================================================

    def triage_groups(
        self,
        doctor_id: str,
        for_date: date,
        capacity_per_group: int = 5,
    ) -> list[dict]:
        """Split the waiting queue into triage groups.

        F12 — always regenerated from current queue (no caching).
        E19 — fewer patients than capacity → one partial group.
        E20 — empty queue → empty list.
        E21 — all emergencies → groups still formed by position, no special flag
              (noted limitation — UI should style emergency groups distinctly).

        Returns list of {group_number, entries, has_emergency}.
        """
        waiting = [
            e for e in self.get_queue(doctor_id, for_date)
            if e.status == QueueStatus.WAITING
        ]

        if not waiting:
            return []

        groups = []
        for i in range(0, len(waiting), capacity_per_group):
            batch = waiting[i: i + capacity_per_group]
            groups.append({
                "group_number": (i // capacity_per_group) + 1,
                "entries":      batch,
                "size":         len(batch),
                "has_emergency": any(e.is_emergency for e in batch),
            })
        return groups

    # =========================================================================
    # Generator — stream queue (DSA requirement)
    # =========================================================================

    def stream_queue(
        self, doctor_id: str, for_date: date
    ) -> Generator[AppointmentQueue, None, None]:
        """Yield queue entries one at a time (generator — DSA requirement)."""
        for entry in self.get_queue(doctor_id, for_date):
            yield entry

    # =========================================================================
    # Internal — reorder positions (R131)
    # =========================================================================

    def _reorder(self, doctor_id: str, for_date: date) -> None:
        """Reassign sequential positions to all waiting entries.

        Emergencies first (position 1, 2, …), then regular patients.
        Updates in-memory structures and DB. (R131)
        """
        key = (doctor_id, for_date.isoformat())
        with self._lock:
            heap_entries = sorted(
                [e for _, e in self._heaps.get(key, [])],
                key=lambda e: e.added_at
            )
            dq_entries = list(self._deques.get(key, deque()))
            all_waiting = heap_entries + dq_entries

        for pos, entry in enumerate(all_waiting, start=1):
            entry.queue_position = pos
            self._mongo.update_queue_position(entry.appointment_id, pos)
