import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('nbs_old',Path(__file__).resolve().parents[1]/'scripts/history/review_nbs_pre2010.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def test_total_not_residential():
 text='1-11月，全国完成房地产开发投资26546亿元，同比增长22.7%。其中住宅投资同比增长25.2%'
 assert m.extract(text,11)==(26546,22.7)
@pytest.mark.parametrize('text',[
 '11月，全国完成房地产开发投资26546亿元，同比增长22.7%',
 '1-10月，全国完成房地产开发投资26546亿元，同比增长22.7%',
 '1-11月，全国完成住宅开发投资26546亿元，同比增长22.7%',
 '1-11月，全国完成房地产开发投资26546万元，同比增长22.7%',
])
def test_reject_wrong_scope_period_unit(text):
 with pytest.raises(AssertionError):m.extract(text,11)
