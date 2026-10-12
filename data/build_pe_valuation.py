"""Valuation history for the P/E page: P/E, P/B, dividend yield, price and total-return index for
a set of NSE indices, month-end observations (the latest bar is the most recent trading day).

Source: the NSE index site's own backend (the same one behind niftyindices.com > Historical data).
  getpepbHistoricaldataDBtoString  -> pe, pb, divYield   (one calendar year per request)
  getHistoricaldatatabletoString   -> CLOSE
  getTotalReturnIndexString        -> TotalReturnsIndex
Implied EPS is price / P/E, computed on the page (no separate earnings source exists).

First run pulls every year since each index's first P/E; later runs refetch only the last two
calendar years and replace those months, so a weekly refresh is ~80 small requests. The output file
is both the committed cache and the dataset embedded in pe_valuation.html.

Known data limits (also printed on the page): P/E here is NSE's trailing, standalone-earnings
figure; Midcap 150 / Smallcap 250 only have P/E from 2016; Auto and Metal from 2012.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "pe_valuation_dataset.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
HEAD = {**UA, "Content-Type": "application/json; charset=utf-8", "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "https://www.niftyindices.com", "Referer": "https://www.niftyindices.com/reports/historical-data",
        "X-Requested-With": "XMLHttpRequest"}
URL = "https://www.niftyindices.com/BackPage/"
FIRST_YEAR = 1999

# key, display name, NSE names to try (the backend spells some indices differently), group
INDICES = [
    ("nifty50", "Nifty 50", ["NIFTY 50"], "Broad market"),
    ("niftynext50", "Nifty Next 50", ["NIFTY NEXT 50"], "Broad market"),
    ("nifty100", "Nifty 100", ["NIFTY 100"], "Broad market"),
    ("nifty500", "Nifty 500", ["NIFTY 500"], "Broad market"),
    ("niftymidcap150", "Nifty Midcap 150", ["NIFTY MIDCAP 150"], "Broad market"),
    ("niftysmallcap250", "Nifty Smallcap 250", ["NIFTY SMLCAP 250", "NIFTY SMALLCAP 250"], "Broad market"),
    ("niftybank", "Nifty Bank", ["NIFTY BANK"], "Sector"),
    ("niftyit", "Nifty IT", ["NIFTY IT"], "Sector"),
    ("niftypharma", "Nifty Pharma", ["NIFTY PHARMA"], "Sector"),
    ("niftyfmcg", "Nifty FMCG", ["NIFTY FMCG"], "Sector"),
    ("niftyenergy", "Nifty Energy", ["NIFTY ENERGY"], "Sector"),
    ("niftyauto", "Nifty Auto", ["NIFTY AUTO"], "Sector"),
    ("niftymetal", "Nifty Metal", ["NIFTY METAL"], "Sector"),
    ("niftypsubank", "Nifty PSU Bank", ["NIFTY PSU BANK"], "Sector"),
    ("niftyrealty", "Nifty Realty", ["NIFTY REALTY"], "Sector"),
]


def post(endpoint: str, name: str, year: int, today: dt.date) -> list | None:
    """One calendar year of rows (None = request failed, [] = no data for that year)."""
    end = min(dt.date(year, 12, 31), today)
    body = {"cinfo": "{'name':'%s','startDate':'01-Jan-%d','endDate':'%s','indexName':'%s'}"
            % (name, year, end.strftime("%d-%b-%Y"), name)}
    for attempt in range(4):
        try:
            r = requests.post(URL + endpoint, headers=HEAD, data=json.dumps(body), timeout=60)
            text = r.text.strip()
            if text.startswith("["):
                return json.loads(text)
            if text in ("", "null", "[]"):
                return []
        except Exception:
            pass
        time.sleep(2 + attempt * 2)
    return None


def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def fetch_index(key: str, names: list[str], years: range, today: dt.date) -> pd.DataFrame:
    """Daily frame (pe, pb, dy, px, tri) for the given calendar years."""
    pe_rows, name_used = [], None
    for y in years:
        got = None
        for n in ([name_used] if name_used else names):
            got = post("getpepbHistoricaldataDBtoString", n, y, today)
            if got:
                name_used = n
                break
        if got:
            pe_rows += got
    if not pe_rows:
        return pd.DataFrame()
    pe = pd.DataFrame(pe_rows)
    first_year = pd.to_datetime(pe["DATE"], format="%d %b %Y").dt.year.min()
    px_rows, tri_rows = [], []
    for y in years:
        if y < first_year:
            continue
        px_rows += post("getHistoricaldatatabletoString", name_used, y, today) or []
        tri_rows += post("getTotalReturnIndexString", name_used, y, today) or []
    pe["date"] = pd.to_datetime(pe["DATE"], format="%d %b %Y")
    d = pd.DataFrame({"pe": num(pe.set_index("date")["pe"]), "pb": num(pe.set_index("date")["pb"]),
                      "dy": num(pe.set_index("date")["divYield"])})
    d = d[~d.index.duplicated(keep="last")]
    if px_rows:
        px = pd.DataFrame(px_rows)
        px["date"] = pd.to_datetime(px["HistoricalDate"], format="%d %b %Y")
        d["px"] = num(px.set_index("date")["CLOSE"]).groupby(level=0).last()
    if tri_rows:
        tr = pd.DataFrame(tri_rows)
        tr["date"] = pd.to_datetime(tr["Date"], format="%d %b %Y")
        d["tri"] = num(tr.set_index("date")["TotalReturnsIndex"]).groupby(level=0).last()
    for c in ("px", "tri"):
        if c not in d:
            d[c] = float("nan")
    return d.sort_index()


def monthly_rows(d: pd.DataFrame) -> list[list]:
    """Last observation of each month (with a P/E and a price), as [date, pe, pb, dy, px, tri]."""
    d = d.dropna(subset=["pe", "px"])
    d = d[(d["pe"] > 0) & (d["px"] > 0)]
    if d.empty:
        return []
    last = d.groupby(d.index.to_period("M")).tail(1)
    out = []
    for date, r in last.iterrows():
        out.append([date.strftime("%Y-%m-%d"), round(float(r.pe), 2),
                    None if pd.isna(r.pb) else round(float(r.pb), 2),
                    None if pd.isna(r.dy) else round(float(r.dy), 2),
                    round(float(r.px), 2), None if pd.isna(r.tri) else round(float(r.tri), 2)])
    return out


def main() -> None:
    today = dt.date.today()
    prev = {}
    if OUT.exists():
        prev = {i["key"]: i for i in json.loads(OUT.read_text(encoding="utf-8"))["indices"]}
    this_year = today.year

    def work(spec):
        key, name, names, group = spec
        old = prev.get(key, {}).get("rows", [])
        years = range(max(FIRST_YEAR, this_year - 1), this_year + 1) if old else range(FIRST_YEAR, this_year + 1)
        d = fetch_index(key, names, years, today)
        new = monthly_rows(d)
        if not new and not old:
            return key, None, f"{name}: no data returned"
        if old and new:
            cut = new[0][0][:7]
            rows = [r for r in old if r[0][:7] < cut] + new
        else:
            rows = new or old
        return key, dict(key=key, name=name, group=group, rows=rows), None

    results = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for key, item, err in ex.map(work, INDICES):
            if item is None:
                print(f"  WARNING: {err}")
                if key in prev:
                    results[key] = prev[key]
                continue
            results[key] = item
            rows = item["rows"]
            print(f"  {item['name']:20s} {rows[0][0]} -> {rows[-1][0]}  {len(rows):4d} months  P/E now {rows[-1][1]}", flush=True)

    indices = [results[k] for k, *_ in INDICES if k in results]
    if not indices:
        raise RuntimeError("no index returned data")
    as_of = max(i["rows"][-1][0] for i in indices)
    out = dict(as_of=as_of, built=today.isoformat(),
               source="NSE index site (niftyindices.com) - trailing P/E on standalone earnings; price and total-return index",
               indices=indices)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"\nWrote {OUT.name} ({OUT.stat().st_size / 1024:.0f} KB, {len(indices)} indices, as of {as_of})")


if __name__ == "__main__":
    main()
