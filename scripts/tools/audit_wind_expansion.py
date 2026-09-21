"""Read-only reconciliation of the Wind expansion against the PIT database."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import duckdb


def main() -> None:
    connection = duckdb.connect("macro_pit_v2.duckdb", read_only=True)
    queries = {
        "source_grade": """
            SELECT source, pit_grade, count(*) AS row_count,
                   count(DISTINCT canonical_series_id) AS series_count,
                   min(period) AS min_period, max(period) AS max_period
            FROM observation_vintage
            WHERE country='CN'
            GROUP BY 1,2 ORDER BY 1,2
        """,
        "wind_series": """
            SELECT canonical_series_id, count(*) AS row_count,
                   count(DISTINCT period) AS period_count,
                   min(period) AS first_period, max(period) AS last_period,
                   count(DISTINCT source_series_id) AS wind_code_count,
                   min(cast(first_seen_at AS varchar)) AS first_seen,
                   max(cast(first_seen_at AS varchar)) AS last_seen
            FROM observation_vintage
            WHERE country='CN' AND source='WIND'
            GROUP BY 1 ORDER BY 1
        """,
        "wind_grades": """
            SELECT pit_grade, count(*) AS row_count,
                   count(*) FILTER (WHERE release_at IS NOT NULL) AS released_rows,
                   count(*) FILTER (WHERE available_at < first_seen_at) AS backdated_rows
            FROM observation_vintage WHERE source='WIND' GROUP BY 1
        """,
        "duplicate_signatures": """
            SELECT count(*) FROM (
              SELECT source, canonical_series_id, period, value,
                     cast(available_at AS varchar), count(*) AS copies
              FROM observation_vintage WHERE source='WIND'
              GROUP BY 1,2,3,4,5 HAVING count(*)>1
            )
        """,
        "multi_vintage_periods": """
            SELECT canonical_series_id, count(*) AS keys_with_multiple_vintages
            FROM (
              SELECT canonical_series_id, period, count(*) AS versions
              FROM observation_vintage WHERE source='WIND'
              GROUP BY 1,2 HAVING count(*)>1
            ) GROUP BY 1 ORDER BY 1
        """,
    }
    for title, query in queries.items():
        print(f"\n## {title}")
        for row in connection.execute(query).fetchall():
            print(row)

    print("\n## summaries")
    for filename in sorted(glob.glob("reports/v2/history/wind/wind_batch*/summary.json")):
        path = Path(filename)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            print(filename, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            print(filename, "ERROR", exc)

    print("\n## ingestion")
    for filename in sorted(glob.glob("reports/v2/history/wind/wind_batch*/ingestion_result.json")):
        print(filename, Path(filename).read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    main()
