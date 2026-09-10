from __future__ import annotations

import html
from pathlib import Path

import polars as pl

from .sources import ALL_SOURCES


INVENTORY_SCHEMA = {
    "source": pl.String,
    "dataset": pl.String,
    "url": pl.String,
    "earliest_period": pl.String,
    "latest_period": pl.String,
    "frequency": pl.String,
    "format": pl.String,
    "archive_available": pl.Boolean,
    "release_timestamp_available": pl.Boolean,
    "historical_revision_available": pl.Boolean,
    "estimated_count": pl.Int64,
    "evidence": pl.String,
}


def build_declared_inventory() -> pl.DataFrame:
    """Build an offline inventory without inventing historical coverage dates."""
    rows: list[dict] = []
    for source_class in ALL_SOURCES:
        source = source_class(allow_network=False)
        try:
            rows.extend(item.to_dict() for item in source.inventory())
        finally:
            source.close()
    return pl.DataFrame(rows, schema=INVENTORY_SCHEMA)


def run_discovery(
    *,
    data_dir: str | Path = "data",
    reports_dir: str | Path = "reports",
) -> tuple[Path, Path]:
    """Write the offline declared inventory and its evidence report.

    Unknown earliest/latest periods remain null until a separately authorized,
    rate-limited network discovery run verifies them.
    """
    data_path = Path(data_dir)
    reports_path = Path(reports_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)
    frame = build_declared_inventory()
    parquet_path = data_path / "source_inventory.parquet"
    report_path = reports_path / "source_inventory.html"
    frame.write_parquet(parquet_path)
    report_path.write_text(_render_html(frame), encoding="utf-8")
    return parquet_path, report_path


def _render_html(frame: pl.DataFrame) -> str:
    rows = []
    for row in frame.iter_rows(named=True):
        values = [
            row["source"], row["dataset"], row["earliest_period"] or "UNVERIFIED",
            row["latest_period"] or "UNVERIFIED", str(row["release_timestamp_available"]),
            str(row["historical_revision_available"]), row["evidence"],
        ]
        rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>")
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Source Inventory</title>
<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.4rem;vertical-align:top}.warn{color:#9a6700}</style>
</head><body><h1>Phase 1 Source Inventory</h1>
<p class="warn">UNVERIFIED 表示尚未执行经授权的低频网络发现，不代表已完成历史覆盖。</p>
<table><thead><tr><th>Source</th><th>Dataset</th><th>Earliest</th><th>Latest</th><th>Release time</th><th>Revisions</th><th>Evidence</th></tr></thead>
<tbody>""" + "".join(rows) + "</tbody></table></body></html>"
