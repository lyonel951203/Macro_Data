"""Stage three January unemployment observations held from Wind batch 10.

Values remain WIND/PIT_D. Same-period official publications only anchor
the research sidecar availability timestamps; they do not regrade rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "reports/v2/wind_midgap_20260921/wind_cli_2018_2021.json"
BATCH10 = ROOT / "data/manual_import/wind_mcp/batch10_midgap_2018_2021.json"
OVERRIDES = ROOT / "config/estimated_availability_overrides_v1.csv"
OUTPUT = ROOT / "data/manual_import/wind_mcp/batch11_january_unemployment_2019_2021.json"
CANONICAL = "CN_URBAN_SURVEYED_UNEMPLOYMENT"
WIND_CODE = "M5650805"
DATES = {"20190131", "20200131", "20210131"}


def main() -> None:
    raw_bytes = RAW.read_bytes()
    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
    previous = json.loads(BATCH10.read_text(encoding="utf-8"))
    if previous["upstream_raw_sha256"] != raw_hash:
        raise ValueError("Wind raw file differs from reviewed batch 10")
    envelope = json.loads(raw_bytes.decode("utf-8"))
    if envelope.get("isError") or envelope.get("ok") is False:
        raise ValueError("Wind CLI returned an error")
    metrics = json.loads(envelope["content"][0]["text"])["metrics"]
    source_block = next(block for block in metrics if block["meta"]["code"] == WIND_CODE)
    prior_block = next(block for block in previous["response"]["data"] if block["meta"]["code"] == WIND_CODE)
    meta = source_block["meta"]
    if meta != prior_block["meta"]:
        raise ValueError("Wind metadata differs from reviewed batch 10")
    selected = [
        (day, value)
        for day, value in zip(source_block["date"], source_block["value"])
        if day in DATES
    ]
    if {day for day, _ in selected} != DATES or len(selected) != len(DATES):
        raise ValueError("expected exactly three January dates")
    with OVERRIDES.open(encoding="utf-8-sig", newline="") as handle:
        anchors = {
            row["period"]: row
            for row in csv.DictReader(handle)
            if row["canonical_series_id"] == CANONICAL and row["source"] == "WIND"
        }
    if set(anchors) != {f"{day[:4]}-01" for day in DATES}:
        raise ValueError("January availability anchors do not match Wind dates")
    for day, value in selected:
        if abs(float(value) - float(anchors[f"{day[:4]}-01"]["value"])) > 1e-9:
            raise ValueError(f"official/Wind January value mismatch: {day}")
    conn = duckdb.connect(str(ROOT / "macro_pit_v2.duckdb"), read_only=True)
    existing = conn.execute(
        """SELECT period, value, pit_grade, source FROM observation_vintage
           WHERE country='CN' AND canonical_series_id=?
             AND period IN ('2019-01','2020-01','2021-01')""",
        [CANONICAL],
    ).fetchall()
    conn.close()
    for period, value, grade, source in existing:
        if source != "WIND" or grade != "D" or abs(float(value) - float(anchors[period]["value"])) > 1e-9:
            raise ValueError(f"unexpected existing January version: {period} {source}/{grade} {value}")
    payload = {
        "pulled_at": previous["pulled_at"],
        "channel": previous["channel"],
        "source_url": previous["source_url"],
        "request": previous["request"],
        "upstream_raw_file": previous["upstream_raw_file"],
        "upstream_raw_sha256": raw_hash,
        "response": {
            "data": [{
                "meta": meta,
                "date": [day for day, _ in selected],
                "value": [value for _, value in selected],
            }]
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") != serialized:
        raise ValueError("existing batch 11 differs; refusing to rewrite immutable source")
    OUTPUT.write_text(serialized, encoding="utf-8")
    print(f"staged={len(selected)} existing={len(existing)} raw_sha256={raw_hash}")


if __name__ == "__main__":
    main()
