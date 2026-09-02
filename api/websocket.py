"""WebSocket connection manager for real-time analysis updates."""

import json
from contextlib import suppress

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections per run_id."""

    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = {}

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        if run_id not in self.connections:
            self.connections[run_id] = set()
        self.connections[run_id].add(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if run_id in self.connections:
            self.connections[run_id].discard(websocket)
            if not self.connections[run_id]:
                del self.connections[run_id]

    async def broadcast(self, run_id: str, event: dict) -> None:
        """Send an event to all connections for a run_id."""
        if run_id not in self.connections:
            return
        message = json.dumps(event)
        dead = set()
        for ws in self.connections[run_id]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(run_id, ws)

    async def send_error(self, run_id: str, message: str) -> None:
        """Send an error event and close connections."""
        await self.broadcast(run_id, {"type": "error", "message": message})
        # Close all connections after error
        if run_id in self.connections:
            for ws in list(self.connections[run_id]):
                with suppress(Exception):
                    await ws.close()
            del self.connections[run_id]


# Event type constants
class EventType:
    AGENT_STATUS = "agent_status"
    TOOL_CALL = "tool_call"
    REPORT_SECTION = "report_section"
    STATS = "stats"
    COMPLETE = "complete"
    ERROR = "error"


def make_agent_status_event(agent: str, status: str) -> dict:
    return {"type": EventType.AGENT_STATUS, "agent": agent, "status": status}


def make_tool_call_event(name: str, args: dict) -> dict:
    return {"type": EventType.TOOL_CALL, "name": name, "args": args}


def make_report_section_event(section: str, content: str) -> dict:
    return {"type": EventType.REPORT_SECTION, "section": section, "content": content}


def make_stats_event(
    llm_calls: int,
    tool_calls: int,
    tokens_in: int,
    tokens_out: int
) -> dict:
    return {
        "type": EventType.STATS,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def make_complete_event(run_id: str) -> dict:
    return {"type": EventType.COMPLETE, "run_id": run_id}


def make_error_event(message: str) -> dict:
    return {"type": EventType.ERROR, "message": message}


# Global connection manager instance
manager = ConnectionManager()
