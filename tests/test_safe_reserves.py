import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('safe_reserves',Path(__file__).resolve().parents[1]/'scripts/review_safe_reserves.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def page(body,date='2017-08-07'):
 return f'<html><meta name="ArticleTitle" content="2017年7月外汇储备"><meta name="PubDate" content="{date}"><body>发布日期：{date}<div id="content">{body}</div></body></html>'.encode()
@pytest.mark.parametrize('body',[
 '截至2017年7月末，外汇储备规模30807亿美元。',
 '截至2017年7月31日，我国外汇储备规模为30807亿美元。',
])
def test_explicit_month_end_level(body):
 content=page(body);y,mo,date,value,quote=m.extract(content)
 assert (y,mo,value)==(2017,7,3080.7)
 m.verify(content,y,mo,date,value)
@pytest.mark.parametrize('body',[
 '截至2017年7月15日，我国外汇储备规模为30807亿美元。',
 '截至2016年7月末，我国外汇储备规模为30807亿美元。',
 '截至2017年7月末，我国外汇储备规模上升239亿美元。',
 '截至2017年7月末，我国黄金储备规模为30807亿美元。',
 '截至2017年7月末，我国外汇储备规模为30807亿元人民币。',
 '截至2017年7月末，我国外汇储备规模为30807亿美元。截至2017年6月末，我国外汇储备规模为30000亿美元。',
])
def test_reject_wrong_date_measure_currency_or_ambiguity(body):
 with pytest.raises(AssertionError):m.extract(page(body))
def test_visible_date_conflict():
 content=page('截至2017年7月末，外汇储备规模30807亿美元。')
 y,mo,date,value,_=m.extract(content)
 with pytest.raises(AssertionError):m.verify(content.replace('发布日期：2017-08-07'.encode(),'发布日期：2017-08-08'.encode()),y,mo,date,value)
