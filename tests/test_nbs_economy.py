import hashlib
from datetime import datetime

import pytest
from bs4 import BeautifulSoup

from macro_pit.archive import RawArtifact
from macro_pit.errors import DataContractError
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.sources.nbs_economy import economy_table_values
from macro_pit.timeutils import SHANGHAI


def table(month=8, *, cpi="0.6", industrial="4.5", header="同比增长（%）"):
    return f"""<table><tr><td>指标</td><td>{month}月</td><td>1-{month}月</td></tr>
    <tr><td>绝对量</td><td>{header}</td><td>绝对量</td><td>{header}</td></tr>
    <tr><td>一、规模以上工业增加值</td><td>…</td><td>{industrial}</td><td>…</td><td>5.8</td></tr>
    <tr><td>三、固定资产投资（不含农户）（亿元）</td><td>…</td><td>…</td><td>329385</td><td>3.4</td></tr>
    <tr><td>五、社会消费品零售总额（亿元）</td><td>38726</td><td>2.1</td><td>312452</td><td>3.4</td></tr>
    <tr><td>八、居民消费价格</td><td>…</td><td>{cpi}</td><td>…</td><td>0.2</td></tr>
    <tr><td>九、工业生产者出厂价格</td><td>…</td><td>- 1 . 8</td><td>…</td><td>-1.9</td></tr>
    </table>"""


def parse(tmp_path, body, title="2024年8月份国民经济运行总体平稳", outside=""):
    content = f"<html><title>{title}</title><body>2024/09/14 10:00<div class='txt-content'>{body}</div>{outside}</body></html>".encode()
    raw = tmp_path / "release.html"
    raw.write_bytes(content)
    artifact = RawArtifact("NBS", "https://www.stats.gov.cn/sj/zxfb/202409/test.html", str(raw),
                           hashlib.sha256(content).hexdigest(), "text/html", datetime(2026, 9, 8, tzinfo=SHANGHAI), len(content))
    source = NBSSource(allow_network=False)
    try:
        return {r["canonical_series_id"]: r for r in source.parse(content, artifact)}
    finally:
        source.close()


def test_monthly_values_win_over_first_ytd_match(tmp_path):
    result = parse(tmp_path, "1-8月份，全国居民消费价格同比上涨0.2%。" + table())
    assert result["CN_CPI_YOY"]["value"] == 0.6
    assert result["CN_PPI_YOY"]["value"] == -1.8
    assert result["CN_INDUSTRIAL_VALUE_ADDED_YOY"]["value"] == 4.5
    assert result["CN_RETAIL_SALES_YOY"]["value"] == 2.1
    assert result["CN_FAI_YTD_YOY"]["value"] == 3.4
    assert {r["period"] for r in result.values()} == {"2024-08"}


def test_month_end_and_ytd_columns_need_explicit_correct_headers():
    assert not economy_table_values(BeautifulSoup(table(), "lxml"), 9)
    assert not economy_table_values(BeautifulSoup(table(header="环比增长（%）"), "lxml"), 8)


def test_combined_jan_feb_does_not_manufacture_feb_industry(tmp_path):
    result = parse(tmp_path, "1-2月份，规模以上工业增加值同比增长20.7%。" + table(2, industrial="…"),
                   title="2024年1-2月份国民经济主要指标数据")
    assert "CN_INDUSTRIAL_VALUE_ADDED_YOY" not in result
    assert result["CN_CPI_YOY"]["period"] == "2024-02"


def test_old_urban_investment_is_not_modern_fai():
    content = table().replace("固定资产投资（不含农户）", "城镇固定资产投资")
    result = economy_table_values(BeautifulSoup(content, "lxml"), 8)
    assert "CN_FAI_YTD_YOY" not in result


def test_duplicate_tables_must_agree():
    same = economy_table_values(BeautifulSoup(table()+table(), "lxml"), 8)
    assert same["CN_CPI_YOY"] == 0.6
    with pytest.raises(DataContractError, match="Conflicting economy tables"):
        economy_table_values(BeautifulSoup(table()+table(cpi="0.2"), "lxml"), 8)


def test_zero_is_a_valid_official_cell(tmp_path):
    assert parse(tmp_path, table(cpi="0"))["CN_CPI_YOY"]["value"] == 0


def test_fallback_handles_cpi_abbreviation_and_retail_without_amount(tmp_path):
    body = "1-8月份，全国居民消费价格同比上涨0.2%。8月份，全国居民消费价格（CPI）同比上涨0.6%。8月份，社会消费品零售总额同比增长2.1%。"
    result = parse(tmp_path, body)
    assert result["CN_CPI_YOY"]["value"] == 0.6
    assert result["CN_RETAIL_SALES_YOY"]["value"] == 2.1


def test_december_ytd_suffix_cannot_match_february(tmp_path):
    result = parse(tmp_path, "1-12月份，社会消费品零售总额同比增长8.0%。2月份，全国居民消费价格同比上涨0.2%。",
                   title="2024年2月份国民经济运行情况")
    assert "CN_RETAIL_SALES_YOY" not in result


def test_navigation_values_are_not_article_evidence(tmp_path):
    result = parse(tmp_path, "8月份，全国居民消费价格同比上涨0.6%。",
                   outside="<footer>8月份，社会消费品零售总额同比增长99.0%。</footer>")
    assert "CN_RETAIL_SALES_YOY" not in result


def test_cumulative_flat_cpi_is_not_a_monthly_zero(tmp_path):
    result = parse(tmp_path, "1-8月份，居民消费价格同比持平。8月份，社会消费品零售总额同比增长2.1%。")
    assert "CN_CPI_YOY" not in result


def test_legacy_spacer_does_not_shift_yoy_to_level():
    html = table(2, industrial="12.8").replace("<tr><td>一、", "<tr><td></td><td>一、")
    assert economy_table_values(BeautifulSoup(html, "lxml"), 2)["CN_INDUSTRIAL_VALUE_ADDED_YOY"] == 12.8


def test_services_use_monthly_column_even_with_cumulative_prose(tmp_path):
    extra="<tr><td>四、服务业生产指数</td><td>…</td><td>-0.9</td><td>…</td><td>2.5</td></tr>"
    result=parse(tmp_path,"1-8月份，全国服务业生产指数同比增长2.5%。"+table().replace("</table>",extra+"</table>"))
    assert result["CN_SERVICE_PRODUCTION_YOY"]["value"] == -0.9


def test_unemployment_is_monthly_level_not_change_or_ytd_average(tmp_path):
    extra="<tr><td>九、全国城镇调查失业率（%）</td><td>5.8</td><td>0.5（百分点）</td><td>5.5</td><td>0.1（百分点）</td></tr>"
    result=parse(tmp_path,table().replace("</table>",extra+"</table>"))
    assert result["CN_URBAN_SURVEYED_UNEMPLOYMENT"]["value"] == 5.8
    assert result["CN_URBAN_SURVEYED_UNEMPLOYMENT"]["unit"] == "pct"


def test_real_estate_is_ytd_and_old_sales_label_needs_definition_review():
    extra="""<tr><td>（一）房地产开发投资（亿元）</td><td>…</td><td>…</td><td>27765</td><td>0.7</td></tr>
    <tr><td>（五）新建商品房销售面积（万平方米）</td><td>…</td><td>…</td><td>31046</td><td>-13.8</td></tr>
    <tr><td>（六）商品房销售额（亿元）</td><td>…</td><td>…</td><td>29655</td><td>-22.7</td></tr>"""
    result=economy_table_values(BeautifulSoup(table().replace("</table>",extra+"</table>"),"lxml"),8)
    assert result["CN_REAL_ESTATE_INVESTMENT_YTD_YOY"] == 0.7
    assert result["CN_NEW_HOME_SALES_AREA_YTD_YOY"] == -13.8
    assert "CN_NEW_HOME_SALES_VALUE_YTD_YOY" not in result
    reviewed=economy_table_values(BeautifulSoup(table().replace("</table>",extra+"</table>"),"lxml"),8,year=2022)
    assert reviewed["CN_NEW_HOME_SALES_VALUE_YTD_YOY"] == -22.7
    assert "CN_NEW_HOME_SALES_VALUE_YTD_YOY" not in economy_table_values(BeautifulSoup(table().replace("</table>",extra+"</table>"),"lxml"),8,year=2010)


def test_unemployment_paired_months_keep_national_scope(tmp_path):
    body="上半年，全国城镇调查失业率平均为5.7%。4月份，全国城镇调查失业率为6.1%；5、6月份连续回落，分别为5.9%、5.5%。6月份，本地户籍人口调查失业率为5.3%。6月份，全国居民消费价格同比上涨2.5%。"
    result=parse(tmp_path,body,title="2022年6月份国民经济运行情况")
    assert result["CN_URBAN_SURVEYED_UNEMPLOYMENT"]["value"] == 5.5
    local=parse(tmp_path,body.replace("4月份，全国城镇调查失业率","4月份，本地户籍人口调查失业率"),title="2022年6月份国民经济运行情况")
    assert "CN_URBAN_SURVEYED_UNEMPLOYMENT" not in local


def test_quarterly_economy_caption_overrides_prior_quarter_and_publication_date(tmp_path):
    result=parse(tmp_path,"（2022年4月18日）一季度比2021年四季度环比增长1.3%。2022年3月份及一季度主要统计数据"+table(3),title="一季度国民经济开局总体平稳")
    assert {r["period"] for r in result.values()} == {"2022-03"}


def test_annual_economy_caption_identifies_december_monthly_values(tmp_path):
    result=parse(tmp_path,"2023年1月17日。2022年一季度同比增长4.8%。2022年12月份及全年主要统计数据"+table(12),title="2022年国民经济顶住压力再上新台阶")
    assert {r["period"] for r in result.values()} == {"2022-12"}


def test_economy_running_title_uses_combined_release_rules(tmp_path):
    result=parse(tmp_path,"2022年四季度同比增长2.9%。2023年12月份及全年主要统计数据"+table(12),title="2023年经济运行稳中有进")
    assert {r["period"] for r in result.values()} == {"2023-12"}
    assert result["CN_CPI_YOY"]["value"] == 0.6
