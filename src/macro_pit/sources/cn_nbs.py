from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from ..archive import RawArtifact
from ..errors import DataContractError
from .base import BaseSource, SourceInventoryEntry, decode_content
from .cn_common import (
    extract_period,
    extract_release_evidence,
    html_text,
    make_observation,
    make_quarterly_observation,
    signed_percent,
)
from ..timeutils import SHANGHAI
from .nbs_economy import economy_table_values, ordered_national_unemployment
from .nbs_legacy_activity import legacy_activity_values


@dataclass(frozen=True)
class NBSSeries:
    canonical_id: str
    source_id: str
    name: str
    unit: str
    seasonal_adjustment: str = "NSA"


SERIES = {
    "A010101": NBSSeries("CN_CPI_YOY", "A010101", "居民消费价格同比", "pct_yoy"),
}


class NBSSource(BaseSource):
    source = "NBS"
    country = "CN"
    parser_version = "nbs_easyquery_final_v1"

    def inventory(self) -> list[SourceInventoryEntry]:
        return [
            SourceInventoryEntry(
                source=self.source,
                dataset="国家数据月度/季度指标",
                url="https://data.stats.gov.cn/easyquery.htm",
                earliest_period=None,
                latest_period=None,
                frequency="M/Q",
                format="json",
                archive_available=True,
                release_timestamp_available=False,
                historical_revision_available=False,
                estimated_count=None,
                evidence="当前历史表只作为 PIT_D；不得把最终值标成 PIT_A",
            ),
            SourceInventoryEntry(
                source=self.source,
                dataset="主要统计信息发布日程及历史新闻稿",
                url="https://www.stats.gov.cn/sj/zxfb/",
                earliest_period=None,
                latest_period=None,
                frequency="event",
                format="html/xls",
                archive_available=True,
                release_timestamp_available=True,
                historical_revision_available=True,
                estimated_count=None,
                evidence="严格 PIT 必须来自带发布日期/时间的官方历史稿件",
            ),
        ]

    def parse_easyquery_final(
        self,
        content: bytes,
        artifact: RawArtifact,
        *,
        series: dict[str, NBSSeries] | None = None,
    ) -> list[dict]:
        """Parse the current NBS historical table as PIT_D only.

        The easyquery history does not prove original vintages or release times;
        it therefore becomes legally visible only at this project's first-seen
        timestamp.
        """
        payload = _json_payload(content)
        nodes = payload.get("returndata", {}).get("datanodes")
        if not isinstance(nodes, list):
            raise DataContractError("NBS easyquery response has no returndata.datanodes list")
        mappings = series or SERIES
        release = {
            "release_at": None,
            "available_at": artifact.retrieved_at,
            "release_date_source": "first_seen_only",
            "pit_grade": "D",
        }
        rows: list[dict] = []
        for node in nodes:
            data = node.get("data", {})
            if not data.get("hasdata"):
                continue
            dimensions = {item.get("wdcode"): item.get("valuecode") for item in node.get("wds", [])}
            source_id = dimensions.get("zb")
            period_code = dimensions.get("sj")
            mapping = mappings.get(source_id)
            if mapping is None or not period_code or len(period_code) != 6:
                continue
            year, month = int(period_code[:4]), int(period_code[4:])
            rows.append(
                make_observation(
                    source=self.source,
                    canonical_series_id=mapping.canonical_id,
                    source_series_id=mapping.source_id,
                    series_name=mapping.name,
                    unit=mapping.unit,
                    year=year,
                    month=month,
                    value=float(data["data"]),
                    artifact=artifact,
                    release=release,
                    parser_version=self.parser_version,
                    seasonal_adjustment=mapping.seasonal_adjustment,
                )
            )
        self.validate_row_count(rows)
        return rows

    def parse(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        text = decode_content(content).lstrip()
        if "datanodes" in text and (text.startswith("{") or text.startswith("<")):
            return self.parse_easyquery_final(content, artifact)
        soup = BeautifulSoup(text, "lxml")
        title = re.sub(r"\s+", "", soup.title.get_text() if soup.title else "")
        # Older titles include the acronym in parentheses. Dispatch from the
        # title so a GDP reference in another release's footnotes cannot route
        # the whole article to the quarterly parser.
        if "初步核算" in title and re.search(r"GDP|国内生产总值", title, re.IGNORECASE):
            return self.parse_gdp_release(content, artifact)
        return self.parse_news_release(content, artifact)

    def parse_gdp_release(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, text = html_text(content)
        title = soup.title.get_text(" ", strip=True) if soup.title else text[:200]
        from .nbs_gdp import current_gdp
        year, quarter, value = current_gdp(soup)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        rows = [
            make_quarterly_observation(
                source=self.source,
                canonical_series_id="CN_GDP_YOY",
                source_series_id="GDP_YOY",
                series_name="国内生产总值同比",
                unit="pct_yoy",
                year=year,
                quarter=quarter,
                value=value,
                artifact=artifact,
                release=release,
                parser_version="nbs_gdp_explicit_quarter_v3",
            )
        ]
        self.validate_row_count(rows)
        return rows

    def parse_news_release(self, content: bytes, artifact: RawArtifact) -> list[dict]:
        soup, text = html_text(content)
        release = extract_release_evidence(soup, text, artifact.retrieved_at)
        legacy = legacy_activity_values(soup, release)
        if legacy is not None:
            legacy_year, canonical, values = legacy
            names = {"CN_INDUSTRIAL_VALUE_ADDED_YOY": "规模以上工业增加值同比",
                     "CN_RETAIL_SALES_YOY": "社会消费品零售总额同比"}
            rows = [make_observation(source=self.source, canonical_series_id=canonical,
                        source_series_id=canonical.removeprefix("CN_"), series_name=names[canonical],
                        unit="pct_yoy", year=legacy_year, month=m, value=v, artifact=artifact,
                        release=release, parser_version="nbs_legacy_activity_v1", seasonal_adjustment="NSA")
                    for m, v in sorted(values.items())]
            self.validate_row_count(rows)
            return rows
        year, month = _news_period(soup, text, release)
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        is_q_and_a = "答记者问" in title
        is_economy = any(term in title for term in ("国民经济", "经济运行")) and not is_q_and_a
        article = soup.select_one(".txt-content") or soup.select_one(".TRS_Editor") or soup.select_one(".trs_editor")
        parse_text = re.sub(r"\s+", "", article.get_text(" ", strip=True) if article else text)
        table_values = economy_table_values(article or soup, month, year=year) if is_economy else {}
        rows: list[dict] = []

        patterns = [
            ("CN_INDUSTRIAL_VALUE_ADDED_YOY", "INDUSTRIAL_VALUE_ADDED_YOY", "规模以上工业增加值同比", "pct_yoy", r"(?<![-—–])\d{1,2}月份，全国规模以上工业增加值同比(?:实际)?(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_SERVICE_PRODUCTION_YOY", "SERVICE_PRODUCTION_YOY", "服务业生产指数同比", "pct_yoy", r"(?<![-—–])\d{1,2}月份，全国服务业生产指数同比(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_RETAIL_SALES_YOY", "RETAIL_SALES_YOY", "社会消费品零售总额同比", "pct_yoy", r"(?<![-—–])\d{1,2}月份，社会消费品零售总额[\d,]+亿元，同比(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_FAI_YTD_YOY", "FAI_YTD_YOY", "固定资产投资累计同比", "pct_yoy", r"全国固定资产投资（不含农户）[\d,]+亿元，同比(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_INFRA_INVESTMENT_YTD_YOY", "INFRA_INVESTMENT_YTD_YOY", "基础设施投资累计同比", "pct_yoy", r"基础设施投资同比(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            # Require a non-Chinese boundary so a sub-industry such as
            # "锂离子电池制造业投资增长20.6%" cannot become the aggregate
            # manufacturing-investment series.
            ("CN_MANUFACTURING_INVESTMENT_YTD_YOY", "MANUFACTURING_INVESTMENT_YTD_YOY", "制造业投资累计同比", "pct_yoy", r"(?<![\u4e00-\u9fff])制造业投资(?:同比)?(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_REAL_ESTATE_INVESTMENT_YTD_YOY", "REAL_ESTATE_INVESTMENT_YTD_YOY", "房地产开发投资累计同比", "pct_yoy", r"房地产开发投资(?:同比)?(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_NEW_HOME_SALES_AREA_YTD_YOY", "NEW_HOME_SALES_AREA_YTD_YOY", "新建商品房销售面积累计同比", "pct_yoy", r"新建商品房销售面积[\d,]+万平方米，同比(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_NEW_HOME_SALES_VALUE_YTD_YOY", "NEW_HOME_SALES_VALUE_YTD_YOY", "新建商品房销售额累计同比", "pct_yoy", r"新建商品房销售额[\d,]+亿元，(?:同比)?(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_URBAN_SURVEYED_UNEMPLOYMENT", "URBAN_SURVEYED_UNEMPLOYMENT", "城镇调查失业率", "pct", r"(?<![-—–])\d{1,2}月份，全国城镇调查失业率为(?P<value>[\d.]+)[%％]"),
            ("CN_CPI_YOY", "CPI_YOY", "居民消费价格同比", "pct_yoy", r"(?:全国)?居民消费价格(?:总水平)?(?:同比|比上年同月|比去年同月)(?P<direction>上涨|上升|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_PPI_YOY", "PPI_YOY", "工业生产者出厂价格同比", "pct_yoy", r"(?:全国)?(?:工业生产者出厂价格|工业品出厂价格)(?:和购进价格同比均|同比|比上年同月|比去年同月)(?:由上月(?:上涨|上升|下降)[\d.]+[%％]转为)?(?P<direction>上涨|上升|下降)(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_MANUFACTURING", "PMI_MANUFACTURING", "制造业采购经理指数", "index", r"(?:中国)?制造业采购经理指数(?:（PMI）)?(?:为|达到|升至|降至)(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_NONMANUFACTURING", "PMI_NONMANUFACTURING", "非制造业商务活动指数", "index", r"非制造业商务活动指数(?:为|和综合PMI产出指数分别为)(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_COMPOSITE", "PMI_COMPOSITE", "综合PMI产出指数", "index", r"综合PMI产出指数为(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_PRODUCTION", "PMI_PRODUCTION", "制造业PMI生产指数", "index", r"生产指数为(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_NEW_ORDERS", "PMI_NEW_ORDERS", "制造业PMI新订单指数", "index", r"新订单指数为(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_RAW_MATERIAL_INVENTORY", "PMI_RAW_MATERIAL_INVENTORY", "制造业PMI原材料库存指数", "index", r"原材料库存指数为(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_EMPLOYMENT", "PMI_EMPLOYMENT", "制造业PMI从业人员指数", "index", r"从业人员指数为(?P<value>[\d.]+)[%％]"),
            ("CN_PMI_SUPPLIER_DELIVERY", "PMI_SUPPLIER_DELIVERY", "制造业PMI供应商配送时间指数", "index", r"供应商配送时间指数为(?P<value>[\d.]+)[%％]"),
        ]
        # In a combined release, an unqualified first match can be a YTD rate.
        # Fallbacks must explicitly name this month's observation, including CPI.
        monthly_prefix = fr"(?<![\d年\-—–至]){month}月份?[，,](?:全国)?"
        growth = r"(?P<direction>增长|下降)(?P<value>[\d.]+)[%％]"
        price_change = r"(?P<direction>上涨|上升|下降)(?P<value>[\d.]+)[%％]"
        economy_patterns = {
            "CN_INDUSTRIAL_VALUE_ADDED_YOY": monthly_prefix + r"规模以上工业增加值同比(?:实际)?" + growth,
            "CN_SERVICE_PRODUCTION_YOY": monthly_prefix + r"服务业生产指数同比" + growth,
            "CN_RETAIL_SALES_YOY": monthly_prefix + r"社会消费品零售总额(?:[\d,]+亿元[，,])?同比" + growth,
            "CN_CPI_YOY": monthly_prefix + r"居民消费价格(?:总水平)?(?:[（(]CPI[）)])?同比" + price_change,
            "CN_PPI_YOY": monthly_prefix + r"(?:工业生产者出厂价格|工业品出厂价格)同比" + price_change,
            "CN_URBAN_SURVEYED_UNEMPLOYMENT": monthly_prefix + r"城镇调查失业率为(?P<value>[\d.]+)[%％]",
        }
        q_and_a_patterns = dict(economy_patterns)
        # Q&A prose may omit the word "同比" after an explicitly named
        # current month. Keep the month anchor, which prevents an older or
        # comparative price number elsewhere in the interview from matching.
        q_and_a_patterns["CN_PPI_YOY"] = (
            monthly_prefix
            + r"[^。；;]{0,80}?(?:工业生产者出厂价格|工业品出厂价格)(?:同比)?"
            + price_change
        )
        for canonical, source_id, name, unit, pattern in patterns:
            if is_q_and_a and canonical in q_and_a_patterns:
                pattern = q_and_a_patterns[canonical]
            elif is_economy and canonical in economy_patterns:
                pattern = economy_patterns[canonical]
            if is_economy and canonical == "CN_INFRA_INVESTMENT_YTD_YOY":
                pattern = r"(?:基础设施投资同比|分领域看[，,]基础设施投资(?:同比)?)" + growth
            match = re.search(pattern, parse_text)
            if is_economy and canonical == "CN_URBAN_SURVEYED_UNEMPLOYMENT" and not match and month >= 3:
                # June 2022 states April's national rate, then gives May/June
                # as an ordered pair. Keep the national scope and all months
                # explicit; a local-hukou rate or quarterly average is different.
                paired = (fr"(?<![\d\-—–至]){month-2}月份[，,]全国城镇调查失业率为[\d.]+[%％][；;]"
                          fr"{month-1}、{month}月份连续回落[，,]分别为[\d.]+[%％]、(?P<value>[\d.]+)[%％]")
                match = re.search(paired, parse_text)
            if canonical in table_values:
                value = table_values[canonical]
                if value is None:
                    continue
            elif not match:
                continue
            else:
                direction = match.groupdict().get("direction")
                if direction:
                    direction = "下降" if direction == "下降" else None
                value = signed_percent(match.group("value"), direction)
            rows.append(
                make_observation(
                    source=self.source,
                    canonical_series_id=canonical,
                    source_series_id=source_id,
                    series_name=name,
                    unit=unit,
                    year=year,
                    month=month,
                    value=value,
                    artifact=artifact,
                    release=release,
                    parser_version="nbs_news_release_v5",
                    seasonal_adjustment="SA" if canonical.startswith("CN_PMI_") else "NSA",
                )
            )
        if is_economy:
            for observed_month, value in ordered_national_unemployment(parse_text, month).items():
                canonical = "CN_URBAN_SURVEYED_UNEMPLOYMENT"
                period = f"{year:04d}-{observed_month:02d}"
                existing = [r for r in rows if r["canonical_series_id"] == canonical and r["period"] == period]
                if existing:
                    if existing[0]["value"] != value:
                        raise DataContractError("National unemployment prose/table conflict")
                    continue
                rows.append(make_observation(source=self.source, canonical_series_id=canonical,
                            source_series_id="URBAN_SURVEYED_UNEMPLOYMENT", series_name="城镇调查失业率",
                            unit="pct", year=year, month=observed_month, value=value, artifact=artifact,
                            release=release, parser_version="nbs_ordered_unemployment_v1", seasonal_adjustment="NSA"))
        flat_cpi = (monthly_prefix + r"居民消费价格(?:总水平)?(?:[（(]CPI[）)])?同比持平" if is_economy else
                    r"(?:全国)?居民消费价格(?:总水平)?(?:同比|比上年同月|比去年同月)持平")
        if not any(row["canonical_series_id"] == "CN_CPI_YOY" for row in rows) and re.search(flat_cpi, parse_text):
            rows.append(
                make_observation(
                    source=self.source,
                    canonical_series_id="CN_CPI_YOY",
                    source_series_id="CPI_YOY",
                    series_name="居民消费价格同比",
                    unit="pct_yoy",
                    year=year,
                    month=month,
                    value=0.0,
                    artifact=artifact,
                    release=release,
                    parser_version="nbs_news_release_v5",
                    seasonal_adjustment="NSA",
                )
            )
        self.validate_row_count(rows)
        return rows


def _json_payload(content: bytes) -> dict:
    text = decode_content(content).strip()
    if text.startswith("<"):
        text = BeautifulSoup(text, "lxml").get_text(strip=True)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataContractError("NBS response is not valid JSON") from exc
    if payload.get("returncode") not in {None, 200}:
        raise DataContractError(f"NBS returned error code {payload.get('returncode')}")
    return payload


NBSScraper = NBSSource


def _news_period(soup: BeautifulSoup, text: str, release: dict) -> tuple[int, int]:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(term in title for term in ("国民经济", "经济运行")) and "答记者问" not in title:
        article = soup.select_one(".txt-content") or soup.select_one(".TRS_Editor") or soup.select_one(".trs_editor")
        body = re.sub(r"\s+", "", article.get_text(" ", strip=True) if article else text)
        # Quarterly/annual releases cite previous quarters and publication dates
        # early in the prose. The explicitly dated statistics-table caption is
        # evidence for the current monthly data period, unlike those references.
        captions = {(int(y), int(m)) for y,m in re.findall(
            r"(20\d{2})年(1[0-2]|0?[1-9])月份?(?:及[^。]{0,12})?主要统计数据", body)}
        if len(captions) > 1:
            raise DataContractError("Conflicting economy statistics-table periods")
        if captions:
            return captions.pop()
    title_match = re.search(
        r"(?:(20\d{2})\s*年)?(?:1\s*[-—–至]\s*)?(1[0-2]|0?[1-9])\s*月份?",
        title,
    )
    if title_match:
        year = int(title_match.group(1)) if title_match.group(1) else None
        if year is None and release.get("release_at") is not None:
            published = release["release_at"].astimezone(SHANGHAI)
            data_month = int(title_match.group(2))
            year = published.year - 1 if data_month > published.month else published.year
        if year is not None:
            return year, int(title_match.group(2))
    return extract_period(text)
