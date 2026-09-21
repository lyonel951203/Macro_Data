"""Manual contract check for the new PIT_work freshness-first semantics.

Mirrors tests/test_work_mode.py without pytest tmp_path teardown (sandbox
blocks fixture cleanup). Creates throwaway DBs under the report dir and
leaves them in place.

Scenarios:
1. A not yet visible -> fresher WIND estimate fills (work_wind).
2. A visible for same-or-fresher period -> A wins (work_A).
3. Stale A (old period) vs fresher WIND estimate -> WIND wins (work_wind).
4. Strict snapshot before/after work export must be identical and D-free.
"""
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import polars as pl

sys.path.insert(0, r"E:\Macro_Data\src")
from macro_pit.db import get_connection, insert_observations  # noqa: E402
from macro_pit.pit import get_snapshot  # noqa: E402
from macro_pit.snapshot import build_monthly_wide_snapshot  # noqa: E402

CN = timezone(timedelta(hours=8))
BASE = Path(r"E:\Macro_Data\reports\v2\wind_batch5_cpi_ppi\manual_contract")
BASE.mkdir(parents=True, exist_ok=True)
OUT = Path(r"E:\Macro_Data\reports\v2\wind_batch5_cpi_ppi\manual_contract_check.txt")


def base_row(**over):
    row = {
        "country": "CN", "source": "NBS", "canonical_series_id": "CN_X",
        "source_series_id": "x1", "series_name": "X", "frequency": "M",
        "unit": "pct_yoy", "period": "2020-01", "period_start": "2020-01-01",
        "period_end": "2020-01-31", "value": 1.0,
        "release_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "first_seen_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "available_at": datetime(2020, 2, 11, 10, 0, tzinfo=CN),
        "pit_grade": "A", "source_url": "http://example.gov/x",
        "raw_file": "raw/x.html", "raw_sha256": "abc123",
        "retrieved_at": datetime(2020, 2, 11, 12, 0, tzinfo=CN),
        "parser_version": "t1",
    }
    row.update(over)
    return row


def wind_row(series, period, period_end, value):
    return base_row(
        source="WIND", canonical_series_id=series, period=period,
        period_end=period_end, value=value, release_at=None, pit_grade="D",
        first_seen_at=datetime(2026, 9, 8, 14, 10, tzinfo=CN),
        available_at=datetime(2026, 9, 8, 14, 10, tzinfo=CN), raw_sha256="N/A",
    )


def write_sidecar(path, rows):
    buf = io.StringIO()
    buf.write("canonical_series_id,source,period,period_end,value,"
              "estimated_release_date,estimated_available_at\n")
    for r in rows:
        buf.write(f"{r['series']},WIND,{r['period']},{r['period_end']},{r['value']},"
                  f"{r['est_release']},{r['est_available']}\n")
    path.write_text(buf.getvalue(), encoding="utf-8")


results = []


def check(name, cond, detail=""):
    results.append(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")


# --- Scenario 1&2: original waterfall cases still hold -------------------
db1 = BASE / "case1.duckdb"
conn = get_connection(db1)
insert_observations(conn, [base_row()])
insert_observations(conn, [wind_row("CN_X", "2019-12", "2019-12-31", 9.9),
                           wind_row("CN_Y", "2020-01", "2020-01-31", 5.0)])
conn.close()
sc1 = BASE / "est1.csv"
write_sidecar(sc1, [
    {"series": "CN_X", "period": "2019-12", "period_end": "2019-12-31",
     "value": 9.9, "est_release": "2020-01-12",
     "est_available": "2020-01-13T00:00:00+08:00"},
    {"series": "CN_Y", "period": "2020-01", "period_end": "2020-01-31",
     "value": 5.0, "est_release": "2020-02-12",
     "est_available": "2020-02-13T00:00:00+08:00"},
])
conn = duckdb.connect(str(db1), read_only=True)
paths = build_monthly_wide_snapshot(conn, BASE / "work1", "2020-01-31", "2020-02-29",
                                    pit_mode="work", estimated_availability_path=sc1)
conn.close()
values = pl.read_csv(paths["values_csv"])
prov = pl.read_csv(paths["provenance_csv"])
check("S1 jan: WIND fills before A visible", values.row(0, named=True)["CN_X"] == 9.9
      and prov.row(0, named=True)["CN_X"] == "work_wind")
check("S2 feb: A wins once visible", values.row(1, named=True)["CN_X"] == 1.0
      and prov.row(1, named=True)["CN_X"] == "work_A")
check("S2: WIND-only series dropped from panel", "CN_Y" not in values.columns)

# --- Scenario 3: fresher WIND beats stale A -------------------------------
db2 = BASE / "case2.duckdb"
conn = get_connection(db2)
insert_observations(conn, [base_row(
    canonical_series_id="CN_Z", period="2019-12", period_end="2019-12-31",
    value=1.0,
    release_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN),
    first_seen_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN),
    available_at=datetime(2020, 1, 12, 10, 0, tzinfo=CN))])
insert_observations(conn, [wind_row("CN_Z", "2020-01", "2020-01-31", 7.7)])
conn.close()
sc2 = BASE / "est2.csv"
write_sidecar(sc2, [
    {"series": "CN_Z", "period": "2020-01", "period_end": "2020-01-31",
     "value": 7.7, "est_release": "2020-02-12",
     "est_available": "2020-02-13T00:00:00+08:00"},
])
conn = duckdb.connect(str(db2), read_only=True)
paths = build_monthly_wide_snapshot(conn, BASE / "work2", "2020-01-31", "2020-02-29",
                                    pit_mode="work", estimated_availability_path=sc2)
conn.close()
values = pl.read_csv(paths["values_csv"])
prov = pl.read_csv(paths["provenance_csv"])
check("S3 jan: stale A shown while freshest", values.row(0, named=True)["CN_Z"] == 1.0
      and prov.row(0, named=True)["CN_Z"] == "work_A")
check("S3 feb: fresher WIND beats stale A", values.row(1, named=True)["CN_Z"] == 7.7
      and prov.row(1, named=True)["CN_Z"] == "work_wind")

# --- Scenario 4: strict mode untouched ------------------------------------
conn = duckdb.connect(str(db1), read_only=True)
before = get_snapshot(conn, "2020-02-29 23:59:59+08:00", country="CN", pit_mode="strict")
build_monthly_wide_snapshot(conn, BASE / "work3", "2020-01-31", "2020-02-29",
                            pit_mode="work", estimated_availability_path=sc1)
after = get_snapshot(conn, "2020-02-29 23:59:59+08:00", country="CN", pit_mode="strict")
conn.close()
check("S4: strict snapshot identical after work export",
      before.select(["canonical_series_id", "period", "value"]).rows()
      == after.select(["canonical_series_id", "period", "value"]).rows())
check("S4: strict contains no WIND rows", set(after["source"].to_list()) == {"NBS"})

OUT.write_text("\n".join(results), encoding="utf-8")
print("\n".join(results))
