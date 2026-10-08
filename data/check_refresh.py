"""Correctness gate for the unattended weekly refresh. Runs AFTER refresh_all.py --no-git and
BEFORE anything is committed or pushed: any FAIL exits non-zero, the workflow stops, nothing
is published, and GitHub emails the failure. It exists because the pipeline is deliberately
forgiving (a failed fetch falls back to cached data, a failed fund check quietly shrinks the
universe) - fine when you watch it run, dangerous when nobody does.

What it enforces (compares the fresh output with the version committed at HEAD):
  1. Structure: dates sorted/unique, every series the same length as the date axis.
  2. Freshness: as_of never goes backwards; on a scheduled run it must be exactly the most
     recent Friday (the weekly bucket label), i.e. the new week really arrived.
  3. Coverage: in every category >=90% of funds, and every benchmark, have a value in the
     newest week (catches a blocked/failed data source whose cache silently went stale).
  4. Universe: no category loses more than max(3, 15%) of its funds and the total does not
     fall more than 5% (catches an API outage being read as "fund wound up").
  5. Sanity: newest-week move beyond a per-category limit (40% default, 6% for bond/debt
     schemes, 60% crypto) fails (catches unit changes, bad NAVs, currency mix-ups).
  6. Page consistency: the data embedded in the HTML pages matches the JSON just built.
Additions/removals of funds are listed in the report (used for the commit message).

Env: STRICT_ADVANCE=1 enables the "must be the latest Friday" rule (set for scheduled runs;
manual runs mid-week legitimately do not advance). REPORT_PATH overrides where the report goes.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
REPORT = Path(os.environ.get("REPORT_PATH", BASE / "refresh_report.md"))

BOND_LIKE = {"Debt / Parking", "NPS Corp Bond", "NPS Govt Bond"}
MOVE_LIMIT = {"Crypto": 0.60, "ETF - Metals": 0.60, "ETF - World Markets": 0.50, **{c: 0.06 for c in BOND_LIKE}}
DEFAULT_MOVE_LIMIT = 0.40
BENCH_MOVE_LIMIT = 0.25
MIN_COVERAGE = 0.90

fails: list[str] = []
warns: list[str] = []
notes: list[str] = []


def load_previous() -> dict | None:
    try:
        out = subprocess.run(["git", "show", "HEAD:data/leaderboard_combined_dataset.json"],
                              cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(out.stdout)
    except Exception as e:  # first ever run / shallow history
        warns.append(f"could not load the previously committed dataset ({type(e).__name__}); comparison checks skipped")
        return None


def last_two(values):
    """(previous, latest) non-null values, or (None, None)."""
    got = [v for v in values if v is not None]
    return (got[-2], got[-1]) if len(got) >= 2 else (None, None)


def expected_friday(now_utc: dt.datetime) -> dt.date:
    ist = now_utc + dt.timedelta(hours=5, minutes=30)
    d = ist.date()
    return d - dt.timedelta(days=(d.weekday() - 4) % 7)


def html_data(path: Path, prefix: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].rstrip().rstrip(";")
    raise RuntimeError(f"no line starting with {prefix!r} in {path.name}")


def main() -> int:
    new = json.load(open(BASE / "leaderboard_combined_dataset.json", encoding="utf-8"))
    old = load_previous()
    dates = new["dates"]
    n = len(dates)

    # 1. structure
    if dates != sorted(set(dates)):
        fails.append("dates are not strictly increasing / unique")
    for f in new["funds"]:
        if len(f["values"]) != n:
            fails.append(f"fund {f['key']} has {len(f['values'])} values for {n} dates")
    for b in new["benchmarks"]:
        if len(b["values"]) != n:
            fails.append(f"benchmark {b['key']} has {len(b['values'])} values for {n} dates")

    # 2. freshness
    as_of = new["as_of"]
    prev_as_of = old["as_of"] if old else None
    notes.append(f"as_of: {prev_as_of} -> {as_of}")
    if prev_as_of and as_of < prev_as_of:
        fails.append(f"as_of went backwards ({prev_as_of} -> {as_of})")
    if os.environ.get("STRICT_ADVANCE") == "1":
        want = expected_friday(dt.datetime.now(dt.timezone.utc)).isoformat()
        if as_of != want:
            fails.append(f"scheduled run expected the newest week to be {want} but as_of is {as_of} - "
                         f"a data source did not deliver the new week")
    elif prev_as_of and as_of == prev_as_of:
        warns.append("as_of did not advance (fine for a manual mid-week run, a failure on the schedule)")

    # 3. coverage in the newest week
    by_cat: dict[str, list] = {}
    for f in new["funds"]:
        by_cat.setdefault(f["category"], []).append(f)
    for cat, fs in sorted(by_cat.items()):
        have = sum(1 for f in fs if f["values"][-1] is not None)
        if have / len(fs) < MIN_COVERAGE:
            missing = [f["name"] for f in fs if f["values"][-1] is None][:6]
            fails.append(f"{cat}: only {have}/{len(fs)} funds have a value for {as_of} (e.g. {missing})")
    for b in new["benchmarks"]:
        if b["values"][-1] is None:
            fails.append(f"benchmark {b['name']} has no value for {as_of}")

    # 4. universe size + listing of changes
    if old:
        old_by = {f["key"]: f for f in old["funds"]}
        new_by = {f["key"]: f for f in new["funds"]}
        added = [new_by[k] for k in new_by if k not in old_by]
        removed = [old_by[k] for k in old_by if k not in new_by]
        notes.append(f"funds: {len(old_by)} -> {len(new_by)} (+{len(added)} / -{len(removed)})")
        if len(new_by) < 0.95 * len(old_by):
            fails.append(f"total funds fell {len(old_by)} -> {len(new_by)} (more than 5%)")
        old_cat: dict[str, int] = {}
        for f in old["funds"]:
            old_cat[f["category"]] = old_cat.get(f["category"], 0) + 1
        for cat, cnt in old_cat.items():
            now = len(by_cat.get(cat, []))
            if cnt - now > max(3, 0.15 * cnt):
                fails.append(f"{cat} lost {cnt - now} of {cnt} funds ({cnt} -> {now})")
        for label, lst in (("ADDED", added), ("REMOVED", removed)):
            for f in lst[:30]:
                notes.append(f"{label}: [{f['category']}] {f['name']}")
            if len(lst) > 30:
                notes.append(f"{label}: ...and {len(lst) - 30} more")

    # 5. newest-week sanity
    for f in new["funds"]:
        prev, last = last_two(f["values"])
        if prev is None:
            continue
        if not (math.isfinite(last) and last > 0):
            fails.append(f"{f['name']}: latest value {last} is not a positive number")
            continue
        move = last / prev - 1
        limit = MOVE_LIMIT.get(f["category"], DEFAULT_MOVE_LIMIT)
        if abs(move) > limit:
            fails.append(f"{f['name']} [{f['category']}]: {move:+.1%} in the newest week (limit {limit:.0%})")
    for b in new["benchmarks"]:
        prev, last = last_two(b["values"])
        if prev and abs(last / prev - 1) > BENCH_MOVE_LIMIT:
            fails.append(f"benchmark {b['name']}: {last / prev - 1:+.1%} in the newest week")

    # 6. pages carry the data that was just built
    try:
        page = json.loads(html_data(BASE / "mf_relative_strength_6m.html", "  const DATA = "))
        if page["as_of"] != as_of or len(page["funds"]) != len(new["funds"]) or page["dates"] != dates:
            fails.append("mf_relative_strength_6m.html does not embed the dataset that was just built")
        for html, js in (("sector_rotation_map.html", "rrg_series.json"), ("asset_rotation_map.html", "asset_class_rrg_series.json")):
            if json.loads(html_data(BASE / html, "  const RRG = ")) != json.load(open(BASE / js, encoding="utf-8")):
                fails.append(f"{html} does not embed {js}")
    except Exception as e:
        fails.append(f"could not verify the embedded page data: {type(e).__name__}: {e}")

    lines = ["## Data refresh check", ""]
    lines += [f"- {x}" for x in notes]
    if warns:
        lines += ["", "### Warnings"] + [f"- {x}" for x in warns]
    if fails:
        lines += ["", "### FAILURES - nothing was published"] + [f"- {x}" for x in fails]
    else:
        lines += ["", "All checks passed."]
    text = "\n".join(lines) + "\n"
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
