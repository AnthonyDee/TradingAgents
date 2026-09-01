# TradingAgents AGENTS.md

## Quickstart

Create and activate the `tradingagents` conda environment (recommended):

```bash
conda create -n tradingagents python=3.12
conda activate tradingagents
```

Then install the package and run the CLI:

```bash
# 1. Install editable (never `pip install .` — it freezes a copy that drifts)
pip install -e .

# 2. Install dev extras (test, lint, format)
pip install -e ".[dev]"

# 3. Copy env config and fill API keys
cp .env.example .env    # then set your keys

# 4. Run the CLI
tradingagents           # or: python -m cli.main
```

## Commands

| Task | Command |
|---|---|
| Run test suite | `pytest -q` |
| Run tests by marker | `pytest -q -m unit` / `pytest -q -m integration` / `pytest -q -m smoke` |
| Lint (ruff check) | `ruff check .` |
| Format (ruff format) | `ruff format .` |
| Check checkpoints | `~/.tradingagents/cache/checkpoints/<TICKER>.db` |
| Clear memory log | `~/.tradingagents/memory/trading_memory.md` |

## Environment

- **API keys**: Set via `TRADINGAGENTS_*` env vars (see `.env.example`) or export directly (`OPENAI_API_KEY`, etc.)
- **Preferred**: `cp .env.example .env` and edit
- **Backend URL**: Set `TRADINGAGENTS_LLM_BACKEND_URL` for OpenAI-compatible endpoints
- **Temperature**: `TRADINGAGENTS_TEMPERATURE` controls run-to-run variation

## Project structure

- **`tradingagents/`** — main package, graph, agents, dataflows, LLM clients
- **`cli/`** — CLI entry point (`tradingagents` console script, or `python -m cli.main`)
- **`tests/`** — pytest suite with markers: `unit` (fast, isolated), `integration` (external services), `smoke` (quick sanity)
- **`pyproject.toml`** — build config, dev deps (`ruff`, `pytest`), ruff strict lint settings
- **`.github/workflows/ci.yml`** — CI runs `pytest -q` and `ruff check .`

## Testing quirks

- Mark tests with `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.smoke`
- Integration tests need external services (LLM APIs, yfinance, etc.) — skip with `-m "not integration"`
- Some tests have fixtures; see individual test files for prerequisites
- Test data cached under `~/.tradingagents/cache/`

## Lint / typecheck

- `ruff check .` — strict: E, W, F, I, B, UP, C4, SIM rules; E501 ignored (line-length owned by formatter)
- `ruff format .` — line-length=100, py310 target, combine-as-imports=true
- Ruff config in `pyproject.toml`; do not add `.ruffconfig` or ignore rules without updating pyproject

## Data vendors (config)

Defaults in `tradingagents/default_config.py`:

| Category | Default |
|---|---|
| core_stock_apis | yfinance |
| technical_indicators | yfinance |
| fundamental_data | yfinance |
| news_data | yfinance |
| macro_data | fred |
| prediction_markets | polymarket |

Override via `data_vendors` dict in config or `TRADINGAGENTS_*` env vars.

## MCP / Robinhood integration

Optional: configure `mcp_servers.robinhood` in `DEFAULT_CONFIG` or via env. When active, realtime options/market data becomes available through the MCP Robinhood server connected to opencode. Do not call options/order tools unless the account is `agentic_allowed=true` with `option_level_2` or `option_level_3`.

## Memory & checkpoints

- **Decision log**: `~/.tradingagents/memory/trading_memory.md` (appended each run)
- **Checkpoints**: `~/.tradingagents/cache/checkpoints/<TICKER>.db` — use `--checkpoint` flag or `config["checkpoint_enabled"] = True` to enable resume across crashes
- Override paths with `TRADINGAGENTS_CACHE_DIR` and `TRADINGAGENTS_MEMORY_LOG_PATH`

## API server (uvicorn) — restart via launchd

The web API server (`api.server:app` on `127.0.0.1:8001`) is **managed by
launchd** as LaunchAgent `com.tradingagents.api`, not a plain background
process. After editing `api/` or `tradingagents/` code that the server runs,
restart it with the authoritative command:

```bash
launchctl kickstart -k gui/$(id -u)/com.tradingagents.api
```

- `-k` kills the running instance first, then restarts it.
- `gui/$(id -u)` targets the current user's GUI session domain.
- `RunAtLoad=true` starts it at login; `KeepAlive=true` auto-restarts on crash.

Config lives in `~/Library/LaunchAgents/com.tradingagents.api.plist` (uvicorn
binary path, port, env vars like `TRADINGAGENTS_DB_PATH`/`TRADINGAGENTS_MLX_URL`).

Do **not** start a second `nohup uvicorn ... &` by hand — it races the
launchd instance and fails with `[Errno 48] address already in use`.

Verify + logs:

```bash
launchctl list | grep tradingagents            # shows the live PID
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8001/docs
tail -f /opt/homebrew/var/log/tradingagents-api.{out,err}.log
```
