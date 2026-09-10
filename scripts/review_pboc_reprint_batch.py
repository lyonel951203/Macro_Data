"""Review two frozen money/credit reprints; no network and no production writes."""
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import re
from dataclasses import asdict
import pandas as pd
from lxml import html
from macro_pit.archive import RawArtifact
from macro_pit.db import get_connection,insert_observations
from macro_pit.snapshot import get_snapshot
from macro_pit.sources.cn_common import make_observation
from macro_pit.sources.cn_pboc import METRICS,PBOCSource
from macro_pit.timeutils import SHANGHAI

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/v2/pboc_reprints/b02_money_credit'
SPECS=[
 dict(url='https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/jjckb/201001/t20100118_261144.htm',period='2009-12',pub='2010-01-18',
      period_quote='2009年12月末',values=[
  ('CN_M2_YOY',27.68,'广义货币供应量(M2)余额为60.62万亿元，同比增长'),
  ('CN_M1_YOY',32.35,'狭义货币供应量(M1)余额为22.00万亿元，同比增长'),
  ('CN_M0_YOY',11.77,'货币流通量(M0)余额为3.82万亿元，同比增长'),
  ('CN_RMB_LOAN_BAL_YOY',31.74,'金融机构人民币贷款余额39.97万亿元，同比增长'),
  ('CN_RMB_DEPOSIT_BAL_YOY',28.21,'金融机构人民币存款余额59.77万亿元，同比增长'),
  ('CN_NEW_RMB_LOANS_YTD',9.59,'2009年全年人民币贷款增加'),
  ('CN_NEW_RMB_DEPOSITS_YTD',13.13,'全年人民币存款增加')]),
 dict(url='https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/zyzfmhwz/201004/t20100412_286263.htm',period='2010-03',pub='2010-04-12',
      period_quote='2010年3月末',values=[
  ('CN_M2_YOY',22.50,'广义货币供应量(M2)余额为65.00万亿元,同比增长'),
  ('CN_M1_YOY',29.94,'狭义货币供应量(M1)余额为22.94万亿元,同比增长'),
  ('CN_M0_YOY',15.81,'流通中货币(M0)余额为3.91万亿元,同比增长'),
  ('CN_RMB_LOAN_BAL_YOY',21.81,'金融机构人民币各项贷款余额42.58万亿元，同比增长'),
  ('CN_RMB_DEPOSIT_BAL_YOY',22.11,'金融机构人民币各项存款余额为63.82万亿元，同比增长'),
  ('CN_NEW_RMB_LOANS_YTD',2.60,'一季度本外币贷款增加2.80万亿元，其中，人民币贷款增加'),
  ('CN_NEW_RMB_DEPOSITS_YTD',4.04,'一季度本外币存款增加4.07万亿元，其中，人民币存款增加')])]

def compact(text):return re.sub(r'\s+','',text).replace('％','%').replace('，',',')

def review():
    OUT.mkdir(parents=True,exist_ok=True)
    frozen=OUT/'source_checkpoint.json'
    if not frozen.exists():frozen.write_bytes((ROOT/'data/history_backfill/source_workers/pboc/state.json').read_bytes())
    state=json.loads(frozen.read_text(encoding='utf-8'))
    metrics={m.canonical_id:m for m in METRICS};rows=[];proofs=[];legacy=[]
    source=PBOCSource(allow_network=False)
    try:
        for spec in SPECS:
            result=state['results'][spec['url']];assert result['status']=='ARCHIVED'
            a=result['artifact'].copy();a['retrieved_at']=datetime.fromisoformat(a['retrieved_at'])
            artifact=RawArtifact(**a);content=(ROOT/artifact.path).read_bytes()
            assert len(content)==artifact.size and hashlib.sha256(content).hexdigest()==artifact.sha256
            doc=html.fromstring(content.decode('utf-8'))
            body=doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," my_conboxzw ")]')
            assert len(body)==1
            for node in body[0].xpath('.//script|.//style|.//*[contains(@class,"gu-download")]'):node.drop_tree()
            text=compact(''.join(body[0].itertext()));assert compact(spec['period_quote']) in text
            stamp=doc.xpath('//meta[@name="PubDate"]/@content');assert len(stamp)==1 and stamp[0].startswith(spec['pub'])
            index_date=result['item'].get('index_publication_date')
            if index_date:assert index_date.replace('.','-')==spec['pub']
            date=datetime.fromisoformat(spec['pub']).replace(tzinfo=SHANGHAI)
            release=dict(release_at=date,available_at=date+timedelta(days=1),pit_grade='B',
                         release_date_source='mof_reprint_date_conservative_original_release_unverified')
            year,month=map(int,spec['period'].split('-'))
            assert release['available_at']<=artifact.retrieved_at and (year,month)<=(date.year,date.month)
            for key,expected,prefix in spec['values']:
                metric=metrics[key];unit_suffix='%' if metric.percent else '万亿元'
                matches=list(re.finditer(re.escape(compact(prefix))+r'(?P<value>\d+(?:\.\d+)?)'+unit_suffix,text))
                assert matches and all(float(m['value'])==expected for m in matches),(key,spec['period'],'quote mismatch')
                value=float(matches[0]['value'])
                row=make_observation(source='PBOC',canonical_series_id=key,source_series_id=metric.source_id,
                    series_name=metric.name,unit=metric.unit,year=year,month=month,value=value,artifact=artifact,
                    release=release,parser_version='mof_pboc_reviewed_money_credit_b02_v1')
                rows.append(row)
                proofs.append(dict(indicator=key,period=spec['period'],value=value,unit=metric.unit,quote=matches[0][0],
                    period_quote=spec['period_quote'],metadata_pubdate=stamp[0],available_at=release['available_at'].isoformat(),
                    hosting_organization='www.mof.gov.cn',statistical_source='PBOC',original_release_verified=False,
                    source_url=artifact.url,raw_sha256=artifact.sha256,pit_grade='B'))
            try:
                parsed=source.parse_article(content,artifact)
                legacy.extend(dict(indicator=r['canonical_series_id'],period=r['period'],value=r['value'],url=artifact.url) for r in parsed)
            except Exception as exc:legacy.append(dict(url=artifact.url,error=str(exc)))
    finally:source.close()
    assert len(rows)==14 and len({(r['canonical_series_id'],r['period']) for r in rows})==14
    with get_connection(':memory:') as conn:
        first=insert_observations(conn,rows);assert first.inserted==14
        repeat=insert_observations(conn,rows);assert repeat.unchanged==14 and repeat.inserted==0
        for row in rows:
            for offset,visible in [(-1,False),(0,True)]:
                result=get_snapshot(conn,(row['available_at']+timedelta(seconds=offset)).isoformat(),'CN')
                hits=[r for r in result.to_dicts() if r['canonical_series_id']==row['canonical_series_id'] and r['period']==row['period']]
                assert bool(hits)==visible
    pd.DataFrame(rows).to_parquet(OUT/'validated_observations.parquet',index=False)
    pd.DataFrame(proofs).to_csv(OUT/'evidence.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(legacy).to_csv(OUT/'legacy_parser_comparison.csv',index=False,encoding='utf-8-sig')
    report=dict(status='PASS',articles=2,fields=7,validated_rows=14,pit_grade='B',boundary_checks=28,idempotency=asdict(repeat),
                at=datetime.now(SHANGHAI).isoformat(),production_writes=0,sha256=hashlib.sha256((OUT/'validated_observations.parquet').read_bytes()).hexdigest())
    (OUT/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':review()
