"""The latest trading day's bar must not silently vanish (#1201).

yfinance can return the newest in-range bar with a NaN close (an unsettled or
glitched session). The old path parsed dates without normalizing timezone and
dropped every NaN-close row before applying the curr_date cutoff, so the latest
bar disappeared and the previous trading day looked like the latest. Now dates
are normalized. A latest in-range bar with no close is degraded gracefully —
the unsettled trailing bar is dropped and the previous settled bar is served —
so the analysis keeps running rather than aborting. Only when *every* in-range
bar is un-priced does load_ohlcv raise.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import stockstats_utils as su
from tradingagents.dataflows.symbol_utils import NoMarketDataError

# --- date normalization -----------------------------------------------------

@pytest.mark.unit
def test_normalize_dates_strips_tz_and_normalizes_to_midnight():
    aware = pd.Series(pd.to_datetime(
        ["2026-05-08 09:30:00-04:00", "2026-05-09 16:00:00-04:00"]
    ))
    out = su._normalize_dates(aware)
    assert out.dt.tz is None
    assert list(out) == [pd.Timestamp("2026-05-08"), pd.Timestamp("2026-05-09")]


@pytest.mark.unit
def test_normalize_dates_leaves_naive_dates_at_midnight():
    naive = pd.Series(pd.to_datetime(["2026-05-08 14:30:00", "2026-05-09 00:00:00"]))
    out = su._normalize_dates(naive)
    assert out.dt.tz is None
    assert list(out) == [pd.Timestamp("2026-05-08"), pd.Timestamp("2026-05-09")]


@pytest.mark.unit
def test_normalize_dates_handles_mixed_dst_offsets():
    # 5y of US bars span DST; via a cache CSV they arrive as mixed-offset
    # strings, which pd.to_datetime can't unify. Each keeps its own local date.
    mixed = pd.Series([
        "2026-01-08 00:00:00-05:00",  # EST
        "2026-06-08 00:00:00-04:00",  # EDT
        "not-a-date",                 # -> NaT
    ])
    out = su._normalize_dates(mixed)
    assert out.iloc[0] == pd.Timestamp("2026-01-08")
    assert out.iloc[1] == pd.Timestamp("2026-06-08")
    assert pd.isna(out.iloc[2])


@pytest.mark.unit
def test_normalize_dates_keeps_positive_offset_local_date():
    # A Tokyo bar at local midnight (+09:00) must stay on its own calendar day,
    # not shift to the previous UTC day (which utc=True parsing would cause).
    jst = pd.Series(["2026-05-08 00:00:00+09:00"])
    assert su._normalize_dates(jst).iloc[0] == pd.Timestamp("2026-05-08")


# --- fill vs guard responsibilities ----------------------------------------

@pytest.mark.unit
def test_clean_dataframe_keeps_nan_close_for_the_caller_to_inspect():
    # _clean_dataframe normalizes but no longer drops the NaN close itself.
    df = pd.DataFrame({"Date": ["2026-05-08", "2026-05-09"], "Close": [100.0, float("nan")]})
    cleaned = su._clean_dataframe(df)
    assert len(cleaned) == 2
    assert pd.isna(cleaned["Close"].iloc[-1])


@pytest.mark.unit
def test_fill_price_gaps_drops_nan_close_rows():
    df = pd.DataFrame({"Date": pd.to_datetime(["2026-05-07", "2026-05-08"]),
                       "Close": [float("nan"), 100.0]})
    filled = su._fill_price_gaps(df)
    assert len(filled) == 1
    assert filled["Close"].iloc[0] == 100.0


# --- load_ohlcv end-to-end (with a mocked cache read) -----------------------

def _run_load(monkeypatch, tmp_path, frame, curr_date):
    """Drive load_ohlcv against a pre-seeded cache frame (no network)."""
    monkeypatch.setattr(su, "get_config", lambda: {"data_cache_dir": str(tmp_path)})
    today = pd.Timestamp(curr_date)
    monkeypatch.setattr(su.pd.Timestamp, "today", staticmethod(lambda: today))
    start = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    (tmp_path / f"AAPL-YFin-data-{start}-{end}.csv").write_text(frame.to_csv(index=False))

    def _fail_download(*a, **k):
        raise AssertionError("should use the seeded cache, not download")
    monkeypatch.setattr(su.yf, "download", _fail_download)
    monkeypatch.setattr(su, "_assert_ohlcv_not_stale", lambda *a, **k: None)
    return su.load_ohlcv("AAPL", curr_date)


@pytest.mark.unit
def test_latest_in_range_nan_close_degrades_to_previous_settled(monkeypatch, tmp_path):
    # Newest bar (the curr_date) has a real Open/High but no close — an unsettled
    # in-progress session. Degrade gracefully: drop it and serve the previous
    # settled bar instead of raising and aborting the run.
    frame = pd.DataFrame({
        "Date": ["2026-05-07", "2026-05-08"],
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, float("nan")], "Volume": [1_000_000, 1_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert out["Close"].iloc[-1] == 100.5
    assert out["Date"].iloc[-1] == pd.Timestamp("2026-05-07")
    assert (out["Date"] == pd.Timestamp("2026-05-08")).sum() == 0


@pytest.mark.unit
def test_unsettled_latest_bar_flags_recency_for_transparency(monkeypatch, tmp_path):
    # When the degrade-to-previous-session path is taken because the requested
    # date's bar is unsettled, the returned frame must carry a marker so callers
    # can tell the user the data is a day prior to the current date.
    frame = pd.DataFrame({
        "Date": ["2026-05-07", "2026-05-08"],
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, float("nan")], "Volume": [1_000_000, 1_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert out.attrs["latest_unsettled_date"] == "2026-05-08"
    assert out.attrs["served_latest_date"] == "2026-05-07"


@pytest.mark.unit
def test_no_recency_flag_when_curr_date_is_settled(monkeypatch, tmp_path):
    # When the requested date's bar is fully settled, no recency flag is set.
    frame = pd.DataFrame({
        "Date": ["2026-05-07", "2026-05-08"],
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, 101.5], "Volume": [1_000_000, 1_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert "latest_unsettled_date" not in out.attrs
    assert "served_latest_date" not in out.attrs


@pytest.mark.unit
def test_get_stock_stats_discloses_unsettled_instead_of_fake_trading_day(monkeypatch):
    # StockstatsUtils.get_stock_stats must not return the misleading
    # "Not a trading day" string when the real reason today's bar is absent is
    # that the session is unsettled; it must name the prior settled date.
    monkeypatch.setattr(su, "load_ohlcv", lambda s, d: _seeded_frame())
    out = su.StockstatsUtils.get_stock_stats("HOOD", "rsi", "2026-05-08")
    assert "not yet settled" in out
    assert "2026-05-08" in out
    assert "2026-05-07" in out


def _seeded_frame():
    # A frame whose latest bar (curr_date) was dropped as unsettled, carrying the
    # recency flag that load_ohlcv would set.
    frame = pd.DataFrame({
        "Date": pd.to_datetime(["2026-05-07", "2026-05-08"]),
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, float("nan")], "Volume": [1_000_000, 1_000_000],
    })
    frame = frame.dropna(subset=["Close"]).reset_index(drop=True)
    frame.attrs["latest_unsettled_date"] = "2026-05-08"
    frame.attrs["served_latest_date"] = "2026-05-07"
    return frame


@pytest.mark.unit
def test_phantom_unpriced_trailing_bar_drops_to_previous_settled(monkeypatch, tmp_path):
    # Newest in-range bar has no price at all (all of Open/High/Low/Close NaN —
    # a phantom/in-progress row yfinance emits today with volume only). It carries
    # no price signal, so it is dropped and the previous settled bar is served.
    frame = pd.DataFrame({
        "Date": ["2026-05-07", "2026-05-08"],
        "Open": [100.0, float("nan")], "High": [101.0, float("nan")],
        "Low": [99.0, float("nan")], "Close": [100.5, float("nan")],
        "Volume": [1_000_000, 2_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert out["Close"].iloc[-1] == 100.5
    assert out["Date"].iloc[-1] == pd.Timestamp("2026-05-07")
    assert (out["Date"] == pd.Timestamp("2026-05-08")).sum() == 0
    # The requested day's bar is unpriced, so the recency flag is set too.
    assert out.attrs["latest_unsettled_date"] == "2026-05-08"
    assert out.attrs["served_latest_date"] == "2026-05-07"


@pytest.mark.unit
def test_all_unpriced_raises_no_settled_bar(monkeypatch, tmp_path):
    # Every in-range bar is un-priced -> there is no usable bar, so raise rather
    # than returning an empty frame downstream.
    frame = pd.DataFrame({
        "Date": ["2026-05-07", "2026-05-08"],
        "Open": [float("nan"), float("nan")], "High": [float("nan"), float("nan")],
        "Low": [float("nan"), float("nan")], "Close": [float("nan"), float("nan")],
        "Volume": [1_000_000, 2_000_000],
    })
    with pytest.raises(NoMarketDataError, match="no settled OHLCV bar"):
        _run_load(monkeypatch, tmp_path, frame, "2026-05-08")


@pytest.mark.unit
def test_older_nan_close_row_is_still_dropped(monkeypatch, tmp_path):
    # A stale gap mid-series is dropped; the valid latest bar is served.
    frame = pd.DataFrame({
        "Date": ["2026-05-06", "2026-05-07", "2026-05-08"],
        "Open": [100.0, 101.0, 102.0], "High": [101.0, 102.0, 103.0],
        "Low": [99.0, 100.0, 101.0],
        "Close": [100.5, float("nan"), 102.5], "Volume": [1_000_000, 1_000_000, 1_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert out["Close"].iloc[-1] == 102.5
    assert (out["Date"] == pd.Timestamp("2026-05-07")).sum() == 0  # the NaN row is gone


@pytest.mark.unit
def test_tz_aware_latest_bar_is_kept_at_the_cutoff(monkeypatch, tmp_path):
    # A tz-aware/intraday latest bar on the cutoff day must not be filtered out
    # by a naive-vs-aware comparison.
    frame = pd.DataFrame({
        "Date": ["2026-05-07 09:30:00-04:00", "2026-05-08 09:30:00-04:00"],
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, 101.5], "Volume": [1_000_000, 1_000_000],
    })
    out = _run_load(monkeypatch, tmp_path, frame, "2026-05-08")
    assert out["Close"].iloc[-1] == 101.5
    assert out["Date"].iloc[-1] == pd.Timestamp("2026-05-08")
