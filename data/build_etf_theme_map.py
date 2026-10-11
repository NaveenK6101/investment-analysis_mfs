"""ETF Theme Map: US-listed thematic/sector ETFs grouped into themes, in rupee terms, for a map of
"which themes are leading and which ETFs express them". A MAP, not a rotation signal: tested on
unseen years (2016-26) the theme-momentum edge had consistent sign but weak statistics, carried
survivorship bias, and was consumed by switching costs for every multi-theme portfolio.

Universe (committed to etf_theme_universe.json, rebuilt monthly):
  NASDAQ Trader symbol directory -> ETFs, not test issues
  - drop leveraged / inverse / short funds (by name)
  - drop bond / income / option-overlay funds (by name)
  - keep only funds >= 3 years old trading >= $1M a day (average of the last 6 months)
  - group by keywords in the fund name into themes (first match wins; broad market, country and
    style funds are NOT themes and are left out; unclassified funds are left out)
  - a theme needs >= 3 ETFs to be shown
The weekly run only re-fetches the ~400 universe members (a minute); the full scan of ~4,800 ETFs
happens when ETF_UNIVERSE_REBUILD=1 (refresh_all.py sets it on full, non --prices-only runs) or
when the universe file doesn't exist.

Returns: Yahoo adjusted close (distributions included) in USD x USDINR, monthly bars - the
current month's bar is the latest price. Theme index = equal-weight chain-linked average of the
member ETFs that existed that month (point-in-time membership, >= 3 funds), base 100.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
UNIVERSE = BASE / "etf_theme_universe.json"
OUT = BASE / "etf_theme_dataset.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
DIRECTORY_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
MIN_AGE_Y, MIN_DOLLAR_VOL_M, MIN_PER_THEME = 3.0, 1.0, 3

LEVERAGED = re.compile(r"\b(2X|3X|-1X|-2X|-3X|Ultra|UltraShort|UltraPro|Bear|Inverse|Leveraged|Short|Daily)\b|2x|3x", re.I)
NON_EQUITY = re.compile(r"\b(?:bonds?|treasur\w*|income|municipal\w*|muni\w*|aggregate|tips|high yield|corporate|credit|loan\w*|"
                        r"preferred|floating|duration|money market|t-bill|ultra short|convertible|mortgage|ETN|buffer|defined outcome|"
                        r"covered call|option\w*|premium|yield\w*|intermediate|short-term|long-term|inflation)\b", re.I)
THEMES = [
    ("Fintech / payments", r"fintech|payment|financial technology"),  # before crypto: "ARK Blockchain & Fintech"
    ("Crypto / blockchain", r"bitcoin|crypto|blockchain|digital asset|ethereum"),  # before mining: "Bitcoin Mining"
    ("Rare earth / strategic metals", r"rare earth|strategic metal"), ("Uranium / nuclear", r"uranium|nuclear"),
    ("Lithium / battery", r"lithium|battery"), ("Copper / base metals", r"copper|base metal|industrial metal"),
    ("Gold miners", r"gold miner|junior gold|gold mining"), ("Silver miners", r"silver miner"),
    ("Gold / silver / precious metals", r"\bgold\b|\bsilver\b|precious|platinum|palladium"),
    ("Metals & mining", r"metals? (&|and) mining|mining|steel|materials"),
    ("Defense / aerospace", r"defen[cs]e|aerospace|\bnato\b|military"), ("Space", r"\bspace\b"),
    ("Semiconductors", r"semiconductor|\bsemi\b|(?<!blue )\bchips?\b"), ("Cybersecurity", r"cyber|security (&|and)|network security"),
    ("AI / robotics / automation", r"artificial intelligence|\bai\b|robotic|automation|machine learning"),
    ("Cloud / software", r"cloud|software|saas|data center|digital infrastructure"),
    ("Internet / e-commerce", r"internet|e-commerce|ecommerce|online"),
    ("Solar / wind / clean energy", r"solar|\bwind\b|clean energy|renewable|clean tech|cleantech|\bgreen\b|climate|hydrogen|fuel cell|smart grid"),
    ("Oil & gas / energy", r"\boil\b|\bgas\b|petroleum|energy|natural resources|pipeline|midstream|\bmlp\b|exploration"),
    ("Biotech / genomics", r"biotech|genom|\bgene\b|immuno|oncology|cancer|clinical"),
    ("Healthcare / pharma / devices", r"health|medical|pharma|device|\bcare\b|life science"),
    ("Banks / financials", r"\bbank|financial|insurance|broker|capital markets|\bfinance\b"),
    ("Real estate", r"real estate|reit|\bhome|housing|\bproperty\b|mortgage reit"),
    ("Utilities / infrastructure", r"utilit|infrastructure|water\b"),
    ("Industrials / transport", r"industrial(?! average)|transport|airline|shipping|logistic|\btruck|\brail|aviation|engineering|construction"),
    ("Agriculture / food", r"agricultur|\bfood|\bfarm"),  # before broad baskets: "Agriculture Commodity Strategy"
    ("Broad commodities", r"commodit"),
    ("Consumer / retail / leisure", r"consumer|retail|leisure|travel|cruise|restaurant|apparel|luxury|gaming|esport|entertainment|\bmedia\b|sports|cannabis|alcohol|beverage"),
]
NOT_A_THEME = [  # recognised but deliberately not shown as themes: broad market, country and style funds
    r"emerging|china|india|japan|korea|taiwan|brazil|mexico|germany|europe|united kingdom|latin|asia|pacific|vietnam|indonesia|"
    r"thailand|africa|saudi|canada|australia|singapore|hong kong|israel|turkey|poland|international|world|global ex|ex-us|all country",
    r"s&p|nasdaq|russell|dow|total (stock )?market|large cap|mid cap|small cap|micro|value|growth|momentum|quality|dividend|"
    r"equal weight|low volatility|min vol|factor|multi-?factor|buyback|\bcore\b",
]
THEME_RX = [(n, re.compile(p, re.I)) for n, p in THEMES]
SKIP_RX = [re.compile(p, re.I) for p in NOT_A_THEME]


def theme_of(name: str) -> str | None:
    for n, rx in THEME_RX:
        if rx.search(name):
            return n
    return None


def fetch_monthly(sym: str, rng: str = "max") -> pd.DataFrame | None:
    for _ in range(3):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": "1mo", "range": rng}, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(3)
                continue
            res = r.json()["chart"]["result"]
            if not res or not res[0].get("timestamp"):
                return None
            res = res[0]
            ts = pd.to_datetime(res["timestamp"], unit="s").to_period("M").to_timestamp()
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
            df = pd.DataFrame({"adj": adj, "close": q["close"], "vol": q["volume"]}, index=ts)
            return df[~df.index.duplicated(keep="last")].dropna(subset=["adj"])
        except Exception:
            time.sleep(1)
    return None


def fetch_many(syms: list[str], workers: int = 5) -> dict[str, pd.DataFrame]:
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (s, df) in enumerate(zip(syms, ex.map(fetch_monthly, syms)), 1):
            if df is not None and len(df):
                out[s] = df
            if i % 800 == 0:
                print(f"    fetched {i}/{len(syms)}", flush=True)
    return out


def rebuild_universe() -> dict:
    print("  rebuilding the ETF universe from the NASDAQ Trader directory ...", flush=True)
    r = requests.get(DIRECTORY_URL, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), sep="|")
    df = df[df["Symbol"].notna() & ~df["Symbol"].astype(str).str.startswith("File Creation")]
    etf = df[(df["ETF"] == "Y") & (df["Test Issue"] == "N")]
    names = dict(zip(etf["Symbol"].astype(str), etf["Security Name"].astype(str)))
    cand = [s for s, n in names.items() if not LEVERAGED.search(n) and not NON_EQUITY.search(n)]
    print(f"    {len(names)} ETFs listed, {len(cand)} after dropping leveraged/inverse and bond/income names", flush=True)
    previous = json.loads(UNIVERSE.read_text(encoding="utf-8")) if UNIVERSE.exists() else None
    series = fetch_many(cand)
    if len(series) < 0.8 * len(cand):
        msg = f"only {len(series)}/{len(cand)} ETF histories came back (rate limit or outage)"
        if previous is None:
            raise RuntimeError(msg + " and there is no earlier universe to fall back on")
        print(f"  WARNING: {msg} - keeping the existing universe unchanged", flush=True)
        return previous
    held = {e["symbol"] for e in previous["etfs"]} if previous else set()
    now = pd.Timestamp.today().to_period("M").to_timestamp()
    last_full = now - pd.DateOffset(months=1)
    keep = {}
    for s, d in series.items():
        d = d[d.index <= last_full]
        if len(d) < 36:
            continue
        age = (now - d.index[0]).days / 365.25
        tail = d.tail(6)
        dv = float((tail["vol"].astype(float) * tail["close"].astype(float)).mean() / 21 / 1e6)
        # hysteresis: a fund already in the universe stays until it falls under half the entry bar
        bar = MIN_DOLLAR_VOL_M / 2 if s in held else MIN_DOLLAR_VOL_M
        if age < MIN_AGE_Y or not np.isfinite(dv) or dv < bar:
            continue
        t = theme_of(names[s])
        if t is None:
            continue
        keep[s] = dict(symbol=s, name=names[s], theme=t, first=d.index[0].strftime("%Y-%m"), age_y=round(age, 1), dollar_vol_m=round(dv, 1))
    counts = pd.Series([v["theme"] for v in keep.values()]).value_counts()
    ok_themes = set(counts[counts >= MIN_PER_THEME].index)
    keep = {s: v for s, v in keep.items() if v["theme"] in ok_themes}
    uni = dict(built=dt.date.today().isoformat(), scanned=len(cand), etfs=list(keep.values()))
    UNIVERSE.write_text(json.dumps(uni, indent=0), encoding="utf-8")
    print(f"    universe: {len(keep)} ETFs in {len(ok_themes)} themes", flush=True)
    return uni


def main() -> None:
    rebuild = os.environ.get("ETF_UNIVERSE_REBUILD") == "1" or not UNIVERSE.exists()
    uni = rebuild_universe() if rebuild else json.loads(UNIVERSE.read_text(encoding="utf-8"))
    etfs = {e["symbol"]: e for e in uni["etfs"]}
    bench_syms = {"VT": "World (VT)", "VOO": "S&P 500 (VOO)", "INDA": "India MSCI (INDA)"}
    print(f"  fetching {len(etfs)} theme ETFs + {len(bench_syms)} benchmarks + USDINR ...", flush=True)
    data = fetch_many(list(etfs) + list(bench_syms))
    fx = fetch_monthly("USDINR=X")
    if fx is None or len(fx) < 100:
        raise RuntimeError("USDINR monthly history unavailable")
    fx = fx["adj"]
    missing = [s for s in etfs if s not in data]
    if missing:
        print(f"    no data this run for {len(missing)} ETFs: {missing[:10]}")

    def inr(d: pd.DataFrame) -> pd.Series:
        s = (d["adj"] * fx.reindex(d.index)).dropna()
        return s

    START = pd.Timestamp("2010-01-01")
    inr_s = {s: inr(d)[lambda x: x.index >= START] for s, d in data.items()}
    months = sorted(set().union(*[set(x.index) for x in inr_s.values()]))
    months = pd.DatetimeIndex(months)
    month_str = [m.strftime("%Y-%m") for m in months]

    def rebase(s: pd.Series) -> list:
        s = s.reindex(months)
        first = s.first_valid_index()
        base = s[first]
        return [None if pd.isna(v) else round(float(v / base * 100), 2) for v in s]

    themes_out = []
    by_theme: dict[str, list[str]] = {}
    for s, e in etfs.items():
        if s in inr_s and len(inr_s[s]) >= 12:
            by_theme.setdefault(e["theme"], []).append(s)
    for theme, syms in sorted(by_theme.items()):
        if len(syms) < MIN_PER_THEME:
            continue
        ret = pd.DataFrame({s: inr_s[s].reindex(months).pct_change(fill_method=None) for s in syms})
        cnt = ret.notna().sum(axis=1)
        tr = ret.mean(axis=1).where(cnt >= MIN_PER_THEME)
        lvl = (1 + tr.fillna(0)).cumprod()
        first = tr.first_valid_index()
        lvl = lvl / lvl[first] * 100
        lvl = lvl.where(lvl.index >= first)
        themes_out.append(dict(
            name=theme, n=len(syms),
            index=[None if pd.isna(v) else round(float(v), 2) for v in lvl],
            etfs=[dict(symbol=s, name=etfs[s]["name"], first=etfs[s]["first"], age_y=etfs[s]["age_y"],
                       dollar_vol_m=etfs[s]["dollar_vol_m"], values=rebase(inr_s[s])) for s in
                  sorted(syms, key=lambda x: -etfs[x]["dollar_vol_m"])]))
    benches = [dict(key=k.lower(), name=n, values=rebase(inr_s[k])) for k, n in bench_syms.items() if k in inr_s]
    last_day = None
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/VT", params={"interval": "1d", "range": "5d"}, headers=UA, timeout=30)
        last_day = pd.to_datetime(r.json()["chart"]["result"][0]["timestamp"][-1], unit="s").date().isoformat()
    except Exception:
        last_day = months[-1].date().isoformat()
    out = dict(as_of=last_day, built=dt.date.today().isoformat(), universe_built=uni["built"], months=month_str,
               benchmarks=benches, themes=themes_out,
               meta=dict(scanned=uni.get("scanned"), etfs=sum(t["n"] for t in themes_out), themes=len(themes_out)))
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"\nWrote etf_theme_dataset.json ({kb:.0f} KB): {out['meta']['themes']} themes, {out['meta']['etfs']} ETFs, "
          f"{len(month_str)} months, as of {last_day}")


if __name__ == "__main__":
    main()
