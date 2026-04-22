from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import settings
from features.core.rate_limiter import limiter
from features.shared.database.mongo import MongoManager
from features.shared.database.postgres import PostgresManager
from features.appointments.router import router as appointments_router
from features.auth.router import router as auth_router
from features.core.dependencies import app_state
from features.doctors.router import router as doctors_router
from features.llm.router import router as llm_router
from features.nurses.router import router as nurses_router
from features.patients.router import router as patients_router
from features.prescriptions.router import router as prescriptions_router
from features.queue.router import router as queue_router
from features.reports.router import router as reports_router
from features.scheduling.router import router as scheduling_router
from features.triage.router import router as triage_router
from features.gsuite.router import router as gsuite_router
from features.shared.services.auth_service import AuthService
from features.shared.services.booking_service import BookingService
from features.shared.services.queue_manager import QueueManager
from features.shared.services.schedule_manager import ScheduleManager
from features.shared.utils.rbac import RBACError
import os

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(name)-28s | %(levelname)-5s | %(message)s",
    )

    app_state.db = PostgresManager()
    app_state.mongo = MongoManager()
    app_state.schedule = ScheduleManager(db=app_state.db)
    app_state.queue_mgr = QueueManager(db=app_state.db, mongo=app_state.mongo)
    app_state.booking = BookingService(
        db=app_state.db,
        mongo=app_state.mongo,
        schedule=app_state.schedule,
        queue=app_state.queue_mgr,
    )
    app_state.auth = AuthService(db=app_state.db)

    # Auto-regenerate weekly slots in the background — never block startup
    import threading as _threading
    def _regen_slots():
        try:
            doctors = app_state.db.list_doctors(active_only=True)
            for doctor in doctors:
                app_state.schedule.auto_regenerate_weekly_slots(doctor)
            logger.info(f"Slot regen complete for {len(doctors)} doctors.")
        except Exception as e:
            logger.warning(f"Startup slot regeneration failed: {e}")
    _threading.Thread(target=_regen_slots, daemon=True, name="slot-regen").start()

    # Start Google Forms background sync (non-blocking)
    try:
        from features.gsuite.forms_sync import start_background_sync
        if settings.GOOGLE_FORMS_SPREADSHEET_ID:
            start_background_sync(app_state.booking)
            logger.info("Google Forms background sync started.")
        else:
            logger.info("Google Forms sync disabled — GOOGLE_FORMS_SPREADSHEET_ID not set.")
    except Exception as e:
        logger.warning(f"Google Forms sync start failed (non-critical): {e}")

    logger.info(
        "DPAS API started | Postgres=%s | Mongo=%s",
        app_state.db.is_connected,
        app_state.mongo.is_connected if hasattr(app_state.mongo, "is_connected") else "unknown",
    )
    yield
    logger.info("DPAS API shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Doctor-Patient Appointment Management System",
        description=(
            "REST API for the DPAS — organized as a feature-sliced modular monolith "
            "with patient, doctor, nurse, scheduling, appointment, queue, triage, auth, and report modules."
        ),
        version="2.0.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(RBACError)
    async def rbac_error_handler(request: Request, exc: RBACError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/health", tags=["System"])
    async def health_check():
        return {
            "status": "ok",
            "postgres": app_state.db.is_connected if hasattr(app_state.db, "is_connected") else True,
            "mongo": app_state.mongo.is_connected if hasattr(app_state.mongo, "is_connected") else True,
            "llm_configured": bool(os.environ.get("GROQ_API_KEY")),
            "rag_configured": bool(
                settings.RAG_POSTGRES_HOST
                and settings.RAG_POSTGRES_DB
                and settings.RAG_POSTGRES_USER
                and settings.RAG_POSTGRES_PASSWORD
            ),
            "gsuite_connected": bool(settings.GOOGLE_FORMS_SPREADSHEET_ID or settings.GOOGLE_DRIVE_FOLDER_ID),
        }

    app.include_router(patients_router, prefix="/patients", tags=["GO1 — Patients"])
    app.include_router(auth_router, prefix="/auth", tags=["Auth"])
    app.include_router(doctors_router, prefix="/doctors", tags=["GO2 — Doctors"])
    app.include_router(nurses_router, prefix="/nurses", tags=["Nurses"])
    app.include_router(scheduling_router, prefix="", tags=["GO3 — Slots"])
    app.include_router(appointments_router, prefix="/appointments", tags=["GO4/5/6 — Appointments"])
    app.include_router(queue_router, prefix="/queue", tags=["GO7 — Queue"])
    app.include_router(triage_router, prefix="/triage", tags=["Triage"])
    app.include_router(prescriptions_router, prefix="/prescriptions", tags=["Prescriptions"])
    app.include_router(reports_router, prefix="/reports", tags=["GO8 — Reports"])
    app.include_router(llm_router, prefix="/llm", tags=["LLM Assistant"])
    app.include_router(gsuite_router, prefix="/gsuite", tags=["G-Suite"])

    return app


app = create_app()
