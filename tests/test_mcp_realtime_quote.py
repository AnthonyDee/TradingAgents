"""Tests for the Robinhood MCP realtime-quote integration.

Covers the durable OAuth token provider/refresh, the httpx auth flow that
injects and refreshes the bearer token, the normalized ``get_realtime_quote``
wrapper, and graceful degradation when the MCP server is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import httpx as real_httpx
import pytest

from tradingagents.mcp.client import (
    MCPClientManager,
    RobinhoodTokenAuth,
    _OAuthTokenProvider,
    _derive_token_url,
)


def _running_loop():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


@pytest.fixture
def loop():
    l = _running_loop()
    yield l
    l.call_soon_threadsafe(l.stop)


def _fake_store(tmp_path, access="AT0", refresh="RT0", expired=False,
                client_id="CID", server_url="https://agent.robinhood.com/mcp/trading"):
    exp = "2020-01-01T00:00:00Z" if expired else "2999-01-01T00:00:00Z"
    p = tmp_path / "mcp-auth.json"
    p.write_text(json.dumps({
        "robinhood-trading": {
            "tokens": {"accessToken": access, "refreshToken": refresh,
                       "expiresAt": exp, "scope": "x"},
            "clientInfo": {"clientId": client_id},
            "serverUrl": server_url,
        }
    }))
    return str(p)


@pytest.mark.unit
class TestTokenUrlDerivation:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://agent.robinhood.com/mcp/trading",
             "https://agent.robinhood.com/oauth2/token"),
            ("https://api.robinhood.com/mcp/x",
             "https://api.robinhood.com/oauth2/token"),
            ("", ""),
        ],
    )
    def test_derive(self, url, expected):
        assert _derive_token_url(url) == expected


@pytest.mark.unit
class TestOAuthTokenProvider:
    def test_load_from_store(self, tmp_path):
        prov = _OAuthTokenProvider(
            token_url="https://x/oauth2/token", client_id="CID",
            token_store_path=_fake_store(tmp_path), server_key="robinhood-trading",
        )
        assert prov.access_token == "AT0"
        assert prov.refresh_token == "RT0"
        assert not prov.is_expired()

    def test_expired_when_past(self, tmp_path):
        prov = _OAuthTokenProvider(
            token_url="x", client_id="CID",
            token_store_path=_fake_store(tmp_path, expired=True),
            server_key="robinhood-trading",
        )
        assert prov.is_expired()

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2020-01-01T00:00:00Z", True),   # past ISO -> expired
            ("2999-01-01T00:00:00Z", False),  # future ISO -> valid
            (4_000_000_000, False),           # epoch seconds (2096)
            (4_000_000_000_000, False),       # epoch milliseconds (2096)
            (None, False),                    # unknown -> optimistic
        ],
    )
    def test_is_expired_variants(self, value, expected):
        prov = _OAuthTokenProvider(
            token_url="x", client_id="CID", access_token="AT", expires_at=value
        )
        assert prov.is_expired() == expected

    def test_refresh_updates_and_writes_back(self, tmp_path):
        store = _fake_store(tmp_path, access="AT0", refresh="RT0")
        prov = _OAuthTokenProvider(
            token_url="https://x/oauth2/token", client_id="CID",
            token_store_path=store, server_key="robinhood-trading", write_back=True,
        )
        calls = {}

        class FakeResp:
            def __init__(self, b):
                self._b = b
                self.status_code = 200

            def json(self):
                return self._b

            @property
            def text(self):
                return json.dumps(self._b)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data):
                calls["url"] = url
                calls["data"] = data
                return FakeResp({"access_token": "AT1", "refresh_token": "RT1",
                                 "expires_in": 3600})

        with patch.object(real_httpx, "AsyncClient", FakeClient):
            asyncio.run(prov.refresh())

        assert prov.access_token == "AT1"
        assert prov.refresh_token == "RT1"
        assert calls["data"]["grant_type"] == "refresh_token"
        assert calls["data"]["client_id"] == "CID"
        # Refreshed tokens are persisted back to the store.
        sd = json.loads(open(store).read())
        assert sd["robinhood-trading"]["tokens"]["accessToken"] == "AT1"

    def test_refresh_failure_is_raised(self, tmp_path):
        prov = _OAuthTokenProvider(
            token_url="https://x/oauth2/token", client_id="CID",
            token_store_path=_fake_store(tmp_path), server_key="robinhood-trading",
        )

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data):
                return SimpleNamespace(status_code=401, text="invalid_grant")

        with patch.object(real_httpx, "AsyncClient", FakeClient):
            with pytest.raises(RuntimeError):
                asyncio.run(prov.refresh())


@pytest.mark.unit
class TestRobinhoodTokenAuth:
    def test_injects_bearer_header(self):
        prov = _OAuthTokenProvider(
            token_url="x", client_id="CID", access_token="ATX", refresh_token="RTX"
        )
        auth = RobinhoodTokenAuth(prov)
        req = SimpleNamespace(headers={})

        async def run():
            gen = auth.async_auth_flow(req)
            r = await gen.asend(None)
            try:
                await gen.asend(SimpleNamespace(status_code=200))
            except StopAsyncIteration:
                pass
            return r

        r = asyncio.run(run())
        assert r.headers["Authorization"] == "Bearer ATX"

    def test_401_retry_refreshes(self):
        prov = _OAuthTokenProvider(
            token_url="x", client_id="CID", access_token="ATX", refresh_token="RTX"
        )
        auth = RobinhoodTokenAuth(prov)
        calls = {}

        class FakeResp:
            def __init__(self, b):
                self._b = b
                self.status_code = 200

            def json(self):
                return self._b

            @property
            def text(self):
                return json.dumps(self._b)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data):
                calls["data"] = data
                return FakeResp({"access_token": "ATY", "refresh_token": "RTY",
                                 "expires_in": 3600})

        req = SimpleNamespace(headers={})

        async def run():
            gen = auth.async_auth_flow(req)
            r1 = await gen.asend(None)
            first_auth = r1.headers["Authorization"]  # captured before retry mutates it
            r2 = await gen.asend(SimpleNamespace(status_code=401))
            try:
                await gen.asend(SimpleNamespace(status_code=200))
            except StopAsyncIteration:
                pass
            return first_auth, r2

        with patch.object(real_httpx, "AsyncClient", FakeClient):
            first_auth, r2 = asyncio.run(run())

        # The original request carries the stale token; the retry carries the
        # freshly refreshed token (same request object is mutated on retry).
        assert first_auth == "Bearer ATX"
        assert r2.headers["Authorization"] == "Bearer ATY"
        assert calls["data"]["grant_type"] == "refresh_token"

    def test_proactive_refresh_on_expiry(self):
        prov = _OAuthTokenProvider(
            token_url="x", client_id="CID", access_token="ATZ", refresh_token="RTX",
            expires_at="2020-01-01T00:00:00Z",
        )
        auth = RobinhoodTokenAuth(prov)
        calls = {}

        class FakeResp:
            def __init__(self, b):
                self._b = b
                self.status_code = 200

            def json(self):
                return self._b

            @property
            def text(self):
                return json.dumps(self._b)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data):
                calls["data"] = data
                return FakeResp({"access_token": "ATY", "refresh_token": "RTY",
                                 "expires_in": 3600})

        req = SimpleNamespace(headers={})

        async def run():
            gen = auth.async_auth_flow(req)
            r = await gen.asend(None)  # should already be refreshed
            try:
                await gen.asend(SimpleNamespace(status_code=200))
            except StopAsyncIteration:
                pass
            return r

        with patch.object(real_httpx, "AsyncClient", FakeClient):
            r = asyncio.run(run())

        assert r.headers["Authorization"] == "Bearer ATY"
        assert calls["data"]["grant_type"] == "refresh_token"


@pytest.mark.unit
class TestRealtimeQuoteWrapper:
    def test_wrapper_builds_symbols_arg(self, loop):
        mgr = MCPClientManager({})
        mgr._loop = loop
        raw = SimpleNamespace(
            name="get_equity_quotes", description="q",
            inputSchema={"type": "object",
                         "properties": {"symbols": {"type": "array",
                                                    "items": {"type": "string"}}},
                         "required": ["symbols"]},
        )
        mgr._raw_tools["get_equity_quotes"] = raw
        captured = {}

        class FakeSession:
            async def call_tool(self, name, arguments):
                captured["name"] = name
                captured["args"] = arguments
                return SimpleNamespace(content=[SimpleNamespace(text="HOOD 716.44")])

        mgr._sessions["robinhood"] = FakeSession()
        mgr._tool_servers["get_equity_quotes"] = "robinhood"

        tool = mgr.build_realtime_quote_tool()
        assert tool.name == "get_realtime_quote"
        out = tool.func("HOOD")

        assert captured == {"name": "get_equity_quotes", "args": {"symbols": ["HOOD"]}}
        assert out == "HOOD 716.44"

    def test_wrapper_normalizes_list_type_schema(self, loop):
        # Robinhood's get_equity_quotes declares `symbols` as
        # {"type": ["null","array"]} (a list of allowed types). The wrapper must
        # normalize the list type and send an array — not a bare string — or the
        # server rejects it with `invalid params: validating "arguments"`.
        mgr = MCPClientManager({})
        mgr._loop = loop
        raw = SimpleNamespace(
            name="get_equity_quotes", description="q",
            inputSchema={"type": "object",
                         "properties": {"symbols": {"type": ["null", "array"],
                                                    "items": {"type": "string"}}},
                         "required": ["symbols"]},
        )
        mgr._raw_tools["get_equity_quotes"] = raw
        captured = {}

        class FakeSession:
            async def call_tool(self, name, arguments):
                captured["name"] = name
                captured["args"] = arguments
                return SimpleNamespace(content=[SimpleNamespace(text="HOOD 716.44")])

        mgr._sessions["robinhood"] = FakeSession()
        mgr._tool_servers["get_equity_quotes"] = "robinhood"

        tool = mgr.build_realtime_quote_tool()
        assert tool.name == "get_realtime_quote"
        out = tool.func("HOOD")

        assert captured == {"name": "get_equity_quotes", "args": {"symbols": ["HOOD"]}}
        assert out == "HOOD 716.44"

    def test_only_quote_tool_surfaced_orders_excluded(self, loop):
        mgr = MCPClientManager({})
        mgr._loop = loop
        mgr._raw_tools = {
            "get_equity_quotes": SimpleNamespace(
                name="get_equity_quotes", description="q",
                inputSchema={"type": "object",
                             "properties": {"symbols": {"type": "array"}},
                             "required": ["symbols"]}),
            "place_equity_order": SimpleNamespace(
                name="place_equity_order", description="o",
                inputSchema={"type": "object", "properties": {}}),
        }
        mgr._sessions["robinhood"] = SimpleNamespace()
        mgr._tool_servers = {"get_equity_quotes": "robinhood",
                             "place_equity_order": "robinhood"}

        tools = mgr.get_realtime_quote_tools()
        # The order/execution tool must never be surfaced to analysts.
        assert [t.name for t in tools] == ["get_realtime_quote"]

    def test_prefers_quotes_over_position_tool_listed_first(self, loop):
        # Regression (#realquote): the Robinhood server lists many "equity"
        # tools (positions, orders, option quotes). The old name-only sort
        # could bind the wrapper to get_equity_positions, whose schema has no
        # `symbols` property — so every call failed server-side with
        # `unexpected additional properties ["symbols"]` and the analysts'
        # mandated realtime-quote call degraded to "[realtime quote
        # unavailable]". Even when the position tool is listed FIRST, the
        # wrapper must bind to the genuine quotes tool.
        mgr = MCPClientManager({})
        mgr._loop = loop
        mgr._raw_tools = {
            "get_equity_positions": SimpleNamespace(
                name="get_equity_positions", description="positions",
                inputSchema={"type": "object",
                             "properties": {"account_number": {"type": "string"}},
                             "required": ["account_number"]}),
            "get_equity_quotes": SimpleNamespace(
                name="get_equity_quotes", description="quotes",
                inputSchema={"type": "object",
                             "properties": {"symbols": {"type": "array",
                                                        "items": {"type": "string"}}},
                             "required": ["symbols"]}),
        }
        captured = {}

        class FakeSession:
            async def call_tool(self, name, arguments):
                captured["name"] = name
                captured["args"] = arguments
                return SimpleNamespace(content=[SimpleNamespace(text="QQQ 707.64")])

        mgr._sessions["robinhood"] = FakeSession()
        mgr._tool_servers = {"get_equity_positions": "robinhood",
                             "get_equity_quotes": "robinhood"}

        tool = mgr.build_realtime_quote_tool()
        assert tool.name == "get_realtime_quote"
        out = tool.func("QQQ")

        assert captured == {"name": "get_equity_quotes", "args": {"symbols": ["QQQ"]}}
        assert out == "QQQ 707.64"

    def test_order_tool_listed_first_never_bound(self, loop):
        # An equity order tool (also "equity"-named, also score-0 under the old
        # sort) must never be chosen for get_realtime_quote.
        mgr = MCPClientManager({})
        mgr._loop = loop
        mgr._raw_tools = {
            "get_equity_orders": SimpleNamespace(
                name="get_equity_orders", description="orders",
                inputSchema={"type": "object",
                             "properties": {"account_number": {"type": "string"}},
                             "required": ["account_number"]}),
            "get_equity_quotes": SimpleNamespace(
                name="get_equity_quotes", description="quotes",
                inputSchema={"type": "object",
                             "properties": {"symbols": {"type": ["null", "array"]}},
                             "required": ["symbols"]}),
        }
        captured = {}

        class FakeSession:
            async def call_tool(self, name, arguments):
                captured["name"] = name
                captured["args"] = arguments
                return SimpleNamespace(content=[SimpleNamespace(text="QQQ 707.64")])

        mgr._sessions["robinhood"] = FakeSession()
        mgr._tool_servers = {"get_equity_orders": "robinhood",
                             "get_equity_quotes": "robinhood"}

        tool = mgr.build_realtime_quote_tool()
        assert tool is not None
        out = tool.func("QQQ")

        assert captured == {"name": "get_equity_quotes", "args": {"symbols": ["QQQ"]}}
        assert out == "QQQ 707.64"

    def test_index_quote_tool_without_ticker_arg_not_bound(self, loop):
        # get_index_quotes / get_option_quotes are keyed by instrument ids and
        # have no symbols/symbol/tickers property; binding the wrapper to them
        # would send a bogus `symbols` arg that the server rejects. When only
        # such tools exist, no realtime-quote wrapper is built.
        mgr = MCPClientManager({})
        mgr._loop = loop
        mgr._raw_tools = {
            "get_index_quotes": SimpleNamespace(
                name="get_index_quotes", description="index quotes",
                inputSchema={"type": "object",
                             "properties": {"instrument_ids": {"type": "array"}},
                             "required": ["instrument_ids"]}),
        }
        assert mgr.build_realtime_quote_tool() is None
        assert mgr.get_realtime_quote_tools() == []

    def test_no_tool_when_none_available(self):
        mgr = MCPClientManager({})
        assert mgr.build_realtime_quote_tool() is None
        assert mgr.get_realtime_quote_tools() == []


@pytest.mark.unit
class TestCallToolResilience:
    def test_error_returns_string(self, loop):
        mgr = MCPClientManager({})
        mgr._loop = loop

        async def boom(*a, **k):
            raise RuntimeError("connection reset")

        out = mgr._call_tool_sync(boom())
        assert out.startswith("[realtime quote unavailable]")
        assert "connection reset" in out

    def test_success_formats_result(self, loop):
        mgr = MCPClientManager({})
        mgr._loop = loop
        cap = SimpleNamespace(content=[SimpleNamespace(text="OK 1")])
        out = mgr._call_tool_sync(asyncio.sleep(0, cap))
        assert out == "OK 1"


@pytest.mark.unit
class TestBuildOAuthProvider:
    def test_from_store(self, tmp_path):
        store = tmp_path / "mcp-auth.json"
        store.write_text(json.dumps({
            "robinhood-trading": {
                "tokens": {"accessToken": "AT", "refreshToken": "RT",
                           "expiresAt": "2999-01-01T00:00:00Z"},
                "clientInfo": {"clientId": "CID"},
                "serverUrl": "https://agent.robinhood.com/mcp/trading"},
        }))
        mgr = MCPClientManager({
            "robinhood": {
                "transport": "remote",
                "url": "https://agent.robinhood.com/mcp/trading",
                "oauth": {"token_store": str(store), "server_key": "robinhood-trading"},
            }
        })
        prov = mgr._providers.get("robinhood")
        assert prov is not None
        assert prov.token_url == "https://agent.robinhood.com/oauth2/token"
        assert prov.access_token == "AT"

    def test_missing_client_id_falls_back(self, tmp_path):
        store = tmp_path / "mcp-auth.json"
        store.write_text(json.dumps({
            "robinhood-trading": {
                "tokens": {"accessToken": "AT", "refreshToken": "RT"},
                "clientInfo": {}},
        }))
        mgr = MCPClientManager({
            "robinhood": {
                "transport": "remote", "url": "x",
                "oauth": {"token_store": str(store), "server_key": "robinhood-trading"},
            }
        })
        # No client_id resolvable -> no auto-refresh provider (static token path).
        assert mgr._providers.get("robinhood") is None

    def test_missing_store_no_provider(self):
        mgr = MCPClientManager({
            "robinhood": {
                "transport": "remote", "url": "x",
                "oauth": {"token_store": "/no/such/file.json"},
            }
        })
        assert mgr._providers.get("robinhood") is None
