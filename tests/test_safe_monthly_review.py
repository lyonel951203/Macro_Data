import importlib.util
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location('safe_monthly_review',Path(__file__).resolve().parents[1]/'scripts/history/parse_safe_monthly_review.py')
module=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

def page(text,title='国家外汇管理局公布2015年9月银行结售汇和银行代客涉外收付款数据'):
    return f'<html><head><meta name="ArticleTitle" content="{title}"><meta name="PubDate" content="2015-10-20"></head><body><div id="content">{text}</div></body></html>'.encode()

def test_monthly_bank_scope_and_units():
    _,_,_,values,_,_=module.extract(page('2015年9月，银行结汇7829亿元人民币（等值1229亿美元），售汇14781亿元人民币（等值2321亿美元）。2015年1-9月，银行累计结汇99999亿美元，累计售汇88888亿美元。'))
    assert {k:float(v) for k,v in values.items()}=={'CN_BANK_FX_SETTLEMENT_USD':122.9,'CN_BANK_FX_SALES_USD':232.1}

def test_client_settlement_excluded_crossborder_kept():
    _,_,_,values,_,_=module.extract(page('2015年9月，银行代客结汇900亿美元，售汇800亿美元。2015年9月，境内银行代客涉外收入2238亿美元，对外付款2100亿美元。'))
    assert set(values)=={'CN_CROSS_BORDER_RECEIPTS_USD','CN_CROSS_BORDER_PAYMENTS_USD'}
    assert float(values['CN_CROSS_BORDER_RECEIPTS_USD'])==223.8

@pytest.mark.parametrize('text',[
    '2015年1-9月，银行结汇999亿美元，售汇888亿美元。',
    '2015年9月，银行代客结汇999亿美元，售汇888亿美元。',
    '2015年9月，银行结汇999亿元人民币，售汇888亿元人民币。',
    '2015年9月，银行累计结汇999亿美元，累计售汇888亿美元。',
])
def test_reject_ambiguous_or_wrong_scope(text):
    with pytest.raises(ValueError,match='no_supported'):module.extract(page(text))

def test_conflicting_values_held():
    with pytest.raises(ValueError,match='conflicting'):
        module.extract(page('2015年9月，银行结汇100亿美元，售汇90亿美元。2015年9月，银行结汇200亿美元，售汇90亿美元。'))

def test_annual_title_not_monthly():
    with pytest.raises(ValueError,match='not_explicit'):
        module.extract(page('2015年银行结汇100亿美元。','国家外汇管理局公布2015年银行结售汇和银行代客涉外收付款数据'))
SPEC2=importlib.util.spec_from_file_location('verify_safe_monthly',Path(__file__).resolve().parents[1]/'scripts/history/verify_safe_monthly_review.py')
verify_module=importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(verify_module)

def review_page(text):
    return page(text).replace(b'<body>','<body>发布日期：2015-10-20'.encode())

def test_independent_same_sentence_rmb_then_usd():
    _,_,values,_=verify_module.independent(review_page('2015年9月，银行结汇100亿元人民币，售汇90亿元人民币，结售汇顺差10亿元人民币；按美元计值，银行结汇15亿美元，售汇14亿美元。'))
    assert values['CN_BANK_FX_SETTLEMENT_USD']==1.5
    assert values['CN_BANK_FX_SALES_USD']==1.4

@pytest.mark.parametrize('text',[
    '2015年1-9月，银行结汇15亿美元，售汇14亿美元。',
    '2015年9月，银行代客结汇15亿美元，售汇14亿美元。',
    '2015年9月，银行结汇100亿元人民币，售汇90亿元人民币。按美元计值，银行结汇15亿美元，售汇14亿美元。',
])
def test_independent_no_unsupported_inference(text):
    assert verify_module.independent(review_page(text))[2]=={}

def test_visible_publication_must_agree():
    with pytest.raises(AssertionError):
        verify_module.independent(review_page('2015年9月，银行结汇15亿美元，售汇14亿美元。').replace('发布日期：2015-10-20'.encode(),'发布日期：2015-10-21'.encode()))
