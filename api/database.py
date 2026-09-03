"""SQLite database operations for TradingAgents Web API."""

import json
import os
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

DB_PATH = os.getenv("TRADINGAGENTS_DB_PATH", "./data/tradingagents.db")


async def init_db() -> None:
    """Initialize the database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                analysis_date TEXT NOT NULL,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                report_json TEXT,
                error_message TEXT,
                final_state_json TEXT,
                report_path TEXT
            )
        """)
        # Migration: add columns for older databases that predate them.
        cols = await db.execute_fetchall("PRAGMA table_info(runs)")
        existing = {c[1] for c in cols}
        if "final_state_json" not in existing:
            await db.execute("ALTER TABLE runs ADD COLUMN final_state_json TEXT")
        if "report_path" not in existing:
            await db.execute("ALTER TABLE runs ADD COLUMN report_path TEXT")
        if "started_at" not in existing:
            await db.execute("ALTER TABLE runs ADD COLUMN started_at TEXT")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)
        """)
        await db.commit()


async def create_run(
    ticker: str,
    analysis_date: str,
    config: dict[str, Any]
) -> str:
    """Create a new analysis run record. Returns the run ID."""
    run_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO runs (id, ticker, analysis_date, config_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, ticker, analysis_date, json.dumps(config), "pending", now)
        )
        await db.commit()
    return run_id


async def update_run_status(
    run_id: str,
    status: str,
    report: dict[str, Any] | None = None,
    error: str | None = None,
    final_state: dict[str, Any] | None = None,
    report_path: str | None = None,
    started_at: str | None = None,
) -> None:
    """Update run status, optionally with final report or error."""
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if report is not None:
            await db.execute(
                """
                UPDATE runs SET status = ?, completed_at = ?, report_json = ?,
                    final_state_json = ?, report_path = ?
                WHERE id = ?
                """,
                (
                    status,
                    now,
                    json.dumps(report),
                    json.dumps(final_state) if final_state is not None else None,
                    report_path,
                    run_id,
                )
            )
        elif error is not None:
            await db.execute(
                """
                UPDATE runs SET status = ?, completed_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, now, error, run_id)
            )
        else:
            if started_at is not None:
                await db.execute(
                    """
                    UPDATE runs SET status = ?, started_at = ? WHERE id = ?
                    """,
                    (status, started_at, run_id)
                )
            else:
                await db.execute(
                    """
                    UPDATE runs SET status = ? WHERE id = ?
                    """,
                    (status, run_id)
                )
        await db.commit()


async def get_run(run_id: str) -> dict[str, Any] | None:
    """Get a single run by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
    return None


async def get_run_report(run_id: str) -> dict[str, Any] | None:
    """Get the final report for a run."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT report_json FROM runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row["report_json"]:
                return json.loads(row["report_json"])
    return None


async def list_runs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None
) -> list[dict[str, Any]]:
    """List runs with pagination and optional status filter."""
    query = "SELECT id, ticker, analysis_date, status, created_at, completed_at, error_message FROM runs"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def count_runs(status: str | None = None) -> int:
    """Count total runs, optionally filtered by status."""
    query = "SELECT COUNT(*) FROM runs"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)

    async with aiosqlite.connect(DB_PATH) as db, db.execute(query, params) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0
