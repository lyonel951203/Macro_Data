from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..archive import RawArtifact
from .base import BaseSource, SourceInventoryEntry
from .cn_common import (
    extract_period_from_title,
    extract_release_evidence,
    html_text,
    make_observation,
    signed_percent,
)


@dataclass(frozen=True)
class MetricPattern:
    canonical_id: str
    source_id: str
    name: str
    unit: str
    pattern: str
    percent: bool = True


METRICS = [
    MetricPattern("CN_M2_YOY", "M2_YOY", "M2同比", "pct_yoy", r"广义货币[（(]?M2[）)]?余额.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_M1_YOY", "M1_YOY", "M1同比", "pct_yoy", r"狭义货币[（(]?M1[）)]?余额.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_M0_YOY", "M0_YOY", "M0同比", "pct_yoy", r"流通中货币[（(]?M0[）)]?余额.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_RMB_LOAN_BAL_YOY", "RMB_LOAN_BAL_YOY", "人民币贷款余额同比", "pct_yoy", r"(?<!的)人民币贷款余额.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_RMB_DEPOSIT_BAL_YOY", "RMB_DEPOSIT_BAL_YOY", "人民币存款余额同比", "pct_yoy", r"人民币存款余额.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_NEW_RMB_LOANS_YTD", "NEW_RMB_LOANS_YTD", "新增人民币贷款累计", "tn_cny_ytd", r"(?<!的)人民币贷款增加(?P<value>[\d.,]+)万亿元", False),
    MetricPattern("CN_NEW_RMB_DEPOSITS_YTD", "NEW_RMB_DEPOSITS_YTD", "新增人民币存款累计", "tn_cny_ytd", r"人民币存款增加(?P<value>[\d.,]+)万亿元", False),
    MetricPattern("CN_TSF_STOCK", "TSF_STOCK", "社会融资规模存量", "tn_cny", r"社会融资规模存量为(?P<value>[\d.,]+)万亿元", False),
    MetricPattern("CN_TSF_STOCK_YOY", "TSF_STOCK_YOY", "社会融资规模存量同比", "pct_yoy", r"社会融资规模存量.*?同比(?P<direction>增长|下降)(?P<value>[\d.,]+)[%％]"),
    MetricPattern("CN_TSF_FLOW_YTD", "TSF_FLOW_YTD", "社会融资规模增量累计", "tn_cny_ytd", r"社会融资规模增量累计为(?P<value>[\d.,]+)万亿元", False),
]


PBOC_CORE_IDS = frozenset(metric.canonical_id for metric in METRICS)


class PBOCSource(BaseSource):
    source = "PBOC"
    observation_source = "PBOC"
    country = "CN"
    parser_version = "pboc_article_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        base = "http://www.pbc.gov.cn/diaochatongjisi/116219/index.html"
        return [
            SourceInventoryEntry(
                source=self.observation_source,
                dataset="金融统计数据报告及社会融资规模历史新闻稿",
                url=base,
                earliest_period=None,
                latest_period=None,
                frequency="M",
                format="html/xls",
                archive_available=True,
                release_timestamp_available=True,
                historical_revision_available=True,
                estimated_count=None,
                evidence="官方历史年度索引；起止期须由受限 discovery 实测，不使用预填日期",
            )
        ]

    def parse_article(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, text = html_text(content)
        if len(re.findall(r"20\d{2}[.年/-](?:0?[1-9]|1[0-2])", text)) >= 6 and (
            "货币供应量" in text or "Money Supply" in text
        ):
            rows = self._parse_money_supply_table(soup, artifact)
            self.validate_row_count(rows)
            return rows
        year, month = extract_period_from_title(soup, text)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        metric_text = re.sub(r"\s+", "", text)
        rows: list[dict] = []
        for metric in METRICS:
            match = re.search(metric.pattern, metric_text, flags=re.S)
            if not match:
                continue
            if metric.percent:
                value = signed_percent(match.group("value"), match.groupdict().get("direction"))
            else:
                value = float(match.group("value").replace(",", ""))
            rows.append(
                make_observation(
                    source=self.observation_source,
                    canonical_series_id=metric.canonical_id,
                    source_series_id=metric.source_id,
                    series_name=metric.name,
                    unit=metric.unit,
                    year=year,
                    month=month,
                    value=value,
                    artifact=artifact,
                    release=release,
                    parser_version=self.parser_version,
                )
            )
        self.validate_row_count(rows)
        return rows

    def _parse_money_supply_table(self, soup, artifact: RawArtifact) -> list[dict]:
        """Parse annual official money-supply tables as current-history PIT_D."""
        release = {
            "release_at": None,
            "available_at": artifact.retrieved_at,
            "release_date_source": "official_bulk_history_first_seen_only",
            "pit_grade": "D",
        }
        periods: list[tuple[int, int]] = []
        metric_values: dict[str, list[float]] = {}
        aliases = {
            "CN_M2_STOCK": ("M2_STOCK", "M2余额", ("货币和准货币", "M2")),
            "CN_M1_STOCK": ("M1_STOCK", "M1余额", ("货币（M1）", "货币(M1)", "M1")),
            "CN_M0_STOCK": ("M0_STOCK", "M0余额", ("流通中现金", "流通中货币", "M0")),
        }
        for table in soup.find_all("table"):
            table_periods: list[tuple[int, int]] = []
            table_metrics: dict[str, list[float]] = {}
            for tr in table.find_all("tr"):
                cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all(["th", "td"])]
                row_text = " ".join(cells)
                found_periods = [
                    (int(year), int(month))
                    for year, month in re.findall(r"(20\d{2})[.年/-](0?[1-9]|1[0-2])", row_text)
                ]
                if len(found_periods) >= 6:
                    table_periods = found_periods
                    continue
                for canonical, (_, _, labels) in aliases.items():
                    if not any(label in row_text for label in labels):
                        continue
                    numbers = [
                        float(value.replace(",", ""))
                        for value in re.findall(r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.\d+)?", row_text)
                    ]
                    # Remove the M0/M1/M2 label number if it was captured.
                    if numbers and numbers[0] in {0.0, 1.0, 2.0} and len(numbers) > len(table_periods):
                        numbers = numbers[1:]
                    if table_periods and len(numbers) >= len(table_periods):
                        table_metrics[canonical] = numbers[-len(table_periods):]
            if len(table_periods) > len(periods) and table_metrics:
                periods = table_periods
                metric_values = table_metrics
        if not periods or not metric_values:
            return []
        rows: list[dict[str, Any]] = []
        for canonical, values in metric_values.items():
            source_id, name, _ = aliases[canonical]
            for (year, month), value in zip(periods, values, strict=True):
                rows.append(make_observation(
                    source=self.observation_source,
                    canonical_series_id=canonical,
                    source_series_id=source_id,
                    series_name=name,
                    unit="tn_cny",
                    year=year,
                    month=month,
                    value=value / 10000.0,
                    artifact=artifact,
                    release=release,
                    parser_version="pboc_money_supply_table_v1",
                ))
        return rows


class PBOCMirrorSource(PBOCSource):
    """Parse national PBOC reports republished by reviewed government sites.

    The network adapter has its own host allowlist, while observations retain
    PBOC as the producing source. A government reprint proves visibility only
    from the reprint publication time, so even an exact timestamp is PIT_B.
    """

    source = "PBOC_MIRROR"
    observation_source = "PBOC"
    parser_version = "pboc_government_reprint_v1"
    expected_min_rows = len(PBOC_CORE_IDS)

    def parse_article(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, _ = html_text(content)
        headlines = [
            " ".join(str(node).split())
            for node in soup.find_all(string=re.compile(r"20\d{2}年.*金融统计数据报告"))
        ]
        headline = min(headlines, key=len) if headlines else ""
        if not headline or re.search(
            r"(?:上海|吉林|青岛)(?:市|省)?.*金融统计数据报告", headline
        ):
            raise ValueError(
                "government reprint is not an unambiguous national PBOC report"
            )

        rows = super().parse_article(content, artifact)
        observed_ids = {row["canonical_series_id"] for row in rows}
        missing = sorted(PBOC_CORE_IDS - observed_ids)
        if missing:
            raise ValueError(
                f"government reprint is missing PBOC core fields: {missing}"
            )

        for row in rows:
            if row["pit_grade"] == "D" or row["release_at"] is None:
                raise ValueError("government reprint has no publication date evidence")
            evidence = str(row["release_date_source"] or "")
            row["pit_grade"] = "B"
            row["release_date_source"] = (
                "government_reprint_page_timestamp"
                if "timestamp" in evidence
                else "government_reprint_page_date"
            )
            row["parser_version"] = self.parser_version
        return rows


# Backward-compatible import name; network remains disabled unless explicitly enabled.
PBOCScraper = PBOCSource
