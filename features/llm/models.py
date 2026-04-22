from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class SuggestedDoctor(BaseModel):
    doctor_id: str
    uhid: Optional[str] = None
    full_name: str
    specialization: str


class KnowledgeSource(BaseModel):
    title: str
    source_path: str
    chunk_index: int
    score: float


class SymptomExplainerRequest(BaseModel):
    symptoms: str = Field(..., min_length=5, max_length=1000)
    patient_age: Optional[int] = Field(default=None, ge=0, le=120)
    patient_gender: Optional[str] = Field(default=None, max_length=20)

    model_config = {"extra": "forbid"}


class SymptomExplainerResponse(BaseModel):
    symptoms: str
    suggested_specializations: list[str]
    doctor_recommendation: str
    explanation: str
    suggested_doctors: list[SuggestedDoctor]
    self_care_guidance: str
    safety_note: str


class ReportSummaryRequest(BaseModel):
    report_date: date
    doctor_id: Optional[str] = None

    model_config = {"extra": "forbid"}


class ReportSummaryResponse(BaseModel):
    summary: str
    report: dict


class PatientChatRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=2000)

    model_config = {"extra": "forbid"}


class PatientChatResponse(BaseModel):
    reply: str
    sources: list[KnowledgeSource]


class RAGReindexResponse(BaseModel):
    documents_indexed: int
    chunks_indexed: int


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AgentChatResponse(BaseModel):
    reply: str
    updated_history: list[dict[str, Any]]
    tools_used: list[str]
    sources: list[KnowledgeSource]


class HealthSummaryRequest(BaseModel):
    triage_records: list[dict[str, Any]] = Field(default_factory=list)
    prescriptions: list[dict[str, Any]] = Field(default_factory=list)
    patient_name: Optional[str] = None

    model_config = {"extra": "forbid"}


class HealthSummaryResponse(BaseModel):
    summary: str
