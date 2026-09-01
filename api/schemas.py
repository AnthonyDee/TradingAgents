"""Pydantic schemas for TradingAgents Web API."""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    key: str
    label: str
    default_url: Optional[str] = None
    requires_region: bool = False
    region_options: Optional[List[Dict[str, str]]] = None


class ModelOption(BaseModel):
    label: str
    value: str


class AnalystOption(BaseModel):
    key: str
    label: str
    asset_types: List[str] = ["stock", "crypto"]


class ResearcherOption(BaseModel):
    key: str
    label: str


class RiskOption(BaseModel):
    key: str
    label: str


class DepthOption(BaseModel):
    label: str
    value: int
    description: str


class LanguageOption(BaseModel):
    label: str
    value: str


class ProviderReasoningConfig(BaseModel):
    provider: str
    options: List[Dict[str, str]]


class ConfigSchema(BaseModel):
    providers: List[ProviderInfo]
    analysts: List[AnalystOption]
    researchers: List[ResearcherOption]
    risk: List[RiskOption]
    depths: List[DepthOption]
    languages: List[LanguageOption]
    reasoning_configs: List[ProviderReasoningConfig]


# Allowed researcher / risk-debator values (mirrors cli.models enums).
VALID_RESEARCHERS = ["bull", "bear"]
VALID_RISK = ["aggressive", "conservative", "neutral"]


class RunConfig(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    analysis_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    output_language: str = "English"
    analysts: List[str] = Field(..., min_length=1)
    researchers: List[str] = Field(default_factory=lambda: list(VALID_RESEARCHERS))
    risk: List[str] = Field(default_factory=lambda: list(VALID_RISK))
    research_depth: int = Field(..., ge=1, le=10)
    llm_provider: str
    backend_url: Optional[str] = None
    shallow_thinker: str
    deep_thinker: str
    google_thinking_level: Optional[str] = None
    openai_reasoning_effort: Optional[str] = None
    anthropic_effort: Optional[str] = None


class RunCreateResponse(BaseModel):
    run_id: str


class RunStatusResponse(BaseModel):
    id: str
    ticker: str
    analysis_date: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class RunDetailResponse(RunStatusResponse):
    config: Dict[str, Any]
    report: Optional[Dict[str, Any]] = None


class HistoryResponse(BaseModel):
    runs: List[RunStatusResponse]
    total: int
    limit: int
    offset: int


class ModelListResponse(BaseModel):
    models: List[ModelOption]
    source: Literal["live", "static", "error"] = "live"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"