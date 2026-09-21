"""Review SAFE reserve level releases using independent HTML parsers and dates."""
import calendar,hashlib,json,re
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
import pandas as pd
from lxml import html
from bs4 import BeautifulSoup
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_common import make_observation
from macro_pit.timeutils import SHANGHAI
OUT=Path('reports/v2/history/archive_parse/archive_parse_20260911/safe_reserves')
PATTERN=r'截至(20\d{2})年(\d{1,2})月(末|\d{1,2}日)[，,](?:我国)?外汇储备(?:规模|余额)?(?:为)?([\d,]+(?:\.\d+)?)亿美元'

def extract(content):
 doc=html.fromstring(content.decode('utf-8'))
 dates=doc.xpath('//meta[@name="PubDate"]/@content');title=doc.xpath('//meta[@name="ArticleTitle"]/@content')
 bodies=doc.xpath('//*[@id="content"]')
 assert len(dates)==len(title)==len(bodies)==1
 assert '外汇储备' in title[0]
 release=datetime.strptime(dates[0],'%Y-%m-%d').replace(tzinfo=SHANGHAI)
 text=re.sub(r'\s+','',bodies[0].text_content())
 matches=list(re.finditer(PATTERN,text))
 assert len(matches)==1,'missing_or_ambiguous_reserve_level'
 m=matches[0];year,month=int(m[1]),int(m[2]);day=calendar.monthrange(year,month)[1]
 assert m[3]=='末' or int(m[3][:-1])==day,'not_month_end'
 end=datetime(year,month,day,tzinfo=SHANGHAI)
 assert 0<=(release-end).days<=45,'not_current_monthly_release'
 value=float(Decimal(m[4].replace(',',''))/10)
 assert value>0
 return year,month,release,value,m[0]

def verify(content,year,month,date,value):
 soup=BeautifulSoup(content,'html.parser')
 assert soup.find('meta',attrs={'name':'PubDate'})['content']==date.date().isoformat()
 text=re.sub(r'\s+','',soup.get_text())
 assert '发布日期：'+date.date().isoformat() in text
 body=re.sub(r'\s+','',soup.find(id='content').get_text())
 # Split the explicitly dated clause, then independently check label and USD scale.
 end=calendar.monthrange(year,month)[1]
 anchor=rf'截至{year}年{month}月(?:末|{end}日)[，,]'
 parts=re.split(anchor,body)
 assert len(parts)==2
 match=re.match(r'(?:我国)?外汇储备(?:规模|余额)?(?:为)?([0-9,]+(?:\.[0-9]+)?)亿美元',parts[1])
 assert match and float(match[1].replace(',',''))/10==value
 return match[0]

def main():
 OUT.mkdir(exist_ok=True)
 state=json.loads(Path('data/history_backfill/source_workers/safe/state.json').read_text(encoding='utf-8'))
 rows=[];proofs=[];held=[]
 for url,item in state['results'].items():
  if item.get('status')!='ARCHIVED' or item['item']['kind']!='article' or '外汇储备规模' not in item['item']['title']:continue
  try:
   a=item['artifact'].copy();a['retrieved_at']=datetime.fromisoformat(a['retrieved_at']);art=RawArtifact(**a)
   content=Path(art.path).read_bytes();assert len(content)==art.size and hashlib.sha256(content).hexdigest()==art.sha256
   y,m,date,value,quote=extract(content);independent=verify(content,y,m,date,value)
   release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='safe_official_metadata_date_next_day')
   assert release['available_at']<=art.retrieved_at
   rows.append(make_observation(source='SAFE',canonical_series_id='CN_FX_RESERVE_USD',source_series_id='FX_RESERVE_USD',series_name='外汇储备',unit='bn_usd',year=y,month=m,value=value,artifact=art,release=release,parser_version='safe_reviewed_month_end_reserves_v1'))
   proofs.append(dict(period=f'{y}-{m:02d}',value=value,publication_date=date.date().isoformat(),source_url=url,raw_sha256=art.sha256,quote=quote,independent_quote=independent))
  except Exception as exc:held.append(dict(source_url=url,title=item['item']['title'],reason=str(exc)))
 frame=pd.DataFrame(rows)
 assert not frame.duplicated(['canonical_series_id','period']).any()
 frame.to_parquet(OUT/'verified_observations.parquet',index=False)
 pd.DataFrame(proofs).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(held).to_csv(OUT/'held_articles.csv',index=False,encoding='utf-8-sig')
 result=dict(status='PASS',scope='Only individually verified rows; held articles excluded',verified_rows=len(rows),held_articles=len(held),first_period=frame.period.min(),last_period=frame.period.max(),verified_sha256=hashlib.sha256((OUT/'verified_observations.parquet').read_bytes()).hexdigest(),held=held)
 (OUT/'independent_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
