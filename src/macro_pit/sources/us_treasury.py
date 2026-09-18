from __future__ import annotations

import calendar
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..archive import RawArtifact
from .base import BaseSource, SourceInventoryEntry


FEED_PAGE = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml"
)
NEW_YORK = ZoneInfo("America/New_York")
SERIES = {
    "BC_2YEAR": (
        "US_TREASURY_YIELD_2Y",
        "U.S. 2-Year Treasury Constant Maturity Rate",
    ),
    "BC_10YEAR": (
        "US_TREASURY_YIELD_10Y",
        "U.S. 10-Year Treasury Constant Maturity Rate",
    ),
    "BC_30YEAR": (
        "US_TREASURY_YIELD_30Y",
        "U.S. 30-Year Treasury Constant Maturity Rate",
    ),
}


class USTreasurySource(BaseSource):
    """Monthly final-trading-day rates from Treasury's official daily feed."""

    source = "USTREASURY"
    country = "US"
    parser_version = "us_treasury_daily_xml_month_end_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="Daily Treasury Par Yield Curve Rates",
                url=self.history_url(date.today().year),
                earliest_period=None,
                latest_period=None,
                frequency="M",
                format="xml",
                archive_available=True,
                release_timestamp_available=False,
                historical_revision_available=True,
                estimated_count=None,
                evidence=(
                    "Official daily Treasury par yield curve. Each closed month "
                    "uses the last published trading-day rate. Availability is "
                    "conservatively placed at 00:00 America/New_York on the "
                    "following calendar day because the feed has no stable "
                    "publication timestamp."
                ),
            )
        ]

    @staticmethod
    def history_url(year: int) -> str:
        query = urlencode(
            {
                "data": "daily_treasury_yield_curve",
                "field_tdr_date_value": str(int(year)),
            }
        )
        return f"{FEED_PAGE}?{query}"

    def parse_history(
        self,
        content: bytes,
        artifact: RawArtifact,
        *,
        closed_before: date | None = None,
    ) -> list[dict]:
        root = ET.fromstring(content)
        monthly: dict[
            tuple[int, int],
            dict[str, tuple[date, str, str, float]],
        ] = defaultdict(dict)

        for entry in (node for node in root.iter() if _local(node.tag) == "entry"):
            properties = next(
                (
                    node for node in entry.iter()
                    if _local(node.tag) == "properties"
                ),
                None,
            )
            if properties is None:
                continue
            values = {
                _local(node.tag): (node.text or "").strip()
                for node in list(properties)
            }
            raw_date = values.get("NEW_DATE") or values.get("Date")
            if not raw_date:
                continue
            try:
                observed = date.fromisoformat(raw_date[:10])
            except ValueError:
                continue
            if closed_before is not None and observed >= closed_before:
                continue

            key = (observed.year, observed.month)
            for source_id, (canonical_id, name) in SERIES.items():
                raw_value = values.get(source_id, "")
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                current = monthly[key].get(canonical_id)
                if current is None or observed > current[0]:
                    monthly[key][canonical_id] = (
                        observed,
                        source_id,
                        name,
                        value,
                    )

        rows: list[dict] = []
        for (year, month), series in sorted(monthly.items()):
            period_start = date(year, month, 1)
            period_end = date(
                year, month, calendar.monthrange(year, month)[1]
            )
            for canonical_id, details in sorted(series.items()):
                observed, source_id, name, value = details
                release_at = datetime.combine(
                    observed + timedelta(days=1),
                    time.min,
                    tzinfo=NEW_YORK,
                )
                rows.append(
                    {
                        "country": self.country,
                        "source": self.source,
                        "canonical_series_id": canonical_id,
                        "source_series_id": source_id,
                        "series_name": name,
                        "frequency": "M",
                        "unit": "pct",
                        "seasonal_adjustment": "NSA",
                        "period": f"{year:04d}-{month:02d}",
                        "period_start": period_start,
                        "period_end": period_end,
                        "value": round(value, 8),
                        "release_at": release_at,
                        "release_date_source": (
                            "us_treasury_observation_date_plus_1d_00_et"
                        ),
                        "first_seen_at": artifact.retrieved_at,
                        "available_at": release_at,
                        "pit_grade": "B",
                        "source_url": artifact.url,
                        "raw_file": artifact.path,
                        "raw_sha256": artifact.sha256,
                        "retrieved_at": artifact.retrieved_at,
                        "parser_version": self.parser_version,
                    }
                )
        self.validate_row_count(rows)
        return rows


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]