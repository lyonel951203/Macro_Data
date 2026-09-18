"""Frozen pre-2010 PBOC money/credit releases reprinted by MOF; offline review."""
from pathlib import Path
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib,json,re
import pandas as pd
from lxml import html
from bs4 import BeautifulSoup
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_common import make_observation
from macro_pit.sources.cn_pboc import METRICS
from macro_pit.timeutils import SHANGHAI
OUT=Path('reports/v2/pre2010_backfill/pboc_2009')
SPECS=[
 dict(url='https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/zyzfmhwz/200906/t20090612_166811.htm',period='2009-05',date='2009-06-12',values=[
 ('CN_M2_YOY',25.74,'广义货币供应量(M2)余额54.82万亿元,同比增长25.74%'),
 ('CN_M1_YOY',18.69,'狭义货币供应量(M1)余额18.2万亿元,同比增长18.69%'),
 ('CN_M0_YOY',11.24,'市场货币流通量(M0)余额3.36万亿元,同比增长11.24%'),
 ('CN_RMB_LOAN_BAL_YOY',30.6,'金融机构人民币各项贷款余额36.21万亿元,同比增长30.6%'),
 ('CN_RMB_DEPOSIT_BAL_YOY',26.67,'金融机构人民币各项存款余额54.63万亿元,同比增长26.67%'),
 ('CN_NEW_RMB_LOANS_YTD',5.84,'1-5月份人民币各项贷款增加5.84万亿元'),
 ('CN_NEW_RMB_DEPOSITS_YTD',7.98,'1-5月份人民币各项存款增加7.98万亿元')]),
 dict(url='https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/zyzfmhwz/200908/t20090811_192101.htm',period='2009-07',date='2009-08-11',values=[
 ('CN_M2_YOY',28.42,'广义货币供应量(M2)余额为57.3万亿元,同比增长28.42%'),
 ('CN_M1_YOY',26.37,'狭义货币供应量(M1)余额为19.59万亿元,同比增长26.37%'),
 ('CN_M0_YOY',11.59,'市场货币流通量(M0)余额为3.42万亿元,同比增长11.59%'),
 ('CN_RMB_LOAN_BAL_YOY',33.9,'金融机构人民币各项贷款余额38.1万亿元,同比增长33.9%'),
 ('CN_RMB_DEPOSIT_BAL_YOY',28.54,'金融机构人民币各项存款余额为57.03万亿元,同比增长28.54%'),
 ('CN_NEW_RMB_LOANS_YTD',7.73,'1-7月人民币各项贷款增加7.73万亿元'),
 ('CN_NEW_RMB_DEPOSITS_YTD',10.38,'1-7月份人民币各项存款增加10.38万亿元')])]
def compact(x):return re.sub(r'\s+','',x).replace('，',',').replace('％','%')
def verify_quote(text,quote,expected,ytd,month):
 assert text.count(quote)==1
 if ytd:
  assert re.match(fr'1-{month}月份?人民币各项(?:贷款|存款)增加',quote)
  value=re.search(r'增加([0-9.]+)万亿元$',quote)
 else:value=re.search(r'同比增长([0-9.]+)%$',quote)
 assert value and float(value[1])==expected
 return float(value[1])
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 state=json.loads(Path('data/history_backfill/source_workers/pboc/state.json').read_text(encoding='utf-8'))
 metrics={m.canonical_id:m for m in METRICS};rows=[];proof=[]
 for spec in SPECS:
  item=state['results'][spec['url']];assert item['status']=='ARCHIVED'
  a=item['artifact'].copy();a['retrieved_at']=datetime.fromisoformat(a['retrieved_at']);art=RawArtifact(**a)
  content=Path(art.path).read_bytes();assert hashlib.sha256(content).hexdigest()==art.sha256 and len(content)==art.size
  doc=html.fromstring(content.decode('utf-8'));stamps=doc.xpath('//meta[@name="PubDate"]/@content')
  assert len(stamps)==1 and stamps[0][:10]==spec['date']
  body=doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," my_conboxzw ")]');assert len(body)==1
  for node in body[0].xpath('.//script|.//style'):node.drop_tree()
  text=compact(body[0].text_content())
  soup=BeautifulSoup(content,'html.parser');ind=soup.select_one('.my_conboxzw');assert ind is not None
  for node in ind.select('script,style'):node.decompose()
  independent=compact(ind.get_text())
  assert soup.find('meta',attrs={'name':'PubDate'})['content']==stamps[0]
  year,month=map(int,spec['period'].split('-'));period_quote=f'{year}年{month}月末'
  assert period_quote in text and period_quote in independent
  date=datetime.fromisoformat(spec['date']).replace(tzinfo=SHANGHAI)
  release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='mof_reprint_date_conservative_original_release_unverified')
  assert release['available_at']<=art.retrieved_at
  for key,expected,quote in spec['values']:
   metric=metrics[key];value=verify_quote(text,quote,expected,not metric.percent,month)
   assert independent.count(quote)==1
   number=re.findall(r'[0-9]+(?:\.[0-9]+)?',quote)[-1]
   assert float(Decimal(number))==value
   rows.append(make_observation(source='PBOC',canonical_series_id=key,source_series_id=metric.source_id,series_name=metric.name,unit=metric.unit,year=year,month=month,value=value,artifact=art,release=release,parser_version='mof_pboc_pre2010_frozen_v1'))
   proof.append(dict(indicator=key,period=spec['period'],value=value,unit=metric.unit,quote=quote,period_quote=period_quote,metadata_pubdate=stamps[0],available_at=release['available_at'].isoformat(),source_url=spec['url'],raw_sha256=art.sha256,original_release_verified=False))
 assert len(rows)==14
 pd.DataFrame(rows).to_parquet(OUT/'verified_observations.parquet',index=False)
 pd.DataFrame(proof).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
 result=dict(status='PASS',verified_rows=14,fields=7,articles=2,verified_sha256=hashlib.sha256((OUT/'verified_observations.parquet').read_bytes()).hexdigest())
 (OUT/'independent_review.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
