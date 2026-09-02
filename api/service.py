"""Analysis service - core logic extracted from CLI for web API."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from api.database import create_run, update_run_status
from api.schemas import RunConfig
from api.websocket import (
    make_agent_status_event,
    make_complete_event,
    make_error_event,
    make_report_section_event,
    make_stats_event,
    make_tool_call_event,
    manager,
)
from tradingagents.dataflows.symbol_utils import crypto_base
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.analyst_execution import (
    AnalystWallTimeTracker,
    build_analyst_execution_plan,
    get_initial_analyst_node,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree

# Type for event callback
EventCallback = Callable[[str, dict], Awaitable[None]]


class AnalysisService:
    """Service for running trading analysis with event streaming."""

    def __init__(self, config: RunConfig, run_id: str, event_callback: EventCallback | None = None):
        self.config = config
        self.run_id = run_id
        self.event_callback = event_callback
        self.running = False
        self._task: asyncio.Task | None = None

        # Analysis components (initialized in run)
        self.graph: TradingAgentsGraph | None = None
        self.stats_handler: Any | None = None
        self.message_buffer: Any | None = None
        self.selected_analyst_keys: list[str] = []

        # Logging (CLI-compatible)
        self._log_file: Path | None = None
        self._log_dir: Path | None = None

    async def _emit(self, event: dict) -> None:
        """Emit an event via callback and WebSocket manager."""
        if self.event_callback:
            await self.event_callback(self.run_id, event)
        await manager.broadcast(self.run_id, event)

    def _build_run_config(self) -> dict[str, Any]:
        """Build the internal config dict from RunConfig."""
        cfg = DEFAULT_CONFIG.copy()
        cfg["max_debate_rounds"] = self.config.research_depth
        cfg["max_risk_discuss_rounds"] = self.config.research_depth
        cfg["quick_think_llm"] = self.config.shallow_thinker
        cfg["deep_think_llm"] = self.config.deep_thinker
        cfg["backend_url"] = self.config.backend_url
        cfg["llm_provider"] = self.config.llm_provider.lower()
        cfg["google_thinking_level"] = self.config.google_thinking_level
        cfg["openai_reasoning_effort"] = self.config.openai_reasoning_effort
        cfg["anthropic_effort"] = self.config.anthropic_effort
        cfg["output_language"] = self.config.output_language
        cfg["checkpoint_enabled"] = False
        # LLM settings
        if self.config.temperature is not None:
            cfg["temperature"] = self.config.temperature
        if self.config.llm_max_retries is not None:
            cfg["llm_max_retries"] = self.config.llm_max_retries
        # Data vendor configuration
        if self.config.data_vendors is not None:
            cfg["data_vendors"] = self.config.data_vendors
        if self.config.tool_vendors is not None:
            cfg["tool_vendors"] = self.config.tool_vendors
        # Benchmark configuration
        if self.config.benchmark_ticker is not None:
            cfg["benchmark_ticker"] = self.config.benchmark_ticker
        if self.config.benchmark_map is not None:
            cfg["benchmark_map"] = self.config.benchmark_map
        # MCP server configuration
        if self.config.mcp_servers is not None:
            cfg["mcp_servers"] = self.config.mcp_servers
        if self.config.mcp_realtime_tool_filter is not None:
            cfg["mcp_realtime_tool_filter"] = self.config.mcp_realtime_tool_filter
        return cfg

    def _normalize_ticker(self, ticker: str) -> str:
        """Normalize ticker symbol."""
        try:
            from tradingagents.dataflows.symbol_utils import normalize_symbol

            return normalize_symbol(ticker)
        except Exception:
            return ticker.strip().upper()

    def _detect_asset_type(self, ticker: str) -> str:
        """Detect asset type from ticker."""
        canonical = self._normalize_ticker(ticker)
        if crypto_base(canonical):
            return "crypto"
        return "stock"

    def _save_report_files(self, final_state: dict[str, Any], ticker: str) -> Path | None:
        """Write CLI-equivalent report files to the same directory the CLI uses.

        The CLI's interactive save defaults to
        ``<cwd>/reports/<TICKER>_<YYYYmmdd_HHMMSS>`` (see ``cli/main.py``), so
        the web API writes there too, keeping both interfaces' reports in one
        place. Each run gets its own time-stamped directory (so same-ticker
        runs never overwrite each other). Reports include the per-section
        markdown files, ``complete_report.md``, and the ``.epub``.
        """
        try:
            cfg = self._build_run_config()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_dir = Path.cwd() / "reports" / f"{self._safe_component(ticker)}_{timestamp}"
            report_dir.mkdir(parents=True, exist_ok=True)
            write_report_tree(final_state, ticker, report_dir, cfg)
            return report_dir
        except Exception as e:
            # Log but never fail the run because report-writing failed.
            print(f"[api.service] report save failed: {e}")
            return None

    @staticmethod
    def _safe_component(name: str) -> str:
        """Sanitize a path component (e.g. a ticker) for use in a filesystem path."""
        return "".join(c for c in name if c.isalnum() or c in "._-") or "ticker"

    def _init_logging(self) -> None:
        """Initialize CLI-compatible logging to ~/.tradingagents/logs/."""
        run_cfg = self._build_run_config()
        results_dir = Path(run_cfg.get("results_dir", DEFAULT_CONFIG["results_dir"]))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_ticker = self._safe_component(self.config.ticker)
        self._log_dir = results_dir / f"{safe_ticker}_{self.config.analysis_date}_{timestamp}"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "message_tool.log"
        self._log_file.touch(exist_ok=True)
        self._log_message(
            "System", f"Analysis started for {self.config.ticker} on {self.config.analysis_date}"
        )

    def _log_message(self, msg_type: str, content: str) -> None:
        """Write a message to the log file (CLI format)."""
        if self._log_file:
            timestamp = datetime.now().strftime("%H:%M:%S")
            # Replace newlines with spaces like CLI does
            content = content.replace("\n", " ")
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{msg_type}] {content}\n")

    def _log_tool_call(self, tool_name: str, args: dict) -> None:
        """Write a tool call to the log file (CLI format)."""
        if self._log_file:
            timestamp = datetime.now().strftime("%H:%M:%S")
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")

    @staticmethod
    def _sanitize_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
        """Return a JSON-serializable copy of a graph state.

        The raw state accumulating ``astream`` chunks includes ``messages`` lists
        of LangChain ``HumanMessage``/``AIMessage``/``ToolMessage`` objects, which
        cannot be ``json.dumps``-ed. Only the report text fields are needed for
        persistence/export, so drop ``messages`` and coerce any remaining
        non-serializable value to its string form.
        """
        if not isinstance(state, dict):
            return state

        def _convert(value):
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, (list, tuple)):
                return [_convert(v) for v in value]
            if isinstance(value, dict):
                return {str(k): _convert(v) for k, v in value.items()}
            # LangChain message objects and any other unknown types -> string form.
            content = getattr(value, "content", None)
            if content is not None and (isinstance(content, str) or content == ""):
                return content
            return str(value)

        out = {}
        for key, value in state.items():
            if key == "messages":
                # Large, non-serializable and not needed for reports/export.
                continue
            out[key] = _convert(value)
        return out

    async def run(self) -> dict[str, Any]:
        """Run the analysis and return final state."""
        self.running = True
        await update_run_status(self.run_id, "running")

        # Initialize logging (CLI-compatible)
        self._init_logging()

        try:
            # Normalize ticker and detect asset type
            normalized_ticker = self._normalize_ticker(self.config.ticker)
            asset_type = self._detect_asset_type(normalized_ticker)

            # Filter analysts for asset type
            analyst_keys = list(self.config.analysts)
            if asset_type == "crypto":
                analyst_keys = list(filter(lambda a: a != "fundamentals", analyst_keys))

            self.selected_analyst_keys = analyst_keys

            # Build execution plan
            analyst_execution_plan = build_analyst_execution_plan(analyst_keys)
            analyst_wall_time_tracker = AnalystWallTimeTracker(analyst_execution_plan)

            # Initialize graph with config
            run_cfg = self._build_run_config()

            # Import stats handler
            from cli.stats_handler import StatsCallbackHandler

            self.stats_handler = StatsCallbackHandler()

            self.graph = TradingAgentsGraph(
                selected_analysts=analyst_keys,
                selected_researchers=self.config.researchers,
                selected_risk=self.config.risk,
                config=run_cfg,
                debug=True,
                callbacks=[self.stats_handler],
            )

            # Resolve instrument context
            instrument_context = self.graph.resolve_instrument_context(
                normalized_ticker, asset_type
            )

            # Create initial state
            init_agent_state = self.graph.propagator.create_initial_state(
                normalized_ticker,
                self.config.analysis_date,
                asset_type=asset_type,
                instrument_context=instrument_context,
            )

            # Get graph args with callbacks
            args = self.graph.propagator.get_graph_args(callbacks=[self.stats_handler])

            # Emit initial events
            await self._emit(make_agent_status_event("System", "starting"))
            await self._emit(make_agent_status_event("System", "analyzing"))

            # Set first analyst to in_progress
            first_analyst = get_initial_analyst_node(analyst_execution_plan)
            await self._emit(make_agent_status_event(first_analyst, "in_progress"))
            analyst_wall_time_tracker.mark_started(analyst_keys[0])

            # Stream the analysis. Streamed chunks are per-node deltas, not full
            # state, so merge them (same as the CLI) to ensure every report field
            # populated across the run is present in the final state.
            final_state: dict[str, Any] = {}
            async for chunk in self._stream_analysis(
                init_agent_state, args, analyst_wall_time_tracker, normalized_ticker, asset_type
            ):
                final_state.update(chunk)

            # Build final report
            final_report = self._build_final_report(final_state)

            # Save CLI-equivalent report files to the per-run reports directory and
            # persist both the compiled report and a JSON-safe final state.
            report_path = self._save_report_files(final_state, normalized_ticker)

            await update_run_status(
                self.run_id,
                "completed",
                report=final_report,
                final_state=self._sanitize_state(final_state),
                report_path=str(report_path) if report_path else None,
            )
            await self._emit(make_complete_event(self.run_id))

            return final_report

        except Exception as e:
            error_msg = f"Analysis failed: {str(e)}"
            self._log_message("System", f"ERROR: {error_msg}")
            await update_run_status(self.run_id, "failed", error=error_msg)
            await self._emit(make_error_event(error_msg))
            raise
        finally:
            self.running = False

    async def _stream_analysis(
        self,
        init_state: dict[str, Any],
        graph_args: dict[str, Any],
        wall_time_tracker: AnalystWallTimeTracker,
        ticker: str,
        asset_type: str,
    ):
        """Stream analysis chunks and emit events."""

        # Initialize message buffer (reuse CLI logic)
        class MessageBuffer:
            ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
            ANALYST_NAMES = {
                "market": "Market Analyst",
                "social": "Sentiment Analyst",
                "news": "News Analyst",
                "fundamentals": "Fundamentals Analyst",
            }
            REPORT_MAP = {
                "market": "market_report",
                "social": "sentiment_report",
                "news": "news_report",
                "fundamentals": "fundamentals_report",
            }

            def __init__(self, selected_analysts: list[str]):
                self.selected_analysts = selected_analysts
                self.agent_status = {}
                self.report_sections = {}
                self._processed_message_ids = set()
                self._analyst_reruns_last = {}
                self._init_status()

            def _init_status(self):
                for key in self.selected_analysts:
                    name = self.ANALYST_NAMES.get(key, key)
                    self.agent_status[name] = "pending"
                    self.report_sections[self.REPORT_MAP[key]] = None
                # Fixed teams
                for team_agents in [
                    ["Bull Researcher", "Bear Researcher", "Research Manager"],
                    ["Trader"],
                    ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
                    ["Portfolio Manager"],
                ]:
                    for agent in team_agents:
                        self.agent_status[agent] = "pending"

            def update_agent_status(self, agent: str, status: str):
                if agent in self.agent_status:
                    self.agent_status[agent] = status

            def update_report_section(self, section: str, content: str):
                if section in self.report_sections:
                    self.report_sections[section] = content

        self.message_buffer = MessageBuffer(self.selected_analyst_keys)

        # Stream graph
        async for chunk in self.graph.graph.astream(init_state, **graph_args):
            # Process messages
            for message in chunk.get("messages", []):
                msg_id = getattr(message, "id", None)
                if msg_id and msg_id in self.message_buffer._processed_message_ids:
                    continue
                if msg_id:
                    self.message_buffer._processed_message_ids.add(msg_id)

                # Classify and emit message
                msg_type, content = self._classify_message(message)
                if content and content.strip():
                    await self._emit({"type": "message", "msg_type": msg_type, "content": content})
                    self._log_message(msg_type.capitalize(), content)

                # Emit tool calls
                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tool_call in message.tool_calls:
                        if isinstance(tool_call, dict):
                            await self._emit(
                                make_tool_call_event(tool_call["name"], tool_call["args"])
                            )
                            self._log_tool_call(tool_call["name"], tool_call["args"])
                        else:
                            await self._emit(make_tool_call_event(tool_call.name, tool_call.args))
                            self._log_tool_call(tool_call.name, tool_call.args)

            # Update analyst statuses from reports
            await self._update_analyst_statuses(chunk)

            # Surface pre-research gate re-runs (analyst finished empty, re-running)
            await self._handle_analyst_reruns(chunk)

            # Handle report sections
            await self._handle_report_sections(chunk)

            # Emit stats periodically
            if self.stats_handler:
                stats = self.stats_handler.get_stats()
                await self._emit(
                    make_stats_event(
                        stats.get("llm_calls", 0),
                        stats.get("tool_calls", 0),
                        stats.get("tokens_in", 0),
                        stats.get("tokens_out", 0),
                    )
                )

            yield chunk

    def _classify_message(self, message) -> tuple[str, str | None]:
        """Classify message type and extract content."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        content = self._extract_content(getattr(message, "content", None))

        if isinstance(message, HumanMessage):
            if content and content.strip() == "Continue":
                return ("control", content)
            return ("user", content)

        if isinstance(message, ToolMessage):
            return ("data", content)

        if isinstance(message, AIMessage):
            return ("agent", content)

        return ("system", content)

    def _extract_content(self, content) -> str | None:
        """Extract string content from various formats."""
        if content is None or content == "":
            return None
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, dict):
            text = content.get("text", "")
            return text.strip() if text else None
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = item.get("text", "").strip()
                    if t:
                        parts.append(t)
                elif isinstance(item, str):
                    t = item.strip()
                    if t:
                        parts.append(t)
            return " ".join(parts) if parts else None
        return str(content).strip() if content else None

    async def _update_analyst_statuses(self, chunk: dict[str, Any]) -> None:
        """Update analyst statuses based on accumulated reports."""
        selected = self.message_buffer.selected_analysts
        found_active = False

        for analyst_key in self.message_buffer.ANALYST_ORDER:
            if analyst_key not in selected:
                continue

            agent_name = self.message_buffer.ANALYST_NAMES[analyst_key]
            report_key = self.message_buffer.REPORT_MAP[analyst_key]

            # Capture new report content
            if chunk.get(report_key):
                self.message_buffer.update_report_section(report_key, chunk[report_key])
                await self._emit(make_report_section_event(report_key, chunk[report_key]))

            # Determine status
            has_report = bool(self.message_buffer.report_sections.get(report_key))

            if has_report:
                self.message_buffer.update_agent_status(agent_name, "completed")
                await self._emit(make_agent_status_event(agent_name, "completed"))
            elif not found_active:
                self.message_buffer.update_agent_status(agent_name, "in_progress")
                await self._emit(make_agent_status_event(agent_name, "in_progress"))
                found_active = True
            else:
                self.message_buffer.update_agent_status(agent_name, "pending")

        # Transition to research team
        if (
            not found_active
            and selected
            and self.message_buffer.agent_status.get("Bull Researcher") == "pending"
        ):
            self.message_buffer.update_agent_status("Bull Researcher", "in_progress")
            await self._emit(make_agent_status_event("Bull Researcher", "in_progress"))

    async def _handle_analyst_reruns(self, chunk: dict[str, Any]) -> None:
        """Surface pre-research gate re-runs in the status feed.

        The completion gate (setup.py) bumps ``analyst_reruns`` for an analyst
        that cleared without a report, routing it back for another attempt.
        When a counter grows, flip that analyst back to ``in_progress`` so the
        UI shows it is being re-run rather than stuck "completed" pending the
        research team.
        """
        reruns = chunk.get("analyst_reruns")
        if not isinstance(reruns, dict):
            return

        prev = self.message_buffer._analyst_reruns_last or {}
        for analyst_key, count in reruns.items():
            if count > prev.get(analyst_key, 0):
                name = self.message_buffer.ANALYST_NAMES.get(analyst_key, analyst_key)
                self.message_buffer.update_agent_status(name, "in_progress")
                await self._emit(make_agent_status_event(name, "in_progress"))
        self.message_buffer._analyst_reruns_last = dict(reruns)

    async def _handle_report_sections(self, chunk: dict[str, Any]) -> None:
        """Handle research, trading, and risk report sections."""
        # Research team
        if chunk.get("investment_debate_state"):
            debate = chunk["investment_debate_state"]
            bull = debate.get("bull_history", "").strip()
            bear = debate.get("bear_history", "").strip()
            judge = debate.get("judge_decision", "").strip()

            if bull or bear:
                await self._emit(make_agent_status_event("Bull Researcher", "in_progress"))
                await self._emit(make_agent_status_event("Bear Researcher", "in_progress"))

            if bull:
                content = f"### Bull Researcher Analysis\n{bull}"
                self.message_buffer.update_report_section("investment_plan", content)
                await self._emit(make_report_section_event("investment_plan", content))
            if bear:
                content = f"### Bear Researcher Analysis\n{bear}"
                self.message_buffer.update_report_section("investment_plan", content)
                await self._emit(make_report_section_event("investment_plan", content))
            if judge:
                content = f"### Research Manager Decision\n{judge}"
                self.message_buffer.update_report_section("investment_plan", content)
                await self._emit(make_report_section_event("investment_plan", content))
                await self._emit(make_agent_status_event("Research Manager", "completed"))
                await self._emit(make_agent_status_event("Trader", "in_progress"))

        # Trading team
        if chunk.get("trader_investment_plan"):
            content = chunk["trader_investment_plan"]
            self.message_buffer.update_report_section("trader_investment_plan", content)
            await self._emit(make_report_section_event("trader_investment_plan", content))
            await self._emit(make_agent_status_event("Trader", "completed"))

        # Risk management
        if chunk.get("risk_debate_state"):
            risk = chunk["risk_debate_state"]
            for agent_key, label in [
                ("aggressive_history", "Aggressive Analyst"),
                ("conservative_history", "Conservative Analyst"),
                ("neutral_history", "Neutral Analyst"),
            ]:
                hist = risk.get(agent_key, "").strip()
                if hist:
                    await self._emit(make_agent_status_event(label, "in_progress"))

            if risk.get("judge_decision"):
                await self._emit(make_agent_status_event("Portfolio Manager", "completed"))

    def _build_final_report(self, final_state: dict[str, Any] | None) -> dict[str, Any]:
        """Build the final compiled report from state."""
        if not final_state:
            return {}

        report = {}

        # Analyst reports
        analyst_reports = {}
        for key, label in [
            ("market_report", "Market Analyst"),
            ("sentiment_report", "Sentiment Analyst"),
            ("news_report", "News Analyst"),
            ("fundamentals_report", "Fundamentals Analyst"),
        ]:
            if final_state.get(key):
                analyst_reports[label] = final_state[key]
        if analyst_reports:
            report["analyst_reports"] = analyst_reports

        # Research team
        if final_state.get("investment_debate_state"):
            debate = final_state["investment_debate_state"]
            research = {}
            if debate.get("bull_history"):
                research["Bull Researcher"] = debate["bull_history"]
            if debate.get("bear_history"):
                research["Bear Researcher"] = debate["bear_history"]
            if debate.get("judge_decision"):
                research["Research Manager"] = debate["judge_decision"]
            if research:
                report["research_team"] = research

        # Trader
        if final_state.get("trader_investment_plan"):
            report["trader_plan"] = final_state["trader_investment_plan"]

        # Risk management
        if final_state.get("risk_debate_state"):
            risk = final_state["risk_debate_state"]
            risk_reports = {}
            if risk.get("aggressive_history"):
                risk_reports["Aggressive Analyst"] = risk["aggressive_history"]
            if risk.get("conservative_history"):
                risk_reports["Conservative Analyst"] = risk["conservative_history"]
            if risk.get("neutral_history"):
                risk_reports["Neutral Analyst"] = risk["neutral_history"]
            if risk_reports:
                report["risk_management"] = risk_reports
            if risk.get("judge_decision"):
                report["portfolio_manager_decision"] = risk["judge_decision"]

        return report


async def run_analysis_background(
    config: RunConfig, run_id: str, event_callback: EventCallback | None = None
) -> None:
    """Run analysis in background with event streaming."""
    service = AnalysisService(config, run_id, event_callback)
    await service.run()


# Queue for sequential analysis execution
analysis_queue: asyncio.Queue = asyncio.Queue()
analysis_worker_running = False


async def enqueue_analysis(config: RunConfig) -> str:
    """Add analysis to queue and return run_id. Starts worker if not running."""
    global analysis_worker_running
    run_id = await create_run(config.ticker, config.analysis_date, config.model_dump())
    await analysis_queue.put((config, run_id))

    if not analysis_worker_running:
        asyncio.create_task(_analysis_worker())
        analysis_worker_running = True

    return run_id


async def _analysis_worker() -> None:
    """Background worker that processes analysis queue sequentially."""
    global analysis_worker_running
    while True:
        config, run_id = await analysis_queue.get()
        try:
            await run_analysis_background(config, run_id)
        except Exception:
            # Error already handled in run_analysis_background
            pass
        finally:
            analysis_queue.task_done()

    analysis_worker_running = False
