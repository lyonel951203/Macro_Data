"""Append the verified B02 sample and explain all strict-export changes."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import pandas as pd
from macro_pit.db import get_connection,insert_observations
from macro_pit.snapshot import build_monthly_wide_snapshot
from macro_pit.pit import get_snapshot
from macro_pit.timeutils import SHANGHAI
from review_pboc_reprint_batch import ROOT,OUT
from monitor_source_progress import process_alive

PREFIX='cn_pit_month_end_2005_20260731'
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def commit():
    os.chdir(ROOT)
    state=json.loads(Path('data/history_backfill/pit_history_autorun.json').read_text(encoding='utf-8'))
    assert not Path('data/history_backfill/nbs_price_batch.lock').exists() and not process_alive(state['pid'])
    assert state['inserted']==0 and not list(Path('reports/v2/pit_history_autorun/receipts').glob('*.json')),'NBS baseline migration only valid before its own inserts'
    review=json.loads((OUT/'review.json').read_text(encoding='utf-8'))
    assert review['status']=='PASS' and hashlib.sha256((OUT/'validated_observations.parquet').read_bytes()).hexdigest()==review['sha256']
    incoming=pd.read_parquet(OUT/'validated_observations.parquet')
    before=OUT/'before';before.mkdir(exist_ok=True)
    receipt=OUT/'ingestion.json'
    if not receipt.exists():
        for p in Path('data/exports').glob(PREFIX+'*'):shutil.copyfile(p,before/p.name)
        shutil.copyfile('reports/v2/pit_csv_inspection/field_history.csv',before/'field_history.csv')
        with get_connection('macro_pit_v2.duckdb') as conn:
            counts=conn.sql('SELECT source,count(*) n FROM observation_vintage GROUP BY source').df()
            counts.to_csv(before/'source_counts.csv',index=False)
            for r in incoming.itertuples():
                assert conn.execute("SELECT count(*) FROM observation_vintage WHERE source='PBOC' AND canonical_series_id=? AND period=?",[r.canonical_series_id,r.period]).fetchone()[0]==0
                assert conn.execute("SELECT count(*) FROM observation_vintage WHERE pit_grade IN ('A','B') AND canonical_series_id=? AND period=? AND available_at<=TIMESTAMPTZ '2026-07-31 23:59:59+08:00'",[r.canonical_series_id,r.period]).fetchone()[0]==0
            stats=insert_observations(conn,incoming.to_dict('records'))
            assert stats.inserted==14 and stats.revisions==0 and stats.metadata_updates==0
            save(receipt,dict(at=datetime.now(SHANGHAI).isoformat(),stats=asdict(stats),review_sha256=review['sha256']))
    with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
        counts=conn.sql('SELECT source,count(*) n FROM observation_vintage GROUP BY source').df().set_index('source').n
        baseline=pd.read_csv(before/'source_counts.csv').set_index('source').n
        diff=counts-baseline;assert diff['PBOC']==14 and diff.drop('PBOC').eq(0).all()
        for r in incoming.itertuples():
            actual=conn.execute("SELECT value,epoch_us(available_at),pit_grade,raw_sha256 FROM observation_vintage WHERE source='PBOC' AND canonical_series_id=? AND period=?",[r.canonical_series_id,r.period]).fetchone()
            assert actual==(r.value,r.available_at.value//1000,r.pit_grade,r.raw_sha256)
        exports=build_monthly_wide_snapshot(conn,'data/exports/'+PREFIX,'2005-01-31','2026-07-31',country='CN',pit_mode='strict')
        total=conn.sql('SELECT count(*) FROM observation_vintage').fetchone()[0]
        china=conn.sql("SELECT count(*) FROM observation_vintage WHERE country='CN'").fetchone()[0]
        reference_rows=conn.sql("SELECT * FROM observation_vintage WHERE country='CN' AND NOT (source='PBOC' AND parser_version='mof_pboc_reviewed_money_credit_b02_v1')").pl()
        assert reference_rows.height==china-14
    reference_dir=OUT/'before_batch_database_export';reference_dir.mkdir(exist_ok=True)
    # Reconstruct the actual pre-batch database panel. The old published CSV was stale.
    with get_connection(':memory:') as reference:
        reference.execute('DROP TABLE observation_vintage')
        reference.register('observation_vintage',reference_rows)
        reference_exports=build_monthly_wide_snapshot(reference,reference_dir/PREFIX,'2005-01-31','2026-07-31',country='CN',pit_mode='strict')
    def load_values(path):return pd.read_csv(path).set_index('as_of_month_end')
    def load_periods(path):
        f=pd.read_parquet(path);f.as_of_month_end=f.as_of_month_end.astype(str);return f.set_index('as_of_month_end')
    stale=load_values(before/(PREFIX+'_values.csv'));stale_periods=load_periods(before/(PREFIX+'_periods.parquet'))
    old=load_values(reference_exports['values_csv']);new=load_values(exports['values_csv'])
    op=load_periods(reference_exports['periods_parquet']);np=load_periods(exports['periods_parquet'])
    stale_mask=~(old.eq(stale)|(old.isna()&stale.isna()))|~(op.eq(stale_periods)|(op.isna()&stale_periods.isna()))
    stale_changes=[]
    with get_connection(':memory:') as reference:
        reference.execute('DROP TABLE observation_vintage');reference.register('observation_vintage',reference_rows)
        for date in old.index[stale_mask.any(axis=1)]:
            snapshot=get_snapshot(reference,date+' 23:59:59+08:00','CN').to_dicts()
            for field in old.columns[stale_mask.loc[date]]:
                hits=[r for r in snapshot if r['canonical_series_id']==field and r['period']==op.loc[date,field]]
                assert len(hits)==1 and hits[0]['value']==old.loc[date,field]
                r=hits[0]
                assert hashlib.sha256(Path(r['raw_file']).read_bytes()).hexdigest()==r['raw_sha256']
                stale_changes.append(dict(as_of=date,indicator=field,old_csv_value=stale.loc[date,field],pre_batch_db_value=old.loc[date,field],period=r['period'],available_at=r['available_at'],raw_file=r['raw_file'],raw_sha256=r['raw_sha256'],reason='EXISTING_DATABASE_RECORD_NOT_THIS_BATCH'))
    pd.DataFrame(stale_changes).to_csv(OUT/'stale_export_reconciliation.csv',index=False,encoding='utf-8-sig')
    assert new.index.equals(old.index) and new.columns.equals(old.columns) and new.notna().equals(np.notna())
    changed=~(new.eq(old)|(new.isna()&old.isna()))|~(np.eq(op)|(np.isna()&op.isna()))
    proofs={(r.canonical_series_id,r.period):r for r in incoming.itertuples()};explanation=[]
    for date in new.index:
        for field in new.columns[changed.loc[date]]:
            row=proofs[(field,np.loc[date,field])]
            assert new.loc[date,field]==row.value and row.available_at<=pd.Timestamp(date+' 23:59:59',tz='Asia/Shanghai')
            explanation.append(dict(as_of=date,indicator=field,before_value=old.loc[date,field],after_value=row.value,period=row.period,available_at=row.available_at))
    pd.DataFrame(explanation).to_csv(OUT/'export_changes.csv',index=False,encoding='utf-8-sig')
    runpy.run_path('reports/v2/pit_csv_inspection/field_history_review.py')
    history=pd.read_csv('reports/v2/pit_csv_inspection/field_history.csv')
    old_history=pd.read_csv(before/'field_history.csv')
    comparison=history.merge(old_history,on='indicator',suffixes=('_after','_before'))
    comparison=comparison[comparison.indicator.isin(incoming.canonical_series_id)]
    assert len(comparison)==7 and (comparison.strict_periods_by_cutoff_after-comparison.strict_periods_by_cutoff_before).eq(2).all()
    comparison.to_csv(OUT/'field_coverage_changes.csv',index=False,encoding='utf-8-sig')
    first=[]
    for r in history.itertuples():
        date=new[r.indicator].first_valid_index()
        assert date==r.first_nonnull_as_of
        first.append(dict(indicator=r.indicator,name=r.name,source=r.source,frequency=r.frequency,first_nonnull_as_of=date,
            first_selected_source_period=np.loc[date,r.indicator],first_value=new.loc[date,r.indicator],
            strict_first_data_period=r.strict_first_period_by_cutoff,strict_original_period_count=r.strict_periods_by_cutoff))
    pd.DataFrame(first).to_csv('reports/v2/pit_csv_inspection/first_points.csv',index=False,encoding='utf-8-sig')
    save(Path('reports/v2/pit_csv_inspection/first_points_check.json'),dict(status='PASS',fields=len(first),sha256={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [exports['values_csv'],exports['periods_parquet']]}))
    # Preserve the old NBS baseline and document this external change before it resumes.
    # Its own inserted count is zero, so the new baseline can include this verified PBOC batch.
    rollover=OUT/'nbs_baseline_before';rollover.mkdir(exist_ok=True)
    base=Path('reports/v2/pit_history_autorun/before')
    for p in Path('data/exports').glob(PREFIX+'*'):
        if (base/p.name).exists() and not (rollover/p.name).exists():shutil.copyfile(base/p.name,rollover/p.name)
        shutil.copyfile(p,base/p.name)
    save(OUT/'nbs_baseline_rollover.json',dict(at=datetime.now(SHANGHAI).isoformat(),nbs_inserted=0,external_source='PBOC',external_rows=14,preserved_original=str(rollover)))
    result=dict(status='PASS',inserted=14,fields=7,changed_cells=len(explanation),stale_export_cells=len(stale_changes),total_rows=total,china_rows=china,
        missing_pct_stale_export=round(float(stale.isna().mean().mean()*100),2),
        missing_pct_before=round(float(old.isna().mean().mean()*100),2),missing_pct_after=round(float(new.isna().mean().mean()*100),2),
        first_nonnull=sorted(comparison.first_nonnull_as_of_after.unique()),at=datetime.now(SHANGHAI).isoformat())
    save(OUT/'result.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':commit()
