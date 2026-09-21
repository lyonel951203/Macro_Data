"""Independent SAFE review: whole monthly pairs, visible date, metadata and raw hash."""
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
import hashlib,json,re
import pandas as pd
from bs4 import BeautifulSoup
from macro_pit.timeutils import SHANGHAI

OUT=Path('reports/v2/history/archive_parse/archive_parse_20260911/safe_monthly')
NUMBER=r'[0-9][0-9,]*(?:\.[0-9]+)?'
MONEY=rf'(?:{NUMBER}亿美元|{NUMBER}亿元人民币[（(]等值{NUMBER}亿美元[）)])'

def independent(content):
    soup=BeautifulSoup(content,'html.parser')
    title=soup.find('meta',attrs={'name':'ArticleTitle'})['content']
    dates=soup.find_all('meta',attrs={'name':'PubDate'})
    assert len(dates)==1
    stamp=dates[0]['content']
    release=datetime.strptime(stamp,'%Y-%m-%d').replace(tzinfo=SHANGHAI)
    visible=re.sub(r'\s+','',soup.get_text())
    assert '发布日期：'+stamp in visible or '发布日期:'+stamp in visible
    m=re.search(r'公布(20\d{2})年(\d{1,2})月银行',title)
    assert m
    y,mo=map(int,m.groups())
    content_node=soup.find_all(id='content')
    assert len(content_node)==1
    text=re.sub(r'\s+','',content_node[0].get_text())
    expected={};proof=[]
    for opening,second,ids in [
        ('银行结汇','(?:银行)?售汇',('CN_BANK_FX_SETTLEMENT_USD','CN_BANK_FX_SALES_USD')),
        ('(?:境内)?银行代客涉外收入','(?:银行代客)?对外付款',('CN_CROSS_BORDER_RECEIPTS_USD','CN_CROSS_BORDER_PAYMENTS_USD'))]:
        pair=rf'{y}年{mo}月[，,]{opening}(?:为)?(?P<a>{MONEY})[，,]{second}(?:为)?(?P<b>{MONEY})'
        matches=list(re.finditer(pair,text))
        if ids[0]=='CN_BANK_FX_SETTLEMENT_USD':
            # Older pages state RMB first, then USD in the same dated sentence.
            lead=rf'{y}年{mo}月[，,]银行结汇{NUMBER}亿元人民币[，,]售汇{NUMBER}亿元人民币(?:[，,]结售汇(?:顺差|逆差){NUMBER}亿元人民币)?[；;]按美元计值[，,]'
            usd=rf'银行结汇(?P<a>{NUMBER}亿美元)[，,]售汇(?P<b>{NUMBER}亿美元)'
            matches.extend(re.finditer(lead+usd,text))
        for hit in matches:
            for key,amount in zip(ids,[hit['a'],hit['b']]):
                nums=re.findall(rf'({NUMBER})亿美元',amount)
                assert len(nums)==1
                value=float(Decimal(nums[0].replace(',',''))/Decimal(10))
                assert key not in expected or expected[key]==value
                expected[key]=value
            proof.append(hit[0])
    return f'{y}-{mo:02d}',release,expected,proof

def main():
    frame=pd.read_parquet(OUT/'review_candidates.parquet')
    evidence=[];errors=[];accepted=[]
    for (path,sha,url),group in frame.groupby(['raw_file','raw_sha256','source_url']):
        try:
            assert urlsplit(url).hostname=='www.safe.gov.cn'
            content=Path(path).read_bytes();assert hashlib.sha256(content).hexdigest()==sha
            period,release,expected,proof=independent(content)
            for row in group.to_dict('records'):
                assert row['period']==period and expected[row['canonical_series_id']]==row['value']
                assert row['source']=='SAFE' and row['country']=='CN' and row['pit_grade']=='B'
                assert row['unit']=='bn_usd' and row['frequency']=='M'
                assert row['release_at']==release and row['available_at']==release+timedelta(days=1)
                assert row['available_at']<=row['retrieved_at']
                row['series_name']={'CN_BANK_FX_SETTLEMENT_USD':'银行结汇','CN_BANK_FX_SALES_USD':'银行售汇','CN_CROSS_BORDER_RECEIPTS_USD':'涉外收入','CN_CROSS_BORDER_PAYMENTS_USD':'对外付款'}[row['canonical_series_id']]
                accepted.append(row)
            evidence.append(dict(source_url=url,raw_sha256=sha,period=period,release_at=release.isoformat(),whole_pair_evidence=proof,rows=len(group)))
        except Exception as exc:errors.append(dict(url=url,error=repr(exc)))
    # Fail the batch rather than silently accept partial source groups.
    result=dict(status='PASS' if not errors and len(accepted)==len(frame) else 'FAIL',checked_rows=len(frame),verified_rows=len(accepted),articles=len(evidence),errors=errors)
    (OUT/'independent_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'independent_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    if result['status']=='PASS':
        verified=pd.DataFrame(accepted).drop(columns=['comparison'])
        verified.to_parquet(OUT/'verified_observations.parquet',index=False)
        result['verified_sha256']=hashlib.sha256((OUT/'verified_observations.parquet').read_bytes()).hexdigest()
        (OUT/'independent_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
