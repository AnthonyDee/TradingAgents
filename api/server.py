"""FastAPI server for TradingAgents Web UI."""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from api.database import count_runs, get_run, init_db, list_runs
from api.schemas import (
    VALID_RESEARCHERS,
    VALID_RISK,
    AnalystOption,
    ConfigSchema,
    DepthOption,
    HealthResponse,
    HistoryResponse,
    LanguageOption,
    ModelListResponse,
    ModelOption,
    ProviderInfo,
    ProviderReasoningConfig,
    ResearcherOption,
    RiskOption,
    RunCreateResponse,
    RunDetailResponse,
    RunStatusResponse,
)
from api.service import RunConfig, analysis_queue, enqueue_analysis
from api.websocket import manager
from cli.utils import _llm_provider_table
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.reporting import _collect_sections, build_epub


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


# --- FastAPI App ---
app = FastAPI(
    title="TradingAgents Web API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
cors_origins = os.getenv("TRADINGAGENTS_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Helper functions ---

def get_providers_schema() -> list[ProviderInfo]:
    """Get provider schema for wizard."""
    providers = []
    for label, key, url in _llm_provider_table():
        requires_region = key in ("qwen", "glm", "minimax")
        region_options = None
        if key == "qwen":
            region_options = [
                {"label": "International (dashscope-intl)", "value": "qwen"},
                {"label": "China (dashscope.cn)", "value": "qwen-cn"},
            ]
        elif key == "glm":
            region_options = [
                {"label": "Z.AI International (api.z.ai)", "value": "glm"},
                {"label": "BigModel China (open.bigmodel.cn)", "value": "glm-cn"},
            ]
        elif key == "minimax":
            region_options = [
                {"label": "Global (api.minimax.io)", "value": "minimax"},
                {"label": "China (api.minimaxi.com)", "value": "minimax-cn"},
            ]
        providers.append(ProviderInfo(
            key=key,
            label=label,
            default_url=url,
            requires_region=requires_region,
            region_options=region_options,
        ))
    return providers


def get_analysts_schema() -> list[AnalystOption]:
    """Get analyst options schema."""
    return [
        AnalystOption(key="market", label="Market Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="social", label="Sentiment Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="news", label="News Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="fundamentals", label="Fundamentals Analyst", asset_types=["stock"]),
    ]


def get_researchers_schema() -> list[ResearcherOption]:
    """Get researcher options schema."""
    return [
        ResearcherOption(key="bull", label="Bull Researcher"),
        ResearcherOption(key="bear", label="Bear Researcher"),
    ]


def get_risk_schema() -> list[RiskOption]:
    """Get risk debator options schema."""
    return [
        RiskOption(key="aggressive", label="Aggressive Analyst"),
        RiskOption(key="conservative", label="Conservative Analyst"),
        RiskOption(key="neutral", label="Neutral Analyst"),
    ]


def get_depths_schema() -> list[DepthOption]:
    """Get research depth options."""
    return [
        DepthOption(label="Shallow - Quick research", value=1, description="1 debate round, 1 risk round"),
        DepthOption(label="Medium - Balanced research", value=3, description="3 debate rounds, 3 risk rounds"),
        DepthOption(label="Deep - Comprehensive research", value=5, description="5 debate rounds, 5 risk rounds"),
    ]


def get_languages_schema() -> list[LanguageOption]:
    """Get output language options."""
    return [
        LanguageOption(label="English", value="English"),
        LanguageOption(label="Chinese (中文)", value="Chinese"),
        LanguageOption(label="Japanese (日本語)", value="Japanese"),
        LanguageOption(label="Korean (한국어)", value="Korean"),
        LanguageOption(label="Hindi (हिन्दी)", value="Hindi"),
        LanguageOption(label="Spanish (Español)", value="Spanish"),
        LanguageOption(label="Portuguese (Português)", value="Portuguese"),
        LanguageOption(label="French (Français)", value="French"),
        LanguageOption(label="German (Deutsch)", value="German"),
        LanguageOption(label="Arabic (العربية)", value="Arabic"),
        LanguageOption(label="Russian (Русский)", value="Russian"),
        LanguageOption(label="Custom", value="custom"),
    ]


def get_reasoning_configs_schema() -> list[ProviderReasoningConfig]:
    """Get provider-specific reasoning configs."""
    return [
        ProviderReasoningConfig(
            provider="google",
            options=[
                {"label": "Enable Thinking (recommended)", "value": "high"},
                {"label": "Minimal/Disable Thinking", "value": "minimal"},
            ]
        ),
        ProviderReasoningConfig(
            provider="openai",
            options=[
                {"label": "High (More thorough)", "value": "high"},
                {"label": "Medium (Default)", "value": "medium"},
                {"label": "Low (Faster)", "value": "low"},
            ]
        ),
        ProviderReasoningConfig(
            provider="anthropic",
            options=[
                {"label": "High (recommended)", "value": "high"},
                {"label": "Medium (balanced)", "value": "medium"},
                {"label": "Low (faster, cheaper)", "value": "low"},
            ]
        ),
    ]


def get_temperature_schema() -> list[dict[str, Any]]:
    """Get temperature configuration options."""
    return [
        {"label": "Default (provider-specific)", "value": None, "description": "Use provider default"},
        {"label": "Deterministic (0.0)", "value": 0.0, "description": "Minimal variation, reproducible"},
        {"label": "Low (0.2)", "value": 0.2, "description": "Focused, slightly varied"},
        {"label": "Medium (0.5)", "value": 0.5, "description": "Balanced creativity"},
        {"label": "High (0.8)", "value": 0.8, "description": "More creative, more variation"},
        {"label": "Very High (1.0)", "value": 1.0, "description": "Maximum variation"},
    ]


def get_max_retries_schema() -> list[dict[str, Any]]:
    """Get LLM max retries configuration options."""
    return [
        {"label": "Default (provider-specific, usually 2)", "value": None, "description": "Use provider/SDK default"},
        {"label": "No Retries (0)", "value": 0, "description": "Fail fast on errors"},
        {"label": "Conservative (3)", "value": 3, "description": "Standard retry budget"},
        {"label": "Aggressive (5)", "value": 5, "description": "Ride out bursty throttling"},
        {"label": "Very Aggressive (10)", "value": 10, "description": "Maximum resilience for rate-limited deployments"},
    ]


def get_data_vendors_schema() -> list[dict[str, Any]]:
    """Get data vendor configuration options."""
    return [
        {
            "category": "core_stock_apis",
            "label": "Core Stock APIs",
            "description": "Primary source for stock price data",
            "options": [
                {"value": "yfinance", "label": "Yahoo Finance (default)", "requires_key": False},
                {"value": "alpha_vantage", "label": "Alpha Vantage", "requires_key": True},
            ],
        },
        {
            "category": "technical_indicators",
            "label": "Technical Indicators",
            "description": "Source for technical indicator calculations",
            "options": [
                {"value": "yfinance", "label": "Yahoo Finance (default)", "requires_key": False},
                {"value": "alpha_vantage", "label": "Alpha Vantage", "requires_key": True},
            ],
        },
        {
            "category": "fundamental_data",
            "label": "Fundamental Data",
            "description": "Source for financial statements and ratios",
            "options": [
                {"value": "yfinance", "label": "Yahoo Finance (default)", "requires_key": False},
                {"value": "alpha_vantage", "label": "Alpha Vantage", "requires_key": True},
            ],
        },
        {
            "category": "news_data",
            "label": "News Data",
            "description": "Source for news articles",
            "options": [
                {"value": "yfinance", "label": "Yahoo Finance (default)", "requires_key": False},
                {"value": "alpha_vantage", "label": "Alpha Vantage", "requires_key": True},
            ],
        },
        {
            "category": "macro_data",
            "label": "Macro Data",
            "description": "Source for macroeconomic indicators",
            "options": [
                {"value": "fred", "label": "FRED (default)", "requires_key": True},
            ],
        },
        {
            "category": "prediction_markets",
            "label": "Prediction Markets",
            "description": "Source for prediction market data",
            "options": [
                {"value": "polymarket", "label": "Polymarket (default)", "requires_key": False},
            ],
        },
    ]


def get_benchmark_schema() -> dict[str, Any]:
    """Get benchmark configuration options."""
    return {
        "benchmark_ticker": {
            "label": "Override Benchmark Ticker",
            "description": "Single ticker to use as benchmark for all alpha calculations (e.g., 'SPY', '^NSEI'). Overrides the suffix map when set.",
            "type": "string",
            "placeholder": "e.g., SPY",
        },
        "benchmark_map": {
            "label": "Benchmark Suffix Map",
            "description": "Maps ticker suffixes to benchmark tickers for automatic alpha calculation. US tickers (no suffix) default to SPY.",
            "type": "object",
            "default": DEFAULT_CONFIG.get("benchmark_map", {}),
        },
    }


def get_mcp_schema() -> dict[str, Any]:
    """Get MCP server configuration info (read-only)."""
    mcp_config = DEFAULT_CONFIG.get("mcp_servers", {})
    return {
        "configured_servers": list(mcp_config.keys()),
        "realtime_tool_filter": DEFAULT_CONFIG.get("mcp_realtime_tool_filter", {}),
        "note": "MCP servers are configured server-side via TRADINGAGENTS_MCP_SERVERS env var or DEFAULT_CONFIG. The web UI shows status only.",
    }


# --- API Routes ---

@app.get("/api/v1/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.get("/api/v1/config/schema", response_model=ConfigSchema)
async def config_schema():
    """Get complete configuration schema for the wizard."""
    return ConfigSchema(
        providers=get_providers_schema(),
        analysts=get_analysts_schema(),
        researchers=get_researchers_schema(),
        risk=get_risk_schema(),
        depths=get_depths_schema(),
        languages=get_languages_schema(),
        reasoning_configs=get_reasoning_configs_schema(),
        temperatures=get_temperature_schema(),
        max_retries_options=get_max_retries_schema(),
        data_vendors=get_data_vendors_schema(),
        benchmark_options=get_benchmark_schema(),
        mcp_info=get_mcp_schema(),
    )


@app.get("/api/v1/models", response_model=ModelListResponse)
async def list_models(provider: str = Query(...), url: str | None = Query(None)):
    """Get available models for a provider."""
    provider = provider.lower()

    # OpenRouter
    if provider == "openrouter":
        try:
            import requests
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
            resp.raise_for_status()
            models = resp.json().get("data", [])
            models.sort(key=lambda m: m.get("created") or 0, reverse=True)
            mainstream = {"openai", "anthropic", "google", "deepseek", "qwen", "mistralai",
                          "meta-llama", "x-ai", "z-ai", "minimax", "moonshotai"}
            filtered = [
                ModelOption(label=m.get("name") or m["id"], value=m["id"])
                for m in models
                if not m["id"].startswith("~") and m["id"].split("/", 1)[0] in mainstream
            ][:5]
            return ModelListResponse(models=filtered + [ModelOption(label="Custom model ID", value="custom")], source="live")
        except Exception:
            pass

    # OpenAI-compatible (including oMLX)
    if provider == "openai_compatible":
        target_url = url or DEFAULT_CONFIG.get("backend_url") or "http://e1.local:8000/v1"
        try:
            import requests
            models_url = target_url.rstrip("/") + "/models"
            resp = requests.get(models_url, timeout=10)
            resp.raise_for_status()
            models = resp.json().get("data", [])
            opts = [ModelOption(label=m.get("id") or m.get("name"), value=m.get("id") or m.get("name"))
                    for m in models if m.get("id") or m.get("name")]
            return ModelListResponse(models=opts + [ModelOption(label="Custom model ID", value="custom")], source="live")
        except Exception:
            pass

    # Static catalog fallback
    try:
        options = list(get_model_options(provider, "quick"))  # Use quick as representative
        opts = [ModelOption(label=d, value=v) for d, v in options]
        return ModelListResponse(models=opts + [ModelOption(label="Custom model ID", value="custom")], source="static")
    except Exception:
        return ModelListResponse(models=[ModelOption(label="Custom model ID", value="custom")], source="error")


@app.post("/api/v1/analyze", response_model=RunCreateResponse)
async def start_analysis(config: RunConfig):
    """Start a new analysis run."""
    # Validate at least one analyst AND at least one researcher selected,
    # matching the CLI's combined agents-team constraint (#risk debators may be 0).
    if not config.analysts:
        raise HTTPException(400, "At least one analyst must be selected")
    if not config.researchers:
        raise HTTPException(400, "At least one researcher must be selected")
    invalid_researchers = [r for r in config.researchers if r not in VALID_RESEARCHERS]
    if invalid_researchers:
        raise HTTPException(400, f"Invalid researchers: {invalid_researchers}")
    invalid_risk = [r for r in config.risk if r not in VALID_RISK]
    if invalid_risk:
        raise HTTPException(400, f"Invalid risk debators: {invalid_risk}")

    # Validate ticker
    ticker = config.ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Ticker symbol required")

    # Validate date not in future
    from datetime import datetime
    try:
        analysis_date = datetime.strptime(config.analysis_date, "%Y-%m-%d").date()
        if analysis_date > datetime.now().date():
            raise HTTPException(400, "Analysis date cannot be in the future")
    except ValueError:
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD)") from None

    run_id = await enqueue_analysis(config)
    return RunCreateResponse(run_id=run_id)


@app.websocket("/api/v1/analyze/{run_id}/stream")
async def stream_analysis(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for real-time analysis updates."""
    await manager.connect(run_id, websocket)
    try:
        # Send current status if run exists
        run = await get_run(run_id)
        if run:
            status_msg = {
                "type": "status",
                "status": run["status"],
                "run_id": run_id
            }
            # Include start_time if analysis is running or completed
            if run.get("started_at"):
                status_msg["start_time"] = run["started_at"]
            await websocket.send_json(status_msg)
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)
    except Exception:
        manager.disconnect(run_id, websocket)


@app.get("/api/v1/reports/{run_id}", response_model=RunDetailResponse)
async def get_report(run_id: str):
    """Get final report for a run."""
    run = await get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    report = None
    if run["report_json"]:
        report = json.loads(run["report_json"])

    return RunDetailResponse(
        id=run["id"],
        ticker=run["ticker"],
        analysis_date=run["analysis_date"],
        status=run["status"],
        created_at=run["created_at"],
        completed_at=run["completed_at"],
        error_message=run["error_message"],
        config=json.loads(run["config_json"]),
        report=report,
    )


@app.get("/api/v1/reports/{run_id}/export")
async def export_report(run_id: str, format: str = Query("md", pattern="^(md|epub)$")):
    """Export a run's report in the CLI's on-disk format.

    ``format=md`` returns the consolidated ``complete_report.md``; ``format=epub``
    returns the CLI-style EPUB. Prefers the files persisted to disk by the run
    (``report_path``), falling back to in-memory generation from the stored raw
    final state when they are unavailable (e.g. older runs).
    """
    run = await get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    config = json.loads(run["config_json"]) if run["config_json"] else {}
    ticker = run["ticker"]

    if format == "md":
        md_bytes = _build_markdown_export(run, config)
        if md_bytes is None:
            raise HTTPException(404, "No report content available for this run")
        return Response(
            content=md_bytes,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{ticker}_report.md"'},
        )

    # EPUB
    epub_bytes = _build_epub_export(run, config)
    if epub_bytes is None:
        raise HTTPException(404, "No report content available for this run")
    date_suffix = run["analysis_date"]
    return Response(
        content=epub_bytes,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{ticker}_{date_suffix}.epub"'},
    )


def _run_final_state(run) -> dict | None:
    """Return the best-available final state for a run.

    Prefers the raw per-agent state persisted since the report-export feature
    landed (``final_state_json``), then synthesizes a close equivalent from the
    structured ``report_json`` so older completed runs can still export.
    """
    if run.get("final_state_json"):
        try:
            state = json.loads(run["final_state_json"])
            if isinstance(state, dict):
                return state
        except Exception:
            pass

    if not run.get("report_json"):
        return None
    try:
        rj = json.loads(run["report_json"])
    except Exception:
        return None
    if not isinstance(rj, dict):
        return None

    state = {}
    analysts = rj.get("analyst_reports") or {}
    if isinstance(analysts, dict):
        for key, name in [
            ("market_report", "Market Analyst"),
            ("sentiment_report", "Sentiment Analyst"),
            ("news_report", "News Analyst"),
            ("fundamentals_report", "Fundamentals Analyst"),
        ]:
            for k, v in analysts.items():
                if k == name and isinstance(v, str):
                    state[key] = v
                    break

    research = rj.get("research_team") or {}
    if isinstance(research, dict):
        debate = {}
        for k, v in research.items():
            if not isinstance(v, str):
                continue
            kl = k.lower()
            if "bull" in kl:
                debate["bull_history"] = v
            elif "bear" in kl:
                debate["bear_history"] = v
            elif "manager" in kl:
                debate["judge_decision"] = v
        if debate:
            state["investment_debate_state"] = debate

    if rj.get("trader_plan") is not None:
        state["trader_investment_plan"] = rj["trader_plan"]

    risk = rj.get("risk_management") or {}
    pm = rj.get("portfolio_manager_decision")
    if isinstance(risk, dict) or pm:
        rd = {}
        if isinstance(risk, dict):
            for k, v in risk.items():
                if not isinstance(v, str):
                    continue
                rd[k.lower()] = v
        if pm:
            rd["judge_decision"] = pm
        if rd:
            state["risk_debate_state"] = rd

    return state or None


def _build_markdown_export(run, config) -> bytes | None:
    """Return CLI-identical consolidated markdown for a run, or None if empty."""
    # Prefer the persisted complete_report.md, if present on disk.
    report_path = run.get("report_path")
    if report_path:
        md_file = Path(report_path) / "complete_report.md"
        if md_file.exists():
            return md_file.read_bytes()

    # Fall back to regenerating from the best-available final state.
    final_state = _run_final_state(run)
    if final_state and _collect_sections(final_state):
        from datetime import datetime
        header = f"# {run['ticker']} Report\n\n{datetime.now().strftime('%A, %B %d, %Y %H:%M %p')}\n\n"
        content = header + "\n\n".join(_collect_sections(final_state))
        return content.encode("utf-8")
    return None


def _build_epub_export(run, config) -> bytes | None:
    """Return CLI-identical EPUB bytes for a run, or None if empty."""
    # Prefer the persisted .epub, if present on disk.
    report_path = run.get("report_path")
    if report_path:
        epubs = sorted(Path(report_path).glob("*.epub"))
        if epubs:
            return epubs[0].read_bytes()

    # Fall back to building in memory from the best-available final state.
    final_state = _run_final_state(run)
    if final_state:
        try:
            return build_epub(final_state, run["ticker"], config)
        except Exception:
            return None
    return None


@app.get("/api/v1/history", response_model=HistoryResponse)
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None)
):
    """Get paginated analysis history."""
    runs = await list_runs(limit, offset, status)
    total = await count_runs(status)
    return HistoryResponse(
        runs=[RunStatusResponse(**r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/queue/status")
async def queue_status():
    """Get analysis queue status."""
    return {
        "queue_size": analysis_queue.qsize(),
        "worker_running": analysis_queue.qsize() > 0,
    }


# --- Frontend fallback ---
web_dist = Path(__file__).parent.parent / "web" / "dist"

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve React app for all non-API routes."""
    index_path = web_dist / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "Frontend not built. Run `npm run build` in web/ directory."}
