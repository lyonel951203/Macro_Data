from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest

from macro_pit.archive import RawArtifact
from macro_pit.nbs_price_review import review_price_article, search_expectation
from macro_pit.timeutils import SHANGHAI


@pytest.fixture
def evidence(tmp_path):
    url = "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1900631.html"
    title = "2020年1月份居民消费价格同比上涨5.4%"
    stamp = datetime(2020, 2, 10, 9, 30, tzinfo=SHANGHAI)
    index = tmp_path / "search.json"
    index.write_text(json.dumps({"resultDocs": [{"data": {
        "url": url, "titleO": title, "docDate": "2020-02-10", "dreDate": int(stamp.timestamp() * 1000)
    }}]}, ensure_ascii=False), encoding="utf-8")
    item = {"url": url, "title": title, "period": "2020-01", "indicator": "CN_CPI_YOY",
            "index_raw_file": str(index), "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest()}
    content = f"""<html><head><title>{title} - 国家统计局</title></head><body>
    <div class="detail-title-des"><p>2020/02/10 09:30</p></div>
    <div class="txt-content">2020 年 1 月份，全国居民消费价格同比上涨 5.4%。环比上涨1.4%。</div>
    </body></html>""".encode("utf-8")
    raw = tmp_path / "article.html"
    raw.write_bytes(content)
    artifact = RawArtifact("NBS", url, str(raw), hashlib.sha256(content).hexdigest(), "text/html", stamp, len(content))
    return item, content, artifact


def test_independent_price_review_retains_original_date_despite_migrated_url(evidence):
    item, content, artifact = evidence
    review = review_price_article(item, content, artifact)
    assert review["value"] == 5.4
    assert review["period"] == "2020-01"
    assert review["release_at"] == "2020-02-10T09:30:00+08:00"
    assert review["pit_grade"] == "A"


@pytest.mark.parametrize("old,new", [
    ("上涨 5.4%", "上涨 1.4%"),
    ("上涨 5.4%", "下降 5.4%"),
    ("2020 年 1 月份", "2020 年 2 月份"),
    ("2020/02/10 09:30", "2023/02/03 09:30"),
    ("2020/02/10 09:30", "2020/02/10 10:00"),
    ("2020 年 1 月份", "2020年1—2月份"),
])
def test_independent_price_review_rejects_wrong_value_period_or_release(evidence, old, new):
    item, content, artifact = evidence
    changed = content.decode().replace(old, new).encode()
    assert changed != content
    artifact = replace(artifact, sha256=hashlib.sha256(changed).hexdigest(), size=len(changed))
    with pytest.raises(ValueError):
        review_price_article(item, changed, artifact)


def test_search_evidence_cannot_be_silently_replaced(evidence):
    item, _, _ = evidence
    Path(item["index_raw_file"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        search_expectation(item)
