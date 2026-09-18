import sys
from pathlib import Path
from datetime import datetime
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import archive_format_fallbacks as m
from macro_pit.archive import RawArtifact
from macro_pit.timeutils import SHANGHAI

def artifact(host):return RawArtifact('NBS','https://'+host+'/test','unused','unused','text/html',datetime(2026,9,12,tzinfo=SHANGHAI),0)
def nbs_page(title,body):return f'<html><title>{title}</title><div class="detail-title-des">2013/06/09 10:00</div><div class="txt-content">{body}</div></html>'.encode()
def test_industry_month_not_ytd():
 content=nbs_page('2013年5月份规模以上工业生产运行情况','2013年5月份，规模以上工业增加值同比实际增长9.2%。1-5月，规模以上工业增加值同比增长9.4%。')
 rows=m.nbs(content,artifact('www.stats.gov.cn'));assert rows[0]['value']==9.2 and rows[0]['period']=='2013-05'
def test_reject_combined_industry_month():
 with pytest.raises(AssertionError):m.nbs(nbs_page('2013年5月份规模以上工业生产运行情况','1-5月，规模以上工业增加值同比增长9.4%。'),artifact('www.stats.gov.cn'))
def test_realestate_total_nominal():
 content=nbs_page('2013年1-5月份全国房地产开发和销售情况','2013年1-5月份，全国房地产开发投资100亿元，同比名义增长10.5%（实际增长9.9%）。其中住宅投资增长8%。')
 assert m.nbs(content,artifact('www.stats.gov.cn'))[0]['value']==10.5
@pytest.mark.parametrize('title',['2013年1-5月城镇固定资产投资情况','2013年1-5月住宅投资情况'])
def test_reject_wrong_scope(title):
 with pytest.raises((AssertionError,ValueError)):m.nbs(nbs_page(title,'2013年1-5月，全国城镇固定资产投资100亿元，同比增长10%。'),artifact('www.stats.gov.cn'))
def test_money_requires_explicit_year():
 content='<html><meta name="PubDate" content="2010-03-12"><div class="my_conboxzw">2月末，广义货币供应量（M2）余额63.6万亿元，同比增长25.52%。</div></html>'.encode()
 with pytest.raises(AssertionError):m.pboc(content,artifact('www.mof.gov.cn'))
def test_money_no_cross_sentence_match():
 content='<html><meta name="PubDate" content="2009-06-12"><div class="my_conboxzw">2009年5月末，广义货币供应量（M2）余额54.82万亿元。别的指标同比增长25.74%。</div></html>'.encode()
 with pytest.raises(AssertionError):m.pboc(content,artifact('www.mof.gov.cn'))
