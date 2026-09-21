"""Frozen NBS pre-2010 total real estate development investment evidence."""
from pathlib import Path
from datetime import datetime
import re,json,hashlib
import pandas as pd
from lxml import html
from bs4 import BeautifulSoup
from macro_pit.archive import RawArtifact,UrlCache
from macro_pit.sources.cn_common import make_observation
from macro_pit.timeutils import SHANGHAI
OUT=Path('reports/v2/history/pit/pre2010_backfill/nbs_realestate_2008')
SPECS=[('1919483',2008,11,'2008/12/12 10:13',26546,22.7),('1919504',2009,3,'2009/04/13 08:22',4880,4.1)]
def compact(x):return re.sub(r'\s+','',x)
def extract(text,month):
 matches=re.findall(fr'1-{month}月，全国完成房地产开发投资([0-9.]+)亿元，同比增长([0-9.]+)%',text)
 assert len(matches)==1
 return tuple(map(float,matches[0]))
def main():
 OUT.mkdir(parents=True,exist_ok=True);rows=[];proof=[]
 for ident,y,m,stamp,level,expected in SPECS:
  url=f'https://www.stats.gov.cn/sj/zxfb/202303/t20230301_{ident}.html';cache=UrlCache().get('NBS',url);assert cache
  art=RawArtifact(source='NBS',url=url,path=cache['raw_file'],sha256=cache['raw_sha256'],content_type=cache['content_type'],retrieved_at=datetime.fromisoformat(cache['retrieved_at']),size=cache['size'])
  content=Path(art.path).read_bytes();assert hashlib.sha256(content).hexdigest()==art.sha256 and len(content)==art.size
  doc=html.fromstring(content.decode('utf-8'));body=doc.xpath('//div[@class="txt-content"]');assert len(body)==1
  text=compact(body[0].text_content());assert extract(text,m)==(level,expected)
  title=f'{y}年1-{m}月全国房地产市场运行情况'
  assert title in compact(''.join(doc.xpath('//div[@class="detail-title"]/h1/text()')))
  dates=re.findall(r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}',doc.xpath('//div[@class="detail-title-des"]')[0].text_content());assert dates==[stamp]
  soup=BeautifulSoup(content,'html.parser');assert soup.select_one('.detail-title h1').get_text(strip=True)==title
  assert soup.select_one('.detail-title-des h2 p').get_text(strip=True)==stamp
  quote=f'1-{m}月，全国完成房地产开发投资{level}亿元，同比增长{expected}%'
  assert compact(soup.select_one('.txt-content').get_text()).count(quote)==1
  release_at=datetime.strptime(stamp,'%Y/%m/%d %H:%M').replace(tzinfo=SHANGHAI)
  assert release_at<=art.retrieved_at
  release=dict(release_at=release_at,available_at=release_at,pit_grade='A',release_date_source='official_page_timestamp')
  rows.append(make_observation(source='NBS',canonical_series_id='CN_REAL_ESTATE_INVESTMENT_YTD_YOY',source_series_id='REAL_ESTATE_INVESTMENT_YTD_YOY',series_name='房地产开发投资累计同比',unit='pct_yoy',year=y,month=m,value=expected,artifact=art,release=release,parser_version='nbs_realestate_pre2010_frozen_v1'))
  proof.append(dict(period=f'{y}-{m:02d}',value=expected,quote=quote,release_at=release_at.isoformat(),source_url=url,raw_sha256=art.sha256))
 pd.DataFrame(rows).to_parquet(OUT/'verified_observations.parquet',index=False)
 pd.DataFrame(proof).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
 result=dict(status='PASS',verified_rows=len(rows),verified_sha256=hashlib.sha256((OUT/'verified_observations.parquet').read_bytes()).hexdigest())
 (OUT/'independent_review.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result)
if __name__=='__main__':main()
