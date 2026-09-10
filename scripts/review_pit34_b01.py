"""Independently verify B01 raw cells, release boundaries and append-only ingestion."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import runpy
from lxml import html
import pandas as pd
from macro_pit.archive import RawArtifact
from macro_pit.db import OBSERVATION_COLUMNS, get_connection, insert_observations
from macro_pit.snapshot import get_snapshot
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI

OUT = Path('reports/v2/pit_34_backfill/b01')


def save(name, result):
    (OUT/name).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


def compact(value):
    return re.sub(r'\s+', '', value).replace('％','%')


def review(ingest=False):
    state = json.loads(Path('data/history_backfill/pit34_b01_download_state.json').read_text(encoding='utf-8'))
    assert state['status']=='COMPLETE'
    assert hashlib.sha256(Path('config/pit34_b01_candidates.json').read_bytes()).hexdigest()==state['manifest_sha256']
    specs = json.loads(Path('config/pit34_b01_review_values.json').read_text(encoding='utf-8'))['items']
    baseline = pd.read_parquet(OUT/'before_nbs_observations.parquet')
    keys = set(zip(baseline.canonical_series_id,baseline.period))
    rows, evidence, deferred = [], [], []
    source = NBSSource(allow_network=False)
    try:
        for spec in specs:
            item = state['items'][spec['url']]
            a = item['artifact'].copy()
            a['retrieved_at'] = datetime.fromisoformat(a['retrieved_at'])
            artifact = RawArtifact(**a)
            content = Path(artifact.path).read_bytes()
            assert len(content)==artifact.size and hashlib.sha256(content).hexdigest()==artifact.sha256
            doc = html.fromstring(content.decode('utf-8'))
            assert compact(item['title']) in compact(doc.xpath('string(//title)'))
            body = doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," txt-content ")]')[0]
            text = compact(''.join(body.itertext()))
            release = datetime.fromisoformat(spec['release_at'])
            stamp = release.strftime('%Y/%m/%d%H:%M')
            assert stamp in compact(''.join(doc.itertext()))
            parsed = {(r['canonical_series_id'],r['period']):r for r in source.parse(content,artifact)}
            selected = {(v['id'],v['period']) for v in spec['values']}
            for key, row in parsed.items():
                if key not in selected:
                    deferred.append(dict(**row,reason='outside_B01_review_scope_not_ingested'))
            for expected in spec['values']:
                key = expected['id'],expected['period']
                assert key not in keys
                row = parsed[key]
                if 'quote' in expected:
                    assert compact(expected['quote']) in text
                    proof = expected['quote']
                else:
                    tables = []
                    for table in body.xpath('.//table'):
                        cells = [[compact(''.join(c.itertext())) for c in tr.xpath('./td|./th')] for tr in table.xpath('.//tr')]
                        if ['指标',expected['table_month'],expected['table_ytd']] not in cells:
                            continue
                        assert ['绝对量','同比增长（%）','绝对量','同比增长（%）'] in cells
                        matches = [r for r in cells if r and r[0]==expected['table_label']]
                        tables.extend(matches)
                    assert tables and all(len(r)==5 and float(r[expected['column']])==expected['value'] for r in tables)
                    proof = json.dumps(tables,ensure_ascii=False)
                assert row['value']==expected['value'] and row['available_at']==release and row['release_at']==release
                assert row['pit_grade']=='A' and row['frequency']=='M'
                unit = 'index' if key[0].startswith('CN_PMI_') else ('pct' if key[0].endswith('UNEMPLOYMENT') else 'pct_yoy')
                assert row['unit']==unit and row['seasonal_adjustment']==('SA' if unit=='index' else 'NSA')
                rows.append(row)
                evidence.append(dict(canonical_series_id=key[0],period=key[1],value=row['value'],unit=unit,
                                     release_at=spec['release_at'],pit_grade='A',url=artifact.url,raw_file=artifact.path,
                                     raw_sha256=artifact.sha256,proof=proof,timestamp_evidence=stamp,result='PASS'))
    finally:
        source.close()
    assert len(rows)==12 and len({(r['canonical_series_id'],r['period']) for r in rows})==12
    with get_connection(':memory:') as conn:
        assert insert_observations(conn,rows).inserted==12
        repeat=insert_observations(conn,rows)
        assert repeat.inserted==0 and repeat.unchanged==12
        for row in rows:
            for offset,visible in [(-1,False),(0,True)]:
                frame = get_snapshot(conn,(row['available_at']+timedelta(seconds=offset)).isoformat(),'CN')
                matching=[r for r in frame.to_dicts() if r['canonical_series_id']==row['canonical_series_id'] and r['period']==row['period']]
                assert bool(matching)==visible
    pd.DataFrame(rows).to_parquet(OUT/'validated_observations.parquet',index=False)
    pd.DataFrame(evidence).to_csv(OUT/'validated_samples.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(deferred).to_csv(OUT/'deferred_parser_candidates.csv',index=False,encoding='utf-8-sig')
    result=dict(status='PASS',articles=3,verified_rows=12,fields=10,boundary_checks=24,idempotency='PASS',raw_sha256='PASS',
                independent_cells_and_time='PASS',deferred_rows=len(deferred),at=datetime.now(SHANGHAI).isoformat())
    if ingest:
        assert not Path('data/history_backfill/nbs_price_batch.lock').exists()
        assert json.loads((OUT/'regression_result.json').read_text())['status']=='PASS'
        tests=json.loads((OUT/'test_results.json').read_text())
        assert tests['status']=='PASS'
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in tests['sha256'].items())
        with get_connection('macro_pit_v2.duckdb') as conn:
            count_before=conn.sql('SELECT count(*) FROM observation_vintage').fetchone()[0]
            stats=insert_observations(conn,rows)
            assert stats.revisions==0
            conn.register('frozen',baseline[OBSERVATION_COLUMNS])
            assert conn.sql("SELECT count(*) FROM (SELECT * FROM frozen EXCEPT ALL SELECT * FROM observation_vintage WHERE source='NBS')").fetchone()[0]==0
            for row in rows:
                frame=get_snapshot(conn,row['available_at'].isoformat(),'CN')
                matching=[r for r in frame.to_dicts() if r['canonical_series_id']==row['canonical_series_id'] and r['period']==row['period']]
                assert len(matching)==1 and matching[0]['value']==row['value']
            count_after=conn.sql('SELECT count(*) FROM observation_vintage').fetchone()[0]
        name='ingestion_replay.json' if (OUT/'ingestion_result.json').exists() else 'ingestion_result.json'
        save(name,dict(before_rows=count_before,after_rows=count_after,stats=asdict(stats),baseline_preserved=True,**result))
    save('validation_summary.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--regress',action='store_true')
    p.add_argument('--ingest',action='store_true')
    args=p.parse_args()
    if args.regress:
        checker=runpy.run_path('scripts/regress_nbs_economy_batch2.py')['check']
        checker.__globals__['OUT']=OUT
        checker()
    else:
        review(args.ingest)
