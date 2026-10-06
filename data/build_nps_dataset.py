"""NPS (National Pension System) Tier I schemes: Equity (E), Corporate Bond (C)
and Government Bond (G), one category each, ~10 pension fund managers per class.

Source: npsnav.in's free API (/api/latest for the scheme list, /api/historical/{code}
for daily NAVs). It states that it republishes Protean CRA's official NAVs; Protean
itself has no bulk API. It is a one-person site, so each scheme's history is cached in
nav_all/nps_{code}.csv and the cache is used if a fetch fails (same policy as mfapi.in).

Scope (chosen with the user, 2026-10-06): Tier I only. Left out on purpose:
  - Tier II: near-duplicates of Tier I.
  - Class A (alternative assets): every manager shows a ~50-58% one-week fall on
    2026-01-23 that never recovers - a real write-down or a feed error, unverified.
  - Central/State Govt, NPS Lite, APY, UPS, Tax Saver, Vatsalya, and the new
    multiple-scheme-framework funds (Smart Retirement, Growth Plus, ...): not choosable
    by a private subscriber, different products, or only ~1 year of history.

Data cleaning (checked against the raw series before writing this): the feed has
single-day garbage NAVs that revert the next day - e.g. every scheme on 2016-11-04 and
2020-10-02, the equity schemes at 26.16 vs ~19.2 on 2020-04-02, a Sunday point on
2025-04-06 - which would otherwise show up as 8-11% weekly moves in a bond scheme.
drop_spike_reverts() removes a point only if it moves more than a threshold AND reverses
most of that move on the next observation, so genuine multi-day moves (the March 2020
crash) are untouched.

Benchmarks: equity defaults to Nifty 500 (set in merge_datasets.py). We have no Indian
bond index, so bond classes use a peer average instead: an equal-weight composite of the
managers that existed by 2014 (common start = the youngest of them), one per class
(npspeer_e/c/g). "Excess" there means "better or worse than the average manager".
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from data_fetch_utils import UA, fresh_cutoff

BASE = Path(r"C:\Users\Naveen\Desktop\Naveen_imp\investment\data")
NAV_DIR = BASE / "nav_all"
NAV_DIR.mkdir(exist_ok=True)
API = "https://npsnav.in/api"

SCHEME_RE = re.compile(r"SCHEME ([ECG]) - TIER I( POP)?$")
CLASSES = {
    "E": {"category": "NPS Equity", "label": "Equity (E)", "peer_key": "npspeer_e"},
    "C": {"category": "NPS Corp Bond", "label": "Corporate Bond (C)", "peer_key": "npspeer_c"},
    "G": {"category": "NPS Govt Bond", "label": "Govt Bond (G)", "peer_key": "npspeer_g"},
}
SPIKE_THRESHOLD = {"E": 0.05, "C": 0.02, "G": 0.02}
PEER_STARTED_BY = pd.Timestamp("2014-01-01")
# The rest of the page starts in Sep 2011. Keeping NPS back to 2009 would stretch the shared
# date axis by ~130 weeks and pad every other fund row with nulls (+0.45 MB) for years no
# window uses, so values are trimmed here; real inception dates are kept in inception_label.
AXIS_START = pd.Timestamp("2011-09-30")
MIN_POINTS = 100

PFM_SHORT = {
    "SBI": "SBI", "UTI": "UTI", "LIC": "LIC", "KOTAK MAHINDRA": "Kotak", "ICICI": "ICICI Pru",
    "HDFC": "HDFC", "ADITYA BIRLA SUNLIFE": "Aditya Birla SL", "TATA": "Tata", "AXIS": "Axis",
    "DSP": "DSP", "MAX LIFE": "Max Life",
}


def pfm_short(pfm_name: str) -> str:
    base = re.sub(r"^NPS TRUST[- ]*A/C[- ]*", "", pfm_name.upper()).split(" PENSION")[0].strip()
    return PFM_SHORT.get(base, base.title())


def get_json(url: str):
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    return r.json()


def load_scheme_list() -> list[dict]:
    cache = NAV_DIR / "nps_schemes.json"
    try:
        rows = get_json(f"{API}/latest")["data"]
        if not rows:
            raise ValueError("empty scheme list")
        cache.write_text(json.dumps(rows), encoding="utf-8")
        return rows
    except Exception as e:
        if cache.exists():
            print(f"  scheme list fetch failed ({e}) - using cached nps_schemes.json")
            return json.loads(cache.read_text(encoding="utf-8"))
        raise


def fetch_history(code: str) -> pd.Series:
    cache = NAV_DIR / f"nps_{code}.csv"
    last_err = None
    for attempt in range(3):
        try:
            data = get_json(f"{API}/historical/{code}")["data"]
            if not data:
                raise ValueError("empty NAV history")
            s = pd.Series({pd.to_datetime(d["date"], format="%d-%m-%Y"): float(d["nav"]) for d in data}).sort_index()
            s.rename_axis("date").rename("nav").to_csv(cache)
            return s
        except Exception as e:
            last_err = e
            time.sleep(2)
    if cache.exists() and cache.stat().st_size > 500:
        print(f"    {code}: fetch failed ({last_err}) - using cached {cache.name}")
        df = pd.read_csv(cache, parse_dates=["date"]).set_index("date")["nav"]
        return df.sort_index()
    raise RuntimeError(f"{code}: fetch failed and no cache ({last_err})")


def drop_spike_reverts(s: pd.Series, thr: float) -> tuple[pd.Series, int]:
    """Drop single observations that jump by more than thr and mostly reverse next."""
    s = s.copy()
    dropped = 0
    for _ in range(2):  # second pass catches an error sitting next to another one
        r1 = s / s.shift(1) - 1
        r2 = s.shift(-1) / s - 1
        net = s.shift(-1) / s.shift(1) - 1
        bad = (r1.abs() > thr) & (r2.abs() > thr) & (r1 * r2 < 0) & (net.abs() < 0.5 * r1.abs())
        if not bad.any():
            break
        dropped += int(bad.sum())
        s = s[~bad]
    return s, dropped


def main() -> None:
    cutoff = pd.Timestamp(fresh_cutoff())
    rows = load_scheme_list()
    picked = []
    for r in rows:
        m = SCHEME_RE.search(r["Scheme Name"].upper().strip())
        if m:
            picked.append({**r, "cls": m.group(1)})
    print(f"  {len(picked)} Tier I E/C/G schemes listed")

    weekly: dict[str, pd.Series] = {}
    first_nav: dict[str, str] = {}
    meta: dict[str, dict] = {}
    skipped = []
    for r in picked:
        code, cls = r["Scheme Code"], r["cls"]
        s = fetch_history(code)
        s, dropped = drop_spike_reverts(s, SPIKE_THRESHOLD[cls])
        if len(s) < MIN_POINTS or s.index[-1] < cutoff:
            skipped.append((r["Scheme Name"], f"last NAV {s.index[-1].date()}, {len(s)} points"))
            continue
        key = f"nps_{code.lower()}"
        weekly[key] = s.resample("W-FRI").last().dropna()
        first_nav[key] = s.index[0].strftime("%Y-%m-%d")
        name = f"NPS {pfm_short(r['PFM Name'])} - {CLASSES[cls]['label']}, Tier I"
        meta[key] = {"key": key, "name": name, "category": CLASSES[cls]["category"], "cls": cls}
        print(f"  {name:48s} {s.index[0].date()} -> {s.index[-1].date()}  {len(s):5d} pts"
              f"{'  (dropped %d bad NAV point%s)' % (dropped, 's' if dropped != 1 else '') if dropped else ''}")
        time.sleep(0.3)
    if skipped:
        print("  skipped:", skipped)

    weekly = {k: s[s.index >= AXIS_START] for k, s in weekly.items()}
    all_dates = sorted(set().union(*[s.index for s in weekly.values()]))
    idx = pd.DatetimeIndex(all_dates)
    date_strs = [d.strftime("%Y-%m-%d") for d in idx]
    frame = pd.DataFrame({k: s.reindex(idx) for k, s in weekly.items()})

    funds = []
    for key, m in meta.items():
        vals = [None if pd.isna(v) else round(float(v), 4) for v in frame[key]]
        funds.append({"key": key, "name": m["name"], "category": m["category"], "values": vals,
                      "inception_label": f"Inception: {first_nav[key]}"})

    benchmarks = []
    for cls, spec in CLASSES.items():
        keys = [k for k, m in meta.items() if m["cls"] == cls and frame[k].first_valid_index() <= PEER_STARTED_BY]
        sub = frame[keys].ffill(limit=2)
        start = sub.dropna().index[0]
        sub = sub.loc[start:]
        comp = (100 * sub / sub.iloc[0]).mean(axis=1, skipna=False)
        vals = [None] * (len(idx) - len(comp)) + [None if pd.isna(v) else round(float(v), 4) for v in comp]
        benchmarks.append({"key": spec["peer_key"], "name": f"NPS {spec['label']} peer average", "values": vals})
        print(f"  peer average {cls}: {len(keys)} managers, common start {start.date()}, latest level {vals[-1]}")

    out = {"dates": date_strs, "funds": funds, "benchmarks": benchmarks}
    with open(BASE / "nps_dataset.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"\nWrote nps_dataset.json ({len(funds)} schemes, {len(benchmarks)} peer benchmarks, {len(date_strs)} weeks)")


if __name__ == "__main__":
    main()
