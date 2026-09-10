from __future__ import annotations

import calendar
import csv
import io
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..archive import RawArtifact
from ..errors import DataContractError
from ..timeutils import ensure_aware
from .base import BaseSource, SourceInventoryEntry, decode_content


PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class OECDSeries:
    canonical_id: str
    name: str
    unit: str
    seasonal_adjustment: str = "UNKNOWN"
    country: str | None = None


class OECDSource(BaseSource):
    source = "OECD"
    country = "GLOBAL"
    parser_version = "oecd_stes_revisions_csv_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="Short-term economic statistics revisions",
                url="https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,4.0/",
                earliest_period=None,
                latest_period=None,
                frequency="M/Q",
                format="csv/sdmx-json",
                archive_available=True,
                release_timestamp_available=False,
                historical_revision_available=True,
                estimated_count=None,
                evidence="Official OECD edition dimension contains monthly publication snapshots; queries must be split by country and indicator",
            )
        ]

    def parse_csv(
        self,
        content: bytes,
        artifact: RawArtifact,
        mappings: dict[tuple[str, str, str, str], OECDSeries],
    ) -> list[dict]:
        text = decode_content(content)
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        required = {"REF_AREA", "FREQ", "MEASURE", "UNIT_MEASURE", "EDITION", "TIME_PERIOD", "OBS_VALUE"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise DataContractError(f"OECD CSV missing columns: {', '.join(missing)}")

        rows: list[dict] = []
        for item in reader:
            key = (item["REF_AREA"], item["FREQ"], item["MEASURE"], item["UNIT_MEASURE"])
            mapping = mappings.get(key)
            if mapping is None:
                continue
            try:
                value = float(item["OBS_VALUE"])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            if mapping.unit == "index" and value <= 0:
                # Index levels cannot be zero or negative. Some historical
                # provider extracts use zero as a missing/sentinel value.
                continue
            period = _period(item["TIME_PERIOD"], item["FREQ"])
            edition_end = _edition_end(item["EDITION"])
            if period is None or edition_end is None:
                continue
            period_label, period_start, period_end = period
            release_at = datetime.combine(edition_end, time.min, tzinfo=PARIS)
            available_at = datetime.combine(edition_end + timedelta(days=1), time.min, tzinfo=PARIS)
            rows.append(
                {
                    "country": mapping.country or item["REF_AREA"],
                    "source": self.source,
                    "canonical_series_id": mapping.canonical_id,
                    "source_series_id": f"{item['MEASURE']}|{item['UNIT_MEASURE']}",
                    "series_name": mapping.name,
                    "frequency": item["FREQ"],
                    "unit": mapping.unit,
                    "seasonal_adjustment": mapping.seasonal_adjustment,
                    "period": period_label,
                    "period_start": period_start,
                    "period_end": period_end,
                    "value": value,
                    "release_at": ensure_aware(release_at),
                    "release_date_source": "oecd_edition_period_end",
                    "first_seen_at": artifact.retrieved_at,
                    "available_at": ensure_aware(available_at),
                    "pit_grade": "B",
                    "source_url": artifact.url,
                    "raw_file": artifact.path,
                    "raw_sha256": artifact.sha256,
                    "retrieved_at": artifact.retrieved_at,
                    "parser_version": self.parser_version,
                }
            )
        rows.sort(
            key=lambda row: (
                row["country"], row["canonical_series_id"], row["period"], row["available_at"]
            )
        )
        compressed: list[dict] = []
        last_value: dict[tuple[str, str, str], float] = {}
        for row in rows:
            key = (row["country"], row["canonical_series_id"], row["period"])
            previous = last_value.get(key)
            if previous is not None and math.isclose(previous, row["value"], rel_tol=0.0, abs_tol=1e-12):
                continue
            last_value[key] = row["value"]
            compressed.append(row)
        self.validate_row_count(compressed)
        return compressed


def _edition_end(value: str) -> date | None:
    clean = str(value or "").strip()
    if len(clean) == 6 and clean.isdigit():
        year, month = int(clean[:4]), int(clean[4:])
        if 1 <= month <= 12:
            return date(year, month, calendar.monthrange(year, month)[1])
    for separator in ("-", "M"):
        if separator in clean:
            parts = clean.split(separator)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                year, month = int(parts[0]), int(parts[1])
                if 1 <= month <= 12:
                    return date(year, month, calendar.monthrange(year, month)[1])
    return None


def _period(value: str, frequency: str) -> tuple[str, date, date] | None:
    clean = str(value or "").strip().upper()
    if frequency == "M" and "-" in clean:
        year, month = (int(part) for part in clean.split("-")[:2])
        return clean[:7], date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if frequency == "Q" and "-Q" in clean:
        year_text, quarter_text = clean.split("-Q", 1)
        year, quarter = int(year_text), int(quarter_text)
        start_month, end_month = (quarter - 1) * 3 + 1, quarter * 3
        return clean, date(year, start_month, 1), date(year, end_month, calendar.monthrange(year, end_month)[1])
    return None
