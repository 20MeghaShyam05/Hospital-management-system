from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from features.core.dependencies import ensure_doctor_scope, require_roles
from features.core.dependencies import app_state
from features.reports.models import ReportResponse
from features.reports.service import ReportModuleService, get_report_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.get("/audit/logs", summary="View audit logs")
async def get_audit_logs(
    event: str | None = Query(None, description="Optional event filter"),
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    return app_state.mongo.get_audit_logs(event_filter=event, limit=limit)


@router.get("/analytics/visualize", summary="Data science report — NumPy stats + Matplotlib/Seaborn charts")
async def get_visualization_report(
    days: int = Query(30, ge=1, le=365, description="Number of past days to analyse"),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    """Generate full DS report: busiest doctor, peak hours, and base64 chart images."""
    from features.reports.visualizer import generate_visualization_report
    end = date.today()
    start = end - timedelta(days=days)
    records = app_state.booking.get_analytics_data(start, end)
    return generate_visualization_report(records)


@router.get("/{report_date}", response_model=ReportResponse, summary="Generate daily report (GO8 LO1 + LO2)")
async def get_report(
    report_date: date,
    doctor_id: str = Query(None, description="Optional — filter by doctor ID"),
    svc: ReportModuleService = Depends(get_report_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    if current_user.get("role") == Role.DOCTOR.value:
        doctor_id = current_user.get("linked_doctor_id")
    elif doctor_id:
        doctor = svc.get_doctor(doctor_id)
        if doctor:
            ensure_doctor_scope(current_user, doctor)
    return svc.get_report_data(report_date, doctor_id=doctor_id)
