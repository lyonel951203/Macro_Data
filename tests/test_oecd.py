from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from macro_pit.archive import RawArtifact
from macro_pit.sources.oecd import OECDSeries, OECDSource
from macro_pit.pipeline import _expand_oecd_country_jobs


def test_oecd_edition_dimension_becomes_vintages(tmp_path):
    content = (
        "REF_AREA,FREQ,MEASURE,UNIT_MEASURE,EDITION,TIME_PERIOD,OBS_VALUE\n"
        "DEU,M,IP,IX,2025-02,2025-01,100.0\n"
        "DEU,M,IP,IX,2025-03,2025-01,100.2\n"
        "DEU,M,IP,IX,2025-04,2025-01,100.2\n"
    ).encode("utf-8")
    raw = tmp_path / "oecd.csv"
    raw.write_bytes(content)
    artifact = RawArtifact(
        source="OECD",
        url="https://sdmx.oecd.org/query",
        path=raw.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type="text/csv",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        size=len(content),
    )
    source = OECDSource(allow_network=False)
    try:
        rows = source.parse_csv(
            content,
            artifact,
            {("DEU", "M", "IP", "IX"): OECDSeries("DE_INDUSTRIAL_PRODUCTION", "Industrial production", "index")},
        )
    finally:
        source.close()
    assert len(rows) == 2
    assert [row["value"] for row in rows] == [100.0, 100.2]
    assert rows[0]["available_at"] < rows[1]["available_at"]
    assert {row["pit_grade"] for row in rows} == {"B"}


def test_oecd_mapping_can_normalize_ref_area_to_project_country(tmp_path):
    content = (
        "REF_AREA,FREQ,MEASURE,UNIT_MEASURE,EDITION,TIME_PERIOD,OBS_VALUE\n"
        "CHN,M,CP,IX,2025-02,2025-01,100.0\n"
    ).encode("utf-8")
    raw = tmp_path / "oecd_china.csv"
    raw.write_bytes(content)
    artifact = RawArtifact(
        source="OECD",
        url="https://sdmx.oecd.org/query",
        path=raw.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type="text/csv",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        size=len(content),
    )
    source = OECDSource(allow_network=False)
    try:
        rows = source.parse_csv(
            content,
            artifact,
            {("CHN", "M", "CP", "IX"): OECDSeries(
                "CN_OECD_CPI_INDEX", "Consumer prices", "index", country="CN"
            )},
        )
    finally:
        source.close()
    assert rows[0]["country"] == "CN"
    assert rows[0]["canonical_series_id"] == "CN_OECD_CPI_INDEX"


def test_oecd_index_parser_drops_zero_sentinel(tmp_path):
    content = (
        "REF_AREA,FREQ,MEASURE,UNIT_MEASURE,EDITION,TIME_PERIOD,OBS_VALUE\n"
        "CHN,M,PRVM,IX,2013-03,2013-01,0\n"
        "CHN,M,PRVM,IX,2013-04,2013-02,101.2\n"
    ).encode("utf-8")
    raw = tmp_path / "oecd_index.csv"
    raw.write_bytes(content)
    artifact = RawArtifact(
        source="OECD",
        url="https://sdmx.oecd.org/query",
        path=raw.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type="text/csv",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        size=len(content),
    )
    source = OECDSource(allow_network=False)
    try:
        rows = source.parse_csv(
            content,
            artifact,
            {("CHN", "M", "PRVM", "IX"): OECDSeries(
                "CN_OECD_INDUSTRIAL_PRODUCTION", "Industrial production", "index", country="CN"
            )},
        )
    finally:
        source.close()
    assert len(rows) == 1
    assert rows[0]["period"] == "2013-02"
    assert rows[0]["value"] == 101.2


def test_australia_split_retail_uses_configured_quarterly_frequency():
    jobs = _expand_oecd_country_jobs({"countries": [{
        "ref_area": "AUS", "prefix": "AU", "split_production_retail": True,
        "production_frequency": "Q", "retail_frequency": "Q",
    }]})
    retail = next(job for job in jobs if ".TOVM." in job["url"])
    assert "/AUS.Q.TOVM." in retail["url"]
    assert retail["series"][0]["frequency"] == "Q"


def test_india_only_marks_verified_stale_queries_as_no_recent_data():
    jobs = _expand_oecd_country_jobs({"countries": [{
        "ref_area": "IND", "prefix": "IN",
        "no_recent_measures": ["B1GQ_Q", "PRVM", "TOVM"],
    }]})
    assert jobs[0]["allow_no_recent_records"] is True
    assert "allow_no_recent_records" not in jobs[1]
    assert jobs[2]["allow_no_recent_records"] is True
