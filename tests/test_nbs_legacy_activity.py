from datetime import datetime
import hashlib

import pytest

from macro_pit.archive import RawArtifact
from macro_pit.errors import DataContractError, ParserRowCountError
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI


def parse(tmp_path, title, body, stamp="2005/03/15 10:04"):
    content = f"<html><title>{title}</title><body>{stamp}<div class='txt-content'>{body}</div></body></html>".encode()
    path = tmp_path / "old.html"
    path.write_bytes(content)
    artifact = RawArtifact("NBS", "https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919867.html",
                           str(path), hashlib.sha256(content).hexdigest(), "text/html", datetime(2026,9,8,tzinfo=SHANGHAI), len(content))
    source = NBSSource(allow_network=False)
    try:
        return source.parse(content, artifact)
    finally:
        source.close()


def test_original_monthly_industry_excludes_holiday_adjustment(tmp_path):
    rows = parse(tmp_path, "1月份全国工业生产平稳增长 完成增加值4844亿元",
                 "<p>1月份，全部国有工业企业及年产品销售收入500万元以上的非国有工业企业完成增加值4844亿元，比去年同月增长20.9%，如果扣除去年1月春节放假因素的影响，按日均水平计算，增长8.9％。</p>", "2005/02/18 09:35")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-01",20.9)]
    assert rows[0]["seasonal_adjustment"] == "NSA" and rows[0]["pit_grade"] == "A"
    assert rows[0]["available_at"] == datetime(2005,2,18,9,35,tzinfo=SHANGHAI)


def test_retail_jan_feb_each_inherits_actual_march_publication(tmp_path):
    rows = parse(tmp_path, "1-2月份全国社会消费品零售总额同比增长13.6%",
                 "<p>1-2月份，社会消费品零售总额10313亿元，比上年同期增长13.6%。其中1月份增长11.5%，2月份增长15.8%。</p>", "2005/03/14 13:19")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-01",11.5),("2005-02",15.8)]
    assert all(r["available_at"] == datetime(2005,3,14,13,19,tzinfo=SHANGHAI) for r in rows)


def test_quarter_industry_extracts_only_explicit_month(tmp_path):
    rows = parse(tmp_path, "一季度我国工业实现增加值14415亿 增长16.2%",
                 "<p>一季度，工业生产继续保持较快增长，全部国有工业企业及年产品销售收入500万元以上的非国有工业企业完成增加值14415亿元，同比增长16.2%，增速比去年同期回落1.5个百分点。其中，3月份完成增加值5367亿元，同比增长15.1%。</p>", "2005/04/22 10:32")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-03",15.1)]


def test_half_year_retail_excludes_ytd_and_sector_values(tmp_path):
    rows = parse(tmp_path, "上半年全国社会消费品零售总额同比增长13.2%",
                 "<p>上半年，社会消费品零售总额29610亿元，比去年同期增长13.2%。其中，6月份增长12.9%。</p><p>分地域看，6月份城市增长14.2%。</p>", "2005/07/22 10:31")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-06",12.9)]


def test_ytd_only_industry_does_not_create_february(tmp_path):
    with pytest.raises(ParserRowCountError):
        parse(tmp_path, "1-2月份全国实现工业增加值9034亿元 同比增长16.9%",
              "<p>1-2月份，全部国有工业企业及年产品销售收入500万元以上的非国有工业企业完成增加值9034亿元，同比增长16.9%。</p><p>其中2月份电子行业增长25%。</p>")


def test_ytd_only_retail_does_not_create_february(tmp_path):
    with pytest.raises(ParserRowCountError):
        parse(tmp_path, "1-2月份全国社会消费品零售总额同比增长13.6%",
              "<p>1-2月份，社会消费品零售总额10313亿元，比上年同期增长13.6%。</p><p>分地域看，2月份城市增长15%。</p>")


def test_conflicting_explicit_months_fail_closed(tmp_path):
    with pytest.raises(DataContractError, match="Conflicting legacy"):
        parse(tmp_path, "1-2月份全国社会消费品零售总额同比增长13.6%",
              "<p>1-2月份，社会消费品零售总额10313亿元，比上年同期增长13.6%。其中2月份增长15.8%，2月份增长15.9%。</p>")


def test_industrial_population_must_be_verified(tmp_path):
    with pytest.raises(DataContractError, match="industrial population"):
        parse(tmp_path, "1月份全国工业生产平稳增长",
              "<p>1月份，国有企业完成增加值904亿元，同比增长21.3%。</p>")


def test_retail_monthly_fall_is_not_real_growth_or_ytd(tmp_path):
    rows = parse(tmp_path, "4月份社会消费品零售总额同比下降1.2%",
                 "<p>4月份，社会消费品零售总额4663亿元，比去年同月下降1.2%，扣除价格因素实际增长0.1%。1-4月份同比增长2.5%。</p>", "2005/05/13 09:00")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-04",-1.2)]


def test_official_april_typo_keeps_monthly_national_value(tmp_path):
    rows = parse(tmp_path, "4月份全国实现工业增加值5647亿 同比增长16%",
                 "<p>4月份，全部国有工业企业及年产品销售收入500万元以上的非国有工业企业完成增加5647亿元，同比增长16%。其中，重工业完成增加值3913亿元，增长16.5%。</p><p>1-4月份累计同比增长16.2%。</p>", "2005/05/18 13:24")
    assert [(r["period"],r["value"]) for r in rows] == [("2005-04",16.0)]
