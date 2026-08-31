"""FastAPI server for TradingAgents Web UI."""

import os
import json
from contextlib import asynccontextmanager
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.database import init_db, create_run, get_run, get_run_report, list_runs, count_runs
from api.service import enqueue_analysis, RunConfig, analysis_queue
from api.schemas import (
    ConfigSchema, RunCreateResponse, RunStatusResponse, RunDetailResponse,
    HistoryResponse, ModelListResponse, HealthResponse,
    ProviderInfo, AnalystOption, DepthOption, LanguageOption,
    ProviderReasoningConfig, ModelOption
)
from api.websocket import manager
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import get_model_options
from cli.utils import _llm_provider_table, filter_analysts_for_asset_type
from cli.models import AnalystType, AssetType


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

def get_providers_schema() -> List[ProviderInfo]:
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


def get_analysts_schema() -> List[AnalystOption]:
    """Get analyst options schema."""
    return [
        AnalystOption(key="market", label="Market Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="social", label="Sentiment Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="news", label="News Analyst", asset_types=["stock", "crypto"]),
        AnalystOption(key="fundamentals", label="Fundamentals Analyst", asset_types=["stock"]),
    ]


def get_depths_schema() -> List[DepthOption]:
    """Get research depth options."""
    return [
        DepthOption(label="Shallow - Quick research", value=1, description="1 debate round, 1 risk round"),
        DepthOption(label="Medium - Balanced research", value=3, description="3 debate rounds, 3 risk rounds"),
        DepthOption(label="Deep - Comprehensive research", value=5, description="5 debate rounds, 5 risk rounds"),
    ]


def get_languages_schema() -> List[LanguageOption]:
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


def get_reasoning_configs_schema() -> List[ProviderReasoningConfig]:
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
        depths=get_depths_schema(),
        languages=get_languages_schema(),
        reasoning_configs=get_reasoning_configs_schema(),
    )


@app.get("/api/v1/models", response_model=ModelListResponse)
async def list_models(provider: str = Query(...), url: Optional[str] = Query(None)):
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
    # Validate at least one analyst selected
    if not config.analysts:
        raise HTTPException(400, "At least one analyst must be selected")

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
        raise HTTPException(400, "Invalid date format (YYYY-MM-DD)")

    run_id = await enqueue_analysis(config)
    return RunCreateResponse(run_id=run_id)


@app.get("/api/v1/analyze/{run_id}/stream")
async def stream_analysis(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for real-time analysis updates."""
    await manager.connect(run_id, websocket)
    try:
        # Send current status if run exists
        run = await get_run(run_id)
        if run:
            await websocket.send_json({
                "type": "status",
                "status": run["status"],
                "run_id": run_id
            })
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


@app.get("/api/v1/history", response_model=HistoryResponse)
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None)
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