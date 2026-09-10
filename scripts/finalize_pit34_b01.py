"""Export and explain every B01 change; keep the frozen 34-field plan intact."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import duckdb
import pandas as pd
from macro_pit.acceptance import run_acceptance
from macro_pit.audit import run_audit
from macro_pit.snapshot import build_monthly_wide_snapshot
from macro_pit.timeutils import SHANGHAI

OUT=Path('reports/v2/pit_34_backfill/b01')
PLAN=OUT.parent
PREFIX='cn_pit_month_end_2005_20260731'


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def finish():
    ingestion=json.loads((OUT/'ingestion_result.json').read_text(encoding='utf-8'))
    assert ingestion['stats']['inserted']==12 and ingestion['stats']['revisions']==0
    incoming=pd.read_parquet(OUT/'validated_observations.parquet')
    with duckdb.connect('macro_pit_v2.duckdb',read_only=True) as conn:
        audit=run_audit(conn,reports_dir=OUT/'audit')
        acceptance=run_acceptance(conn)
        (OUT/'acceptance.txt').write_text(acceptance.render(),encoding='utf-8')
        exports=build_monthly_wide_snapshot(conn,f'data/exports/{PREFIX}','2005-01-31','2026-07-31',country='CN',pit_mode='strict')
        counts=conn.sql('SELECT source,count(*) row_count FROM observation_vintage GROUP BY source ORDER BY source').df()
        china=conn.sql("SELECT count(*),count(DISTINCT canonical_series_id) FROM observation_vintage WHERE country='CN'").fetchone()
        obs=conn.sql("SELECT canonical_series_id,period,available_at FROM observation_vintage WHERE country='CN' AND pit_grade IN ('A','B') AND available_at<=TIMESTAMPTZ '2026-07-31 23:59:59+08:00'").df()
    previous_counts=pd.read_csv(OUT/'before/database_source_counts.csv').set_index('source').row_count
    difference=counts.set_index('source').row_count-previous_counts
    assert difference.loc['NBS']==12 and difference.drop('NBS').eq(0).all()
    counts.to_csv(OUT/'database_source_counts.csv',index=False)
    before=pd.read_csv(OUT/'before'/f'{PREFIX}_values.csv').set_index('as_of_month_end')
    values=pd.read_csv(exports['values_csv']).set_index('as_of_month_end')
    periods=pd.read_parquet(exports['periods_parquet'])
    prior_periods=pd.read_parquet(OUT/'before'/f'{PREFIX}_periods.parquet')
    for frame in (periods,prior_periods):
        frame.as_of_month_end=frame.as_of_month_end.astype(str)
        frame.set_index('as_of_month_end',inplace=True)
    assert values.index.equals(before.index) and values.columns.equals(before.columns)
    assert values.notna().equals(periods.notna())
    vc=~(values.eq(before)|(values.isna()&before.isna()))
    pc=~(periods.eq(prior_periods)|(periods.isna()&prior_periods.isna()))
    expected={(r.canonical_series_id,r.period):r for r in incoming.itertuples()}
    changes=[]
    for date in values.index:
        for canonical in values.columns[(vc|pc).loc[date]]:
            row=expected[(canonical,periods.loc[date,canonical])]
            assert row.value==values.loc[date,canonical]
            assert row.available_at<=pd.Timestamp(date+' 23:59:59',tz='Asia/Shanghai')
            changes.append(dict(as_of_month_end=date,indicator=canonical,before_value=before.loc[date,canonical],after_value=row.value,
                                before_period=prior_periods.loc[date,canonical],after_period=row.period,
                                value_changed=bool(vc.loc[date,canonical]),period_changed=bool(pc.loc[date,canonical])))
    pd.DataFrame(changes).to_csv(OUT/'export_changes.csv',index=False,encoding='utf-8-sig')
    for name in ['audit.html','cn_coverage.csv','us_coverage.csv','global_coverage.csv']:
        shutil.copyfile(OUT/'audit'/name,Path('reports/v2')/name)
    helper=runpy.run_path('scripts/finalize_nbs_economy_batch.py')
    execute=runpy.run_path('scripts/run_nbs_price_batch_once.py')['execute_notebook']
    history_py=Path('reports/v2/pit_csv_inspection/field_history_review.py')
    history_nb=history_py.with_suffix('.ipynb')
    cells=[helper['code_cell'](s.lstrip()) for s in history_py.read_text(encoding='utf-8').split('# %%') if s.strip()]
    save(history_nb,helper['notebook'](cells))
    execute(history_nb)
    execute(Path('reports/v2/pit_csv_inspection/review.ipynb'))
    history=pd.read_csv(history_py.parent/'field_history.csv')
    previous=pd.read_csv(OUT/'before/field_history.csv')
    comparison=history.merge(previous,on='indicator',suffixes=('_after','_before'))
    comparison=comparison[comparison.indicator.isin(incoming.canonical_series_id)].copy()
    comparison['new_strict_periods']=comparison.strict_periods_by_cutoff_after-comparison.strict_periods_by_cutoff_before
    assert len(comparison)==10 and comparison.new_strict_periods.sum()==12
    assert (comparison.first_nonnull_as_of_after<comparison.first_nonnull_as_of_before).all()
    comparison.to_csv(OUT/'field_coverage_changes.csv',index=False,encoding='utf-8-sig')
    # Refresh the actual CSV/parquet first-point inspection without touching the plan baseline.
    first=[]
    for row in history.itertuples():
        date=values[row.indicator].first_valid_index()
        assert date==row.first_nonnull_as_of and periods.loc[date,row.indicator]==row.first_selected_source_period
        first.append(dict(indicator=row.indicator,name=row.name,source=row.source,frequency=row.frequency,first_nonnull_as_of=date,
                          first_selected_source_period=periods.loc[date,row.indicator],first_value=values.loc[date,row.indicator],
                          strict_first_data_period=row.strict_first_period_by_cutoff,strict_original_period_count=row.strict_periods_by_cutoff))
    pd.DataFrame(first).to_csv(history_py.parent/'first_points.csv',index=False,encoding='utf-8-sig')
    save(history_py.parent/'first_points_check.json',dict(status='PASS',fields=len(first),method='actual_export_and_current_field_history',
         sha256={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [exports['values_csv'],exports['periods_parquet']]}))
    tasks=pd.read_csv(PLAN/'tasks.csv')
    progress=tasks[['task_id','indicator','name','batch']].merge(history,on=['indicator','name'])
    progress['execution_status']=progress.indicator.map(lambda x:'ANCHOR_ADDED' if x in set(incoming.canonical_series_id) else 'PLANNED')
    gap_details=[]
    for i,row in progress.iterrows():
        selected=obs[obs.canonical_series_id.eq(row.indicator)]
        observed=set(selected.period)
        calendar=pd.period_range(min(observed),max(observed),freq=row.frequency)
        longest=[]; current=[]
        for p in calendar:
            if str(p) not in observed:
                current.append(str(p))
                if len(current)>len(longest): longest=current.copy()
            else: current=[]
        progress.loc[i,'earliest_verified_available_at']=selected.available_at.min().tz_convert('Asia/Shanghai').isoformat()
        progress.loc[i,'longest_uncovered_periods']=len(longest)
        progress.loc[i,'longest_uncovered_start']=longest[0] if longest else ''
        progress.loc[i,'longest_uncovered_end']=longest[-1] if longest else ''
        if row.batch=='B01':
            year=min(observed)[:4]
            for p in pd.period_range(year+'-01',year+'-12',freq='M'):
                status='OBSERVED' if str(p) in observed else 'MISSING_NOT_YET_REVIEWED'
                if row.indicator=='CN_SERVICE_PRODUCTION_YOY' and p.month<3:
                    status='PRE_MONTHLY_START_COMBINED_PERIOD_REVIEW'
                gap_details.append(dict(indicator=row.indicator,period=str(p),status=status))
    progress.to_csv(PLAN/'execution_progress.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(gap_details).to_csv(OUT/'first_year_period_review.csv',index=False,encoding='utf-8-sig')
    result=dict(status='ANCHOR_BATCH_COMPLETE',at=datetime.now(SHANGHAI).isoformat(),database_rows=int(counts.row_count.sum()),
                china_rows=china[0],china_series=china[1],nbs_rows=int(counts.set_index('source').loc['NBS','row_count']),inserted=12,
                revisions=0,fields_moved_earlier=10,primary_fields_moved=3,wide_rows=len(values),wide_indicators=len(values.columns),
                before_missing_pct=round(before.isna().to_numpy().mean()*100,2),after_missing_pct=round(values.isna().to_numpy().mean()*100,2),
                changed_cells=len(changes),newly_nonnull_cells=int((before.isna()&values.notna()).to_numpy().sum()),
                acceptance_passed=acceptance.passed,acceptance_failures=[asdict(c) for c in acceptance.checks if not c.passed],
                audit=asdict(audit),history_complete=False,next_batch='B02',next_batch_started=False)
    save(OUT/'final_result.json',result)
    save(PLAN/'execution_state.json',dict(status='IN_PROGRESS',last_completed_batch='B01_ANCHORS',next_batch='B02',
         active_worker=False,at=result['at'],tasks={r.task_id:dict(indicator=r.indicator,status=r.execution_status) for r in progress.itertuples()}))
    code=helper['code_cell']
    nb=OUT/'review.ipynb'
    save(nb,helper['notebook']([
        dict(cell_type='markdown',metadata={},source=['# B01 起点回溯核验\n','原值与实际发布时间、覆盖变化、首年待补期。\n']),
        code("from pathlib import Path\nimport os, json, pandas as pd\nroot=next(p for p in [Path.cwd(),*Path.cwd().parents] if (p/'macro_pit_v2.duckdb').exists())\nos.chdir(root)\nout=Path('reports/v2/pit_34_backfill/b01')\nsamples=pd.read_csv(out/'validated_samples.csv')\nassert len(samples)==12 and samples.result.eq('PASS').all()\nassert not samples.duplicated(['canonical_series_id','period']).any()\nsamples[['canonical_series_id','period','value','release_at']]\n"),
        code("coverage=pd.read_csv(out/'field_coverage_changes.csv')\nassert coverage.new_strict_periods.sum()==12\ncoverage[['indicator','first_nonnull_as_of_before','first_nonnull_as_of_after','strict_periods_by_cutoff_after','max_source_age_months_after']]\n"),
        code("gaps=pd.read_csv(out/'first_year_period_review.csv')\nassert len(gaps)==36\ngaps.groupby(['indicator','status']).size()\n")]))
    execute(nb)
    save(OUT/'notebook_execution.json',dict(status='PASS',notebooks=[str(nb),str(history_nb),'reports/v2/pit_csv_inspection/review.ipynb']))
    print(json.dumps({k:v for k,v in result.items() if k!='audit'},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    finish()
