"""MCP client manager for connecting TradingAgents to MCP servers (e.g. Robinhood).

The manager boots configured MCP servers (stdio or SSE/HTTP), holds an async
``ClientSession`` per server on a dedicated event loop (background thread), and
surfaces each server's tools as *synchronous* LangChain tools so they can be
bound to agents and executed by LangGraph ``ToolNode``s exactly like the
built-in tools.

Only read-only realtime-data tools (quotes, prices, market data) are surfaced to
the analyst agents via :meth:`get_realtime_quote_tools`; execution/order tools
are deliberately excluded so analysts can never place trades.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)

# Substring classifiers used to pick the read-only realtime-data surface. A tool
# is surfaced only if its (lower-cased) name contains an ``include`` substring
# and none of the ``exclude`` substrings. Overridable via config
# (``mcp_realtime_tool_filter``). Execution and account/portfolio tools are
# excluded so analysts get market data without account access or trade ability.
DEFAULT_REALTIME_INCLUDE = ("quote", "price", "market")
DEFAULT_REALTIME_EXCLUDE = (
    "order",
    "trade",
    "buy",
    "sell",
    "exercise",
    "cancel",
    "place",
    "account",
    "position",
    "portfolio",
    "watchlist",
)


def _derive_token_url(server_url: str) -> str:
    """Best-effort OAuth token endpoint from an MCP server URL.

    e.g. ``https://agent.robinhood.com/mcp/trading`` -> ``https://agent.robinhood.com/oauth2/token``.
    Override via ``oauth.token_url`` when the provider differs.
    """
    if not server_url:
        return ""
    parts = urlsplit(server_url)
    if not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/oauth2/token"


class _OAuthTokenProvider:
    """Holds OAuth2 tokens and refreshes them via the ``refresh_token`` grant.

    Tokens are sourced from an opencode-style auth store file (the same one
    opencode writes when it connects to the Robinhood MCP server) or from
    explicit config. Before each request the holder checks expiry and refreshes
    proactively; on a 401 it forces a refresh and retries. Refreshed tokens are
    written back to the store (best-effort) so the token stays valid for every
    consumer (including opencode itself).
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        *,
        refresh_token: str | None = None,
        access_token: str | None = None,
        expires_at: str | int | float | None = None,
        client_secret: str | None = None,
        token_store_path: str | None = None,
        server_key: str | None = None,
        write_back: bool = True,
    ):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_store_path = Path(token_store_path).expanduser() if token_store_path else None
        self.server_key = server_key
        self.write_back = write_back
        self._lock = asyncio.Lock()
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = self._parse_expiry(expires_at)
        if self.token_store_path and self.token_store_path.exists():
            try:
                self.load_from_store()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Could not preload tokens from store: %s", exc)

    @staticmethod
    def _parse_expiry(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return value / 1000.0 if value > 1e12 else float(value)
        if isinstance(value, str):
            s = value.strip()
            if s.lstrip("-").isdigit():
                num = float(s)
                return num / 1000.0 if num > 1e12 else num
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                return None
        return None

    def is_expired(self, skew: int = 300) -> bool:
        if not self.access_token:
            return True
        if self.expires_at is None:
            return False  # unknown expiry; be optimistic
        return _time.time() >= (self.expires_at - skew)

    def load_from_store(self) -> bool:
        if not self.token_store_path or not self.token_store_path.exists():
            return False
        with open(self.token_store_path) as fh:
            data = json.load(fh)
        entry = data.get(self.server_key or "", {})
        if not entry and len(data) == 1:
            entry = next(iter(data.values()))
        tokens = entry.get("tokens", {})
        if not tokens:
            return False
        at = tokens.get("accessToken") or tokens.get("access_token")
        rt = tokens.get("refreshToken") or tokens.get("refresh_token")
        exp = tokens.get("expiresAt") or tokens.get("expires_at")
        cid = (entry.get("clientInfo") or {}).get("clientId") or entry.get("client_id")
        if at:
            self.access_token = at
        if rt:
            self.refresh_token = rt
        if exp is not None:
            self.expires_at = self._parse_expiry(exp)
        if cid:
            self.client_id = cid
        return bool(self.access_token)

    def save_to_store(self) -> None:
        if not self.write_back or not self.token_store_path:
            return
        try:
            with open(self.token_store_path) as fh:
                data = json.load(fh)
        except Exception:
            return
        key = self.server_key or (next(iter(data)) if len(data) == 1 else "")
        if not key or key not in data:
            return
        data[key].setdefault("tokens", {})
        t = data[key]["tokens"]
        t["accessToken"] = self.access_token
        if self.refresh_token:
            t["refreshToken"] = self.refresh_token
        if self.expires_at is not None:
            t["expiresAt"] = datetime.fromtimestamp(self.expires_at, timezone.utc).isoformat()
        try:
            with open(self.token_store_path, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Could not write refreshed token back to store: %s", exc)

    async def refresh(self) -> None:
        async with self._lock:
            if not self.refresh_token:
                raise RuntimeError("No refresh_token available to refresh the OAuth token.")
            import httpx

            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            }
            if self.client_secret:
                payload["client_secret"] = self.client_secret
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.token_url, data=payload)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"OAuth refresh failed ({resp.status_code}): {resp.text[:200]}"
                )
            body = resp.json()
            self.access_token = body.get("access_token") or body.get("accessToken")
            new_rt = body.get("refresh_token") or body.get("refreshToken")
            if new_rt:
                self.refresh_token = new_rt
            exp = body.get("expires_at") or body.get("expiresAt")
            if exp is not None:
                self.expires_at = self._parse_expiry(exp)
            elif "expires_in" in body:
                self.expires_at = _time.time() + float(body["expires_in"])
            if not self.access_token:
                raise RuntimeError("OAuth refresh returned no access_token.")
            self.save_to_store()

    def header(self) -> str:
        return f"Bearer {self.access_token}"


try:
    from httpx import Auth as _HttpxAuth
except ImportError:  # pragma: no cover - httpx ships with mcp
    class _HttpxAuth:  # type: ignore
        pass


class RobinhoodTokenAuth(_HttpxAuth):
    """httpx auth that injects a bearer token and refreshes it on expiry/401."""

    def __init__(self, provider: _OAuthTokenProvider):
        self._provider = provider

    async def async_auth_flow(self, request):
        await self._ensure_valid()
        request.headers["Authorization"] = self._provider.header()
        response = yield request
        if response.status_code == 401:
            logger.warning("MCP auth returned 401; forcing OAuth refresh and retrying.")
            await self._force_refresh()
            request.headers["Authorization"] = self._provider.header()
            yield request

    async def _ensure_valid(self):
        if self._provider.is_expired():
            try:
                await self._provider.refresh()
            except Exception as exc:
                logger.warning("OAuth proactive refresh failed (%s); reloading store.", exc)
                self._provider.load_from_store()

    async def _force_refresh(self):
        try:
            await self._provider.refresh()
        except Exception as exc:
            logger.warning("OAuth forced refresh failed (%s); reloading store.", exc)
            self._provider.load_from_store()


def _json_type_to_python(prop: dict) -> type:
    """Best-effort mapping of a JSON-schema property to a Python type.

    Falls back to ``str`` for anything not recognised (incl. refs / nested
    schemas), which is fine because the value is passed straight through to the
    MCP server via ``session.call_tool``.
    """
    t = prop.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(t, str)


def _build_args_model(tool_name: str, schema: dict | None) -> type[BaseModel]:
    """Build a pydantic model from an MCP tool's JSON-schema input."""
    schema = schema or {"type": "object", "properties": {}}
    properties = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    fields = {}
    for name, prop in properties.items():
        ptype = _json_type_to_python(prop)
        # Ellipsis => required field; None => optional with default.
        default = ... if name in required else None
        description = prop.get("description", "")
        fields[name] = (ptype, Field(default, description=description))
    return create_model(f"{tool_name}_Args", **fields)


class MCPClientManager:
    """Connects to MCP servers and exposes their tools as LangChain tools.

    Usage::

        mgr = MCPClientManager(config.get("mcp_servers") or {})
        mgr.start()                       # boots servers (no-op if empty)
        tools = mgr.get_realtime_quote_tools()
        ...                               # bind ``tools`` to agents / ToolNodes
        mgr.close()                       # tear down servers + loop
    """

    def __init__(
        self,
        servers: dict[str, dict] | None = None,
        filter_config: dict | None = None,
    ):
        self.servers = dict(servers or {})
        self.filter_config = filter_config or {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: Any = None
        self._sessions: dict[str, Any] = {}
        self._tool_servers: dict[str, str] = {}
        self._tools: list[StructuredTool] = []
        self._tool_by_name: dict[str, StructuredTool] = {}
        self._http_clients: list[Any] = []
        self._raw_tools: dict[str, Any] = {}
        self._providers: dict[str, _OAuthTokenProvider] = {}
        self._configured = bool(self.servers)
        for name, scfg in self.servers.items():
            prov = self._build_oauth_provider(scfg)
            if prov is not None:
                self._providers[name] = prov

    @property
    def is_configured(self) -> bool:
        return self._configured

    def start(self) -> None:
        """Boot the configured servers. No-op when none are configured."""
        if not self.servers:
            logger.debug("MCPClientManager: no MCP servers configured; skipping.")
            return
        try:
            from mcp import ClientSession, StdioServerParameters  # noqa: F401
            from mcp.client.stdio import stdio_client  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "The 'mcp' package is required to use MCP servers. "
                "Install it with: pip install 'tradingagents[mcp]'"
            ) from exc

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        try:
            future.result(timeout=90)
        except Exception as exc:
            self.close()
            raise RuntimeError(f"Failed to start MCP servers: {exc}") from exc

        self._build_tools()
        logger.info(
            "MCPClientManager started with %d tool(s) from %d server(s).",
            len(self._tools),
            len(self.servers),
        )

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self) -> None:
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stack = AsyncExitStack()
        for name, cfg in self.servers.items():
            transport = cfg.get("transport", "stdio")
            if transport == "stdio":
                cmd = list(cfg["command"])
                params = StdioServerParameters(
                    command=cmd[0],
                    args=cmd[1:] + list(cfg.get("args", [])),
                    env=cfg.get("env"),
                )
                read, write = await self._stack.enter_async_context(stdio_client(params))
            elif transport in ("sse", "http", "streamable_http", "streamablehttp", "remote"):
                provider = self._providers.get(name)
                headers = self._resolve_headers(cfg, provider)
                auth = RobinhoodTokenAuth(provider) if provider else None
                if transport == "sse":
                    from mcp.client.sse import sse_client

                    # Older SDKs accept headers=; newer ones take an http_client.
                    try:
                        client_cm = sse_client(cfg["url"], headers=headers)
                    except TypeError:
                        client_cm = sse_client(cfg["url"])
                else:
                    # Streamable HTTP transport (remote servers like Robinhood).
                    # The factory was renamed streamablehttp_client (no underscore)
                    # in newer SDKs; older ones use streamable_http_client.
                    import mcp.client.streamable_http as _sh

                    factory = getattr(_sh, "streamablehttp_client", None) or getattr(
                        _sh, "streamable_http_client", None
                    )
                    if factory is None:
                        raise RuntimeError(
                            "The installed 'mcp' SDK has no streamable HTTP client."
                        )
                    client_cm = factory(
                        cfg["url"], **self._http_client_kwargs(factory, headers, auth)
                    )
                result = await self._stack.enter_async_context(client_cm)
                # Yields a (read, write) tuple/NamedTuple, or (read, write,
                # get_session_id) in some SDK versions. Unpack defensively.
                try:
                    read, write = result.read, result.write
                except AttributeError:
                    read, write = result[0], result[1]
            else:
                raise ValueError(
                    f"Unsupported MCP transport for server '{name}': {transport}"
                )

            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[name] = session
            logger.info("MCP server '%s' connected (%s).", name, transport)

    def _build_oauth_provider(self, cfg: dict) -> _OAuthTokenProvider | None:
        """Build an OAuth token provider for a server, or None.

        Sources tokens from an opencode-style auth store (``oauth.token_store``)
        or from explicit ``oauth`` fields, and resolves the token endpoint
        (``oauth.token_url``, else derived from the store/server URL).
        """
        oauth = cfg.get("oauth")
        if not oauth:
            return None
        store_path = oauth.get("token_store")
        server_key = oauth.get("server_key", "robinhood-trading")

        store_tokens: dict = {}
        store_client_id = None
        store_server_url = None
        if store_path:
            try:
                with open(Path(store_path).expanduser()) as fh:
                    sdata = json.load(fh)
                sentry = sdata.get(server_key, {})
                if not sentry and len(sdata) == 1:
                    sentry = next(iter(sdata.values()))
                store_tokens = sentry.get("tokens", {})
                store_client_id = (sentry.get("clientInfo") or {}).get("clientId")
                store_server_url = sentry.get("serverUrl")
            except Exception as exc:
                logger.debug("Could not read token store %s: %s", store_path, exc)

        token_url = (
            oauth.get("token_url")
            or (store_server_url and _derive_token_url(store_server_url))
            or _derive_token_url(cfg.get("url", ""))
        )
        client_id = oauth.get("client_id") or store_client_id or ""
        if not token_url or not client_id:
            logger.warning(
                "OAuth configured for a server but token_url/client_id are missing; "
                "falling back to a static token (no auto-refresh)."
            )
            return None
        return _OAuthTokenProvider(
            token_url=token_url,
            client_id=client_id,
            client_secret=oauth.get("client_secret"),
            access_token=oauth.get("access_token")
            or store_tokens.get("accessToken")
            or os.environ.get("ROBINHOOD_MCP_TOKEN"),
            refresh_token=oauth.get("refresh_token") or store_tokens.get("refreshToken"),
            expires_at=oauth.get("expires_at") or store_tokens.get("expiresAt"),
            token_store_path=store_path,
            server_key=server_key,
            write_back=oauth.get("write_back", True),
        )

    def _resolve_headers(self, cfg: dict, provider: _OAuthTokenProvider | None = None) -> dict | None:
        """Build auth headers for a server config.

        When an OAuth ``provider`` is present, headers are left to
        :class:`RobinhoodTokenAuth` (returned as ``None``). Otherwise a bearer
        token may be supplied directly via ``cfg["token"]`` or via the
        ``ROBINHOOD_MCP_TOKEN`` environment variable. Extra ``cfg["headers"]``
        are merged on top.
        """
        if provider is not None:
            return None
        headers: dict[str, str] = dict(cfg.get("headers") or {})
        token = cfg.get("token") or os.environ.get("ROBINHOOD_MCP_TOKEN")
        if token:
            headers.setdefault("Authorization", f"Bearer {token}")
        return headers or None

    def _http_client_kwargs(self, factory, headers: dict | None, auth=None) -> dict:
        """Return the version-correct kwargs to inject auth headers.

        mcp 2.x takes an ``http_client`` (a pre-built ``httpx.AsyncClient``); mcp
        1.x takes a top-level ``headers`` argument. When an ``auth`` (the
        refreshing OAuth handler) is supplied it is attached to the
        ``http_client``; otherwise ``headers`` are used. Returns ``{}`` when
        neither is configured (or the SDK supports neither form).
        """
        if not (headers or auth):
            return {}
        import inspect

        import httpx

        sig = inspect.signature(factory)
        if "http_client" in sig.parameters:
            if auth is not None:
                client = httpx.AsyncClient(auth=auth, timeout=30)
            else:
                client = httpx.AsyncClient(headers=headers or {})
            self._http_clients.append(client)
            return {"http_client": client}
        if "headers" in sig.parameters and headers:
            return {"headers": headers}
        logger.warning(
            "MCP SDK version does not support auth injection; connecting "
            "without it (likely 401)."
        )
        return {}

    def _build_tools(self) -> None:
        for server_name, session in self._sessions.items():
            try:
                resp = asyncio.run_coroutine_threadsafe(
                    session.list_tools(), self._loop
                ).result(timeout=60)
            except Exception as exc:
                logger.warning("Could not list tools for server '%s': %s", server_name, exc)
                continue
            for mcp_tool in getattr(resp, "tools", []):
                tool = self._make_tool(server_name, mcp_tool)
                if tool.name in self._tool_by_name:
                    # Avoid name collisions with built-ins; prefix with server.
                    tool.name = f"{server_name}__{tool.name}"
                self._tools.append(tool)
                self._tool_by_name[tool.name] = tool
                self._tool_servers[tool.name] = server_name
                self._raw_tools[tool.name] = mcp_tool

    def _make_tool(self, server_name: str, mcp_tool: Any) -> StructuredTool:
        session = self._sessions[server_name]
        model = _build_args_model(
            mcp_tool.name, getattr(mcp_tool, "inputSchema", None)
        )
        tool_name = mcp_tool.name
        description = (
            mcp_tool.description
            or f"MCP tool '{tool_name}' from server '{server_name}'."
        )

        def _invoke(**kwargs):
            # Route the coroutine onto the manager's dedicated event loop so the
            # MCP session (created there) is always invoked on its own loop.
            # ``call_tool`` takes the tool arguments as a raw dict (not wrapped).
            coro = session.call_tool(tool_name, arguments=kwargs)
            return self._call_tool_sync(coro)

        return StructuredTool(
            name=tool_name,
            description=description,
            args_schema=model,
            func=_invoke,
        )

    def get_tools(
        self, server: str | None = None, names: list[str] | None = None
    ) -> list[StructuredTool]:
        """Return all tools, or a subset by server or explicit tool names."""
        if names is not None:
            return [self._tool_by_name[n] for n in names if n in self._tool_by_name]
        if server is not None:
            return [
                t for t in self._tools if self._tool_servers.get(t.name) == server
            ]
        return list(self._tools)

    def get_realtime_quote_tools(self, filter_config: dict | None = None) -> list[StructuredTool]:
        """Return a normalized realtime-quote tool for the analysts.

        Instead of exposing the raw MCP tools (whose parameter names/schemas
        vary per server and are easy for the LLM to call incorrectly -- e.g.
        omitting a required ``symbols``), this returns a single stable
        ``get_realtime_quote(symbol)`` wrapper that maps to the server's
        underlying quote tool with the correct arguments.
        """
        wrapper = self.build_realtime_quote_tool()
        return [wrapper] if wrapper else []

    @staticmethod
    def _format_call_result(res) -> str:
        """Flatten an MCP ``CallToolResult`` into a plain string for the LLM."""
        if res is None:
            return ""
        blocks = getattr(res, "content", None)
        if blocks is None:
            return str(res)
        parts = []
        for block in blocks:
            text = getattr(block, "text", None)
            parts.append(text if text is not None else str(block))
        return "\n".join(parts)

    def _call_tool_sync(self, coro, timeout: int = 120) -> str:
        """Run an MCP coroutine on the manager loop and return a string.

        On any failure (network, server error, timeout) returns an error string
        instead of raising, so a transient MCP hiccup degrades to "quote
        unavailable" rather than aborting the entire analysis run.
        """
        try:
            res = asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - surface as text to the agent
            logger.warning("MCP tool call failed: %s", exc)
            return f"[realtime quote unavailable] MCP error: {exc}"
        return self._format_call_result(res)

    def build_realtime_quote_tool(self) -> StructuredTool | None:
        """Build a normalized ``get_realtime_quote(symbol)`` wrapper tool.

        Picks the best quote/price MCP tool and adapts the single ``symbol``
        argument to that tool's expected parameters (e.g. a ``symbols`` list).
        Returns None when no suitable tool is available.
        """
        if not self._raw_tools:
            return None
        candidate = None
        for name, raw in self._raw_tools.items():
            if "quote" in name.lower():
                candidate = (name, raw)
                break
        if candidate is None:
            for name, raw in self._raw_tools.items():
                if "price" in name.lower():
                    candidate = (name, raw)
                    break
        if candidate is None:
            return None

        name, raw = candidate
        session = self._sessions[self._tool_servers[name]]
        props = (getattr(raw, "inputSchema", None) or {}).get("properties", {}) or {}

        def _build_args(symbol: str) -> dict:
            if "symbols" in props:
                return {"symbols": [symbol] if props["symbols"].get("type") == "array" else symbol}
            if "symbol" in props:
                return {"symbol": symbol}
            if "tickers" in props:
                return {"tickers": [symbol]}
            return {"symbols": [symbol]}

        def _invoke(symbol: str) -> str:
            coro = session.call_tool(name, arguments=_build_args(symbol))
            return self._call_tool_sync(coro)

        return StructuredTool(
            name="get_realtime_quote",
            description=(
                "Get the realtime market quote/price for a single ticker symbol "
                "(e.g. 'HOOD'). Returns the latest price/quote from the connected "
                "market-data server. Pass the ticker as the 'symbol' argument."
            ),
            args_schema=_build_args_model(
                "get_realtime_quote",
                {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Ticker symbol, e.g. 'HOOD'",
                        }
                    },
                    "required": ["symbol"],
                },
            ),
            func=_invoke,
        )

    def close(self) -> None:
        """Shut down servers and stop the event loop."""
        if self._loop is None:
            return
        try:
            if self._stack is not None:
                asyncio.run_coroutine_threadsafe(
                    self._stack.aclose(), self._loop
                ).result(timeout=30)
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.warning("Error closing MCP sessions: %s", exc)
        finally:
            # Close any httpx clients we built for auth (mcp 2.x http_client).
            for client in self._http_clients:
                try:
                    asyncio.run_coroutine_threadsafe(
                        client.aclose(), self._loop
                    ).result(timeout=10)
                except Exception:  # pragma: no cover
                    pass
            self._http_clients.clear()
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=10)
            self._loop = None
            self._thread = None
            self._sessions.clear()
            self._tool_servers.clear()
            self._tools = []
            self._tool_by_name.clear()
