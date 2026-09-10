"""Review a SHA-archived Wind workbook; optional append-only PIT_D ingestion."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from macro_pit.db import get_connection, insert_observations
from macro_pit.pit import get_snapshot
from macro_pit.wind import review_workbook


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def review(output_dir: Path, *, ingest: bool = False, db_path: str = "macro_pit_v2.duckdb"):
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    batch = review_workbook(manifest)
    cells = pd.DataFrame(batch["cells"])
    profiles = pd.DataFrame(batch["profiles"])
    records = batch["observations"]
    normalized = pd.DataFrame(records)
    for name, frame in [("all_source_cells", cells), ("field_profile", profiles),
                        ("quarantined_cells", cells[cells.status == "quarantined"]),
                        ("accepted_values_long", normalized)]:
        frame.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    normalized.to_parquet(output_dir / "accepted_values_long.parquet", index=False)
    normalized.pivot(index="period", columns="canonical_series_id", values="value").to_csv(
        output_dir / "wind_current_history_values.csv", encoding="utf-8-sig")
    save_json(output_dir / "embedded_export_settings.json", batch["settings"])
    yearly = (cells.assign(year=cells.period.str[:4], nonzero=lambda x: x.raw_value.ne(0),
                           accepted=lambda x: x.status.eq("accepted"))
              .groupby(["wind_code", "year"]).agg(input_cells=("period", "size"),
                 nonzero_cells=("nonzero", "sum"), accepted_cells=("accepted", "sum")).reset_index())
    yearly.to_csv(output_dir / "year_coverage.csv", index=False, encoding="utf-8-sig")
    transformed = profiles[profiles.operations.ne("")][[
        "wind_code", "raw_wind_code", "original_name", "original_unit", "original_frequency", "operations"]].copy()
    transformed["original_frequency"] = transformed.original_frequency.map({4: "月", 5: "季"})
    transformed["action"] = "导出原始指标；不换汇、不变频、空值留空"
    transformed.to_csv(output_dir / "reexport_10.csv", index=False, encoding="utf-8-sig")
    # The desired P0 checklist remains authoritative; level/flow variants cannot substitute.
    target = pd.read_csv("reports/v2/wind_download_plan/wind_first_batch_15.csv")
    key = "canonical_series_id"
    target["this_batch_received"] = target[key].isin(normalized.canonical_series_id)
    target["this_batch_accepted_cells"] = target[key].map(normalized.groupby(key).size()).fillna(0).astype(int)
    received_metadata = profiles[profiles.accepted_cells.gt(0)].set_index(key)
    target["wind_code"] = target[key].map(received_metadata.wind_code).fillna("")
    target["wind_unit"] = target[key].map(received_metadata.source_unit).fillna("")
    target.to_csv(output_dir / "p0_receipt.csv", index=False, encoding="utf-8-sig")
    # Cross-field diagnostics have a deliberately documented tolerance, not forced equality.
    trade = cells[cells.wind_code.isin(["M0000606", "M0000608", "M0000610"]) &
                  cells.period.ge("2005-01")].pivot(index="period", columns="wind_code", values="raw_value")
    trade["balance_residual_100mn_usd"] = trade.M0000606-trade.M0000608-trade.M0000610
    trade.to_csv(output_dir / "trade_identity_check.csv", encoding="utf-8-sig")
    with get_connection(":memory:") as conn:
        first = insert_observations(conn, records)
        replay = insert_observations(conn, records)
        cutoff = datetime.fromisoformat(manifest["first_seen_at"])
        assert first.inserted == len(records) and replay.unchanged == len(records)
        assert replay.inserted == 0
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "strict").is_empty()
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "loose").is_empty()
        assert get_snapshot(conn, (cutoff-timedelta(seconds=1)).isoformat(), "CN", "observed").is_empty()
        assert get_snapshot(conn, cutoff.isoformat(), "CN", "observed").height == len(records)
    summary = dict(
        reviewed_at=datetime.now().astimezone().isoformat(),
        raw_sha256=manifest["sha256"], first_seen_at=manifest["first_seen_at"],
        input_rows=cells.period.nunique(), input_indicators=len(profiles), input_cells=len(cells),
        zero_cells=int(cells.raw_value.eq(0).sum()), accepted_indicators=normalized.canonical_series_id.nunique(),
        accepted_cells=len(records), quarantined_cells=int(cells.status.eq("quarantined").sum()),
        reason_counts=dict(Counter(reason for x in cells.reasons for reason in x.split(";") if reason)),
        pit_grade="D", release_at=None, estimated_availability_implemented=False,
        validation=dict(raw_sha256_verified=True, duplicate_accepted_keys=int(normalized.duplicated(
            ["canonical_series_id", "period"]).sum()), in_memory_ingest=asdict(first), replay=asdict(replay),
            strict_and_loose_exclusion=True, first_seen_boundary=True,
            trade_identity_months=len(trade), trade_identity_tolerance_100mn_usd=0.02,
            trade_identity_exceedances=int(trade.balance_residual_100mn_usd.abs().gt(0.02).sum()),
            trade_identity_max_abs_100mn_usd=float(trade.balance_residual_100mn_usd.abs().max())),
    )
    if ingest:
        # Do not take a DB lock while the finite NBS worker still needs to write.
        if Path("data/history_backfill/nbs_price_batch.lock").exists():
            raise RuntimeError("Wind staging passed. NBS worker still holds its batch lock; retry ingestion after it exits.")
        export_files = sorted(Path("data/exports").glob("cn_pit_month_end_2005_20260731*"))
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in export_files}
        with get_connection(db_path) as conn:
            before = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            strict_before = get_snapshot(conn, manifest["first_seen_at"], "CN", "strict")
            result = insert_observations(conn, records)
            strict_after = get_snapshot(conn, manifest["first_seen_at"], "CN", "strict")
            assert strict_before.equals(strict_after), "PIT_D changed strict results"
            after = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            rows = conn.execute("SELECT source, count(*) n, count(distinct canonical_series_id) indicators "
                                "FROM observation_vintage WHERE country='CN' GROUP BY source ORDER BY source").fetchdf()
            rows.to_csv(output_dir / "cn_sources_after.csv", index=False, encoding="utf-8-sig")
        assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in export_files}
        ingestion = dict(stats=asdict(result), db_before=before, db_after=after,
                         strict_snapshot_unchanged=True, strict_exports_unchanged=True, export_sha256=hashes)
        old_path = output_dir / "ingestion_result.json"
        if old_path.exists():
            save_json(output_dir / "replay_result.json", ingestion)
        else:
            save_json(old_path, ingestion)
    if (output_dir / "ingestion_result.json").exists():
        summary["ingestion"] = json.loads((output_dir / "ingestion_result.json").read_text(encoding="utf-8"))
        summary["status"] = "PARTIAL_INGESTED"
    else:
        summary["status"] = "STAGED"
    # Display the original ingestion outcome on later read-only reviews as well.
    save_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("reports/v2/wind_batch1"))
    parser.add_argument("--db-path", default="macro_pit_v2.duckdb")
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    review(args.output_dir, ingest=args.ingest, db_path=args.db_path)
