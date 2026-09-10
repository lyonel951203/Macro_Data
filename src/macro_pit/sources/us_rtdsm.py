from __future__ import annotations

import calendar
import io
import math
import random
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from ..archive import RawArtifact
from ..errors import DataContractError
from ..timeutils import ensure_aware
from .base import BaseSource, SourceInventoryEntry


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class RTDSMSeries:
    canonical_id: str
    source_id: str
    name: str
    unit: str
    observation_frequency: str
    seasonal_adjustment: str = "SA"


@dataclass(frozen=True)
class RTDSMValidation:
    sample_size: int
    matches: int

    @property
    def match_rate(self) -> float:
        return self.matches / self.sample_size if self.sample_size else 0.0


class RTDSMSource(BaseSource):
    source = "RTDSM"
    country = "US"
    parser_version = "rtdsm_xlsx_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="Philadelphia Fed Real-Time Data Set for Macroeconomists",
                url="https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists",
                earliest_period=None,
                latest_period=None,
                frequency="M/Q",
                format="xlsx",
                archive_available=True,
                release_timestamp_available=False,
                historical_revision_available=True,
                estimated_count=None,
                evidence="Official vintage matrices; vintage period end is handled conservatively as PIT_B",
            )
        ]

    def parse_workbook(
        self,
        content: bytes,
        artifact: RawArtifact,
        series: RTDSMSeries,
    ) -> list[dict]:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        header_row, vintage_columns = _find_header(sheet, series.source_id)
        rows: list[dict] = []
        for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            if not values:
                continue
            observation = _parse_period(values[0], series.observation_frequency)
            if observation is None:
                continue
            period, period_start, period_end = observation
            last_value: float | None = None
            for column_index, vintage in vintage_columns.items():
                if column_index >= len(values):
                    continue
                raw_value = values[column_index]
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue
                # A PIT snapshot only needs the first known value and subsequent
                # changes. Repeated cells across editions are losslessly
                # compressed and reconstructed by the as-of query.
                if last_value is not None and math.isclose(value, last_value, rel_tol=0.0, abs_tol=1e-12):
                    continue
                last_value = value
                release_at, available_at = _vintage_times(vintage)
                rows.append(
                    {
                        "country": "US",
                        "source": self.source,
                        "canonical_series_id": series.canonical_id,
                        "source_series_id": series.source_id,
                        "series_name": series.name,
                        "frequency": series.observation_frequency,
                        "unit": series.unit,
                        "seasonal_adjustment": series.seasonal_adjustment,
                        "period": period,
                        "period_start": period_start,
                        "period_end": period_end,
                        "value": value,
                        "release_at": ensure_aware(release_at),
                        "release_date_source": f"rtdsm_{vintage[0]}_vintage_period_end",
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
        workbook.close()
        self.validate_row_count(rows)
        return rows

    def validate_workbook(
        self,
        conn,
        content: bytes,
        artifact: RawArtifact,
        series: RTDSMSeries,
        *,
        sample_size: int = 100,
        seed: int = 20260903,
    ) -> RTDSMValidation:
        """Compare a deterministic sample of source cells with reconstructed PIT values."""
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        header_row, vintage_columns = _find_header(sheet, series.source_id)
        rng = random.Random(seed)
        samples: list[tuple[str, tuple[str, int, int, date], float]] = []
        seen = 0
        for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
            if not values:
                continue
            observation = _parse_period(values[0], series.observation_frequency)
            if observation is None:
                continue
            period = observation[0]
            for column_index, vintage in vintage_columns.items():
                if column_index >= len(values):
                    continue
                try:
                    value = float(values[column_index])
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue
                seen += 1
                candidate = (period, vintage, value)
                if len(samples) < sample_size:
                    samples.append(candidate)
                else:
                    index = rng.randrange(seen)
                    if index < sample_size:
                        samples[index] = candidate
        workbook.close()

        matches = 0
        for period, vintage, expected in samples:
            _, available_at = _vintage_times(vintage)
            observed = conn.execute(
                """
                SELECT value FROM observation_vintage
                WHERE source='RTDSM' AND canonical_series_id=? AND period=? AND available_at<=?
                ORDER BY available_at DESC, vintage_no DESC LIMIT 1
                """,
                [series.canonical_id, period, ensure_aware(available_at)],
            ).fetchone()
            if observed and math.isclose(float(observed[0]), expected, rel_tol=0.0, abs_tol=1e-9):
                matches += 1
        result = RTDSMValidation(len(samples), matches)
        conn.execute(
            """
            INSERT INTO validation_result VALUES (?, 'RTDSM', 'vintage_cell_match', ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()), result.sample_size, result.matches, result.match_rate,
                artifact.sha256, datetime.now(timezone.utc), series.canonical_id,
            ],
        )
        return result


def _find_header(sheet, source_id: str | None = None) -> tuple[int, dict[int, tuple[str, int, int, date]]]:
    for row_number, values in enumerate(
        sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 30), values_only=True),
        start=1,
    ):
        parsed = {
            index: vintage
            for index, value in enumerate(values)
            if index > 0 and (vintage := _parse_vintage(value, source_id)) is not None
        }
        if len(parsed) >= 1:
            return row_number, parsed
    raise DataContractError("RTDSM workbook vintage header was not found")


def _parse_vintage(value, source_id: str | None = None) -> tuple[str, int, int, date] | None:
    if isinstance(value, datetime):
        end = date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])
        return "M", value.year, value.month, end
    if isinstance(value, date):
        end = date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])
        return "M", value.year, value.month, end
    text_value = str(value or "").strip().upper().replace(":", "").replace("-", "")
    prefix = str(source_id or "").strip().upper()
    if prefix and text_value.startswith(prefix):
        text_value = text_value[len(prefix):]
    match = re.search(r"(?P<year>\d{2,4})(?P<freq>[QM])(?P<number>\d{1,2})$", text_value)
    if not match:
        return None
    year = int(match.group("year"))
    if year < 100:
        year += 1900 if year >= 40 else 2000
    number = int(match.group("number"))
    frequency = match.group("freq")
    if frequency == "M" and 1 <= number <= 12:
        end = date(year, number, calendar.monthrange(year, number)[1])
    elif frequency == "Q" and 1 <= number <= 4:
        # RTDSM quarterly vintages represent the information set around the
        # 15th of the middle month of each quarter.
        end = date(year, number * 3 - 1, 15)
    else:
        return None
    return frequency, year, number, end


def _parse_period(value, frequency: str) -> tuple[str, date, date] | None:
    if isinstance(value, (date, datetime)):
        year, month = value.year, value.month
        if frequency == "M":
            return f"{year:04d}-{month:02d}", date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        quarter = (month - 1) // 3 + 1
        return _quarter_period(year, quarter)
    text_value = str(value or "").strip().upper().replace(":", "").replace("-", "")
    if frequency == "M":
        match = re.search(r"(?P<year>\d{4})M?(?P<number>0?[1-9]|1[0-2])$", text_value)
        if match:
            year, month = int(match.group("year")), int(match.group("number"))
            return f"{year:04d}-{month:02d}", date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if frequency == "Q":
        match = re.search(r"(?P<year>\d{4})Q(?P<number>[1-4])$", text_value)
        if match:
            return _quarter_period(int(match.group("year")), int(match.group("number")))
    return None


def _quarter_period(year: int, quarter: int) -> tuple[str, date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month = quarter * 3
    return (
        f"{year:04d}-Q{quarter}",
        date(year, start_month, 1),
        date(year, end_month, calendar.monthrange(year, end_month)[1]),
    )


def _vintage_times(vintage: tuple[str, int, int, date]) -> tuple[datetime, datetime]:
    release_date = vintage[3]
    release_at = datetime.combine(release_date, time.min, tzinfo=NEW_YORK)
    available_at = datetime.combine(release_date + timedelta(days=1), time.min, tzinfo=NEW_YORK)
    return release_at, available_at
