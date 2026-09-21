"""Stage verified Wind EDB values for two NBS mid-history PIT gaps.

The raw Wind CLI envelope is preserved separately. This script only stages
periods absent from official A/B, and holds January unemployment until its
historical publication calendar has been verified.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "reports/v2/wind_midgap_20260921/wind_cli_2018_2021.json"
STAGED = ROOT / "data/manual_import/wind_mcp/batch10_midgap_2018_2021.json"
REPORT_DIR = ROOT / "reports/v2/wind_midgap_20260921"
FIELDS = {
    "M5809944": ("CN_PMI_COMPOSITE", "中国综合PMI:产出指数", "%"),
    "M5650805": ("CN_URBAN_SURVEYED_UNEMPLOYMENT", "中国:城镇调查失业率", "%"),
}


def main() -> None:
    raw_bytes = RAW.read_bytes()
    envelope = json.loads(raw_bytes.decode("utf-8"))
    if envelope.get("isError") or envelope.get("ok") is False:
        raise ValueError("Wind CLI returned an error, not a data response")
    metrics = json.loads(envelope["content"][0]["text"])["metrics"]
    if {block["meta"]["code"] for block in metrics} != set(FIELDS):
        raise ValueError("unexpected Wind code set")
    connection = duckdb.connect(str(ROOT / "macro_pit_v2.duckdb"), read_only=True)
    staged_blocks = []
    overlap_rows = []
    held_rows = []
    for block in metrics:
        meta = block["meta"]
        code = meta["code"]
        field, name, unit = FIELDS[code]
        if (meta["name"], meta["unit"], meta["freq"], meta["source"]) != (
            name, unit, "月", "国家统计局"
        ):
            raise ValueError(f"Wind metadata changed for {code}: {meta}")
        dates, values = block["date"], block["value"]
        if len(dates) != len(values) or len(dates) != 48:
            raise ValueError(f"expected 48 monthly values for {code}")
        official = dict(connection.execute(
            """SELECT period, value FROM observation_vintage
               WHERE country='CN' AND canonical_series_id=? AND pit_grade IN ('A','B')
                 AND period BETWEEN '2018-01' AND '2021-12'
               QUALIFY row_number() OVER (
                 PARTITION BY period ORDER BY available_at DESC, vintage_no DESC
               )=1""",
            [field],
        ).fetchall())
        kept_dates, kept_values = [], []
        for day, value in zip(dates, values):
            period = f"{day[:4]}-{day[4:6]}"
            if period in official:
                difference = float(official[period]) - float(value)
                if abs(difference) > 0.05 + 1e-9:
                    raise ValueError(f"official/Wind overlap differs too much: {field} {period}")
                overlap_rows.append((field, period, official[period], value, difference))
            elif field == "CN_URBAN_SURVEYED_UNEMPLOYMENT" and day[4:6] == "01":
                held_rows.append((field, period, value, "January release calendar unverified"))
            else:
                kept_dates.append(day)
                kept_values.append(value)
        staged_blocks.append({"meta": meta, "date": kept_dates, "value": kept_values})
    connection.close()
    by_code = {block["meta"]["code"]: block for block in staged_blocks}
    if len(by_code["M5809944"]["date"]) != 41 or len(by_code["M5650805"]["date"]) != 38:
        raise ValueError("unexpected staged gap counts")
    payload = {
        "pulled_at": datetime.now().astimezone().isoformat(),
        "channel": "wind-mcp:economic_data.query_economic_indicator_data",
        "source_url": "wind-mcp://economic_data/query_economic_indicator_data",
        "request": {"question": "M5809944,M5650805", "beginDate": "2018-01-01", "endDate": "2021-12-31"},
        "upstream_raw_file": str(RAW.relative_to(ROOT)).replace("\\", "/"),
        "upstream_raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "response": {"data": staged_blocks},
    }
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for filename, header, rows in (
        ("official_overlap.csv", ["field", "period", "official", "wind", "difference"], overlap_rows),
        ("held_january.csv", ["field", "period", "wind", "reason"], held_rows),
    ):
        with (REPORT_DIR / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
    print(f"staged={sum(len(block['date']) for block in staged_blocks)} "
          f"official_overlap={len(overlap_rows)} held_january={len(held_rows)}")


if __name__ == "__main__":
    main()
