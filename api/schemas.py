"""Pydantic schemas for TradingAgents Web API."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    key: str
    label: str
    default_url: str | None = None
    requires_region: bool = False
    region_options: list[dict[str, str]] | None = None


class ModelOption(BaseModel):
    label: str
    value: str


class AnalystOption(BaseModel):
    key: str
    label: str
    asset_types: list[str] = ["stock", "crypto"]


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
    options: list[dict[str, str]]


class ConfigSchema(BaseModel):
    providers: list[ProviderInfo]
    analysts: list[AnalystOption]
    researchers: list[ResearcherOption]
    risk: list[RiskOption]
    depths: list[DepthOption]
    languages: list[LanguageOption]
    reasoning_configs: list[ProviderReasoningConfig]
    # New configuration options
    temperatures: list[dict[str, Any]]
    max_retries_options: list[dict[str, Any]]
    data_vendors: list[dict[str, Any]]
    benchmark_options: dict[str, Any]
    mcp_info: dict[str, Any]


# Allowed researcher / risk-debator values (mirrors cli.models enums).
VALID_RESEARCHERS = ["bull", "bear"]
VALID_RISK = ["aggressive", "conservative", "neutral"]


class RunConfig(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    analysis_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    output_language: str = "English"
    analysts: list[str] = Field(..., min_length=1)
    researchers: list[str] = Field(default_factory=lambda: list(VALID_RESEARCHERS))
    risk: list[str] = Field(default_factory=lambda: list(VALID_RISK))
    research_depth: int = Field(..., ge=1, le=10)
    llm_provider: str
    backend_url: str | None = None
    shallow_thinker: str
    deep_thinker: str
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    # LLM settings
    temperature: float | None = None
    llm_max_retries: int | None = None
    # Data vendor configuration
    data_vendors: dict[str, str] | None = None
    tool_vendors: dict[str, str] | None = None
    # Benchmark configuration
    benchmark_ticker: str | None = None
    benchmark_map: dict[str, str] | None = None
    # MCP server configuration (read-only, server-side)
    mcp_servers: dict[str, Any] | None = None
    mcp_realtime_tool_filter: dict[str, list[str]] | None = None


class RunCreateResponse(BaseModel):
    run_id: str


class RunStatusResponse(BaseModel):
    id: str
    ticker: str
    analysis_date: str
    status: Literal["pending", "running", "completed", "failed"]
    created_at: str
    completed_at: str | None = None
    error_message: str | None = None


class RunDetailResponse(RunStatusResponse):
    config: dict[str, Any]
    report: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    runs: list[RunStatusResponse]
    total: int
    limit: int
    offset: int


class ModelListResponse(BaseModel):
    models: list[ModelOption]
    source: Literal["live", "static", "error"] = "live"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
