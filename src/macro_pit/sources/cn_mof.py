from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..archive import RawArtifact
from .base import BaseSource, SourceInventoryEntry
from .cn_common import extract_period_from_title, extract_release_evidence, html_text, make_observation, signed_percent


@dataclass(frozen=True)
class FiscalMetric:
    canonical_id: str
    source_id: str
    name: str
    labels: tuple[str, ...]


METRICS = [
    FiscalMetric("CN_GENERAL_BUDGET_REVENUE_YTD_YOY", "GENERAL_BUDGET_REVENUE_YTD_YOY", "一般公共预算收入累计同比", ("全国一般公共预算收入", "全国一般公共财政收入", "全国公共财政收入", "全国财政收入")),
    FiscalMetric("CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY", "GENERAL_BUDGET_EXPENDITURE_YTD_YOY", "一般公共预算支出累计同比", ("全国一般公共预算支出", "全国一般公共财政支出", "全国公共财政支出", "全国财政支出")),
    FiscalMetric("CN_TAX_REVENUE_YTD_YOY", "TAX_REVENUE_YTD_YOY", "税收收入累计同比", ("全国税收收入", "财政收入中的税收收入", "税收收入")),
    FiscalMetric("CN_NONTAX_REVENUE_YTD_YOY", "NONTAX_REVENUE_YTD_YOY", "非税收入累计同比", ("非税收入",)),
    FiscalMetric("CN_GOV_FUND_REVENUE_YTD_YOY", "GOV_FUND_REVENUE_YTD_YOY", "政府性基金预算收入累计同比", ("全国政府性基金预算收入", "全国政府性基金收入")),
    FiscalMetric("CN_GOV_FUND_EXPENDITURE_YTD_YOY", "GOV_FUND_EXPENDITURE_YTD_YOY", "政府性基金预算支出累计同比", ("全国政府性基金预算支出", "全国政府性基金支出")),
    FiscalMetric("CN_LAND_SALE_REVENUE_YTD_YOY", "LAND_SALE_REVENUE_YTD_YOY", "国有土地出让收入累计同比", ("国有土地使用权出让收入",)),
]


class MOFSource(BaseSource):
    source = "MOF"
    country = "CN"
    parser_version = "mof_fiscal_release_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="财政收支情况历史新闻稿",
                url="https://gks.mof.gov.cn/tongjishuju/",
                earliest_period=None,
                latest_period=None,
                frequency="M",
                format="html/xls",
                archive_available=True,
                release_timestamp_available=False,
                historical_revision_available=True,
                estimated_count=None,
                evidence="官方列表与正文；无时分秒时严格按 PIT_B 次日00:00可用",
            )
        ]

    def parse_release(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, text = html_text(content)
        year, month = extract_period_from_title(soup, text)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        # Legacy MOF releases use full-width digits, decimal points and
        # percent signs. Normalize typography before applying the same
        # evidence-preserving extraction rules used for modern pages.
        parse_text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
        rows: list[dict] = []
        for metric in METRICS:
            match = _find_ytd_change(parse_text, metric.labels, month)
            if not match:
                continue
            rows.append(
                make_observation(
                    source=self.source,
                    canonical_series_id=metric.canonical_id,
                    source_series_id=metric.source_id,
                    series_name=metric.name,
                    unit="pct_yoy",
                    year=year,
                    month=month,
                    value=signed_percent(match.group("value"), match.group("direction")),
                    artifact=artifact,
                    release=release,
                    parser_version=self.parser_version,
                )
            )
        self.validate_row_count(rows)
        return rows


def _find_ytd_change(text: str, labels: tuple[str, ...], month: int):
    markers = (
        rf"1[-—–至]{month}月(?:份)?(?:累计)?",
        rf"前{month}个?月(?:累计)?",
    )
    candidates = []
    for label in labels:
        for occurrence in re.finditer(re.escape(label), text):
            after = text[occurrence.start() : occurrence.start() + 220]
            match = re.search(
                rf"{re.escape(label)}[^。；]{{0,180}}?(?P<direction>增长|下降|微增)(?P<value>[\d.]+)[%％]",
                after,
            )
            if not match:
                continue
            before = text[max(0, occurrence.start() - 160) : occurrence.start()]
            sentence_start = max(before.rfind("。"), before.rfind("；"), before.rfind(";"))
            local_before = before[sentence_start + 1 :]
            is_ytd = any(re.search(marker, local_before) for marker in markers) or "累计" in local_before
            candidates.append((is_ytd, occurrence.start(), match))
    if not candidates:
        return None
    # Prefer an explicitly cumulative/YTD occurrence, then the first matching
    # occurrence to preserve the existing modern-page behavior.
    candidates.sort(key=lambda item: (not item[0], item[1]))
    return candidates[0][2]
