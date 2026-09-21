"""Read-only audit of CN official/Wind overlap and current PIT continuity.

Run from the repository root:
python scripts/one_off/2026-09-21/audit_cn_wind_quality.py
The comparison uses the latest stored official vintage versus the imported
Wind base snapshot for each identical field/period. This is a reconciliation,
not a claim that the two values were simultaneously available historically.
"""

from __future__ import annotations

import calendar
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from macro_pit.asof_wide import build_as_of_wide


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "macro_pit_v2.duckdb"
OUT = ROOT / "reports" / "v2" / "cn_wind_quality_current_20260921"
AS_OF = "2026-09-21"


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def month_number(period: str) -> int:
    year, month = map(int, period.split("-"))
    return year * 12 + month - 1


def period_from_number(number: int) -> str:
    year, zero_month = divmod(number, 12)
    return f"{year:04d}-{zero_month + 1:02d}"


def runs(numbers: list[int]) -> list[list[int]]:
    output: list[list[int]] = []
    for number in sorted(numbers):
        if not output or number != output[-1][-1] + 1:
            output.append([number])
        else:
            output[-1].append(number)
    return output


def reconciliation(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    sql = """
    WITH official AS (
      SELECT canonical_series_id, period, pit_grade, source, unit,
             value, CAST(available_at AS VARCHAR) AS available_at
      FROM observation_vintage
      WHERE country = 'CN' AND pit_grade IN ('A','B')
      QUALIFY row_number() OVER (
        PARTITION BY canonical_series_id, period, pit_grade
        ORDER BY available_at DESC, vintage_no DESC, retrieved_at DESC
      ) = 1
    ), wind AS (
      SELECT canonical_series_id, period, unit, value,
             CAST(available_at AS VARCHAR) AS available_at
      FROM observation_vintage
      WHERE country = 'CN' AND source = 'WIND' AND pit_grade = 'D'
        AND coalesce(release_date_source,'') NOT LIKE 'wind_revision_snapshot_%'
      QUALIFY row_number() OVER (
        PARTITION BY canonical_series_id, period
        ORDER BY retrieved_at DESC, vintage_no DESC
      ) = 1
    )
    SELECT o.canonical_series_id, o.period, o.pit_grade, o.source,
           o.unit, w.unit, o.value, w.value,
           o.available_at, w.available_at
    FROM official o JOIN wind w USING (canonical_series_id, period)
    ORDER BY o.pit_grade, o.canonical_series_id, o.period
    """
    output = []
    for field, period, grade, source, unit, wind_unit, official, wind, official_at, wind_at in conn.execute(sql).fetchall():
        difference = official - wind
        output.append({
            "field": field, "period": period, "official_grade": grade,
            "official_source": source, "unit": unit, "wind_unit": wind_unit,
            "official_value": official, "wind_value": wind,
            "difference": round(difference, 10),
            "abs_difference": round(abs(difference), 10),
            "exact_within_1e_9": abs(difference) <= 1e-9,
            "official_available_at": official_at,
            "wind_record_available_at": wind_at,
        })
    return output


def continuity(conn: duckdb.DuckDBPyConnection) -> tuple[list[dict], list[dict], list[dict]]:
    panel = build_as_of_wide(conn, AS_OF, "CN", frequency="M")
    metadata = {row["canonical_series_id"]: row for row in panel.metadata.to_dicts()}
    by_field: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in panel.selected_long.to_dicts():
        if metadata[row["canonical_series_id"]]["frequency"] != "M":
            continue  # GDP is quarterly, so other months are structurally empty.
        by_field[row["canonical_series_id"]][month_number(row["period"])] = row

    coverage: list[dict] = []
    missing: list[dict] = []
    repeated: list[dict] = []
    for field, observed in sorted(by_field.items()):
        first, last = min(observed), max(observed)
        absent = [month for month in range(first, last + 1) if month not in observed]
        non_january = [month for month in absent if month % 12 != 0]
        january = [month for month in absent if month % 12 == 0]
        non_jan_runs = runs(non_january)
        all_runs = runs(absent)
        coverage.append({
            "field": field, "name": metadata[field]["series_name"],
            "first": period_from_number(first), "last": period_from_number(last),
            "expected_months_first_to_last": last - first + 1,
            "present_months": len(observed), "missing_total": len(absent),
            "missing_january": len(january), "missing_non_january": len(non_january),
            "missing_non_january_single_month_runs": sum(len(run) == 1 for run in non_jan_runs),
            "missing_non_january_multi_month_runs": sum(len(run) >= 2 for run in non_jan_runs),
            "longest_non_january_missing_run": max(map(len, non_jan_runs), default=0),
        })
        for run in all_runs:
            missing.append({
                "field": field, "start": period_from_number(run[0]),
                "end": period_from_number(run[-1]), "months": len(run),
                "january_months": sum(month % 12 == 0 for month in run),
                "non_january_months": sum(month % 12 != 0 for month in run),
                "note": "January may be a combined-publication period; verify indicator/year before exemption"
                if any(month % 12 == 0 for month in run) else "Requires source/definition review",
            })
        # Equal values count only across consecutive *data periods*. Gaps break a run.
        equal_groups: list[list[int]] = []
        for month in sorted(observed):
            if (equal_groups and month == equal_groups[-1][-1] + 1
                    and abs(observed[month]["value"] - observed[equal_groups[-1][-1]]["value"]) <= 1e-9):
                equal_groups[-1].append(month)
            else:
                equal_groups.append([month])
        for group in equal_groups:
            if len(group) < 3:
                continue
            repeated.append({
                "field": field, "start": period_from_number(group[0]),
                "end": period_from_number(group[-1]), "months": len(group),
                "value": observed[group[0]]["value"],
                "unit": observed[group[0]]["unit"],
                "origins": "+".join(sorted({observed[month]["selection_origin"] for month in group})),
                "sources": "+".join(sorted({observed[month]["source"] for month in group})),
            })
    return coverage, missing, repeated


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB), read_only=True)
    pairs = reconciliation(conn)
    coverage, missing, repeated = continuity(conn)
    write_rows(OUT / "official_vs_wind.csv", list(pairs[0]), pairs)
    write_rows(OUT / "monthly_coverage.csv", list(coverage[0]), coverage)
    write_rows(OUT / "internal_missing_runs.csv", list(missing[0]), missing)
    write_rows(OUT / "consecutive_equal_values_3plus.csv", list(repeated[0]), repeated)
    print("pairs", len(pairs), "coverage_fields", len(coverage),
          "missing_runs", len(missing), "equal_runs_3plus", len(repeated))
    for grade in "AB":
        subset = [row for row in pairs if row["official_grade"] == grade]
        print(grade, len(subset), "exact", sum(row["exact_within_1e_9"] for row in subset),
              "fields", len({row["field"] for row in subset}))
    print("missing", sum(row["missing_total"] for row in coverage),
          "january", sum(row["missing_january"] for row in coverage),
          "other", sum(row["missing_non_january"] for row in coverage))


if __name__ == "__main__":
    main()
