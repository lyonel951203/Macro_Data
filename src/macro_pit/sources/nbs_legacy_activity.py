"""Monthly observations explicitly stated in early national activity releases.

Early releases put year-to-date rates in headlines and sometimes state monthly
rates only in the lead paragraph. Never infer a monthly rate from a YTD rate,
rounded amounts, a holiday-adjusted growth rate, or a regional breakdown.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..errors import DataContractError
from ..timeutils import SHANGHAI


def legacy_activity_values(soup: BeautifulSoup, release: dict) -> tuple[int, str, dict[int, float]] | None:
    title = re.sub(r"\s+", "", soup.title.get_text() if soup.title else "")
    industrial = bool(re.search(r"(?:全国|我国)(?:完成|实现)?工业(?:生产(?!者)|增加值|实现增加值)", title))
    retail = bool(re.search(r"(?:全国)?社会消费品零售总额", title))
    if not (industrial or retail) or any(t in title for t in ("国民经济", "经济运行", "答记者问", "解读")):
        return None
    published = release.get("release_at")
    if published is None:
        return None
    published = published.astimezone(SHANGHAI)
    end = re.search(r"(?:1[-—–至])?(1[0-2]|[1-9])月份?", title)
    if end:
        end_month = int(end.group(1))
    elif "一季度" in title:
        end_month = 3
    elif "上半年" in title:
        end_month = 6
    else:
        return None
    named_year = re.search(r"(20\d{2})年", title)
    year = int(named_year.group(1)) if named_year else published.year - int(end_month > published.month)
    if not 2000 <= year <= 2010:
        return None
    article = soup.select_one(".txt-content") or soup.select_one(".TRS_Editor") or soup.select_one(".trs_editor")
    if article is None:
        raise DataContractError("Legacy activity release has no article body")
    paragraphs = [re.sub(r"\s+", "", p.get_text()).replace("％", "%") for p in article.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        raise DataContractError("Legacy activity release has no lead paragraph")
    lead = paragraphs[0]
    rate = r"(?P<direction>增长|下降)(?P<value>\d+(?:\.\d+)?)%"
    yoy = r"(?:同比|比(?:去|上)年同(?:月|期))"
    amount = r"[\d,.]+亿(?:元)?"
    monthly = r"(?<![\d\-—–至])(?P<month>1[0-2]|[1-9])月份?"
    result: dict[int, float] = {}

    def collect(pattern: str):
        for match in re.finditer(pattern, lead):
            month = int(match.group("month"))
            if month > end_month:
                raise DataContractError("Legacy monthly observation exceeds release period")
            value = float(match.group("value")) * (-1 if match.group("direction") == "下降" else 1)
            if month in result and result[month] != value:
                raise DataContractError("Conflicting legacy monthly observations")
            result[month] = value

    if industrial:
        subject = (r"(?:全部国有工业企业(?:及|和)年产品销售收入500万元以上的非国有工业企业"
                   r"|全国规模以上工业(?:企业)?)")
        if not re.search(subject, lead):
            raise DataContractError("Unverified legacy industrial population")
        # April 2005's body omits the final character in '增加值'. Its
        # headline explicitly identifies industrial value added. Preserve the
        # original HTML; permit this spelling only with that headline evidence.
        value_added = r"增加值?" if "工业增加值" in title else r"增加值"
        collect(r"^" + monthly + r"[，,]" + subject + r"(?:完成|实现)(?:工业)?" + value_added + amount + r"[，,]" + yoy + rate)
        # An explicit '其中 N月份…' inherits the national YoY scope of the
        # lead, but never the annual/quarterly/YTD period of its headline.
        if re.search(yoy + rate, lead):
            collect(r"其中[，,]?" + monthly + r"(?:当月)?(?:完成|实现)(?:工业)?增加值" + amount + r"[，,](?:" + yoy + r")?" + rate)
        canonical = "CN_INDUSTRIAL_VALUE_ADDED_YOY"
    else:
        if "社会消费品零售总额" not in lead:
            raise DataContractError("Unverified national retail lead paragraph")
        collect(r"^" + monthly + r"[，,](?:全国)?社会消费品零售总额" + amount + r"[，,]" + yoy + rate)
        if re.search(yoy + rate, lead):
            # The reviewed Jan-Feb release explicitly reports each month;
            # both inherit this article's publication timestamp.
            collect(r"(?:其中[，,]?|[，,])" + monthly + r"(?:" + amount + r"[，,])?(?:" + yoy + r")?" + rate)
        canonical = "CN_RETAIL_SALES_YOY"
    return year, canonical, result
