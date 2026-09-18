from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, time
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..archive import RawArtifact
from ..timeutils import SHANGHAI, ensure_aware
from .base import BaseSource, SourceInventoryEntry


HISTORY_ENDPOINT = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
HISTORY_PAGE = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/showHistory?locale=en_US"
GOVERNMENT_CURVE = "ChinaBond Government Bond Yield Curve"
CP_NOTE_CURVE = "ChinaBond CP&Note Yield Curve (AAA)"


class ChinaBondSource(BaseSource):
    """Monthly market factors derived from official ChinaBond daily curves."""

    source = "CHINABOND"
    country = "CN"
    parser_version = "chinabond_history_html_v2"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="ChinaBond Government Bond Yield Curve and Others",
                url=HISTORY_PAGE,
                earliest_period=None,
                latest_period=None,
                frequency="M",
                format="html",
                archive_available=True,
                release_timestamp_available=True,
                historical_revision_available=False,
                estimated_count=None,
                evidence=(
                    "Official daily curves; each closed month uses its final "
                    "published trading-day observation. ChinaBond documents a "
                    "17:30 Beijing-time business-day publication."
                ),
            )
        ]

    @staticmethod
    def history_url(start_date: date, end_date: date) -> str:
        query = urlencode(
            {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "gjqx": "0",
                "qxId": "ycqx",
                "locale": "en_US",
            }
        )
        return f"{HISTORY_ENDPOINT}?{query}"

    def parse_history(
        self,
        content: bytes,
        artifact: RawArtifact,
        *,
        closed_before: date | None = None,
    ) -> list[dict]:
        text = content.decode("utf-8", errors="strict")
        soup = BeautifulSoup(text, "lxml")
        table = _history_table(soup)
        records: dict[date, dict[str, dict[str, float]]] = defaultdict(dict)
        headers: list[str] | None = None
        for tr in table.find_all("tr"):
            values = [
                cell.get_text(" ", strip=True)
                for cell in tr.find_all(["th", "td"])
            ]
            if not values:
                continue
            if values[:2] == ["Yield Curve Name", "Date"]:
                headers = values
                continue
            if headers is None or len(values) < 2:
                continue
            try:
                observed = date.fromisoformat(values[1])
            except ValueError:
                continue
            if closed_before is not None and observed >= closed_before:
                continue
            curve: dict[str, float] = {}
            for label, raw in zip(headers[2:], values[2:]):
                try:
                    curve[label] = float(raw)
                except (TypeError, ValueError):
                    continue
            records[observed][values[0]] = curve

        series_by_month: dict[
            tuple[int, int],
            dict[str, tuple[date, str, str, str, float]],
        ] = defaultdict(dict)

        def remember(
            observed: date,
            canonical_id: str,
            source_id: str,
            name: str,
            unit: str,
            value: float,
        ) -> None:
            key = (observed.year, observed.month)
            current = series_by_month[key].get(canonical_id)
            if current is None or observed > current[0]:
                series_by_month[key][canonical_id] = (
                    observed,
                    source_id,
                    name,
                    unit,
                    value,
                )

        for observed, curves in records.items():
            government = curves.get(GOVERNMENT_CURVE, {})
            credit = curves.get(CP_NOTE_CURVE, {})
            if "10 Y" in government:
                remember(
                    observed,
                    "CN_CGB_YTM_10Y",
                    "CHINABOND_CGB_10Y",
                    "China 10-Year Government Bond Yield to Maturity",
                    "pct",
                    government["10 Y"],
                )
            if all(term in government for term in ("1 Y", "10 Y")):
                remember(
                    observed,
                    "CN_CGB_TERM_SPREAD_10Y_1Y",
                    "CHINABOND_CGB_10Y_MINUS_1Y",
                    "China Government Bond Term Spread (10Y minus 1Y)",
                    "pct_points",
                    government["10 Y"] - government["1 Y"],
                )
            if "3 Y" in government and "3 Y" in credit:
                remember(
                    observed,
                    "CN_AAA_CP_NOTE_CREDIT_SPREAD_3Y",
                    "CHINABOND_AAA_CP_NOTE_3Y_MINUS_CGB_3Y",
                    "China AAA CP and Note Credit Spread (3Y minus 3Y CGB)",
                    "pct_points",
                    credit["3 Y"] - government["3 Y"],
                )

        rows: list[dict] = []
        for (year, month), series in sorted(series_by_month.items()):
            period_start = date(year, month, 1)
            period_end = date(
                year, month, calendar.monthrange(year, month)[1]
            )
            for canonical_id, details in sorted(series.items()):
                observed, source_id, name, unit, value = details
                released = ensure_aware(
                    datetime.combine(observed, time(17, 30), tzinfo=SHANGHAI)
                )
                rows.append(
                    {
                        "country": self.country,
                        "source": self.source,
                        "canonical_series_id": canonical_id,
                        "source_series_id": source_id,
                        "series_name": name,
                        "frequency": "M",
                        "unit": unit,
                        "seasonal_adjustment": "NSA",
                        "period": f"{year:04d}-{month:02d}",
                        "period_start": period_start,
                        "period_end": period_end,
                        "value": round(float(value), 8),
                        "release_at": released,
                        "release_date_source": (
                            "chinabond_official_business_day_17_30"
                        ),
                        "first_seen_at": artifact.retrieved_at,
                        "available_at": released,
                        "pit_grade": "A",
                        "source_url": HISTORY_PAGE,
                        "raw_file": artifact.path,
                        "raw_sha256": artifact.sha256,
                        "retrieved_at": artifact.retrieved_at,
                        "parser_version": self.parser_version,
                    }
                )
        self.validate_row_count(rows)
        return rows


def _history_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        first = table.find("tr")
        if first is None:
            continue
        values = [
            cell.get_text(" ", strip=True)
            for cell in first.find_all(["th", "td"])
        ]
        if values[:2] == ["Yield Curve Name", "Date"]:
            return table
    raise ValueError("ChinaBond history table was not found")


