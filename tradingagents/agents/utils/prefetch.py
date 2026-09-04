"""Deterministic data pre-fetch, tagging, and confirmation for the analysts.

The market / news / fundamentals analysts used to rely on the LLM driving a
tool-calling loop and then *spontaneously* writing prose; when the model never
wrote prose the heuristic rescue logic either leaked raw tool output into the
report or hardcoded an "inconclusive" string, discarding data that WAS fetched.

This module replaces that with the pre-fetch pattern proven by the sentiment
analyst (rebuild of #796): in code, call each data tool's ``.func`` directly,
classify each result as received / empty / unavailable / error, and render the
non-empty ones into tagged ``<start_of_X>/<end_of_X>`` prompt blocks. The LLM
is then invoked once (no tool loop) with instructions to only cite the tagged
blocks. The classification is returned as ``sources_received`` so the next
stage has an auditable confirmation that data was captured and passed on.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Sentinel markers that some vendors return instead of real data. A block whose
# content contains one of these is treated as *unavailable* rather than *ok* so
# a downstream consumer never mistakes a placeholder for a real value.
UNAVAILABLE_MARKERS = (
    "[realtime quote unavailable]",
    "NO_DATA_AVAILABLE",
    "DATA_UNAVAILABLE",
    "<unavailable>",
)


@dataclass(frozen=True)
class DataSource:
    """A single data-block pre-fetch intent.

    ``label`` is the short human-readable source name surfaced in the
    ``sources_received`` confirmation line and used as the tagged-block key.
    ``fetch`` is a zero-arg callable that runs the underlying data tool and
    returns a string (already degrade-gracefully wrapped by its caller where
    required — typically ``get_foo.func(symbol, date)``).
    """

    label: str
    fetch: Callable[[], str]


def fetch_sources(sources: list[DataSource]) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch every :class:`DataSource` once, returning ``(blocks, statuses)``.

    ``blocks`` maps each label to its usable non-empty, non-sentinel text and is
    what gets rendered into the tagged prompt blocks. ``statuses`` maps *every*
    requested label to ``ok / empty / unavailable / error`` — the auditable
    ``sources_received`` confirmation of what was captured and passed on. A
    single fetch drives both, so vendors are never called twice and a failing
    source can never abort the rest of the analyst.
    """
    blocks: dict[str, str] = {}
    statuses: dict[str, str] = {}
    for source in sources:
        try:
            text = (source.fetch() or "").strip()
        except Exception:  # noqa: BLE001 - a failed vendor must not abort the analyst
            statuses[source.label] = "error"
            continue
        if not text:
            statuses[source.label] = "empty"
            continue
        if any(marker in text for marker in UNAVAILABLE_MARKERS):
            statuses[source.label] = "unavailable"
            continue
        statuses[source.label] = "ok"
        blocks[source.label] = text
    return blocks, statuses


def render_tagged_blocks(blocks: Mapping[str, str]) -> str:
    """Render the received blocks into explicit tagged prompt blocks.

    Each block is wrapped in ``<start_of_<label>>`` / ``<end_of_<label>>``
    markers so the LLM has a hard, machine-delineated contract for what data is
    in scope and can be asked to only cite those blocks.
    """
    parts = [f"<start_of_{label}>\n{text}\n<end_of_{label}>" for label, text in blocks.items()]
    return "\n\n".join(parts)


def format_sources_received(confirmations: Mapping[str, str]) -> str:
    """Render a ``sources_received`` confirmation line for the report.

    Example: ``> Data sources received: market_snapshot=ok, news=ok,
    global_news=unavailable`` — an auditable record of what was captured and
    passed to the next LLM.
    """
    if not confirmations:
        return "> Data sources received: none"
    rendered = ", ".join(f"{label}={status}" for label, status in confirmations.items())
    return f"> Data sources received: {rendered}"


__all__ = [
    "DataSource",
    "fetch_sources",
    "render_tagged_blocks",
    "format_sources_received",
    "UNAVAILABLE_MARKERS",
]
