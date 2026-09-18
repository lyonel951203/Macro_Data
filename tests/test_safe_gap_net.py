import importlib.util
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
spec=importlib.util.spec_from_file_location('safe_gap_net',Path(__file__).resolve().parents[1]/'scripts/review_safe_gap_net.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def pair():
 left=dict(source='SAFE',canonical_series_id='CN_BANK_FX_SETTLEMENT_USD',value=100.1,period='2015-01',source_url='https://www.safe.gov.cn/example',raw_sha256='abc',release_at=datetime(2015,2,1,tzinfo=timezone.utc),available_at=datetime(2015,2,2,tzinfo=timezone.utc),unit='bn_usd',frequency='M',pit_grade='B')
 right=dict(left,canonical_series_id='CN_BANK_FX_SALES_USD',value=110.2)
 return left,right

def test_negative_net_and_original_metadata():
 a,b=pair();r=m.derive(a,b,'CN_BANK_FX_NET_SETTLEMENT_USD')
 assert r['value']==pytest.approx(-10.1)
 assert r['available_at']==a['available_at'] and r['raw_sha256']==a['raw_sha256']
 assert a['canonical_series_id']=='CN_BANK_FX_SETTLEMENT_USD'

@pytest.mark.parametrize('field,value',[('period','2015-02'),('source_url','other'),('raw_sha256','other'),('available_at',datetime(2015,2,3,tzinfo=timezone.utc)),('unit','cny'),('canonical_series_id','CN_CROSS_BORDER_PAYMENTS_USD')])
def test_never_mix_releases_units_or_scopes(field,value):
 a,b=pair();b[field]=value
 with pytest.raises(AssertionError):m.derive(a,b,'CN_BANK_FX_NET_SETTLEMENT_USD')

def test_gap_publication_uses_page_not_url_date():
 assert m.SPECS[1][2]=='2020-02-21'
 assert m.SPECS[2][2]=='2023-01-18'
