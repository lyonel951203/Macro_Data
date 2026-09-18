from __future__ import annotations

import polars as pl

from macro_pit.index_discovery import CandidateUrl
from macro_pit.index_discovery import discover_candidates, write_candidates


def test_archived_index_discovers_only_matching_official_urls(tmp_path):
    raw = tmp_path / "index.html"
    raw.write_text(
        """<html><body>
        <a href="./202608/t20260814_1.htm">2026年1-7月财政收支情况</a>
        <a href="https://evil.example/file">2026年1-6月财政收支情况</a>
        <a href="index_1.htm">下一页</a>
        </body></html>""",
        encoding="utf-8",
    )
    candidates = discover_candidates("MOF", [raw])
    assert len(candidates) == 1
    assert candidates[0].period == "2026-07"
    assert candidates[0].url == "https://gks.mof.gov.cn/tongjishuju/202608/t20260814_1.htm"
    parquet, urls = write_candidates(candidates, output_dir=tmp_path / "out")
    assert parquet.is_file()
    assert candidates[0].url in urls.read_text(encoding="utf-8")


def test_candidate_writes_merge_across_bounded_index_batches(tmp_path):
    output = tmp_path / "out"
    first = CandidateUrl("MOF", "2026年财政收支情况", "https://gks.mof.gov.cn/tongjishuju/202601/t1.htm", "2026-12", "fiscal_release", "raw1.html")
    second = CandidateUrl("MOF", "2025年财政收支情况", "https://gks.mof.gov.cn/tongjishuju/202501/t2.htm", "2025-12", "fiscal_release", "raw2.html")
    write_candidates([first], output_dir=output)
    parquet, urls = write_candidates([second], output_dir=output)

    frame = pl.read_parquet(parquet)
    assert frame.height == 2
    assert set(frame.get_column("url")) == {first.url, second.url}
    assert first.url in urls.read_text(encoding="utf-8")
    assert second.url in urls.read_text(encoding="utf-8")


def test_nbs_historical_release_index_uses_zxfb_as_relative_base(tmp_path):
    raw = tmp_path / "index.html"
    raw.write_text(
        """<html><body>
        <a href="./202303/t20230301_1919889.html">2005年4月份居民消费价格同比上涨1.8%</a>
        </body></html>""",
        encoding="utf-8",
    )

    candidates = discover_candidates("NBS", [raw])

    assert len(candidates) == 1
    assert candidates[0].period == "2005-04"
    assert candidates[0].url == "https://www.stats.gov.cn/sj/zxfb/202303/t20230301_1919889.html"


def test_nbs_economy_titles_without_exact_yunxing_phrase_are_discovered(tmp_path):
    raw = tmp_path / "index.html"
    raw.write_text('<a href="./202608/t20260817_1.html">1—7月份国民经济保持总体平稳</a>', encoding="utf-8")
    assert len(discover_candidates("NBS", [raw])) == 1


def test_nbs_running_title_without_guomin_is_discovered(tmp_path):
    raw=tmp_path/"index.html"
    raw.write_text('<a href="./202501/t20250117_1958332.html">2024年经济运行稳中有进 主要发展目标顺利实现</a>',encoding="utf-8")
    result=discover_candidates("NBS",[raw])
    assert len(result)==1 and result[0].period=="2024-12"

def test_pboc_mirror_discovery_uses_each_index_as_relative_base(tmp_path):
    sh = tmp_path / "sh.html"
    jl = tmp_path / "jl.html"
    sh.write_text(
        '<a href="./20260915/abc.html">2026年8月金融统计数据报告</a>',
        encoding="utf-8",
    )
    jl.write_text(
        '<a href="http://jr.jl.gov.cn/jrzx/zyjrxxzz/gj/202608/t20260817_1.html">2026年7月金融统计数据报告</a>',
        encoding="utf-8",
    )
    rows = discover_candidates(
        "PBOC_MIRROR",
        [sh, jl],
        base_urls=[
            "https://jrj.sh.gov.cn/SCGK194/index.html",
            "https://jr.jl.gov.cn/jrzx/zyjrxxzz/gj/",
        ],
    )
    assert {row.url for row in rows} == {
        "https://jrj.sh.gov.cn/SCGK194/20260915/abc.html",
        "https://jr.jl.gov.cn/jrzx/zyjrxxzz/gj/202608/t20260817_1.html",
    }

def test_nbs_spokesperson_q_and_a_is_not_an_automatic_candidate(tmp_path):
    raw = tmp_path / "index.html"
    raw.write_text(
        '<a href="../zxfbhjd/202609/t20260915_1.html">'
        '国家统计局新闻发言人就2026年8月份国民经济运行情况答记者问</a>'
        '<a href="./202609/t20260915_2.html">'
        '8月份国民经济运行平稳</a>',
        encoding="utf-8",
    )
    result = discover_candidates("NBS", [raw])
    assert [item.url for item in result] == [
        "https://www.stats.gov.cn/sj/zxfb/202609/t20260915_2.html"
    ]
