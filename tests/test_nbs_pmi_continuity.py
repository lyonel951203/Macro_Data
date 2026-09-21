import importlib.util
from pathlib import Path
import pytest
from lxml import html
spec=importlib.util.spec_from_file_location('pmi_review',Path(__file__).resolve().parents[1]/'scripts/history/review_nbs_pmi_continuity.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def body(month='2015年1月',label='生产',value='53.0'):
 return html.fromstring('<div><table><tr><td></td><td>PMI</td><td></td></tr><tr>'+''.join('<td>'+x+'</td>' for x in [label,'新订单','原材料库存','从业人员','供应商配送时间'])+'</tr><tr>'+''.join('<td>'+x+'</td>' for x in [month,'50.1',value,'51.0','48.0','49.0','50.0'])+'</tr></table></div>')
def test_split_header():assert m.cells(body(),2015,1)['CN_PMI_PRODUCTION']==53.0
@pytest.mark.parametrize('b',[body(month='2014年12月'),body(label='新出口订单'),body(value='153.0')])
def test_wrong_month_scope_range(b):
 with pytest.raises(AssertionError):m.cells(b,2015,1)
def test_conflicting_tables():
 b=body();b.append(body(value='54.0')[0])
 with pytest.raises(AssertionError):m.cells(b,2015,1)
def test_vertical_index_header():
 rows=[['指数','2012年2月','2012年1月'],['PMI','51.0','50.5'],['生产','53.8','53.6'],['新订单','51.0','50.4'],['主要原材料库存','48.8','49.7'],['从业人员','49.5','47.1'],['供应商配送时间','50.3','49.7']]
 b=html.fromstring('<div><table>'+''.join('<tr>'+''.join('<td>'+x+'</td>' for x in r)+'</tr>' for r in rows)+'</table></div>')
 assert m.cells(b,2012,2)['CN_PMI_PRODUCTION']==53.8
