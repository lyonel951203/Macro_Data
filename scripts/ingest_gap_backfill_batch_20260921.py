"""Ingest the first official-first, gap-only backfill batch.

Policy enforced by this batch:

* official PIT A/B records are authoritative;
* ordinary Wind PIT D may be written only when the field-period has no row
  from any source;
* official evidence is inserted before the Wind fallback check;
* no existing row is updated or deleted.

The batch contains:

* NBS/PIT_A: May 2010 manufacturing PMI and five components, disclosed in
  the official 1 July 2010 table;
* NBS/PIT_A: December 2025 commodity-housing sales area/value YTD YoY;
* WIND/PIT_D: April 2010 manufacturing PMI and five components;
* WIND/PIT_D: January 2020 M1 YoY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from macro_pit.db import get_connection, insert_observations


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "macro_pit_v2.duckdb"
REPORT_DIR = ROOT / "reports/v2/gap_backfill_batches_20260921"
PMI_RAW = ROOT / "data/raw/nbs/2026/09/09/55091bb9f7f878262847cfd4ba79724bea9983a808577b31c6b872f8891a131c.html"
HOME_RAW = ROOT / "data/raw/nbs/2026/09/10/193910cc11c03b6dc4d55b7e6812098433daf5d4f4c6b8612af324b31645cbb0.html"
WIND_M1_RAW = REPORT_DIR / "wind_cli_m1_201912_202002.json"
WIND_PMI_RAW = REPORT_DIR / "wind_cli_pmi_201003_201006.json"
CN_TZ = ZoneInfo("Asia/Shanghai")

PMI_FIELDS = {
    "M0017126": ("CN_PMI_MANUFACTURING", "PMI_MANUFACTURING", "制造业采购经理指数"),
    "M0017127": ("CN_PMI_PRODUCTION", "PMI_PRODUCTION", "制造业PMI生产指数"),
    "M0017128": ("CN_PMI_NEW_ORDERS", "PMI_NEW_ORDERS", "制造业PMI新订单指数"),
    "M0017135": ("CN_PMI_RAW_MATERIAL_INVENTORY", "PMI_RAW_MATERIAL_INVENTORY", "制造业PMI原材料库存指数"),
    "M0017136": ("CN_PMI_EMPLOYMENT", "PMI_EMPLOYMENT", "制造业PMI从业人员指数"),
    "M0017137": ("CN_PMI_SUPPLIER_DELIVERY", "PMI_SUPPLIER_DELIVERY", "制造业PMI供应商配送时间指数"),
}
PMI_MAY_VALUES = [53.9, 58.2, 54.8, 51.0, 52.1, 50.9]
PMI_APR_VALUES = [55.7, 59.1, 59.3, 51.5, 53.2, 51.1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_wind(path: Path) -> dict[str, dict]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if envelope.get("isError") or envelope.get("ok") is False:
        raise ValueError(f"Wind error envelope: {path}")
    return {
        block["meta"]["code"]: block
        for block in json.loads(envelope["content"][0]["text"])["metrics"]
    }


def table_rows(path: Path) -> list[list[list[str]]]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        tables.append(rows)
    return tables


def completed_at(conn, raw_hash: str) -> datetime:
    row = conn.execute(
        "SELECT completed_at FROM crawl_log WHERE raw_sha256=? AND success=true ORDER BY completed_at LIMIT 1",
        [raw_hash],
    ).fetchone()
    if row is None:
        raise ValueError(f"missing successful crawl_log row for {raw_hash}")
    return row[0]


def base_record(*, source: str, canonical: str, source_id: str, name: str,
                period: str, value: float, unit: str, seasonal: str | None,
                release_at: datetime | None, release_date_source: str | None,
                first_seen: datetime, source_url: str, raw_file: Path,
                raw_hash: str, parser_version: str) -> dict:
    year, month = map(int, period.split("-"))
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    period_start = date(year, month, 1)
    period_end = date.fromordinal(next_month.toordinal() - 1)
    return {
        "country": "CN",
        "source": source,
        "canonical_series_id": canonical,
        "source_series_id": source_id,
        "series_name": name,
        "frequency": "M",
        "unit": unit,
        "seasonal_adjustment": seasonal,
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "value": float(value),
        "release_at": release_at,
        "release_date_source": release_date_source,
        "first_seen_at": first_seen,
        "available_at": release_at if release_at is not None else first_seen,
        "pit_grade": "A" if release_at is not None else "D",
        "source_url": source_url,
        "raw_file": str(raw_file.relative_to(ROOT)).replace("\\", "/"),
        "raw_sha256": raw_hash,
        "retrieved_at": first_seen,
        "parser_version": parser_version,
    }


def build_records(conn) -> tuple[list[dict], list[dict]]:
    pmi_hash = sha256(PMI_RAW)
    home_hash = sha256(HOME_RAW)
    if pmi_hash != PMI_RAW.stem or home_hash != HOME_RAW.stem:
        raise ValueError("official raw filename/hash mismatch")

    # The official page contains the May column directly beside the June column.
    pmi_tables = table_rows(PMI_RAW)
    expected_pmi_rows = [
        ["PMI", "52.1", "53.9"],
        [None, "55.8", "58.2"],
        [None, "52.1", "54.8"],
        [None, "49.4", "51.0"],
        [None, "50.6", "52.1"],
        [None, "50.0", "50.9"],
    ]
    candidate = next((table for table in pmi_tables if len(table) == 7 and table[1][0] == "PMI"), None)
    if candidate is None:
        raise ValueError("official PMI table not found")
    for row, expected in zip(candidate[1:], expected_pmi_rows):
        if row[1:] != expected[1:] or (expected[0] is not None and row[0] != expected[0]):
            raise ValueError(f"official PMI table changed: {row}")

    # The official property table contains the national total for both fields.
    home_tables = table_rows(HOME_RAW)
    if not any(["88101", "-8.7", "83937", "-12.6"] == row[-4:] for table in home_tables for row in table):
        raise ValueError("official 2025 housing-sales row not found")

    pmi_seen = completed_at(conn, pmi_hash)
    home_seen = completed_at(conn, home_hash)
    official: list[dict] = []
    pmi_release = datetime(2010, 7, 1, 10, 54, tzinfo=CN_TZ)
    for (_, (canonical, source_id, name)), value in zip(PMI_FIELDS.items(), PMI_MAY_VALUES):
        official.append(base_record(
            source="NBS", canonical=canonical, source_id=source_id, name=name,
            period="2010-05", value=value, unit="index", seasonal="SA",
            release_at=pmi_release, release_date_source="official_page_timestamp",
            first_seen=pmi_seen,
            source_url="https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919203.html",
            raw_file=PMI_RAW, raw_hash=pmi_hash,
            parser_version="nbs_official_gap_table_v1",
        ))

    home_release = datetime(2026, 1, 19, 10, 0, tzinfo=CN_TZ)
    for canonical, source_id, name, value in [
        ("CN_NEW_HOME_SALES_AREA_YTD_YOY", "NEW_HOME_SALES_AREA_YTD_YOY", "新建商品房销售面积累计同比", -8.7),
        ("CN_NEW_HOME_SALES_VALUE_YTD_YOY", "NEW_HOME_SALES_VALUE_YTD_YOY", "新建商品房销售额累计同比", -12.6),
    ]:
        official.append(base_record(
            source="NBS", canonical=canonical, source_id=source_id, name=name,
            period="2025-12", value=value, unit="pct_yoy", seasonal="NSA",
            release_at=home_release, release_date_source="official_page_metadata",
            first_seen=home_seen,
            source_url="https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962324.html",
            raw_file=HOME_RAW, raw_hash=home_hash,
            parser_version="nbs_official_gap_table_v1",
        ))

    pulled_at = datetime.now().astimezone()
    wind: list[dict] = []
    m1 = parse_wind(WIND_M1_RAW)
    block = m1.get("M0001383")
    if block is None or block["meta"] != {
        "code": "M0001383", "name": "中国:M1:同比", "unit": "%",
        "source": "中国人民银行", "updateDate": "20260914",
        "beginDate": "19861231", "endDate": "20260831", "freq": "月",
    }:
        raise ValueError("unexpected M1 Wind metadata")
    m1_values = dict(zip(block["date"], block["value"]))
    if m1_values.get("20200131") != 0:
        raise ValueError("unexpected M1 January 2020 value")
    wind.append(base_record(
        source="WIND", canonical="CN_M1_YOY", source_id="M0001383", name="中国:M1:同比",
        period="2020-01", value=0.0, unit="pct_yoy", seasonal=None,
        release_at=None, release_date_source=None, first_seen=pulled_at,
        source_url="wind-mcp://economic_data/query_economic_indicator_data",
        raw_file=WIND_M1_RAW, raw_hash=sha256(WIND_M1_RAW),
        parser_version="wind_edb_gap_only_v1",
    ))

    pmi = parse_wind(WIND_PMI_RAW)
    if set(pmi) != set(PMI_FIELDS):
        raise ValueError("unexpected PMI Wind code set")
    for (code, (canonical, _, name)), expected in zip(PMI_FIELDS.items(), PMI_APR_VALUES):
        block = pmi[code]
        meta = block["meta"]
        if (meta["name"], meta["unit"], meta["source"], meta["freq"]) != (
            {"M0017126": "中国:制造业PMI", "M0017127": "中国:制造业PMI:生产",
             "M0017128": "中国:制造业PMI:新订单", "M0017135": "中国:制造业PMI:原材料库存",
             "M0017136": "中国:制造业PMI:从业人员", "M0017137": "中国:制造业PMI:供货商配送时间"}[code],
            "%", "国家统计局", "月",
        ):
            raise ValueError(f"unexpected PMI Wind metadata for {code}")
        values = dict(zip(block["date"], block["value"]))
        if float(values.get("20100430")) != expected:
            raise ValueError(f"unexpected April 2010 Wind value for {code}")
        wind.append(base_record(
            source="WIND", canonical=canonical, source_id=code, name=name,
            period="2010-04", value=expected, unit="index", seasonal="SA",
            release_at=None, release_date_source=None, first_seen=pulled_at,
            source_url="wind-mcp://economic_data/query_economic_indicator_data",
            raw_file=WIND_PMI_RAW, raw_hash=sha256(WIND_PMI_RAW),
            parser_version="wind_edb_gap_only_v1",
        ))
    return official, wind


def rows_for_existing_key(conn, row: dict) -> list[tuple]:
    return conn.execute(
        """SELECT source, pit_grade, value FROM observation_vintage
           WHERE country=? AND canonical_series_id=? AND period=?
           ORDER BY source, vintage_no""",
        [row["country"], row["canonical_series_id"], row["period"]],
    ).fetchall()


def write_plan(rows: list[dict]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "canonical_series_id", "period", "value", "source", "pit_grade",
        "release_at", "available_at", "source_url", "raw_file",
    ]
    with (REPORT_DIR / "accepted_values_long.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--ingest", action="store_true")
    args = parser.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection(args.db_path, read_only=True) as conn:
        official, wind = build_records(conn)
        official_existing = {f"{row['canonical_series_id']}|{row['period']}": rows_for_existing_key(conn, row) for row in official}
        wind_existing = {f"{row['canonical_series_id']}|{row['period']}": rows_for_existing_key(conn, row) for row in wind}
    unexpected_official = {key: value for key, value in official_existing.items() if value}
    unexpected_wind = {key: value for key, value in wind_existing.items() if value}
    if unexpected_official:
        raise ValueError(f"official batch target is no longer empty: {unexpected_official}")
    if unexpected_wind:
        raise ValueError(f"Wind gap-only target is no longer empty: {unexpected_wind}")

    planned = official + wind
    write_plan(planned)
    summary = {
        "policy": "PIT_A/PIT_B authoritative; ordinary Wind PIT_D only for fully empty field-periods",
        "status": "STAGED",
        "official_a_rows": len(official),
        "wind_d_gap_rows": len(wind),
        "planned_rows": len(planned),
        "official_targets": [f"{row['canonical_series_id']}|{row['period']}" for row in official],
        "wind_targets": [f"{row['canonical_series_id']}|{row['period']}" for row in wind],
    }

    if args.ingest:
        if (ROOT / "data/history_backfill/nbs_price_batch.lock").exists():
            raise RuntimeError("NBS worker holds its batch lock; retry after it exits")
        with get_connection(args.db_path) as conn:
            before = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            official_result = insert_observations(conn, official)
            # Recheck immediately before inserting Wind. This is the guard that
            # prevents a newly arrived official or any other source from being
            # duplicated by a fallback row.
            collisions = {
                f"{row['canonical_series_id']}|{row['period']}": rows_for_existing_key(conn, row)
                for row in wind if rows_for_existing_key(conn, row)
            }
            if collisions:
                raise ValueError(f"Wind gap-only collision after official insert: {collisions}")
            wind_result = insert_observations(conn, wind)
            after = conn.execute("SELECT count(*) FROM observation_vintage").fetchone()[0]
            if official_result.inserted != len(official) or wind_result.inserted != len(wind):
                raise ValueError(f"unexpected insert stats: official={official_result}, wind={wind_result}")
            for row in official:
                selected = rows_for_existing_key(conn, row)
                if not any(src == "NBS" and grade == "A" and abs(value - row["value"]) < 1e-12 for src, grade, value in selected):
                    raise ValueError(f"official verification failed: {row['canonical_series_id']} {row['period']}")
            for row in wind:
                selected = rows_for_existing_key(conn, row)
                if selected != [("WIND", "D", row["value"])]:
                    raise ValueError(f"Wind gap verification failed: {row['canonical_series_id']} {row['period']} {selected}")
        summary.update({
            "status": "INGESTED",
            "db_before": before,
            "db_after": after,
            "official_inserted": official_result.inserted,
            "wind_inserted": wind_result.inserted,
            "gap_only_guard": "passed",
        })

    (REPORT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
