"""Independently verify archived manufacturing PMI current-month table cells."""
from pathlib import Path
from datetime import datetime
import re,json,hashlib
import pandas as pd
from lxml import html
from macro_pit.db import get_connection
from macro_pit.timeutils import SHANGHAI
OUT=Path('reports/v2/archive_parse_20260912/nbs_pmi')
KEYS=['CN_PMI_'+x for x in ['MANUFACTURING','PRODUCTION','NEW_ORDERS','RAW_MATERIAL_INVENTORY','EMPLOYMENT','SUPPLIER_DELIVERY']]
LABELS=['PMI','生产','新订单','原材料库存','从业人员','供应商配送时间']
def compact(s):return re.sub(r'\s+','',s).replace('主要原材料库存','原材料库存').replace('供应商配送时间','供应商配送').replace('供应商配送','供应商配送时间')
def cells(body,y,m):
 target=f'{y}年{m}月';proofs=[]
 for table in body.xpath('.//table'):
  rr=[[compact(c.text_content()) for c in tr.xpath('./td|./th')] for tr in table.xpath('.//tr')]
  # Horizontal indicator headers, one dated row per month.
  if any([c for c in r if c] == LABELS for r in rr) or any([c for c in rr[i] if c]==['PMI'] and rr[i+1]==LABELS[1:] for i in range(len(rr)-1)):
   for r in rr:
    if len(r)==7 and r[0]==target:
     proofs.append([float(v) for v in r[1:]])
  # Vertical indicator rows, date headers select the current month column.
  headers=[r for r in rr if target in r and any('年' in c and '月' in c for c in r)]
  for h in headers:
   if any(c not in ['', '指数',target] and not re.fullmatch(r'20\d{2}年\d{1,2}月',c) for c in h):continue
   idx=h.index(target); values={}
   for r in rr:
    if r and r[0] in LABELS and len(r)==len(h) and idx>0:
     values[r[0]]=float(r[idx])
   if set(values)==set(LABELS):proofs.append([values[k] for k in LABELS])
 assert proofs and all(p==proofs[0] for p in proofs),'no_unambiguous_current_month_table'
 assert all(0<=v<=100 for v in proofs[0])
 return dict(zip(KEYS,proofs[0]))
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 f=pd.read_parquet('reports/v2/archive_parse_20260911/unverified_candidates.parquet')
 with get_connection('macro_pit_v2.duckdb',read_only=True) as c:
  old=set(c.sql("select canonical_series_id,period from observation_vintage where country='CN' and pit_grade in ('A','B')").fetchall())
 f=f[f.canonical_series_id.isin(KEYS)].copy();f=f[pd.Series([(r.canonical_series_id,r.period) not in old for r in f.itertuples()],index=f.index)]
 verified=[];evidence=[];held=[]
 for path,group in f.groupby('raw_file'):
  try:
   raw=Path(path).read_bytes();assert all(group.raw_sha256.eq(hashlib.sha256(raw).hexdigest()))
   d=html.fromstring(raw.decode('utf-8'));title=compact(d.findtext('.//title'))
   assert '制造业采购经理指数' in title and '非制造业' not in title,'not_manufacturing_only_release'
   periods=re.findall(r'(20\d{2})年(\d{1,2})月份?',title)
   if not periods:
    intro=compact(d.xpath('//div[@class="txt-content"]')[0].text_content())[:250]
    periods=re.findall(r'(20\d{2})年(\d{1,2})月份?[，,](?:全国|中国)?制造业采购经理指数',intro)
    assert len(periods)==1 and re.search(r'(?<!\d)'+str(int(periods[0][1]))+r'月份?',title)
   assert len(periods)==1
   y,m=map(int,periods[0]);period=f'{y}-{m:02d}'
   body=d.xpath('//div[@class="txt-content"]');assert len(body)==1
   assert '经季节调整' in compact(body[0].text_content()),'seasonal_adjustment_not_proven'
   values=cells(body[0],y,m)
   desc=d.xpath('//div[@class="detail-title-des"]');assert len(desc)==1
   stamps=re.findall(r'20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}',desc[0].text_content());assert len(stamps)==1
   release=datetime.strptime(' '.join(stamps[0].split()),'%Y/%m/%d %H:%M').replace(tzinfo=SHANGHAI)
   end=pd.Period(period).end_time.tz_localize(SHANGHAI);assert -1<=(pd.Timestamp(release)-end).total_seconds()/86400<=10
   article_rows=[];article_evidence=[]
   for row in group.to_dict('records'):
    assert row['period']==period and row['value']==values[row['canonical_series_id']]
    assert row['pit_grade']=='A' and row['available_at']==release and row['release_at']==release
    assert row['unit']=='index' and row['frequency']=='M' and row['seasonal_adjustment']=='SA'
    assert release<=row['retrieved_at']
    row.pop('production_comparison',None);row.pop('review_status',None)
    row['parser_version']='nbs_pmi_independent_current_table_v1';article_rows.append(row)
    article_evidence.append(dict(indicator=row['canonical_series_id'],period=period,value=row['value'],release_at=release.isoformat(),source_url=row['source_url'],raw_sha256=row['raw_sha256'],table_values=json.dumps(values),title=title))
   verified.extend(article_rows);evidence.extend(article_evidence)
  except Exception as e:held.append(dict(raw_file=path,reason=type(e).__name__+':'+str(e)+' line '+str(__import__('traceback').extract_tb(e.__traceback__)[-1].lineno),candidate_rows=len(group)))
 result=pd.DataFrame(verified)
 # Multiple archived copies must agree. Use earliest verified actual publication.
 assert not result.groupby(['canonical_series_id','period']).value.nunique().gt(1).any()
 result=result.sort_values('available_at').drop_duplicates(['canonical_series_id','period'])
 result.to_parquet(OUT/'verified_observations.parquet',index=False)
 pd.DataFrame(evidence).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(held).to_csv(OUT/'held_articles.csv',index=False,encoding='utf-8-sig')
 summary=dict(status='PASS',verified_rows=len(result),reviewed_articles=f.raw_file.nunique(),held_articles=len(held),verified_sha256=hashlib.sha256((OUT/'verified_observations.parquet').read_bytes()).hexdigest(),coverage=result.groupby('canonical_series_id').agg(n=('period','size'),first=('period','min'),last=('period','max')).to_dict('index'))
 (OUT/'independent_review.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
