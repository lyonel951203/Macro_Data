"""Generic Wind MCP JSON intake: stage/validate/ingest any batch as WIND/PIT_D.

Usage:
  py -3.11 scripts/tools/ingest_wind_mcp.py --pattern "batch3_pmi_*.json" \
      --output-dir reports/v2/wind_batch3_pmi [--ingest]

- Mappings come from config/wind_mcp_mappings.csv (append verified rows per batch).
- Same contract and assertions as review_wind_batch.py / ingest_wind_mcp_batch2.py:
  source=WIND, pit_grade=D, release_at=None, available_at=first_seen_at;
  in-memory replay idempotency; strict/loose exclusion; first_seen boundary;
  --ingest additionally asserts strict snapshot and export files unchanged.
- Unit conversion uses division (divisor column) to keep doubles clean.
- Quarantine: periods before 2005-01, unmapped codes, null values.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from macro_pit.db import get_connection, insert_observations
from macro_pit.pit import get_snapshot

PARSER_VERSION = "wind-edb-mcp-intake/2"
SRC = Path("data/manual_import/wind_mcp")
MAPPINGS_CSV = Path("config/wind_mcp_mappings.csv")
START_PERIOD = "2005-01"


def load_mappings() -> dict[str, tuple]:
    with MAPPINGS_CSV.open(encoding="utf-8-sig") as fh:
        return {
            row["wind_code"]: (
                row["canonical_series_id"], row["expected_name"], row["expected_unit"],
                row["target_unit"], float(row["divisor"]),
            )
            for row in csv.DictReader(fh)
        }


def load_records(pattern: str, first_seen: datetime):
    mappings = load_mappings()
    observations, quarantined, review_rows = [], [], []
    files = sorted(SRC.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no files match {pattern} in {SRC}")
    for path in files:
        raw_bytes = path.read_bytes()
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        payload = json.loads(raw_bytes.decode("utf-8"))
        retrieved = datetime.fromisoformat(payload["pulled_at"])
        source_url = payload.get("source_url", "wind-mcp://natural_language_get_edb_data")
        for block in payload["response"]["data"]:
            meta = block["meta"]
            code = meta["code"]
            mapping = mappings.get(code)
            if mapping is None:
                quarantined.append(dict(file=path.name, wind_code=code,
                                        series_name=meta["name"], reason="unreviewed_mapping"))
                continue
            canonical, expected_name, expected_unit, target_unit, divisor = mapping
            if meta["name"] != expected_name or meta["unit"] != expected_unit \
                    or meta["freq"] not in ("月", "季"):
                raise ValueError(f"Reviewed mapping metadata changed for {code}: {meta}")
            quarterly = meta["freq"] == "季"
            dates, values = block["date"], block["value"]
            if len(dates) != len(values):
                raise ValueError(f"{path.name}:{code} date/value length mismatch")
            prev = ""
            n_ingested = 0
            for d, v in zip(dates, values):
                if d <= prev:
                    raise ValueError(f"{path.name}:{code} non-increasing date {d}")
                prev = d
                y, m, day = int(d[:4]), int(d[4:6]), int(d[6:8])
                if day != calendar.monthrange(y, m)[1]:
                    raise ValueError(f"{path.name}:{code} non-month-end {d}")
                when = datetime.strptime(d, "%Y%m%d").date()
                if quarterly:
                    quarter = (m - 1) // 3 + 1
                    if m not in (3, 6, 9, 12):
                        raise ValueError(f"{path.name}:{code} non-quarter-end {d}")
                    period = f"{y:04d}-Q{quarter}"
                    period_start = when.replace(month=3 * quarter - 2, day=1)
                    frequency = "Q"
                else:
                    period = f"{y:04d}-{m:02d}"
                    period_start = when.replace(day=1)
                    frequency = "M"
                if period < START_PERIOD:
                    quarantined.append(dict(file=path.name, wind_code=code, period=period,
                                            series_name=meta["name"], reason="before_requested_start"))
                    continue
                if v is None:
                    quarantined.append(dict(file=path.name, wind_code=code, period=period,
                                            series_name=meta["name"], reason="missing_or_nonnumeric"))
                    continue
                observations.append(dict(
                    country="CN", source="WIND", canonical_series_id=canonical,
                    source_series_id=code, series_name=meta["name"], frequency=frequency,
                    unit=target_unit, seasonal_adjustment=None, period=period,
                    period_start=period_start, period_end=when,
                    value=float(v) / divisor, release_at=None, release_date_source=None,
                    first_seen_at=first_seen, available_at=first_seen, pit_grade="D",
                    source_url=source_url,
                    raw_file=str(path), raw_sha256=sha256, retrieved_at=retrieved,
                    parser_version=PARSER_VERSION,
                ))
                n_ingested += 1
            review_rows.append(dict(
                wind_code=code, wind_name=meta["name"], wind_unit=meta["unit"],
                canonical_series_id=canonical, target_unit=target_unit, divisor=divisor,
                source=meta["source"], wind_updateDate=meta.get("updateDate", ""),
                n_ingested=n_ingested,
            ))
    return observations, quarantined, review_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", required=True, help="glob under data/manual_import/wind_mcp")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--db-path", default="macro_pit_v2.duckdb")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    first_seen = datetime.now().astimezone()
    records, quarantined, review_rows = load_records(args.pattern, first_seen)
    normalized = pd.DataFrame(records)
    normalized.to_csv(out / "accepted_values_long.csv", index=False, encoding="utf-8-sig")
    if not normalized.empty:
        normalized.pivot(index="period", columns="canonical_series_id", values="value").to_csv(
            out / "wind_values_wide.csv", encoding="utf-8-sig")
    pd.DataFrame(quarantined).to_csv(out / "quarantined.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(review_rows).to_csv(out / "mapping_review.csv", index=False, encoding="utf-8-sig")

    dup = int(normalized.duplicated(["canonical_series_id", "period"]).sum()) if not normalized.empty else 0
    if dup:
        raise ValueError(f"duplicate accepted keys: {dup}")

    with get_connection(":memory:") as conn:
        first = insert_observations(conn, records)
        replay = insert_observations(conn, records)
        cutoff = first_seen
        assert first.inserted == len(records) and replay.unchanged == len(records)
        assert replay.inserted == 0
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "strict").is_empty()
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "loose").is_empty()
        assert get_snapshot(conn, (cutoff - timedelta(seconds=1)).isoformat(), "CN", "observed").is_empty()
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "observed").height == len(records)

    summary = dict(
        reviewed_at=datetime.now().astimezone().isoformat(),
        first_seen_at=first_seen.isoformat(),
        pattern=args.pattern,
        accepted_cells=len(records),
        accepted_indicators=int(normalized.canonical_series_id.nunique()) if not normalized.empty else 0,
        quarantined_cells=len(quarantined),
        quarantine_reasons=dict(Counter(q["reason"] for q in quarantined)),
        pit_grade="D", release_at=None,
        validation=dict(in_memory_ingest=asdict(first), replay=asdict(replay),
                        strict_and_loose_exclusion=True, first_seen_boundary=True,
                        duplicate_accepted_keys=dup),
    )

    if args.ingest:
        if Path("data/history_backfill/nbs_price_batch.lock").exists():
            raise RuntimeError("NBS worker holds its batch lock; retry ingestion after it exits.")
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
        ingestion = dict(stats=asdict(result), db_before=before, db_after=after,
                         strict_snapshot_unchanged=True, strict_exports_unchanged=True)
        name = "replay_result.json" if (out / "ingestion_result.json").exists() else "ingestion_result.json"
        (out / name).write_text(json.dumps(ingestion, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        summary["ingestion"] = ingestion
        summary["status"] = "INGESTED"
    else:
        summary["status"] = "STAGED"

    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
