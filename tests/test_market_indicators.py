from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone

from openpyxl import Workbook

from macro_pit.archive import RawArtifact
from macro_pit.asof_wide import build_as_of_wide
from macro_pit.db import get_connection, insert_observations
from macro_pit.pit_long import build_pit_long
from macro_pit.sources.cn_chinabond import ChinaBondSource
from macro_pit.sources.imf_commodity import IMFCommoditySource
from macro_pit.sources.us_treasury import USTreasurySource


def _artifact(tmp_path, source: str, content: bytes, suffix: str):
    raw = tmp_path / f"raw.{suffix}"
    raw.write_bytes(content)
    return RawArtifact(
        source=source,
        url=f"https://example.test/raw.{suffix}",
        path=raw.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type=(
            "text/html"
            if suffix == "html"
            else "application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet"
        ),
        retrieved_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        size=len(content),
    )


def test_chinabond_uses_last_trading_day_and_builds_spreads(tmp_path):
    content = b"""
    <html><body><table>
      <tr><th>Yield Curve Name</th><th>Date</th><th>1 Y</th>
          <th>3 Y</th><th>10 Y</th></tr>
      <tr><td>ChinaBond Government Bond Yield Curve</td>
          <td>2026-08-28</td><td>1.20</td><td>1.30</td><td>1.70</td></tr>
      <tr><td>ChinaBond CP&amp;Note Yield Curve (AAA)</td>
          <td>2026-08-28</td><td>1.50</td><td>1.80</td><td>2.10</td></tr>
      <tr><td>ChinaBond Government Bond Yield Curve</td>
          <td>2026-08-31</td><td>1.22</td><td>1.26</td><td>1.69</td></tr>
      <tr><td>ChinaBond CP&amp;Note Yield Curve (AAA)</td>
          <td>2026-08-31</td><td>1.53</td><td>1.69</td><td>2.09</td></tr>
    </table></body></html>
    """
    artifact = _artifact(tmp_path, "CHINABOND", content, "html")
    source = ChinaBondSource(allow_network=False)
    try:
        rows = source.parse_history(
            content,
            artifact,
            closed_before=datetime(2026, 9, 1).date(),
        )
    finally:
        source.close()

    observed = {row["canonical_series_id"]: row for row in rows}
    assert observed["CN_CGB_YTM_10Y"]["value"] == 1.69
    assert observed["CN_CGB_TERM_SPREAD_10Y_1Y"]["value"] == 0.47
    assert observed["CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y"]["value"] == 0.43
    assert {row["period_end"].isoformat() for row in rows} == {"2026-08-31"}
    assert {row["pit_grade"] for row in rows} == {"A"}
    assert {
        row["available_at"].isoformat() for row in rows
    } == {"2026-08-31T09:30:00+00:00"}



def test_us_treasury_uses_last_trading_day_with_conservative_pit_b(tmp_path):
    content = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
          xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
      <entry><content><m:properties>
        <d:NEW_DATE>2026-08-28T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>3.65</d:BC_2YEAR>
        <d:BC_10YEAR>4.21</d:BC_10YEAR>
        <d:BC_30YEAR>4.88</d:BC_30YEAR>
      </m:properties></content></entry>
      <entry><content><m:properties>
        <d:NEW_DATE>2026-08-31T00:00:00</d:NEW_DATE>
        <d:BC_2YEAR>3.61</d:BC_2YEAR>
        <d:BC_10YEAR>4.18</d:BC_10YEAR>
        <d:BC_30YEAR>4.85</d:BC_30YEAR>
      </m:properties></content></entry>
    </feed>"""
    artifact = _artifact(tmp_path, "USTREASURY", content, "xml")
    source = USTreasurySource(allow_network=False)
    try:
        rows = source.parse_history(
            content, artifact, closed_before=datetime(2026, 9, 1).date()
        )
    finally:
        source.close()

    observed = {row["canonical_series_id"]: row for row in rows}
    assert observed["US_TREASURY_YIELD_2Y"]["value"] == 3.61
    assert observed["US_TREASURY_YIELD_10Y"]["value"] == 4.18
    assert observed["US_TREASURY_YIELD_30Y"]["value"] == 4.85
    assert {row["period_end"].isoformat() for row in rows} == {"2026-08-31"}
    assert {row["pit_grade"] for row in rows} == {"B"}
    assert {row["available_at"].isoformat() for row in rows} == {
        "2026-09-01T00:00:00-04:00"
    }


def test_imf_workbook_is_pit_d_current_history(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "External"
    sheet.append(["Commodity", "PALLFNF"])
    sheet.append(["Commodity.Description", "All Commodity Price Index"])
    sheet.append(["Data Type", "Index"])
    sheet.append(["Frequency", "Monthly"])
    sheet.append(["2005M1", 80.25])
    sheet.append(["2005M2", 81.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()
    artifact = _artifact(tmp_path, "IMF", content, "xlsx")

    source = IMFCommoditySource(allow_network=False)
    try:
        rows = source.parse_workbook(content, artifact)
    finally:
        source.close()

    assert [row["period"] for row in rows] == ["2005-01", "2005-02"]
    assert {row["pit_grade"] for row in rows} == {"D"}
    assert {row["release_at"] for row in rows} == {None}
    assert rows[0]["period_end"].isoformat() == "2005-01-31"


def test_imf_estimated_visibility_is_shared_by_wide_and_long(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "External"
    sheet.append(["Commodity", "PALLFNF"])
    sheet.append(["Commodity.Description", "All Commodity Price Index"])
    sheet.append(["Data Type", "Index"])
    sheet.append(["Frequency", "Monthly"])
    sheet.append(["2005M1", 80.25])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()
    artifact = _artifact(tmp_path, "IMF", content, "xlsx")
    source = IMFCommoditySource(allow_network=False)
    try:
        rows = source.parse_workbook(content, artifact)
    finally:
        source.close()

    conn = get_connection(":memory:")
    insert_observations(conn, rows)
    rules = tmp_path / "rules.csv"
    rules.write_text(
        "canonical_series_id,frequency,lag_days,available_same_day,"
        "confidence,eligible,basis,note\n"
        "GLB_IMF_ALL_COMMODITY_PRICE_INDEX,M,40,false,low,true,"
        "test,test\n",
        encoding="utf-8",
    )

    before = build_as_of_wide(
        conn,
        "2005-03-12",
        "GLB",
        start_date="2005-01-01",
        estimated_rules_path=rules,
    )
    after = build_as_of_wide(
        conn,
        "2005-03-13",
        "GLB",
        start_date="2005-01-01",
        estimated_rules_path=rules,
    )
    field = "GLB_IMF_ALL_COMMODITY_PRICE_INDEX"
    assert before.values[field].to_list()[0] is None
    assert after.values[field].to_list()[0] == 80.25
    assert after.provenance[field].to_list()[0] == "ESTIMATED_D"

    long = build_pit_long(
        conn,
        "GLB",
        start_date="2005-01-01",
        estimated_rules_path=rules,
    )
    conn.close()
    selected = long.events.filter(
        long.events["canonical_series_id"] == field
    )
    assert selected.height == 1
    assert selected["selection_origin"][0] == "ESTIMATED_D"
    assert selected["pit_grade"][0] == "D"


def test_chinabond_keeps_government_series_when_early_credit_tenor_is_missing(
    tmp_path,
):
    content = b"""
    <html><body><table>
      <tr><th>Yield Curve Name</th><th>Date</th><th>1 Y</th>
          <th>3 Y</th><th>10 Y</th></tr>
      <tr><td>ChinaBond Government Bond Yield Curve</td>
          <td>2006-12-31</td><td>2.0890</td><td>2.4413</td>
          <td>3.0269</td></tr>
      <tr><td>ChinaBond CP&amp;Note Yield Curve (AAA)</td>
          <td>2006-12-31</td><td>3.4600</td><td></td><td></td></tr>
    </table></body></html>
    """
    artifact = _artifact(tmp_path, "CHINABOND", content, "html")
    source = ChinaBondSource(allow_network=False)
    try:
        rows = source.parse_history(content, artifact)
    finally:
        source.close()

    observed = {row["canonical_series_id"]: row for row in rows}
    assert set(observed) == {
        "CN_CGB_YTM_10Y",
        "CN_CGB_TERM_SPREAD_10Y_1Y",
    }
    assert observed["CN_CGB_YTM_10Y"]["value"] == 3.0269
    assert observed["CN_CGB_TERM_SPREAD_10Y_1Y"]["value"] == 0.9379
