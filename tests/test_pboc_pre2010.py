import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('pboc_pre2010',Path(__file__).resolve().parents[1]/'scripts/review_pboc_pre2010.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def test_ytd_exact_period():
 q='1-5月份人民币各项贷款增加5.84万亿元'
 assert m.verify_quote(q,q,5.84,True,5)==5.84
@pytest.mark.parametrize('q',[
 '当月人民币各项贷款增加5.84万亿元',
 '1-7月份人民币各项贷款增加5.84万亿元',
 '1-5月份本外币各项贷款增加5.84万亿元',
 '1-5月份人民币各项贷款增加5.84亿元',
])
def test_wrong_flow_period_currency_unit(q):
 with pytest.raises(AssertionError):m.verify_quote(q,q,5.84,True,5)
def test_growth_not_level():
 q='广义货币供应量(M2)余额54.82万亿元,同比增长25.74%'
 assert m.verify_quote(q,q,25.74,False,5)==25.74
 with pytest.raises(AssertionError):m.verify_quote(q,q,54.82,False,5)
def test_duplicate_quote_held():
 q='1-5月份人民币各项贷款增加5.84万亿元'
 with pytest.raises(AssertionError):m.verify_quote(q+q,q,5.84,True,5)
