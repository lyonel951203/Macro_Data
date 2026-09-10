from datetime import datetime
import hashlib
import pytest
from macro_pit.archive import RawArtifact
from macro_pit.errors import DataContractError
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.sources.nbs_economy import ordered_national_unemployment
from macro_pit.timeutils import SHANGHAI


def test_ordered_rates_keep_month_order():
    body = '1至3月份，全国城镇调查失业率分别为5.0%、5.0%和5.1%，分别比上年同月下降0.2、0.4和0.1个百分点；31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。'
    assert ordered_national_unemployment(body, 3) == {1:5.0, 2:5.0, 3:5.1}


@pytest.mark.parametrize('body', [
    '1至3月份，31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。',
    '1至3月份，全国城镇登记失业率分别为4.9%、4.8%和4.9%。',
    '一季度，全国城镇调查失业率平均值为5.1%。',
    '1至3月份，全国城镇调查失业率分别比上年下降0.2、0.4和0.1个百分点。',
])
def test_other_populations_and_averages_are_not_monthly_rates(body):
    assert ordered_national_unemployment(body, 3) == {}


@pytest.mark.parametrize('values', ['5.0%和5.1%', '5.0%、5.0%、5.1%和5.2%', '5.0%、5.0%和105.1%'])
def test_mismatched_or_invalid_values_fail_closed(values):
    with pytest.raises(DataContractError):
        ordered_national_unemployment('1至3月份，全国城镇调查失业率分别为'+values+'。', 3)


def test_all_three_months_available_only_on_april_publication(tmp_path):
    content = ('<title>一季度国民经济实现良好开局</title><body>2018/04/17 10:00'
               '<div class="txt-content"><p>2018年3月份及一季度主要统计数据</p>'
               '<p>1至3月份，全国城镇调查失业率分别为5.0%、5.0%和5.1%。</p></div></body>').encode()
    path = tmp_path/'release.html'
    path.write_bytes(content)
    artifact = RawArtifact('NBS','https://www.stats.gov.cn/example.html',str(path),hashlib.sha256(content).hexdigest(),
                           'text/html',datetime(2026,9,8,tzinfo=SHANGHAI),len(content))
    source = NBSSource(allow_network=False)
    try:
        rows = source.parse(content, artifact)
    finally:
        source.close()
    assert [(r['period'],r['value']) for r in rows] == [('2018-01',5.0),('2018-02',5.0),('2018-03',5.1)]
    assert all(r['available_at'] == datetime(2018,4,17,10,tzinfo=SHANGHAI) and r['pit_grade']=='A' for r in rows)
