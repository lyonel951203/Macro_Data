"""Frozen SAFE gap quotes plus same-release net derivations; no production writes."""
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib,json,re,math
import pandas as pd
from lxml import html
from bs4 import BeautifulSoup
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_common import make_observation
from macro_pit.timeutils import SHANGHAI

OUT=Path('reports/v2/archive_parse_20260911/safe_gap_net')
OLD=Path('reports/v2/archive_parse_20260911/safe_monthly')
SPECS=[
 ('https://www.safe.gov.cn/safe/2011/1125/4942.html','2011-10','2011-11-25','2011年10月份,境内银行代客涉外收入为1868亿美元,对外付款为1759亿美元', [('CN_CROSS_BORDER_RECEIPTS_USD',186.8),('CN_CROSS_BORDER_PAYMENTS_USD',175.9)]),
 ('https://www.safe.gov.cn/safe/2020/0220/15482.html','2020-01','2020-02-21','2020年1月,银行代客涉外收入2871亿美元,对外付款2797亿美元',[('CN_CROSS_BORDER_RECEIPTS_USD',287.1),('CN_CROSS_BORDER_PAYMENTS_USD',279.7)]),
 ('https://www.safe.gov.cn/safe/2023/0117/22258.html','2022-12','2023-01-18','2022年12月,银行结汇2092亿美元,售汇2022亿美元',[('CN_BANK_FX_SETTLEMENT_USD',209.2),('CN_BANK_FX_SALES_USD',202.2)]),
 ('https://www.safe.gov.cn/safe/2023/0117/22258.html','2022-12','2023-01-18','2022年12月,银行代客涉外收入5279亿美元,对外付款5048亿美元',[('CN_CROSS_BORDER_RECEIPTS_USD',527.9),('CN_CROSS_BORDER_PAYMENTS_USD',504.8)]),
]
NAMES={'CN_BANK_FX_SETTLEMENT_USD':'银行结汇','CN_BANK_FX_SALES_USD':'银行售汇','CN_CROSS_BORDER_RECEIPTS_USD':'涉外收入','CN_CROSS_BORDER_PAYMENTS_USD':'对外付款','CN_BANK_FX_NET_SETTLEMENT_USD':'银行结售汇差额','CN_CROSS_BORDER_NET_RECEIPTS_USD':'涉外收付款差额'}
PAIRS=[('CN_BANK_FX_NET_SETTLEMENT_USD','CN_BANK_FX_SETTLEMENT_USD','CN_BANK_FX_SALES_USD'),('CN_CROSS_BORDER_NET_RECEIPTS_USD','CN_CROSS_BORDER_RECEIPTS_USD','CN_CROSS_BORDER_PAYMENTS_USD')]
def compact(s):return re.sub(r'\s+','',s).replace('，',',')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def derive(left,right,key):
 expected=next((a,b) for target,a,b in PAIRS if target==key)
 assert (left['canonical_series_id'],right['canonical_series_id'])==expected
 assert left['source']==right['source']=='SAFE'
 for field in ['period','source_url','raw_sha256','release_at','available_at','unit','frequency','pit_grade']:
  assert left[field]==right[field],field
 assert left['unit']=='bn_usd' and left['frequency']=='M' and left['pit_grade']=='B'
 r=dict(left);r.update(canonical_series_id=key,source_series_id=key[3:],series_name=NAMES[key],value=left['value']-right['value'],parser_version='safe_same_release_net_v1')
 assert math.isclose(r['value'],float(Decimal(str(left['value']))-Decimal(str(right['value']))),abs_tol=1e-10,rel_tol=0)
 return r

def main():
 OUT.mkdir(exist_ok=True)
 state=json.loads(Path('data/history_backfill/source_workers/safe/state.json').read_text(encoding='utf-8'))
 review=json.loads((OLD/'independent_review.json').read_text(encoding='utf-8'))
 assert review['status']=='PASS' and review['verified_sha256']==sha(OLD/'verified_observations.parquet')
 gaps=[];evidence=[]
 for url,period,pub,quote,values in SPECS:
  a=state['results'][url]['artifact'].copy();a['retrieved_at']=datetime.fromisoformat(a['retrieved_at']);art=RawArtifact(**a)
  content=Path(art.path).read_bytes();assert len(content)==art.size and hashlib.sha256(content).hexdigest()==art.sha256
  doc=html.fromstring(content.decode('utf-8'));assert doc.xpath('//meta[@name="PubDate"]/@content')==[pub]
  bodies=doc.xpath('//*[@id="content"]');assert len(bodies)==1
  text=compact(bodies[0].text_content());assert text.count(quote)==1
  # Independent HTML parser and whole-pair quote proof; never use annual totals.
  soup=BeautifulSoup(content,'html.parser');independent=compact(soup.find(id='content').get_text())
  assert independent.count(quote)==1 and '发布日期：'+pub in compact(soup.get_text())
  title=soup.find('meta',attrs={'name':'ArticleTitle'})['content'];year,month=map(int,period.split('-'))
  assert f'{year}年{month}月' in title
  numbers=re.findall(r'([0-9]+)亿美元',quote)
  assert len(numbers)==2 and [float(Decimal(n)/10) for n in numbers]==[v for k,v in values]
  date=datetime.fromisoformat(pub).replace(tzinfo=SHANGHAI)
  release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='safe_official_metadata_date_next_day')
  for key,value in values:
   row=make_observation(source='SAFE',canonical_series_id=key,source_series_id=key[3:],series_name=NAMES[key],unit='bn_usd',year=year,month=month,value=value,artifact=art,release=release,parser_version='safe_frozen_gap_quotes_v1')
   assert row['available_at']<=art.retrieved_at
   gaps.append(row)
  evidence.append(dict(source_url=url,raw_sha256=art.sha256,period=period,publication_date=pub,whole_pair_quote=quote,values=values))
 assert len(gaps)==8
 components=pd.concat([pd.read_parquet(OLD/'verified_observations.parquet'),pd.DataFrame(gaps)],ignore_index=True)
 assert not components.duplicated(['canonical_series_id','period']).any()
 derived=[];derivation=[]
 for (period,url),group in components.groupby(['period','source_url']):
  keyed={r['canonical_series_id']:r for r in group.to_dict('records')}
  for target,left,right in PAIRS:
   if left not in keyed or right not in keyed:continue
   row=derive(keyed[left],keyed[right],target);derived.append(row)
   derivation.append(dict(indicator=target,period=period,value=row['value'],left_indicator=left,left_value=keyed[left]['value'],right_indicator=right,right_value=keyed[right]['value'],available_at=row['available_at'],raw_sha256=row['raw_sha256'],source_url=url,method='same-release published component subtraction; rounding may differ from published net'))
 frame=pd.DataFrame(gaps+derived)
 assert len(derived)==346 and not frame.duplicated(['canonical_series_id','period']).any()
 frame.to_parquet(OUT/'verified_observations.parquet',index=False)
 pd.DataFrame(derivation).to_csv(OUT/'derivation.csv',index=False,encoding='utf-8-sig')
 (OUT/'gap_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 result=dict(status='PASS',gap_rows=8,derived_rows=len(derived),verified_rows=len(frame),expected_incoming=304,verified_sha256=sha(OUT/'verified_observations.parquet'),components_sha256=review['verified_sha256'])
 (OUT/'independent_review.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
