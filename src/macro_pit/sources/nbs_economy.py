"""Read explicitly headed monthly/YTD columns in NBS combined releases."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..errors import DataContractError


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("％", "%").replace("－", "-")


def ordered_national_unemployment(text: str, month: int) -> dict[int, float]:
    """Read explicitly ordered national monthly rates, never quarterly averages.

    The April 2018 first regular release lists Jan/Feb/Mar in one sentence.
    All observations inherit the enclosing article's actual publication time.
    """
    values: dict[int, float] = {}
    pattern = (r"(?<![\d年])([1-9]|1[0-2])至([1-9]|1[0-2])月份[，,]"
               r"全国城镇调查失业率分别为([^。，,；;]+)")
    for match in re.finditer(pattern, compact(text)):
        start, end = int(match[1]), int(match[2])
        if end != month:
            continue
        raw = re.split(r"[、和]", match[3])
        if start > end or len(raw) != end-start+1 or any(
                not re.fullmatch(r"\d+(?:\.\d+)?%", item) for item in raw):
            raise DataContractError("Ambiguous ordered national unemployment months/values")
        for m, item in zip(range(start, end+1), raw):
            value = float(item[:-1])
            if not 0 <= value <= 100 or (m in values and values[m] != value):
                raise DataContractError("Invalid/conflicting ordered national unemployment")
            values[m] = value
    return values


def economy_table_values(soup: BeautifulSoup, month: int, *, year: int | None = None) -> dict[str, float | None]:
    """Fail closed on unknown headers, combined-only months, or conflicting tables.

    The supported table has five data cells: name, monthly level, monthly YoY,
    YTD level, YTD YoY. Empty monthly cells stay empty; no interpolation.
    Duplicate print/mobile tables must agree. Historical urban investment is
    deliberately not mapped to the modern investment-excluding-rural-households series.
    """
    values: dict[str, float | None] = {}
    labels = {
        "规模以上工业增加值": ("CN_INDUSTRIAL_VALUE_ADDED_YOY", 2),
        "服务业生产指数": ("CN_SERVICE_PRODUCTION_YOY", 2),
        "社会消费品零售总额": ("CN_RETAIL_SALES_YOY", 2),
        "居民消费价格": ("CN_CPI_YOY", 2),
        "工业生产者出厂价格": ("CN_PPI_YOY", 2),
        "工业品出厂价格": ("CN_PPI_YOY", 2),
        "固定资产投资（不含农户）": ("CN_FAI_YTD_YOY", 4),
        "房地产开发投资": ("CN_REAL_ESTATE_INVESTMENT_YTD_YOY", 4),
        "新建商品房销售面积": ("CN_NEW_HOME_SALES_AREA_YTD_YOY", 4),
        "新建商品房销售额": ("CN_NEW_HOME_SALES_VALUE_YTD_YOY", 4),
        "全国城镇调查失业率": ("CN_URBAN_SURVEYED_UNEMPLOYMENT", 1),
    }
    # Official 2022 real-estate release definitions explicitly say both sales
    # metrics measure newly built properties and are cumulative. Limit this
    # reviewed historical alias to the 2022/2023 combined-release layouts.
    # Evidence: reports/v2/history/nbs/nbs_economy_batch2/sales_definition_web_evidence.json
    if year in {2022, 2023}:
        labels["商品房销售面积"] = ("CN_NEW_HOME_SALES_AREA_YTD_YOY", 4)
        labels["商品房销售额"] = ("CN_NEW_HOME_SALES_VALUE_YTD_YOY", 4)
    for table in soup.find_all("table"):
        rows = [[compact(c.get_text("", strip=True)) for c in tr.find_all(["th", "td"])]
                for tr in table.find_all("tr")]
        header_index = None
        for i, cells in enumerate(rows[:8]):
            if (len(cells) == 3 and cells[0] in {"", "指标"}
                    and re.fullmatch(fr"0?{month}月份?", cells[1])
                    and re.fullmatch(fr"1[-—–至]0?{month}月份?", cells[2])):
                header_index = i
                break
        if header_index is None or header_index + 1 >= len(rows):
            continue
        subheader = [c.replace("（", "(").replace("）", ")") for c in rows[header_index+1]]
        if subheader != ["绝对量", "同比增长(%)", "绝对量", "同比增长(%)"]:
            continue
        for cells in rows[header_index+2:]:
            # The February 2010 layout has an empty spacer before each data row.
            # Header verification above still fixes the four measure columns.
            if len(cells) == 6 and cells[0] == "":
                cells = cells[1:]
            if len(cells) != 5:
                continue
            label = re.sub(r"^[一二三四五六七八九十]+、", "", cells[0])
            label = re.sub(r"^[（(][一二三四五六七八九十]+[）)]", "", label)
            label = re.sub(r"[（(](?:亿元|万平方米|%)[）)]$", "", label)
            if label not in labels:
                continue
            canonical, column = labels[label]
            raw = cells[column]
            if raw in {"", "…", "...", "—", "-"}:
                value = None
            elif not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
                raise DataContractError(f"Unexpected economy YoY cell: {label}: {raw!r}")
            else:
                value = float(raw)
            if canonical in values and values[canonical] != value:
                raise DataContractError(f"Conflicting economy tables for {canonical}")
            values[canonical] = value
    return values
