"""Extract explicitly dated SAFE monthly flow statements into review staging only."""
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib,json,re
from pathlib import Path
import pandas as pd
from lxml import html
from macro_pit.archive import RawArtifact
from macro_pit.sources.cn_common import make_observation
from macro_pit.timeutils import SHANGHAI
from macro_pit.fileio import atomic_write_text

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/v2/archive_parse_20260911/safe_monthly'
NUM=r'([\d,]+(?:\.\d+)?)'
AMOUNT=rf'(?:为)?{NUM}亿美元'
CONVERTED=rf'(?:为)?[\d,.]+亿元人民币[（(]等值{NUM}亿美元[）)]'
METRICS=[('CN_BANK_FX_SETTLEMENT_USD','银行结汇'),('CN_BANK_FX_SALES_USD','售汇'),('CN_CROSS_BORDER_RECEIPTS_USD','涉外收入'),('CN_CROSS_BORDER_PAYMENTS_USD','对外付款')]

def extract(content):
    doc=html.fromstring(content.decode('utf-8'))
    meta=lambda key:doc.xpath(f'//meta[@name="{key}"]/@content')
    titles=meta('ArticleTitle'); dates=meta('PubDate'); bodies=doc.xpath('//*[@id="content"]')
    if len(titles)!=1 or len(dates)!=1 or len(bodies)!=1: raise ValueError('missing_unique_title_date_body')
    title=titles[0]
    m=re.fullmatch(r'国家外汇管理局公布(20\d{2})年(\d{1,2})月银行(?:代客)?结售汇.*数据',title)
    if not m: raise ValueError('not_explicit_monthly_flow_title')
    year,month=map(int,m.groups()); datetime(year,month,1)
    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}',dates[0]): raise ValueError('unexpected_publication_date_format')
    date=datetime.fromisoformat(dates[0]).replace(tzinfo=SHANGHAI)
    if (year,month)>(date.year,date.month): raise ValueError('period_after_publication')
    text=re.sub(r'\s+','',bodies[0].text_content()).replace('，',',').replace('；',';')
    stamp=rf'{year}年{month}月,'
    found={}
    proofs={}
    for sentence in text.split('。'):
        anchors=list(re.finditer(stamp,sentence))
        if not anchors: continue
        statement=sentence[anchors[-1].end():]
        # Never walk into a second date, a subpopulation, or cumulative statistics.
        statement=re.split(r'其中|同期|累计|20\d{2}年',statement)[0]
        bank=statement.startswith('银行结汇')
        cross=bool(re.match(r'(?:境内)?银行代客涉外收入',statement))
        if not bank and not cross: continue
        selected=METRICS[:2] if bank else METRICS[2:]
        for canonical,label in selected:
            matches=[]
            for pattern in [CONVERTED,AMOUNT]:
                matches.extend(re.finditer(re.escape(label)+pattern,statement))
            if len(matches)!=1: continue
            value=Decimal(matches[0].group(1).replace(',',''))/10
            if canonical in found and found[canonical]!=value: raise ValueError('conflicting_monthly_statements')
            found[canonical]=value
            proofs[canonical]=dict(sentence=sentence,matched_text=matches[0][0],date_anchor=anchors[-1][0],scope='bank_total' if bank else 'bank_client_cross_border')
    if not found: raise ValueError('no_supported_explicit_monthly_usd_statement')
    return year,month,date,found,proofs,title

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    state=json.loads((ROOT/'data/history_backfill/source_workers/safe/state.json').read_text(encoding='utf-8'))
    rows=[]; proofs=[];held=[]
    for url,item in state['results'].items():
        if item.get('status')!='ARCHIVED' or item['item']['kind']!='article':continue
        try:
            a=item['artifact'].copy();a['retrieved_at']=datetime.fromisoformat(a['retrieved_at']);artifact=RawArtifact(**a)
            content=(ROOT/artifact.path).read_bytes()
            assert len(content)==artifact.size and hashlib.sha256(content).hexdigest()==artifact.sha256
            year,month,date,values,evidence,title=extract(content)
            release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',release_date_source='safe_official_metadata_date_next_day')
            assert release['available_at']<=artifact.retrieved_at
            for canonical,value in values.items():
                rows.append(make_observation(source='SAFE',canonical_series_id=canonical,source_series_id=canonical[3:],series_name=dict(METRICS)[canonical],unit='bn_usd',year=year,month=month,value=float(value),artifact=artifact,release=release,parser_version='safe_explicit_monthly_review_v1'))
                proofs.append(dict(canonical_series_id=canonical,period=f'{year}-{month:02d}',value=float(value),unit='bn_usd',publication_date=date.date().isoformat(),source_url=url,raw_sha256=artifact.sha256,**evidence[canonical]))
        except Exception as exc:held.append(dict(url=url,title=item['item']['title'],reason=str(exc)))
    frame=pd.DataFrame(rows)
    frame.to_parquet(OUT/'review_candidates.parquet',index=False)
    pd.DataFrame(proofs).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(held).to_csv(OUT/'held_articles.csv',index=False,encoding='utf-8-sig')
    coverage=frame.groupby('canonical_series_id').agg(rows=('period','size'),unique_periods=('period','nunique'),first_period=('period','min'),last_period=('period','max'))
    coverage.to_csv(OUT/'coverage.csv',encoding='utf-8-sig')
    report=dict(status='EXTRACTED_PENDING_INDEPENDENT_REVIEW',articles_with_rows=frame.source_url.nunique(),rows=len(frame),held_articles=len(held),production_writes=0,coverage=coverage.reset_index().to_dict('records'))
    atomic_write_text(OUT/'summary.json',json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
