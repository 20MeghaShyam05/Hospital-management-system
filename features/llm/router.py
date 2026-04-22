from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from features.core.rate_limiter import limiter
from features.core.dependencies import get_current_user, require_roles
from features.llm.models import (
    AgentChatRequest,
    AgentChatResponse,
    HealthSummaryRequest,
    HealthSummaryResponse,
    PatientChatRequest,
    PatientChatResponse,
    RAGReindexResponse,
    ReportSummaryRequest,
    ReportSummaryResponse,
    SymptomExplainerRequest,
    SymptomExplainerResponse,
)
from features.llm.service import AgentService, LLMService, get_agent_service, get_llm_service
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("/symptom-explainer", response_model=SymptomExplainerResponse, summary="Explain symptoms and map to specializations")
@limiter.limit("10/minute")
async def symptom_explainer(
    request: Request,
    data: SymptomExplainerRequest,
    svc: LLMService = Depends(get_llm_service),
    current_user: dict = Depends(get_current_user),
):
    return svc.problem_guidance(data.symptoms, data.patient_age, data.patient_gender)


@router.post("/report-summary", response_model=ReportSummaryResponse, summary="Generate a natural-language hospital report summary (admin only)")
@limiter.limit("10/minute")
async def report_summary(
    request: Request,
    data: ReportSummaryRequest,
    svc: LLMService = Depends(get_llm_service),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    return svc.summarize_report(data.report_date, doctor_id=data.doctor_id)


@router.post("/health-summary", response_model=HealthSummaryResponse, summary="Personal health summary from vitals and prescriptions")
@limiter.limit("10/minute")
async def health_summary(
    request: Request,
    data: HealthSummaryRequest,
    svc: LLMService = Depends(get_llm_service),
    current_user: dict = Depends(get_current_user),
):
    return svc.summarize_health(
        triage_records=data.triage_records,
        prescriptions=data.prescriptions,
        patient_name=data.patient_name,
    )


@router.post("/patient-chat", response_model=PatientChatResponse, summary="Patient-facing chat assistant")
@limiter.limit("10/minute")
async def patient_chat(
    request: Request,
    data: PatientChatRequest,
    svc: LLMService = Depends(get_llm_service),
    current_user: dict = Depends(get_current_user),
):
    return svc.patient_chat(current_user, data.message)


@router.post("/reindex-knowledge", response_model=RAGReindexResponse, summary="Reindex role knowledge documents into pgvector")
@limiter.limit("2/minute")
async def reindex_knowledge(
    request: Request,
    svc: LLMService = Depends(get_llm_service),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    return svc.reindex_knowledge_documents()


@router.post("/agent-chat", response_model=AgentChatResponse, summary="Agentic assistant — books appointments, queries reports, answers policy questions")
@limiter.limit("10/minute")
async def agent_chat(
    request: Request,
    data: AgentChatRequest,
    svc: AgentService = Depends(get_agent_service),
    current_user: dict = Depends(get_current_user),
):
    try:
        return svc.agent_chat(current_user, data.message, data.conversation_history)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")
