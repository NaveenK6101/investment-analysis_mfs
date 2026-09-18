"""Shared fetch-with-cache logic for every build_*.py script.

Both APIs this project uses (mfapi.in for fund NAVs, Yahoo's chart API for
indices/crypto/metals/FX) return the FULL history in one call every time -
neither supports "just give me what changed since date X." So there is no
such thing as fetching only "this month's new rows" from the API side; the
API call itself is always the same size regardless of how much has changed.

Given that, the useful refresh policy isn't about skipping API calls (that
would just mean not detecting new NAVs, which is the entire point of a
refresh) - it's about ROBUSTNESS: always attempt a fresh full fetch, but
if it fails (network hiccup, a scheme temporarily erroring, mfapi.in being
briefly down), fall back to the existing cache instead of losing that
fund's data or crashing the whole pipeline. On success, the fresh fetch
(which already contains the complete, correct series - old rows included)
simply replaces the cache outright, since re-fetched historical NAVs are
the same immutable facts they always were.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_mfapi_weekly(cache_path: Path, scheme_code: int) -> tuple[pd.Series, bool]:
    """Fund NAV from mfapi.in, weekly (Friday) resampled. Returns (series, refreshed)."""
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{scheme_code}", headers=UA, timeout=30)
        r.raise_for_status()
        payload = r.json()
        rows = [{"date": pd.to_datetime(d["date"], format="%d-%m-%Y"), "nav": float(d["nav"])}
                for d in payload["data"]]
        if not rows:
            raise ValueError("empty NAV history")
        df = pd.DataFrame(rows).sort_values("date")
        df.to_csv(cache_path, index=False)
        return df.set_index("date")["nav"].resample("W-FRI").last(), True
    except Exception as e:
        if cache_path.exists() and cache_path.stat().st_size > 500:
            print(f"    fetch failed ({e}) - using cached {cache_path.name}")
            df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
            return df["nav"].resample("W-FRI").last(), False
        raise


def fetch_yahoo_weekly(cache_path: Path, ticker: str, value_col: str = "close",
                        range_: str = "15y") -> tuple[pd.Series, bool]:
    """Index/crypto/metal/FX price from Yahoo's chart API, weekly (Friday) resampled."""
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"interval": "1d", "range": range_}, headers=UA, timeout=30,
        )
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
        s = pd.Series(
            {pd.Timestamp.fromtimestamp(t).normalize(): c for t, c in zip(ts, close) if c is not None}
        ).sort_index()
        if s.empty:
            raise ValueError("empty price history")
        pd.DataFrame({"date": s.index, value_col: s.values}).to_csv(cache_path, index=False)
        return s.resample("W-FRI").last(), True
    except Exception as e:
        if cache_path.exists() and cache_path.stat().st_size > 500:
            print(f"    fetch failed ({e}) - using cached {cache_path.name}")
            df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
            return df[value_col].resample("W-FRI").last(), False
        raise


def fresh_cutoff(weeks_back: int = 3) -> dt.date:
    """Replaces every build script's old hardcoded FRESH_CUTOFF date. A scheme whose
    latest NAV is older than this is presumed wound up, merged, or renamed under a
    new code - same staleness check as before, just computed relative to today so
    it keeps working on every future run without hand-editing a date."""
    return dt.date.today() - dt.timedelta(weeks=weeks_back)
