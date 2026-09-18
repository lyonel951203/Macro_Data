from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

from ..archive import RawArtifact
from ..errors import DataContractError
from .base import BaseSource, SourceInventoryEntry, decode_content
from .cn_common import make_observation


FIRST_SEEN_RELEASE_SOURCE = "third_party_current_history_first_seen_only"


@dataclass(frozen=True)
class FallbackField:
    canonical_id: str
    source_id: str
    name: str
    unit: str
    value: Callable[[Any], float]


def _identity(value: Any) -> float:
    return float(value)


def _hundred_million_usd_to_bn(value: Any) -> float:
    return float(value) / 10.0


def _cpi_index_to_yoy(value: Any) -> float:
    return float(value) - 100.0


def _period(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(20\d{2})[.-](0?[1-9]|1[0-2])(?:-\d{2}.*)?", value.strip())
    if match is None:
        raise ValueError(f"unsupported monthly period: {value}")
    return int(match.group(1)), int(match.group(2))


def _release(artifact: RawArtifact) -> dict[str, Any]:
    return {
        "release_at": None,
        "available_at": artifact.retrieved_at,
        "release_date_source": FIRST_SEEN_RELEASE_SOURCE,
        "pit_grade": "D",
    }


def _balanced_array(text: str, marker: str) -> list[Any]:
    marker_at = text.rfind(marker)
    if marker_at < 0:
        raise DataContractError(f"JSONP response is missing {marker}")
    start = text.find("[", marker_at)
    if start < 0:
        raise DataContractError("JSONP response has no data array")
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])
    raise DataContractError("unterminated JSONP data array")


def _latest_by_series(rows: list[dict[str, Any]], latest_periods: int) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (row["canonical_series_id"], row["period"]),
        reverse=True,
    )
    counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for row in ordered:
        field = row["canonical_series_id"]
        if counts.get(field, 0) >= latest_periods:
            continue
        selected.append(row)
        counts[field] = counts.get(field, 0) + 1
    return selected


class SinaMacroSource(BaseSource):
    """Reviewed current-history fields from Sina's public macro JSONP API."""

    source = "SINA_MACRO"
    country = "CN"
    parser_version = "sina_macro_first_seen_v1"

    _base = "https://quotes.sina.cn/mac/api/jsonp_v3.php/MACROPIT/MacPage_Service.get_pagedata"
    _jobs = {
        "industrial": ("nation", 9, 5),
        "retail": ("nation", 13, 5),
        "investment": ("fixed", 1, 5),
        "manufacturing_investment": ("fixed", 10, 120),
        "cpi": ("price", 0, 5),
        "pmi": ("boom", 5, 5),
        "money": ("fininfo", 1, 5),
        "reserve": ("fininfo", 5, 5),
    }

    def inventory(self) -> list[SourceInventoryEntry]:
        return [SourceInventoryEntry(
            source=self.source,
            dataset="Sina China macro current-history fallback",
            url="https://finance.sina.com.cn/mac/",
            earliest_period=None,
            latest_period=None,
            frequency="M",
            format="jsonp",
            archive_available=True,
            release_timestamp_available=False,
            historical_revision_available=False,
            estimated_count=16,
            evidence="Third-party current-history tables; first observation only, always PIT_D.",
        )]

    def jobs(self) -> list[tuple[str, str]]:
        jobs: list[tuple[str, str]] = []
        for name, (category, event, count) in self._jobs.items():
            query = urlencode({
                "cate": category,
                "event": event,
                "from": 0,
                "num": count,
                "condition": "",
            })
            jobs.append((name, f"{self._base}?{query}"))
        return jobs

    def parse_job(
        self,
        name: str,
        content: bytes,
        artifact: RawArtifact,
        *,
        latest_periods: int,
    ) -> list[dict[str, Any]]:
        text = decode_content(content)
        data = _balanced_array(text, ",data:")
        rows: list[dict[str, Any]] = []

        def add(raw_period: Any, field: FallbackField, raw_value: Any) -> None:
            if raw_value is None:
                return
            value = field.value(raw_value)
            if not math.isfinite(value):
                return
            year, month = _period(str(raw_period))
            rows.append(make_observation(
                source=self.source,
                canonical_series_id=field.canonical_id,
                source_series_id=field.source_id,
                series_name=field.name,
                unit=field.unit,
                year=year,
                month=month,
                value=value,
                artifact=artifact,
                release=_release(artifact),
                parser_version=self.parser_version,
            ))

        simple: dict[str, list[tuple[int, FallbackField]]] = {
            "industrial": [(1, FallbackField(
                "CN_INDUSTRIAL_VALUE_ADDED_YOY", "nation.9.1",
                "规模以上工业增加值同比", "pct_yoy", _identity,
            ))],
            "retail": [(2, FallbackField(
                "CN_RETAIL_SALES_YOY", "nation.13.2",
                "社会消费品零售总额同比", "pct_yoy", _identity,
            ))],
            "investment": [
                (2, FallbackField(
                    "CN_FAI_YTD_YOY", "fixed.1.2",
                    "固定资产投资累计同比", "pct_yoy", _identity,
                )),
                (46, FallbackField(
                    "CN_REAL_ESTATE_INVESTMENT_YTD_YOY", "fixed.1.46",
                    "房地产开发投资累计同比", "pct_yoy", _identity,
                )),
            ],
            "cpi": [(1, FallbackField(
                "CN_CPI_YOY", "price.0.1",
                "居民消费价格指数同比", "pct_yoy", _cpi_index_to_yoy,
            ))],
            "pmi": [
                (1, FallbackField("CN_PMI_MANUFACTURING", "boom.5.1", "制造业PMI", "index", _identity)),
                (2, FallbackField("CN_PMI_PRODUCTION", "boom.5.2", "制造业PMI生产指数", "index", _identity)),
                (3, FallbackField("CN_PMI_NEW_ORDERS", "boom.5.3", "制造业PMI新订单指数", "index", _identity)),
                (10, FallbackField("CN_PMI_RAW_MATERIAL_INVENTORY", "boom.5.10", "制造业PMI原材料库存指数", "index", _identity)),
                (11, FallbackField("CN_PMI_EMPLOYMENT", "boom.5.11", "制造业PMI从业人员指数", "index", _identity)),
                (12, FallbackField("CN_PMI_SUPPLIER_DELIVERY", "boom.5.12", "制造业PMI供应商配送时间指数", "index", _identity)),
            ],
            "money": [
                (2, FallbackField("CN_M2_YOY", "fininfo.1.2", "广义货币M2同比", "pct_yoy", _identity)),
                (4, FallbackField("CN_M1_YOY", "fininfo.1.4", "狭义货币M1同比", "pct_yoy", _identity)),
                (6, FallbackField("CN_M0_YOY", "fininfo.1.6", "流通中货币M0同比", "pct_yoy", _identity)),
            ],
            "reserve": [(2, FallbackField(
                "CN_FX_RESERVE_USD", "fininfo.5.2",
                "外汇储备", "bn_usd", _hundred_million_usd_to_bn,
            ))],
        }
        if name == "manufacturing_investment":
            field = FallbackField(
                "CN_MANUFACTURING_INVESTMENT_YTD_YOY", "fixed.10.manufacturing",
                "制造业投资累计同比", "pct_yoy", _identity,
            )
            for item in data:
                if len(item) > 3 and str(item[1]).strip() == "制造业":
                    add(item[0], field, item[3])
        elif name in simple:
            for item in data:
                for index, field in simple[name]:
                    if len(item) > index:
                        add(item[0], field, item[index])
        else:
            raise ValueError(f"unsupported Sina macro job: {name}")
        rows = _latest_by_series(rows, latest_periods)
        if not rows:
            raise DataContractError(f"Sina macro job {name} returned no mapped rows")
        return rows


class EastmoneyMacroSource(BaseSource):
    """Reviewed current-history fields from Eastmoney's public data API."""

    source = "EASTMONEY_MACRO"
    country = "CN"
    parser_version = "eastmoney_macro_first_seen_v1"
    _base = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    _jobs = {
        "cpi": "RPT_ECONOMY_CPI",
        "ppi": "RPT_ECONOMY_PPI",
        "industrial": "RPT_ECONOMY_INDUS_GROW",
        "retail": "RPT_ECONOMY_TOTAL_RETAIL",
        "pmi": "RPT_ECONOMY_PMI",
        "money": "RPT_ECONOMY_CURRENCY_SUPPLY",
        "reserve": "RPT_ECONOMY_GOLD_CURRENCY",
        "budget_revenue": "RPT_ECONOMY_INCOME",
    }

    _fields: dict[str, list[tuple[str, FallbackField]]] = {
        "cpi": [("NATIONAL_SAME", FallbackField("CN_CPI_YOY", "RPT_ECONOMY_CPI.NATIONAL_SAME", "居民消费价格指数同比", "pct_yoy", _identity))],
        "ppi": [("BASE_SAME", FallbackField("CN_PPI_YOY", "RPT_ECONOMY_PPI.BASE_SAME", "工业生产者出厂价格指数同比", "pct_yoy", _identity))],
        "industrial": [("BASE_SAME", FallbackField("CN_INDUSTRIAL_VALUE_ADDED_YOY", "RPT_ECONOMY_INDUS_GROW.BASE_SAME", "规模以上工业增加值同比", "pct_yoy", _identity))],
        "retail": [("RETAIL_TOTAL_SAME", FallbackField("CN_RETAIL_SALES_YOY", "RPT_ECONOMY_TOTAL_RETAIL.RETAIL_TOTAL_SAME", "社会消费品零售总额同比", "pct_yoy", _identity))],
        "pmi": [
            ("MAKE_INDEX", FallbackField("CN_PMI_MANUFACTURING", "RPT_ECONOMY_PMI.MAKE_INDEX", "制造业PMI", "index", _identity)),
            ("NMAKE_INDEX", FallbackField("CN_PMI_NONMANUFACTURING", "RPT_ECONOMY_PMI.NMAKE_INDEX", "非制造业商务活动指数", "index", _identity)),
        ],
        "money": [
            ("BASIC_CURRENCY_SAME", FallbackField("CN_M2_YOY", "RPT_ECONOMY_CURRENCY_SUPPLY.BASIC_CURRENCY_SAME", "广义货币M2同比", "pct_yoy", _identity)),
            ("CURRENCY_SAME", FallbackField("CN_M1_YOY", "RPT_ECONOMY_CURRENCY_SUPPLY.CURRENCY_SAME", "狭义货币M1同比", "pct_yoy", _identity)),
            ("FREE_CASH_SAME", FallbackField("CN_M0_YOY", "RPT_ECONOMY_CURRENCY_SUPPLY.FREE_CASH_SAME", "流通中货币M0同比", "pct_yoy", _identity)),
        ],
        "reserve": [("FOREX", FallbackField("CN_FX_RESERVE_USD", "RPT_ECONOMY_GOLD_CURRENCY.FOREX", "外汇储备", "bn_usd", _hundred_million_usd_to_bn))],
        "budget_revenue": [("ACCUMULATE_SAME", FallbackField("CN_GENERAL_BUDGET_REVENUE_YTD_YOY", "RPT_ECONOMY_INCOME.ACCUMULATE_SAME", "一般公共预算收入累计同比", "pct_yoy", _identity))],
    }

    def inventory(self) -> list[SourceInventoryEntry]:
        return [SourceInventoryEntry(
            source=self.source,
            dataset="Eastmoney China macro current-history fallback",
            url="https://data.eastmoney.com/cjsj/cpi.html",
            earliest_period=None,
            latest_period=None,
            frequency="M",
            format="json",
            archive_available=True,
            release_timestamp_available=False,
            historical_revision_available=False,
            estimated_count=11,
            evidence="Choice-derived third-party current history; first observation only, always PIT_D.",
        )]

    def jobs(self) -> list[tuple[str, str]]:
        jobs: list[tuple[str, str]] = []
        for name, report in self._jobs.items():
            query = urlencode({
                "reportName": report,
                "columns": "ALL",
                "pageNumber": 1,
                "pageSize": 5,
                "sortColumns": "REPORT_DATE",
                "sortTypes": -1,
                "source": "WEB",
                "client": "WEB",
            })
            jobs.append((name, f"{self._base}?{query}"))
        return jobs

    def parse_job(
        self,
        name: str,
        content: bytes,
        artifact: RawArtifact,
        *,
        latest_periods: int,
    ) -> list[dict[str, Any]]:
        try:
            payload = json.loads(decode_content(content))
            data = payload["result"]["data"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DataContractError("Eastmoney response has no result.data") from exc
        if not isinstance(data, list):
            raise DataContractError("Eastmoney result.data is not a list")
        mappings = self._fields.get(name)
        if mappings is None:
            raise ValueError(f"unsupported Eastmoney macro job: {name}")
        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("REPORT_DATE"):
                continue
            year, month = _period(str(item["REPORT_DATE"]))
            for key, field in mappings:
                raw_value = item.get(key)
                if raw_value is None:
                    continue
                value = field.value(raw_value)
                if not math.isfinite(value):
                    continue
                rows.append(make_observation(
                    source=self.source,
                    canonical_series_id=field.canonical_id,
                    source_series_id=field.source_id,
                    series_name=field.name,
                    unit=field.unit,
                    year=year,
                    month=month,
                    value=value,
                    artifact=artifact,
                    release=_release(artifact),
                    parser_version=self.parser_version,
                ))
        rows = _latest_by_series(rows, latest_periods)
        if not rows:
            raise DataContractError(f"Eastmoney macro job {name} returned no mapped rows")
        return rows


FALLBACK_SOURCE_CLASSES = {
    SinaMacroSource.source: SinaMacroSource,
    EastmoneyMacroSource.source: EastmoneyMacroSource,
}

