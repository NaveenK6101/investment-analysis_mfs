"""Portfolio overlap: equity holdings of every equity scheme from a chosen set of AMCs, from the AMCs' own
SEBI-mandated monthly portfolio disclosures (no paid data). The page computes overlap between any two schemes as
the sum, over stocks both hold, of the smaller of the two weights (the same formula Dezerv's tool uses; checked
2026-10-20 against their Parag Parikh vs HDFC Flexi Cap result: 29.73% computed, 30% shown, 23 common stocks).

Fetch: one small adapter per AMC, because every AMC publishes differently (verified 2026-10-20):
  groww    plain page, one workbook with every scheme (often uploaded twice under two names)
  helios   plain page, one file per scheme
  abakkus  plain page; real files live under /uploads/<name>_<hash>.xlsx (display names 404)
  trust    the page is a JS app; its own API (Trust/GetData, GetDisclosuresForProductWeb) lists the files
Parse: one generic parser for all of them - find the header row with an ISIN column and a '% to NAV' column, keep
rows with a valid ISIN, and call a row equity when the ISIN's security-type code is 01 (equity shares). Files are
opened by their content, not their extension (AMCs ship .xlsx files named .xls).

Only a newer month triggers downloads. If an AMC cannot be reached, its last published schemes are kept and the
age shows on the page; the refresh gate fails only when data gets old (see check_refresh.py).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "portfolio_overlap_dataset.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

ISIN = re.compile(r"^IN[A-Z0-9]{9}\d$")
EQUITY = re.compile(r"^INE[A-Z0-9]{4}01[A-Z0-9]{2}\d$")          # security-type 01 = equity shares
PCT_HDR = re.compile(r"%\s*(to|of)?\s*(nav|net\s*assets?|aum)|(nav|net\s*assets?)\s*%|percent(age)?\s*(to|of)\s*(nav|net)|^%\s*$", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SKIP_SCHEME = re.compile(r"arbitrage|liquid|overnight|money market|gilt|debt|bond|short (term|duration)|dynamic term|"
                         r"fund of fund|\bfof\b|omni|gold|silver|1d rate|psu debt", re.I)
MIN_EQUITY, MIN_STOCKS = 60.0, 10


# ----------------------------------------------------------------------------------------------- helpers
def get(url: str, **kw) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=kw.pop("timeout", 60), **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        time.sleep(2 + 2 * attempt)
    raise RuntimeError(f"{url[:90]}: {last}")


def safe_url(u: str) -> str:
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc, quote(unquote(p.path), safe="/"), p.query, ""))


def month_of(text: str) -> tuple[int, int] | None:
    """(year, month) of a month-end portfolio, read from a file name or title; None if it carries no year."""
    t = unquote(text).lower().replace("_", " ").replace("-", " ")
    m = re.search(r"(\d{1,2})[.\s/](\d{1,2})[.\s/](20\d{2})", t)                       # 30.09.2026 / 31 12 2025
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(3)), int(m.group(2))
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s.,]*(?:\d{1,2}(?:st|nd|rd|th)?)?[\s.,]*(20\d{2})", t)
    if m:
        return int(m.group(2)), MONTHS[m.group(1)]
    m = re.search(r"\d{1,2}(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s.,]*(20\d{2})", t)
    if m:
        return int(m.group(2)), MONTHS[m.group(1)]
    return None


def links_in(url: str, html: str) -> list[str]:
    raw = re.findall(r"""["']([^"'\s<>][^"'<>]*?\.(?:xlsx?|xlsm))["']""", html, re.I)
    return sorted({urljoin(url, unquote(x).strip()) for x in raw})


# ----------------------------------------------------------------------------------------------- parser
def workbook_sheets(content: bytes):
    head = content[:8]
    if head.lstrip()[:1] == b"<":
        import pandas as pd
        for k, df in enumerate(pd.read_html(io.BytesIO(content))):
            yield f"table{k}", [list(df.columns)] + df.astype(object).where(df.notna(), None).values.tolist()
    elif head[:4] == b"\xd0\xcf\x11\xe0":
        import xlrd
        wb = xlrd.open_workbook(file_contents=content)
        for sh in wb.sheets():
            yield sh.name, [sh.row_values(i) for i in range(sh.nrows)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for ws in wb.worksheets:
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def parse_sheet(rows: list[list]) -> tuple[str, list[tuple[str, float, str]]] | None:
    title = " ".join(str(c) for r in rows[:12] for c in r if isinstance(c, str) and c.strip())
    for i, r in enumerate(rows[:60]):
        cells = [str(c).strip() if c is not None else "" for c in r]
        ic = next((j for j, c in enumerate(cells) if re.fullmatch(r"isin(\s*(no\.?|code|number))?", c, re.I)), None)
        pc = next((j for j, c in enumerate(cells) if PCT_HDR.search(c)), None)
        if ic is None or pc is None:
            continue
        nc = next((j for j, c in enumerate(cells) if re.search(r"name|instrument|issuer|company|security", c, re.I)), None)
        out = []
        for row in rows[i + 1:]:
            if max(ic, pc) >= len(row):
                continue
            code, w = str(row[ic] or "").strip().upper(), num(row[pc])
            if ISIN.match(code) and w is not None:
                nm = str(row[nc]).strip() if nc is not None and nc < len(row) and row[nc] else ""
                out.append((code, w, nm))
        if not out:
            return None
        if sum(w for _, w, _ in out) < 2.5:                # fractions (0.0355) instead of percent (3.55)
            out = [(c, w * 100, n) for c, w, n in out]
        return title, out
    return None


def scheme_name(title: str, amc: str) -> str | None:
    # titles often start with the AMC's own name ("Abakkus Mutual Fund Abakkus Flexi Cap Fund ..."): skip that match
    pat = re.compile(r"((?:groww|helios|abakkus|trustmf|trust mf)\b[\w&\s\-()]*?(?:fund|etf))", re.I)
    m = next((x for x in pat.finditer(title) if not re.search(r"mutual\s+fund$", x.group(1), re.I)), None)
    if not m:
        return None
    name = re.sub(r"\s+", " ", m.group(1)).strip()
    name = re.sub(r"(?i)^trust mf", "TRUSTMF", name)
    return name[0].upper() + name[1:]


def schemes_from(content: bytes, amc: str, date: str, source: str) -> list[dict]:
    found = []
    for sheet, rows in workbook_sheets(content):
        res = parse_sheet(rows)
        if not res:
            continue
        title, holdings = res
        name = scheme_name(title, amc)
        if not name or SKIP_SCHEME.search(name):
            continue
        eq = {}
        names = {}
        for code, w, nm in holdings:
            if EQUITY.match(code):
                eq[code] = eq.get(code, 0.0) + w             # a stock listed twice (e.g. partly paid) is summed
                names.setdefault(code, nm)
        total = sum(eq.values())
        if total < MIN_EQUITY or len(eq) < MIN_STOCKS:
            continue
        found.append(dict(name=name, amc=amc, date=date, source=source,
                          type="passive" if re.search(r"\bindex\b|\betf\b", name, re.I) else "active",
                          equity=round(total, 2), holdings=eq, names=names))
    return found


# ----------------------------------------------------------------------------------------------- AMC adapters
def newest(cands: list[tuple[tuple[int, int], str]]) -> tuple[tuple[int, int], list[str]] | None:
    dated = [(m, u) for m, u in cands if m]
    if not dated:
        return None
    best = max(m for m, _ in dated)
    return best, [u for m, u in dated if m == best]


def groww():
    url = "https://growwmf.in/statutory-disclosure/portfolio"
    links = [l for l in links_in(url, get(url).text) if re.search(r"monthly\s*portfolio", unquote(l), re.I)]
    pick = newest([(month_of(l.split("/")[-1]), l) for l in links])
    return pick and (pick[0], pick[1][:1])          # the same workbook is often uploaded twice: take one


def helios():
    url = "https://www.heliosmf.in/portfolio-disclosure/"
    links = [l for l in links_in(url, get(url).text) if re.search(r"monthly[\s\-]*portfolio", unquote(l), re.I)
             and not re.search(r"fortnight", l, re.I)]
    return newest([(month_of(l.split("/")[-1]), l) for l in links])   # one file per scheme: take them all


def abakkus():
    url = "https://www.abakkusmf.com/statutory-disclosures.html"
    links = [l for l in links_in(url, get(url).text) if "/uploads/" in l and re.search(r"monthly", l, re.I)
             and re.search(r"port(f)?olio", l, re.I) and not re.search(r"fortnight|overlap|aum", l, re.I)]
    pick = newest([(month_of(re.sub(r"_[0-9a-f]{10}(?=\.\w+$)", "", l.split("/")[-1])), l) for l in links])
    return pick and (pick[0], pick[1][:1])


def trust():
    body = {"systemQueryFileName": "productsweb.xml", "tagName": "GetDisclosuresForProductWeb",
            "searchField": "", "searchValue": "", "sortField": "1", "sortDirection": "ASC"}
    r = requests.post("https://www.trustmf.com/api/api/Trust/GetData", data=json.dumps(body), timeout=40,
                      headers={**UA, "Content-type": "application/json; charset=UTF-8"})
    r.raise_for_status()
    items = [o for o in r.json().get("resultSetArray") or [] if "portfolio-monthly-disclosure" in (o.get("matching_slugs") or "")]
    pick = newest([(month_of(o.get("title", "")), o["fileurl"]) for o in items])
    return pick and (pick[0], pick[1][:1])


ADAPTERS = {"Groww": groww, "Helios": helios, "Abakkus": abakkus, "TRUSTMF": trust}


# ----------------------------------------------------------------------------------------------- main
def month_end(ym: tuple[int, int]) -> str:
    y, m = ym
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - dt.timedelta(days=1)).isoformat()


def main() -> None:
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    prev_by_amc: dict[str, list[dict]] = {}
    if prev:
        stocks = prev["stocks"]
        for s in prev["schemes"]:
            prev_by_amc.setdefault(s["amc"], []).append(dict(
                s, holdings={stocks[i][0]: w for i, w in s["h"]}, names={stocks[i][0]: stocks[i][1] for i, _ in s["h"]}))
    schemes, amc_info, problems = [], {}, []
    for amc, fn in ADAPTERS.items():
        old = prev_by_amc.get(amc, [])
        old_date = max((s["date"] for s in old), default="")
        try:
            pick = fn()
            if not pick:
                raise RuntimeError("no dated monthly portfolio link found")
            ym, urls = pick
            date = month_end(ym)
            if old and date <= old_date:
                print(f"  {amc:8s} latest month {date} already held ({len(old)} schemes) - no download")
                schemes += old
                amc_info[amc] = dict(date=old_date, status="current", schemes=len(old))
                continue
            got = []
            for u in urls:
                content = get(safe_url(u), timeout=120).content
                got += schemes_from(content, amc, date, u)
            seen, uniq = set(), []
            for s in got:                                     # Groww lists a scheme once per uploaded copy
                if s["name"] not in seen:
                    seen.add(s["name"])
                    uniq.append(s)
            if not uniq:
                raise RuntimeError(f"{len(urls)} file(s) for {date} parsed to no equity schemes")
            print(f"  {amc:8s} {date}: {len(uniq)} equity schemes from {len(urls)} file(s)")
            schemes += uniq
            amc_info[amc] = dict(date=date, status="updated", schemes=len(uniq))
        except Exception as e:  # noqa: BLE001
            msg = f"{amc}: {type(e).__name__}: {str(e)[:160]}"
            problems.append(msg)
            print(f"  WARNING {msg} - keeping {len(old)} schemes from {old_date or 'nothing'}")
            schemes += old
            amc_info[amc] = dict(date=old_date or None, status="fetch failed, kept previous", schemes=len(old))

    if not schemes:
        raise RuntimeError("no schemes from any AMC: " + "; ".join(problems))
    # compact: one stock table, holdings as [stock index, weight]
    stock_idx: dict[str, int] = {}
    stock_rows: list[list] = []
    out_schemes = []
    for s in sorted(schemes, key=lambda x: (x["amc"], x["type"], x["name"])):
        h = []
        for code, w in sorted(s["holdings"].items(), key=lambda kv: -kv[1]):
            if round(w, 3) <= 0:                      # a holding too small to register (e.g. 0.0004% in a total-market fund)
                continue
            if code not in stock_idx:
                stock_idx[code] = len(stock_rows)
                stock_rows.append([code, clean_stock(s["names"].get(code, code))])
            h.append([stock_idx[code], round(w, 3)])
        key = re.sub(r"[^a-z0-9]+", "_", s["name"].lower()).strip("_")
        out_schemes.append(dict(key=key, name=s["name"], amc=s["amc"], type=s["type"], date=s["date"],
                                equity=round(sum(w for _, w in h), 2), n=len(h), h=h, source=s.get("source", "")))
    as_of = max(s["date"] for s in out_schemes)
    out = dict(built=dt.date.today().isoformat(), as_of=as_of, amcs=amc_info, problems=problems,
               stocks=stock_rows, schemes=out_schemes)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    act = sum(s["type"] == "active" for s in out_schemes)
    print(f"\nWrote {OUT.name} ({OUT.stat().st_size / 1024:.0f} KB): {len(out_schemes)} schemes "
          f"({act} active, {len(out_schemes) - act} index/ETF), {len(stock_rows)} stocks, latest portfolio {as_of}")
    if problems:
        print("Problems (previous data kept):\n  " + "\n  ".join(problems))


def clean_stock(name: str) -> str:
    n = re.sub(r"[#*@^]+$", "", name).strip()
    n = re.sub(r"(?i)\b(limited|ltd\.?)$", "Ltd", n)
    return n.title() if n.isupper() else n


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
