from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO

import pytest
from openpyxl import Workbook

from macro_pit.archive import RawArtifact
from macro_pit.errors import ParserRowCountError
from macro_pit.sources.cn_customs import CustomsSource
from macro_pit.sources.cn_mof import MOFSource
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.sources.cn_pboc import PBOCMirrorSource, PBOCSource
from macro_pit.sources.cn_safe import SAFESource


def artifact(tmp_path, content: bytes, source: str = "PBOC") -> RawArtifact:
    path = tmp_path / "raw.html"
    path.write_bytes(content)
    return RawArtifact(
        source=source,
        url=f"https://official.example/{source.lower()}/release",
        path=path.as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
        content_type="text/html",
        retrieved_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        size=len(content),
    )


def test_pboc_article_extracts_timestamp_and_metrics(tmp_path):
    content = """<html><head><title>2025年1月金融统计数据报告</title><meta name="publishdate" content="2025-02-14"></head><body>
    文章来源：2025-02-14 16:30:05
    广义货币（M2）余额同比增长7.0%。狭义货币（M1）余额同比下降1.2%。
    流通中货币（M0）余额同比增长8.5%。人民币贷款余额同比增长7.2%。
    人民币存款余额同比增长6.1%。人民币贷款增加1.2万亿元。人民币存款增加2.3万亿元。
    社会融资规模存量为400.5万亿元，同比增长8.0%。社会融资规模增量累计为3.2万亿元。
    </body></html>""".encode("utf-8")
    source = PBOCSource(allow_network=False)
    try:
        rows = source.parse_article(content, artifact(tmp_path, content))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert len(rows) == 10
    assert by_id["CN_M1_YOY"]["value"] == -1.2
    assert by_id["CN_TSF_STOCK"]["value"] == 400.5
    assert all(row["pit_grade"] == "A" for row in rows)
    assert all(row["available_at"] == row["release_at"] for row in rows)
    assert by_id["CN_M2_YOY"]["release_at"].isoformat() == "2025-02-14T08:30:05+00:00"


def test_pboc_parser_does_not_confuse_tsf_loan_component_with_total_loans(tmp_path):
    content = """<html><head><title>2026年7月金融统计数据报告</title></head><body>
    文章来源：2026-08-14 16:30:05
    社会融资规模存量为463.27万亿元，同比增长7.4%。其中，对实体经济发放的人民币贷款余额278.57万亿元，同比增长5.2%。
    社会融资规模增量累计为22.25万亿元。其中，对实体经济发放的人民币贷款增加10.17万亿元。
    广义货币（M2）余额同比增长7.7%。狭义货币（M1）余额同比增长4%。流通中货币（M0）余额同比增长11.6%。
    月末人民币存款余额346.47万亿元，同比增长8.1%。前七个月人民币存款增加17.79万亿元。
    月末人民币贷款余额282.29万亿元，同比增长5.1%。前七个月人民币贷款增加10.38万亿元。
    </body></html>""".encode("utf-8")
    source = PBOCSource(allow_network=False)
    try:
        rows = source.parse_article(content, artifact(tmp_path, content))
    finally:
        source.close()
    values = {row["canonical_series_id"]: row["value"] for row in rows}
    assert values["CN_RMB_LOAN_BAL_YOY"] == pytest.approx(5.1)
    assert values["CN_NEW_RMB_LOANS_YTD"] == pytest.approx(10.38)


def test_pboc_government_reprint_is_canonical_pboc_pit_b(tmp_path):
    content = """<html><head><title>2026年7月金融统计数据报告</title></head><body>
    <h1>2026年7月金融统计数据报告</h1> 发布时间：2026-08-17 07:31:14
    社会融资规模存量为 463.27 万亿元，同比增长 7.4%。社会融资规模增量累计为 22.25 万亿元。
    广义货币（M2）余额同比增长 7.7%。狭义货币（M1）余额同比增长 4%。流通中货币（M0）余额同比增长 11.6%。
    月末人民币存款余额同比增长 8.1%。前七个月人民币存款增加 17.79 万亿元。
    月末人民币贷款余额同比增长 5.1%。前七个月人民币贷款增加 10.38 万亿元。
    </body></html>""".encode("utf-8")
    source = PBOCMirrorSource(allow_network=False)
    try:
        rows = source.parse_article(
            content, artifact(tmp_path, content, "PBOC_MIRROR")
        )
    finally:
        source.close()
    assert len(rows) == 10
    assert {row["source"] for row in rows} == {"PBOC"}
    assert {row["pit_grade"] for row in rows} == {"B"}
    assert {row["release_date_source"] for row in rows} == {
        "government_reprint_page_timestamp"
    }
    assert {row["parser_version"] for row in rows} == {
        "pboc_government_reprint_v1"
    }


def test_pboc_government_reprint_rejects_local_report_title(tmp_path):
    content = """<html><head><title>2026年7月青岛市金融统计数据报告</title></head><body>
    <h1>2026年7月青岛市金融统计数据报告</h1> 发布时间：2026-08-17
    </body></html>""".encode("utf-8")
    source = PBOCMirrorSource(allow_network=False)
    try:
        with pytest.raises(ValueError, match="national PBOC report"):
            source.parse_article(
                content, artifact(tmp_path, content, "PBOC_MIRROR")
            )
    finally:
        source.close()


def test_pboc_money_supply_table_is_current_history_pit_d(tmp_path):
    content = """<html><body><table>
    <tr><td>货币供应量 Money Supply</td></tr>
    <tr><td>项目 Item</td><td>2004.01</td><td>2004.02</td><td>2004.03</td><td>2004.04</td><td>2004.05</td><td>2004.06</td></tr>
    <tr><td>货币和准货币（M2）</td><td>225101.93</td><td>227050.72</td><td>231654.60</td><td>233627.86</td><td>234842.40</td><td>238427.49</td></tr>
    <tr><td>货币（M1）</td><td>83805.90</td><td>83556.43</td><td>85815.57</td><td>85603.64</td><td>86780.37</td><td>88627.14</td></tr>
    <tr><td>流通中现金（M0）</td><td>22287.43</td><td>19893.44</td><td>19297.43</td><td>19878.40</td><td>19048.43</td><td>19017.58</td></tr>
    </table></body></html>""".encode("utf-8")
    source = PBOCSource(allow_network=False)
    try:
        rows = source.parse_article(content, artifact(tmp_path, content, "PBOC"))
    finally:
        source.close()
    values = {(row["canonical_series_id"], row["period"]): row for row in rows}
    assert len(rows) == 18
    assert values[("CN_M2_STOCK", "2004-01")]["value"] == pytest.approx(22.510193)
    assert values[("CN_M1_STOCK", "2004-06")]["value"] == pytest.approx(8.862714)
    assert values[("CN_M0_STOCK", "2004-01")]["pit_grade"] == "D"


def test_mof_date_only_release_uses_next_day_boundary(tmp_path):
    content = """<html><head><title>2025年1-7月财政收支情况</title></head><body>
    发布日期：2025-08-20
    全国一般公共预算收入同比下降0.3%。全国一般公共预算支出同比增长3.4%。
    全国税收收入同比下降1.0%。非税收入同比增长2.0%。
    </body></html>""".encode("utf-8")
    source = MOFSource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "MOF"))
    finally:
        source.close()
    assert {row["period"] for row in rows} == {"2025-07"}
    assert {row["pit_grade"] for row in rows} == {"B"}
    assert rows[0]["available_at"].isoformat() == "2025-08-20T16:00:00+00:00"


def test_mof_annual_release_uses_december_and_previous_year_wording(tmp_path):
    content = """<html><head><title>2025年财政收支情况</title></head><body>
    发布日期：2026-01-30
    全国一般公共预算收入216045亿元，比上年下降1.7%。
    全国税收收入176363亿元，比上年增长0.8%；非税收入39682亿元，比上年下降11.3%。
    全国政府性基金预算收入57704亿元，比上年下降7%。
    </body></html>""".encode("utf-8")
    source = MOFSource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "MOF"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert {row["period"] for row in rows} == {"2025-12"}
    assert by_id["CN_GENERAL_BUDGET_REVENUE_YTD_YOY"]["value"] == -1.7
    assert by_id["CN_TAX_REVENUE_YTD_YOY"]["value"] == 0.8


def test_mof_legacy_page_prefers_cumulative_over_monthly_value(tmp_path):
    content = """<html><head><title>2010年10月份财政收支情况</title></head><body>
    发布日期：2010年11月11日
    10月份，全国财政收入7860.31亿元，增长14.8%。
    1-10月累计，全国财政收入70899.82亿元，比去年同期增加12536.02亿元，增长21.5%。
    财政收入中的税收收入62895.14亿元，增长22.6%；非税收入8004.68亿元，增长13.6%。
    10月份，全国财政支出6488.3亿元，增长38.5%。
    1-10月累计，全国财政支出60993.26亿元，增长22.3%。
    </body></html>""".encode("utf-8")
    source = MOFSource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "MOF"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert by_id["CN_GENERAL_BUDGET_REVENUE_YTD_YOY"]["value"] == 21.5
    assert by_id["CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY"]["value"] == 22.3
    assert by_id["CN_TAX_REVENUE_YTD_YOY"]["value"] == 22.6
    assert by_id["CN_NONTAX_REVENUE_YTD_YOY"]["value"] == 13.6


def test_mof_legacy_fullwidth_typography(tmp_path):
    content = """<html><head><title>2013年5月份财政收支情况</title></head><body>
    发布日期：2013年6月9日
    １－５月累计，全国公共财政收入５６２１４亿元，比去年同期增加３４５９亿元，增长６．６％。
    财政收入中的税收收入４８９７９亿元，同比增长６．９％；非税收入７２３５亿元，同比增长４．９％。
    １－５月累计，全国公共财政支出４６６３５亿元，同比增长１３．２％。
    </body></html>""".encode("utf-8")
    source = MOFSource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "MOF"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert by_id["CN_GENERAL_BUDGET_REVENUE_YTD_YOY"]["value"] == 6.6
    assert by_id["CN_TAX_REVENUE_YTD_YOY"]["value"] == 6.9
    assert by_id["CN_NONTAX_REVENUE_YTD_YOY"]["value"] == 4.9
    assert by_id["CN_GENERAL_BUDGET_EXPENDITURE_YTD_YOY"]["value"] == 13.2


def test_nbs_current_history_is_only_pit_d(tmp_path):
    payload = {
        "returncode": 200,
        "returndata": {
            "datanodes": [
                {
                    "data": {"hasdata": True, "data": 0.7},
                    "wds": [
                        {"wdcode": "zb", "valuecode": "A010101"},
                        {"wdcode": "sj", "valuecode": "202501"},
                    ],
                }
            ]
        },
    }
    content = json.dumps(payload).encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse_easyquery_final(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert rows[0]["pit_grade"] == "D"
    assert rows[0]["release_at"] is None
    assert rows[0]["available_at"] == rows[0]["first_seen_at"]


def test_nbs_news_release_uses_reference_month_not_publication_month(tmp_path):
    content = """<html><head><title>1—7月份国民经济运行情况</title></head><body>
    2026/08/17 10:00
    1—7月份，全国规模以上工业增加值同比增长5.3%。7月份，全国规模以上工业增加值同比增长4.5%。
    1—7月份，全国服务业生产指数同比增长4.7%。7月份，全国服务业生产指数同比增长4.3%。
    1—7月份，社会消费品零售总额287744亿元，同比增长1.2%。7月份，社会消费品零售总额39022亿元，同比增长0.6%。
    1—7月份，全国固定资产投资（不含农户）260328亿元，同比下降6.7%。
    基础设施投资同比下降3.6%，制造业投资下降1.7%，房地产开发投资下降19.2%。
    全国新建商品房销售面积45021万平方米，同比下降11.8%；新建商品房销售额42718亿元，下降13.1%。
    7月份，全国城镇调查失业率为5.2%。
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse_news_release(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert {row["period"] for row in rows} == {"2026-07"}
    assert by_id["CN_INDUSTRIAL_VALUE_ADDED_YOY"]["value"] == 4.5
    assert by_id["CN_SERVICE_PRODUCTION_YOY"]["value"] == 4.3
    assert by_id["CN_RETAIL_SALES_YOY"]["value"] == 0.6
    assert by_id["CN_FAI_YTD_YOY"]["value"] == -6.7
    assert by_id["CN_NEW_HOME_SALES_VALUE_YTD_YOY"]["value"] == -13.1
    assert {row["pit_grade"] for row in rows} == {"A"}


def test_nbs_gdp_release_uses_current_quarter_table_cell_only(tmp_path):
    content = """<html><head><title>2026年二季度和上半年国内生产总值初步核算结果</title></head><body>
    2026/07/16 09:30
    <div class="txt-content"><table><tr><th></th><th colspan="2">绝对额（亿元）</th><th colspan="2">比上年同期增长（%）</th></tr>
    <tr><th>二季度</th><th>上半年</th><th>二季度</th><th>上半年</th></tr>
    <tr><td>GDP</td><td>361511</td><td>695704</td><td>4.3</td><td>4.7</td></tr></table></div>
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert len(rows) == 1
    assert rows[0]["period"] == "2026-Q2"
    assert rows[0]["value"] == 4.3
    assert rows[0]["frequency"] == "Q"


def test_nbs_first_quarter_gdp_uses_three_column_layout(tmp_path):
    content = """<html><head><title>2026年一季度国内生产总值初步核算结果</title></head><body>
    2026/04/17 10:00
    <div class="txt-content"><table><tr><th></th><th>绝对额（亿元）</th><th>比上年同期增长（%）</th></tr>
    <tr><td>GDP</td><td>334193</td><td>5.0</td></tr></table></div>
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert rows[0]["period"] == "2026-Q1"
    assert rows[0]["value"] == 5.0


@pytest.mark.parametrize(
    "quarter_title, published, quarter, current, cumulative",
    [
        ("三季度", "2021/10/19", "2021-Q3", 4.9, 9.8),
        ("四季度和全年", "2022/01/18", "2021-Q4", 4.0, 8.1),
    ],
)
def test_nbs_legacy_gdp_parenthesized_title_dispatches_quarterly_table(
    tmp_path, quarter_title, published, quarter, current, cumulative
):
    # Legacy 2021 releases insert the acronym between the Chinese name and
    # the preliminary-accounting label. The final column is cumulative YoY.
    content = f"""<html><head><title>2021年{quarter_title}国内生产总值（GDP）初步核算结果</title></head>
    <body>{published} 09:30
    <div class="txt-content"><table><tr><th></th><th colspan="2">现价总量（亿元）</th><th colspan="2">比上年同期增长（%）</th></tr>
    <tr><th>{3 if quarter.endswith("Q3") else 4}季度</th><th>{"1-3季度" if quarter.endswith("Q3") else "全年"}</th><th>{3 if quarter.endswith("Q3") else 4}季度</th><th>{"1-3季度" if quarter.endswith("Q3") else "全年"}</th></tr>
    <tr><td>GDP</td><td>290964</td><td>823131</td><td>{current}</td><td>{cumulative}</td></tr></table></div>
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert len(rows) == 1
    assert rows[0]["canonical_series_id"] == "CN_GDP_YOY"
    assert rows[0]["frequency"] == "Q"
    assert rows[0]["period"] == quarter
    assert rows[0]["value"] == current
    assert rows[0]["pit_grade"] == "A"


def test_nbs_ppi_joint_equal_price_changes_use_monthly_yoy(tmp_path):
    content = """<html><head><title>2024年12月份工业生产者出厂价格同比降幅收窄</title></head><body>
    2025/01/09 09:30
    2024年12月份，全国工业生产者出厂价格和购进价格同比均下降2.3%；环比均下降0.1%。
    2024年全年，工业生产者出厂价格和购进价格均下降2.2%。
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert len(rows) == 1
    assert rows[0]["canonical_series_id"] == "CN_PPI_YOY"
    assert rows[0]["period"] == "2024-12"
    assert rows[0]["value"] == -2.3


def test_nbs_ppi_joint_unequal_changes_are_not_treated_as_equal(tmp_path):
    content = """<html><head><title>2024年12月份工业生产者价格</title></head><body>
    2025/01/09 09:30 工业生产者出厂价格和购进价格同比分别下降2.3%和2.2%。
    </body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        with pytest.raises(ParserRowCountError):
            source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()


def test_nbs_gdp_footnote_does_not_override_price_release_title(tmp_path):
    content = """<html><head><title>2024年12月份居民消费价格</title></head><body>
    2025/01/09 09:30 全国居民消费价格同比上涨0.1%。
    <footer>相关链接：国内生产总值初步核算结果</footer></body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    assert len(rows) == 1
    assert rows[0]["canonical_series_id"] == "CN_CPI_YOY"
    assert rows[0]["period"] == "2024-12"
    assert rows[0]["value"] == 0.1


def test_nbs_price_release_handles_flat_cpi_and_ppi_without_national_prefix(tmp_path):
    cpi = """<html><head><title>2025年7月份居民消费价格</title></head><body>
    2025/08/09 09:30 全国居民消费价格同比持平。</body></html>""".encode("utf-8")
    ppi = """<html><head><title>2025年7月份工业生产者价格</title></head><body>
    2025/08/09 09:30 工业生产者出厂价格同比下降3.6%。</body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        cpi_rows = source.parse_news_release(cpi, artifact(tmp_path, cpi, "NBS"))
        ppi_rows = source.parse_news_release(ppi, artifact(tmp_path, ppi, "NBS"))
    finally:
        source.close()
    assert cpi_rows[0]["canonical_series_id"] == "CN_CPI_YOY"
    assert cpi_rows[0]["value"] == 0.0
    assert ppi_rows[0]["canonical_series_id"] == "CN_PPI_YOY"
    assert ppi_rows[0]["value"] == -3.6


def test_nbs_legacy_price_wording_and_yearless_december_rollover(tmp_path):
    cpi = """<html><head><title>4月份居民消费价格总水平同比上涨1.8%</title></head><body>
    2005/05/16 13:52 4月份，居民消费价格总水平比去年同月上涨1.8%。</body></html>""".encode("utf-8")
    ppi = """<html><head><title>12月份工业品出厂价格同比下降0.4%</title></head><body>
    2006/01/10 10:00 12月份，工业品出厂价格比去年同月下降0.4%。</body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        cpi_rows = source.parse_news_release(cpi, artifact(tmp_path, cpi, "NBS"))
        ppi_rows = source.parse_news_release(ppi, artifact(tmp_path, ppi, "NBS"))
    finally:
        source.close()

    assert cpi_rows[0]["period"] == "2005-04"
    assert cpi_rows[0]["value"] == 1.8
    assert ppi_rows[0]["period"] == "2005-12"
    assert ppi_rows[0]["value"] == -0.4


def test_nbs_legacy_pmi_wording_without_parenthesized_abbreviation(tmp_path):
    content = """<html><head><title>2009年3月中国制造业采购经理指数为52.4%</title></head><body>
    2009/04/01 10:00 中国制造业采购经理指数为52.4%。</body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse_news_release(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()

    assert rows[0]["canonical_series_id"] == "CN_PMI_MANUFACTURING"
    assert rows[0]["period"] == "2009-03"
    assert rows[0]["value"] == 52.4


def test_customs_english_usd_summary_parses_all_five_series(tmp_path):
    content = """<html><head><title>(1) China's Total Export &amp; Import Values, Dec 2025 (in USD)</title></head><body>
    <p>2026/01/08</p><p>Unit: USD 100 Million</p><table>
    <tr><th>Item</th><th>12</th><th>1-to-12</th><th>Month-on-Month ±%</th><th>Year-on-Year ±%</th><th>Year-on-Year ±%</th></tr>
    <tr><td>Total Export &amp; Import</td><td>6,014.2</td><td>63,547.7</td><td>9.6</td><td>6.2</td><td>3.2</td></tr>
    <tr><td>Total Export</td><td>3,577.8</td><td>37,718.7</td><td>8.4</td><td>6.6</td><td>5.5</td></tr>
    <tr><td>Total Import</td><td>2,436.4</td><td>25,829.0</td><td>11.5</td><td>5.7</td><td>0.0</td></tr>
    <tr><td>Export-Import Balance</td><td>1,141.4</td><td>11,889.8</td><td>-</td><td>-</td><td>-</td></tr>
    </table></body></html>""".encode("utf-8")
    source = CustomsSource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "CUSTOMS"))
    finally:
        source.close()

    values = {row["canonical_series_id"]: row for row in rows}
    assert set(values) == {
        "CN_EXPORT_USD", "CN_IMPORT_USD", "CN_TRADE_BALANCE_USD",
        "CN_EXPORT_USD_YOY", "CN_IMPORT_USD_YOY",
    }
    assert values["CN_EXPORT_USD"]["period"] == "2025-12"
    assert values["CN_EXPORT_USD"]["value"] == pytest.approx(357.78)
    assert values["CN_IMPORT_USD"]["value"] == pytest.approx(243.64)
    assert values["CN_TRADE_BALANCE_USD"]["value"] == pytest.approx(114.14)
    assert values["CN_EXPORT_USD_YOY"]["value"] == pytest.approx(6.6)
    assert values["CN_IMPORT_USD_YOY"]["value"] == pytest.approx(5.7)
    assert all(row["pit_grade"] == "B" for row in rows)
    # Date-only evidence is usable at the next Shanghai midnight, stored as UTC.
    assert all(row["available_at"].isoformat() == "2026-01-08T16:00:00+00:00" for row in rows)


def test_customs_parser_refuses_silent_empty_page(tmp_path):
    content = b"<html><body>blocked</body></html>"
    source = CustomsSource(allow_network=False)
    try:
        with pytest.raises((ParserRowCountError, ValueError)):
            source.parse_release(content, artifact(tmp_path, content, "CUSTOMS"))
    finally:
        source.close()


def test_safe_units_convert_100m_usd_to_bn_usd(tmp_path):
    content = """<html><head><title>2025年7月外汇数据</title></head><body>
    发布时间：2025-08-07 16:00:00 外汇储备规模为32922亿美元，银行结汇1800亿美元，银行售汇1700亿美元。
    </body></html>""".encode("utf-8")
    source = SAFESource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "SAFE"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row["value"] for row in rows}
    assert by_id["CN_FX_RESERVE_USD"] == pytest.approx(3292.2)
    assert by_id["CN_BANK_FX_SETTLEMENT_USD"] == pytest.approx(180.0)
    assert by_id["CN_BANK_FX_SALES_USD"] == pytest.approx(170.0)
    assert by_id["CN_BANK_FX_NET_SETTLEMENT_USD"] == pytest.approx(10.0)


def test_safe_bulk_workbook_is_long_history_pit_d(tmp_path):
    workbook = Workbook()
    reserve = workbook.active
    reserve.title = "FX reserves"
    reserve.append(["Scale of Foreign Exchange Reserves"])
    reserve.append(["Date", "Amount 100 million USD"])
    reserve.append(["January 2005", 6236.46])
    reserve.append(["February 2005", 6426.10])
    flows = workbook.create_sheet("in USD (Monthly)")
    flows.append(["Monthly Data on Foreign Exchange Settlement and Sales by Banks (in USD)"])
    flows.append(["Unit: USD 100 million"])
    flows.append(["Item", None, datetime(2010, 1, 1), datetime(2010, 2, 1)])
    flows.append(["I. Foreign exchange settlement", None, 950.0, 800.0])
    flows.append(["II. Foreign exchange sales", None, 580.0, 600.0])
    payload = BytesIO()
    workbook.save(payload)
    content = payload.getvalue()

    source = SAFESource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "SAFE"))
    finally:
        source.close()

    values = {(row["canonical_series_id"], row["period"]): row for row in rows}
    assert values[("CN_FX_RESERVE_USD", "2005-01")]["value"] == pytest.approx(623.646)
    assert values[("CN_BANK_FX_SETTLEMENT_USD", "2010-01")]["value"] == pytest.approx(95.0)
    assert values[("CN_BANK_FX_SALES_USD", "2010-01")]["value"] == pytest.approx(58.0)
    assert values[("CN_BANK_FX_NET_SETTLEMENT_USD", "2010-01")]["value"] == pytest.approx(37.0)
    assert {row["pit_grade"] for row in rows} == {"D"}
    assert {row["release_date_source"] for row in rows} == {
        "official_bulk_history_first_seen_only"
    }


def test_safe_annual_reserve_table_is_conservative_pit_c(tmp_path):
    content = """<html><head><meta name="publishdate" content="2025-01-07"></head><body>
    <table><tr><td>官方储备资产 Official reserve assets</td></tr>
    <tr><td>项目 Item</td><td>2024.01</td><td>2024.02</td></tr>
    <tr><td>亿美元 100million USD</td><td>亿SDR 100million SDR</td>
        <td>亿美元 100million USD</td><td>亿SDR 100million SDR</td></tr>
    <tr><td>1. 外汇储备 Foreign currency reserves</td>
        <td>32193.20</td><td>24207.52</td><td>32258.17</td><td>24298.76</td></tr>
    </table></body></html>""".encode("utf-8")
    source = SAFESource(allow_network=False)
    try:
        rows = source.parse_release(content, artifact(tmp_path, content, "SAFE"))
    finally:
        source.close()
    assert [row["period"] for row in rows] == ["2024-01", "2024-02"]
    assert [row["value"] for row in rows] == pytest.approx([3219.32, 3225.817])
    assert {row["pit_grade"] for row in rows} == {"C"}
    assert rows[0]["available_at"].isoformat() == "2025-01-07T16:00:00+00:00"
    assert rows[0]["release_date_source"].startswith("official_annual_consolidation:")

def test_nbs_q_and_a_anchors_prices_and_aggregate_manufacturing(tmp_path):
    content = """<html><head><title>国家统计局新闻发言人就2026年8月份国民经济运行情况答记者问</title></head><body>
    2026/09/15 15:34
    <div class="txt-content">
    2025年8月份，工业生产者出厂价格同比下降2.0%。
    8月份，居民消费价格同比上涨0.8%，工业生产者出厂价格上涨3.8%。
    1—8月份，制造业投资下降2.3%。
    锂离子电池制造业投资增长20.6%。
    8月份，全国城镇调查失业率为5.3%。
    </div></body></html>""".encode("utf-8")
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse_news_release(content, artifact(tmp_path, content, "NBS"))
    finally:
        source.close()
    by_id = {row["canonical_series_id"]: row for row in rows}
    assert by_id["CN_PPI_YOY"]["value"] == 3.8
    assert by_id["CN_MANUFACTURING_INVESTMENT_YTD_YOY"]["value"] == -2.3
    assert by_id["CN_URBAN_SURVEYED_UNEMPLOYMENT"]["value"] == 5.3
    assert {row["period"] for row in rows} == {"2026-08"}
