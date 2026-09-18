"""Ingest Wind terminal-EDB historical-revision snapshots (历史修正 xlsx) as WIND/PIT_D vintages.

File semantics (verified 2026-09-15, see revision_analysis.txt):
- 终值 column = value as of EXPORT date (both files extend to 2026-Q2) — it is NOT
  the series state as of the 修正日期 and must NOT be anchored to it.
- 修正日期 marks a revision EVENT: only rows with non-null 修正值 document which
  periods were revised on that date. Those 修正值 rows are the ingestible vintages:
  value = 修正值, available_at = 修正日期 00:00 +08:00 (documented, day granularity).

Grade stays D (Wind-sourced, not official documents): strict/loose untouched;
work mode keeps using the estimated-availability sidecar. Observed mode gains the
true revision vintages (e.g. 2022-Q2 0.4 -> 0.8 effective 2025-01-18).

Usage:
  py -3.11 scripts/ingest_gdp_revision_snapshots.py [--ingest]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from macro_pit.db import get_connection, insert_observations
from macro_pit.pit import get_snapshot

SRC = Path(r"E:\Macro_Data\data\raw\wind\修订")
OUT = Path(r"E:\Macro_Data\reports\v2\wind_batch9_gdp\revision_ingest")
PARSER_VERSION = "wind-revision-xlsx-intake/1"
CN_TZ = timezone(timedelta(hours=8))
START_PERIOD = "2005-Q1"
CANONICAL = "CN_GDP_YOY"
EXPECTED_NAME = "中国:GDP:不变价:当季同比"
EXPECTED_CODE = "M0039354"


def load_records(first_seen: datetime):
    observations, review_rows = [], []
    for path in sorted(SRC.glob("*.xlsx")):
        raw = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        head = pd.read_excel(path, sheet_name="历史修正", header=None, nrows=3)
        name, code, rev_date = head.iloc[0, 1], head.iloc[1, 1], head.iloc[2, 1]
        if name != EXPECTED_NAME or code != EXPECTED_CODE:
            raise ValueError(f"unexpected indicator in {path.name}: {name} / {code}")
        snap_date = pd.Timestamp(rev_date).date()
        tag = snap_date.strftime("%Y%m%d")
        available_at = datetime(snap_date.year, snap_date.month, snap_date.day, tzinfo=CN_TZ)
        df = pd.read_excel(path, sheet_name="历史修正", header=4).dropna(subset=["数据日期"])
        n = 0
        for row in df.itertuples():
            if pd.isna(row.修正值):
                continue  # only rows documenting the revision event on 修正日期
            d = pd.Timestamp(row.数据日期).date()
            quarter = (d.month - 1) // 3 + 1
            period = f"{d.year}-Q{quarter}"
            if period < START_PERIOD:
                continue
            observations.append(dict(
                country="CN", source="WIND", canonical_series_id=CANONICAL,
                source_series_id=EXPECTED_CODE, series_name=name, frequency="Q",
                unit="pct_yoy", seasonal_adjustment=None, period=period,
                period_start=d.replace(month=3 * quarter - 2, day=1), period_end=d,
                value=float(row.修正值), release_at=None,
                release_date_source=f"wind_revision_snapshot_{tag}",
                first_seen_at=first_seen, available_at=available_at, pit_grade="D",
                source_url="wind-terminal://edb/history-revision",
                raw_file=str(path), raw_sha256=sha256,
                retrieved_at=first_seen, parser_version=PARSER_VERSION,
            ))
            n += 1
        review_rows.append(dict(file=path.name, snapshot_date=str(snap_date),
                                available_at=available_at.isoformat(), n_periods=n))
    return observations, review_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="macro_pit_v2.duckdb")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    first_seen = datetime.now().astimezone()
    records, review_rows = load_records(first_seen)
    pd.DataFrame(review_rows).to_csv(OUT / "snapshot_review.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(records).to_csv(OUT / "accepted_values_long.csv", index=False, encoding="utf-8-sig")

    with get_connection(":memory:") as conn:
        first = insert_observations(conn, records)
        replay = insert_observations(conn, records)
        # D-grade signatures exclude temporal fields, so value-identical rows
        # (the second snapshot, and periods already pulled in batch9) dedup to
        # "unchanged" rather than inserting redundant vintages.
        assert first.inserted + first.unchanged == len(records)
        assert replay.unchanged == len(records) and replay.inserted == 0
        # D-grade never enters strict/loose, at any cutoff
        for mode in ("strict", "loose"):
            assert get_snapshot(conn, first_seen.isoformat(), "CN", mode).is_empty()
        # documented-date boundary: nothing visible before the earliest
        # snapshot date; full snapshot visible from that date on
        earliest = min(datetime.fromisoformat(r["available_at"]) for r in review_rows)
        assert get_snapshot(conn, (earliest - timedelta(seconds=1)).isoformat(),
                            "CN", "observed").is_empty()
        snap = get_snapshot(conn, earliest.isoformat(), "CN", "observed")
        assert snap.height >= max(r["n_periods"] for r in review_rows)

    summary = dict(
        reviewed_at=datetime.now().astimezone().isoformat(),
        first_seen_at=first_seen.isoformat(),
        snapshots=review_rows,
        accepted_cells=len(records),
        pit_grade="D", release_at=None,
        available_at_convention="修正日期 00:00 +08:00（Wind 版本日期，日粒度）",
        validation=dict(in_memory_ingest=asdict(first), replay=asdict(replay),
                        strict_and_loose_exclusion=True, documented_date_boundary=True),
    )

    if args.ingest:
        export_files = sorted(Path("data/exports").glob("cn_pit_*"))
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in export_files}
        with get_connection(args.db_path) as conn:
            before = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            strict_before = get_snapshot(conn, first_seen.isoformat(), "CN", "strict")
            result = insert_observations(conn, records)
            strict_after = get_snapshot(conn, first_seen.isoformat(), "CN", "strict")
            assert strict_before.equals(strict_after), "PIT_D changed strict results"
            after = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
        assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in export_files}
        summary["ingestion"] = dict(stats=asdict(result), db_before=before, db_after=after,
                                    strict_snapshot_unchanged=True, strict_exports_unchanged=True)
        summary["status"] = "INGESTED"
    else:
        summary["status"] = "STAGED"

    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                      encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
