"""Finite, resumable oldest-first NBS discovery, verification and gap insertion.

Runs without an LLM or unattended approval prompts. Unknown definitions go to
review; source blocking stops requests, budget exhaustion waits for a new day.
"""
import argparse
from dataclasses import asdict
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import time
import pandas as pd
import httpx
from macro_pit.db import get_connection,insert_observations,record_crawl_events
from macro_pit.errors import CrawlSafetyError
from macro_pit.fileio import atomic_write_text
from macro_pit.nbs_search import discover_nbs_legacy
from macro_pit.snapshot import build_monthly_wide_snapshot,get_snapshot
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI
from pit_autorun_validation import verify

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/v2/history/pit/pit_history_autorun'
STATE=ROOT/'data/history_backfill/pit_history_autorun.json'
LOCK=ROOT/'data/history_backfill/nbs_price_batch.lock'
MARKER='PIT_HISTORY_AUTORUN'


def now(): return datetime.now(SHANGHAI)


def save(path,value):
    atomic_write_text(path,json.dumps(value,ensure_ascii=False,indent=2,default=str))


def checkpoint(state):
    state['updated_at']=now().isoformat()
    save(STATE,state)
    status=ROOT/'reports/v2/STATUS.md'
    original=status.read_text(encoding='utf-8')
    start,end=f'<!-- {MARKER}:start -->',f'<!-- {MARKER}:end -->'
    block='\n'.join([start,'### 后台长任务：从 2005 年向后逐年补齐',
        f"- 状态 `{state['status']}`；进程 {state['pid']}；更新时间 {state['updated_at']}。",
        f"- 当前步骤：{state.get('current_job','初始化')}；已完成年度检索窗口 {len(state['completed_jobs'])}/{state['total_jobs']}。",
        f"- 已处理正文 {len(state['articles'])} 篇；本任务累计新增严格记录 {state['inserted']} 条；待审正文 {sum(bool(v.get('held')) for v in state['articles'].values())} 篇。",
        '- 自动执行范围：NBS 17 个目标字段的发现与已核格式补缺；未知格式/口径隔离待审。PBOC 10 项、SAFE 7 项仍需适配，不能标成全自动完成。',
        '- 检索从 2005 到 2026-07，逐年连续推进；每日和每轮请求数量不限，来源限速与熔断保留。此进程最长运行 7 天，关机/休眠时不推进，重启后可从断点启动。',
        '- 进度以 `data/history_backfill/pit_history_autorun.json` 为准；已插入记录/待审原稿见 `reports/v2/history/pit/pit_history_autorun/`。候选数与非空格不代表真实历史完整度。',
        f"- 最近导出：{state.get('last_export_at','尚未有新记录需要导出')}；运行说明见 [README](pit_history_autorun/README.md)。",
        *([f"- 暂停/错误：{state['last_error']}"] if state.get('last_error') else []),end])
    if start in original and end in original:
        a,b=original.index(start),original.index(end)+len(end)
        updated=original[:a]+block+original[b:]
    else:
        index=original.index('### ')
        updated=original[:index]+block+'\n\n'+original[index:]
    if status.read_text(encoding='utf-8')==original:
        atomic_write_text(status,updated)


def jobs_for(config):
    jobs=[]
    end=config['end_date']
    for year in range(config['start_year'],int(end[:4])+1):
        for i,term in enumerate(config['terms']):
            jobs.append(dict(name=f'{year}_{i}',term=term,start_date=f'{year}-01-01',end_date=min(f'{year}-12-31',end)))
    return jobs


def export(state):
    if state.get('exported_inserted',0)==state['inserted']: return
    prefix='data/exports/cn_pit_month_end_2005_20260731'
    with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
        build_monthly_wide_snapshot(conn,prefix,'2005-01-31','2026-07-31',country='CN',pit_mode='strict')
        coverage=conn.sql("SELECT canonical_series_id,count(DISTINCT period) actual_periods,min(period) first_period,max(period) last_period,min(available_at) first_available_at FROM observation_vintage WHERE country='CN' AND pit_grade IN ('A','B') AND available_at<=TIMESTAMPTZ '2026-07-31 23:59:59+08:00' GROUP BY canonical_series_id").df()
    # This existing report script is entirely offline and reads the new exports.
    runpy.run_path('reports/v2/history/pit/pit_csv_inspection/field_history_review.py')
    values=pd.read_csv(prefix+'_values.csv')
    periods=pd.read_parquet(prefix+'_periods.parquet')
    assert values.iloc[:,1:].notna().equals(periods.iloc[:,1:].notna())
    baseline=pd.read_csv(OUT/'before/cn_pit_month_end_2005_20260731_values.csv')
    baseline_periods=pd.read_parquet(OUT/'before/cn_pit_month_end_2005_20260731_periods.parquet')
    assert values.columns.equals(baseline.columns) and values.as_of_month_end.equals(baseline.as_of_month_end)
    proofs={}
    for receipt in (OUT/'receipts').glob('*.json'):
        for row,proof in json.loads(receipt.read_text(encoding='utf-8'))['verified']:
            proofs[(row['canonical_series_id'],row['period'],row['value'])]=row['available_at']
    changed_cells=0
    for canonical in values.columns[1:]:
        changed=~(values[canonical].eq(baseline[canonical])|(values[canonical].isna()&baseline[canonical].isna()))
        changed |= ~(periods[canonical].eq(baseline_periods[canonical])|(periods[canonical].isna()&baseline_periods[canonical].isna()))
        for i in values.index[changed]:
            available=proofs[(canonical,periods.loc[i,canonical],values.loc[i,canonical])]
            assert pd.Timestamp(available)<=pd.Timestamp(values.loc[i,'as_of_month_end']+' 23:59:59',tz='Asia/Shanghai')
            changed_cells+=1
    state['verified_changed_cells']=changed_cells
    first=[]
    metadata=pd.read_csv(prefix+'_metadata.csv').set_index('canonical_series_id')
    for canonical in values.columns[1:]:
        i=values[canonical].first_valid_index()
        record=coverage[coverage.canonical_series_id.eq(canonical)].iloc[0]
        first.append(dict(indicator=canonical,name=metadata.loc[canonical,'series_name'],source=metadata.loc[canonical,'source'],
            frequency=metadata.loc[canonical,'frequency'],first_nonnull_as_of=values.loc[i,'as_of_month_end'],
            first_selected_source_period=periods.loc[i,canonical],first_value=values.loc[i,canonical],
            strict_first_data_period=record.first_period,strict_original_period_count=int(record.actual_periods)))
    pd.DataFrame(first).to_csv('reports/v2/history/pit/pit_csv_inspection/first_points.csv',index=False,encoding='utf-8-sig')
    save(Path('reports/v2/history/pit/pit_csv_inspection/first_points_check.json'),dict(status='PASS',at=now().isoformat(),fields=len(first),
        sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [prefix+'_values.csv',prefix+'_periods.parquet']}))
    history=pd.read_csv('reports/v2/history/pit/pit_csv_inspection/field_history.csv')
    tasks=pd.read_csv('reports/v2/history/pit/pit_34_backfill/tasks.csv')
    tasks[['task_id','indicator','batch']].merge(history,on='indicator').to_csv(OUT/'live_34_field_coverage.csv',index=False,encoding='utf-8-sig')
    state['last_export_at']=now().isoformat()
    state['exported_inserted']=state['inserted']
    state['wide_missing_pct']=round(values.iloc[:,1:].isna().to_numpy().mean()*100,2)
    checkpoint(state)


def process_article(candidate,source,state,targets):
    url=candidate['url']
    if url in state['articles']: return
    with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
        failed=conn.execute('SELECT count(*) FROM crawl_log WHERE url=? AND http_status=404',[url]).fetchone()[0]
    if failed:
        state['articles'][url]=dict(held=[{'reason':'previously_archived_404_not_retried'}])
        checkpoint(state)
        return
    raw_index=Path(candidate['index_raw_file'])
    payload=json.loads(raw_index.read_text(encoding='utf-8'))
    matches=[x['data'] for x in payload['resultDocs'] if x.get('data',{}).get('url')==url]
    if not matches:
        # Only exact provenance is accepted, never infer dates from migrated URLs.
        state['articles'][url]=dict(held=[{'reason':'no_exact_search_provenance'}])
        return
    date=str(matches[0].get('docDate',''))
    start=len(source.client.events)
    try:
        fetched=source.fetch(url,refresh=False)
    finally:
        if source.client.events[start:]:
            with get_connection('macro_pit_v2.duckdb') as conn:
                record_crawl_events(conn,source.client.events[start:],parser_version='pit_history_autorun_download_v1')
    artifact=fetched.artifact
    held=[]; accepted=[]
    try:
        parsed=source.parse(fetched.content,artifact)
        accepted,held=verify(fetched.content,artifact,candidate['title'],date,parsed,targets)
    except Exception as exc:
        held=[dict(reason='parser_or_evidence_review_required',error=f'{type(exc).__name__}: {exc}')]
    with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
        existing=set(conn.sql("SELECT canonical_series_id,period FROM observation_vintage WHERE country='CN' AND pit_grade IN ('A','B')").fetchall())
    accepted=[(r,p) for r,p in accepted if (r['canonical_series_id'],r['period']) not in existing]
    rows=[r for r,p in accepted]
    if rows:
        # Validate the real time-travel API and append idempotency before touching the main DB.
        with get_connection(':memory:') as conn:
            assert insert_observations(conn,rows).inserted==len(rows)
            assert insert_observations(conn,rows).inserted==0
            for row in rows:
                for offset,visible in [(-1,False),(0,True)]:
                    snapshot=get_snapshot(conn,(row['available_at']+timedelta(seconds=offset)).isoformat(),'CN')
                    found=[r for r in snapshot.to_dicts() if r['canonical_series_id']==row['canonical_series_id'] and r['period']==row['period']]
                    assert bool(found)==visible
        # Evidence is durable before the append. Resume can recover an interrupted append by source SHA.
        receipt=OUT/'receipts'/f'{artifact.sha256}.json'
        save(receipt,dict(url=url,artifact=asdict(artifact),search_raw=str(raw_index),search_date=date,verified=accepted,held=held,status='VERIFIED'))
        with get_connection('macro_pit_v2.duckdb') as conn:
            stats=insert_observations(conn,rows)
            assert stats.revisions==0
        state['inserted']+=stats.inserted
        save(receipt,dict(url=url,artifact=asdict(artifact),search_raw=str(raw_index),search_date=date,verified=accepted,held=held,status='APPENDED',stats=asdict(stats)))
    state['articles'][url]=dict(raw_file=artifact.path,raw_sha256=artifact.sha256,held=held,inserted=len(rows),at=now().isoformat())
    checkpoint(state)
    if state['inserted']-state.get('exported_inserted',0)>=10: export(state)


def run(allow_network=False):
    os.chdir(ROOT)
    config=json.loads(Path('config/history/pit/pit_history_autorun.json').read_text(encoding='utf-8'))
    preflight=json.loads((OUT/'preflight.json').read_text(encoding='utf-8'))
    assert preflight['status']=='PASS', 'Offline replay must pass before unattended execution'
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in preflight['sha256'].items()), 'Code changed since offline replay'
    jobs=jobs_for(config)
    OUT.mkdir(parents=True,exist_ok=True)
    state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else dict(completed_jobs=[],articles={},inserted=0)
    digest=hashlib.sha256(Path('config/history/pit/pit_history_autorun.json').read_bytes()).hexdigest()
    assert state.get('config_sha256',digest)==digest
    if state.get('status') in {'SOURCE_BLOCKED','QUEUE_DRAINED_WITH_REVIEW_PENDING'}:
        raise RuntimeError('Blocked/completed queue requires review before restart')
    with LOCK.open('x',encoding='utf-8') as lock:
        json.dump(dict(pid=os.getpid(),batch='pit_history_autorun'),lock)
    source=None
    try:
        state.update(status='RUNNING',pid=os.getpid(),total_jobs=len(jobs),config_sha256=digest)
        state.setdefault('started_at',now().isoformat())
        state['session_deadline']=(now()+timedelta(days=config['max_calendar_days'])).isoformat()
        before=OUT/'before'
        before.mkdir(exist_ok=True)
        for p in Path('data/exports').glob('cn_pit_month_end_2005_20260731*'):
            if not (before/p.name).exists(): shutil.copyfile(p,before/p.name)
        # Recover counts if a process stopped after DB commit but before checkpoint.
        recovered=0
        with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
            for receipt in (OUT/'receipts').glob('*.json'):
                for row,proof in json.loads(receipt.read_text(encoding='utf-8'))['verified']:
                    found=conn.execute('SELECT count(*) FROM observation_vintage WHERE raw_sha256=? AND canonical_series_id=? AND period=? AND value=? AND available_at=?',
                        [row['raw_sha256'],row['canonical_series_id'],row['period'],row['value'],row['available_at']]).fetchone()[0]
                    recovered+=bool(found)
        state['inserted']=recovered
        targets=set(pd.read_csv('reports/v2/history/pit/pit_34_backfill/tasks.csv').query("source=='NBS'").indicator)
        source=NBSSource(allow_network=allow_network)
        if all(source.client.policy[key] is None for key in ('max_requests_per_day','max_requests_per_run')):
            if 'budget exhausted' in state.get('last_error',''):
                state.pop('last_error')
            for path in (OUT/'discovery').glob('*/search_state.json'):
                search_state=json.loads(path.read_text(encoding='utf-8'))
                if 'budget exhausted' in search_state.get('last_error',''):
                    search_state.pop('last_error')
                    save(path,search_state)
        checkpoint(state)
        for job in jobs:
            if job['name'] in state['completed_jobs']: continue
            output=OUT/'discovery'/job['name']
            while True:
                assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in preflight['sha256'].items()), 'Code changed during unattended execution; review and restart'
                if Path(config['stop_file']).exists() or now()>=datetime.fromisoformat(state['session_deadline']):
                    state['status']='STOPPED_AT_CHECKPOINT'
                    return
                state['current_job']=f"{job['start_date']} 至 {job['end_date']}：{job['term']}"
                checkpoint(state)
                try:
                    search=discover_nbs_legacy('macro_pit_v2.duckdb',terms=[job['term']],start_date=job['start_date'],end_date=job['end_date'],
                        state_path=output/'search_state.json',output_dir=output,allow_network=allow_network,max_network_pages=1,client=source.client)
                    if search['status']=='BLOCKED': raise CrawlSafetyError(search.get('last_error','source blocked'))
                    if 'budget exhausted' in search.get('last_error',''): raise CrawlSafetyError(search['last_error'])
                    if search.get('last_error'):
                        state['last_error']=search['last_error']
                    else:
                        state.pop('last_error',None)
                    checkpoint(state)
                    candidates=output/'nbs_candidates.parquet'
                    if candidates.exists():
                        for candidate in pd.read_parquet(candidates).sort_values(['period','url']).to_dict('records'):
                            if Path(config['stop_file']).exists():
                                state['status']='STOPPED_AT_CHECKPOINT'
                                return
                            try:
                                process_article(candidate,source,state,targets)
                            except httpx.HTTPStatusError as exc:
                                if exc.response.status_code!=404: raise
                                state['articles'][candidate['url']]=dict(held=[{'reason':'official_404_not_retried'}])
                                checkpoint(state)
                    if search['status'] in {'COMPLETE','PARTIAL'}:
                        state['completed_jobs'].append(job['name'])
                        if search['status']=='PARTIAL':
                            state.setdefault('search_review',[]).append(dict(job=job,reason='pagination_needs_narrowing'))
                        export(state)
                        checkpoint(state)
                        break
                except CrawlSafetyError as exc:
                    state['last_error']=str(exc)
                    if 'budget exhausted' not in str(exc):
                        state['status']='SOURCE_BLOCKED'
                        return
                    state['status']='WAITING_NEXT_DAY_BUDGET'
                    checkpoint(state)
                    export(state)
                    today=now().date()
                    while now().date()==today:
                        if Path(config['stop_file']).exists() or now()>=datetime.fromisoformat(state['session_deadline']):
                            state['status']='STOPPED_AT_CHECKPOINT'
                            return
                        time.sleep(30)
                        checkpoint(state)
                    source.close()
                    source=NBSSource(allow_network=allow_network)
                    # Only a new calendar day opens a fresh budget session.
                    state.pop('last_error',None)
                    # Discovery checkpoints retain old budget error text; clear only that resolved condition.
                    path=output/'search_state.json'
                    if path.exists():
                        search_state=json.loads(path.read_text(encoding='utf-8'))
                        if 'budget exhausted' in search_state.get('last_error',''):
                            search_state.pop('last_error',None)
                            save(path,search_state)
                    state['status']='RUNNING'
        state['status']='QUEUE_DRAINED_WITH_REVIEW_PENDING'
    except Exception as exc:
        state.update(status='STOPPED_ERROR',last_error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        try:
            if source: source.close()
            export(state)
            checkpoint(state)
        finally:
            LOCK.unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-network',action='store_true')
    p.add_argument('--show-plan',action='store_true')
    args=p.parse_args()
    if args.show_plan:
        print(json.dumps(jobs_for(json.loads((ROOT/'config/history/pit/pit_history_autorun.json').read_text(encoding='utf-8'))),ensure_ascii=False,indent=2))
    else:
        run(args.allow_network)
