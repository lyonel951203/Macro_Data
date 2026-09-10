"""Inspect all source workers without opening DuckDB or making network requests."""
import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import time
from macro_pit.config import source_policy
from macro_pit.timeutils import SHANGHAI

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/history_backfill/source_workers'
OUT=ROOT/'reports/v2/source_monitor'
TERMINAL={'SOURCE_BLOCKED','STOPPED','STOPPED_ERROR','STOPPED_AT_CHECKPOINT','QUEUE_DRAINED_WITH_REVIEW_PENDING',
          'RAW_QUEUE_COMPLETE_REVIEW_PENDING','QUEUE_COMPLETE_WITH_BLOCKED_ROUTES'}


def read_json(path,default=None):
    if not path.exists(): return {} if default is None else default
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:return {'read_error':str(exc)}


def process_alive(pid):
    if not pid:return False
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,int(pid))
        if not handle:return False
        code=wintypes.DWORD()
        try:return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(int(pid),0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def effective_status(status,alive,age):
    if status in TERMINAL:return status
    if not alive:return 'PROCESS_EXITED' if status!='NOT_STARTED' else status
    if age is not None and age>600:return 'STALE_HEARTBEAT'
    return status


def snapshot():
    current=datetime.now(SHANGHAI);day=current.date().isoformat()
    registry=read_json(BASE/'registry.json')
    legacy=read_json(ROOT/'data/audit/request_budget'/f'{day}.json')
    rows=[]
    for source in ['NBS','PBOC','SAFE']:
        path=ROOT/'data/history_backfill/pit_history_autorun.json' if source=='NBS' else BASE/source.lower()/'state.json'
        state=read_json(path);policy=source_policy(source)
        pid=state.get('pid') or registry.get(source,{}).get('pid')
        alive=process_alive(pid);stamp=state.get('updated_at')
        age=(current-datetime.fromisoformat(stamp)).total_seconds() if stamp else None
        status=state.get('status','STARTING' if alive else 'NOT_STARTED')
        if state.get('read_error'):status='STATE_READ_ERROR'
        own=read_json(BASE/source.lower()/'budget'/f'{day}.json') if source!='NBS' else {}
        budget_valid='read_error' not in legacy and 'read_error' not in own
        if source=='NBS':
            results=state.get('articles',{})
            archived=sum('raw_file' in v for v in results.values())
            indexes=None;pending=None;total=state.get('total_jobs',0);done=len(state.get('completed_jobs',[]))
            current_task=state.get('current_job','')
            held=sum(bool(v.get('held')) for v in results.values())
        else:
            results=state.get('results',{})
            archived=sum(v.get('status')=='ARCHIVED' and v.get('item',{}).get('kind')=='article' for v in results.values())
            indexes=sum(v.get('status')=='ARCHIVED' and v.get('item',{}).get('kind')=='index' for v in results.values())
            pending=len(state.get('queue',[]));done=len(results);total=done+pending
            current_task=state.get('current_title','');held=archived
        rows.append(dict(source=source,status=effective_status(status,alive,age),recorded_status=status,pid=pid,process_alive=alive,
            heartbeat_at=stamp,heartbeat_age_seconds=round(age,1) if age is not None else None,completed=done,total=total,
            progress_unit='search_windows' if source=='NBS' else 'urls',archived_articles=archived,archived_indexes=indexes,
            pending_urls=pending,review_pending_articles=held,inserted_observations=state.get('inserted',0),
            requests_today=int(legacy.get(source,0))+int(own.get(source,0)) if budget_valid else None,
            daily_limit=policy['max_requests_per_day'],run_limit=policy['max_requests_per_run'],
            session_requests=state.get('session_requests'),min_interval_seconds=policy['min_interval_seconds'],
            max_interval_seconds=policy['min_interval_seconds']+policy['jitter_seconds'],current_task=current_task,
            current_url=state.get('current_url',''),last_error=state.get('last_error',''),blocked_hosts=state.get('blocked_hosts',{}),
            resume_at=state.get('resume_at'),deadline=state.get('deadline',state.get('session_deadline')),
            last_export_at=state.get('last_export_at'),state_file=str(path)))
    return dict(as_of=current.isoformat(),workers=rows,monitor_pid=os.getpid(),note='Read-only process/file inspection. Archived raw is not validated PIT data; dead processes never shown as running.')


def render(report):
    limit_text=lambda value:'不限' if value is None else str(value)
    lines=[f"# 多来源拉取监控 — {report['as_of']}",'',
        '| 来源 | 状态 | PID/存活 | 完成/队列 | 正文归档 | 目录归档 | 待审正文 | 入库 | 今日请求/上限 |',
        '|---|---|---|---|---:|---:|---:|---:|---|']
    for r in report['workers']:
        lines.append(f"| {r['source']} | {r['status']} | {r['pid'] or '-'} / {'是' if r['process_alive'] else '否'} | {r['completed']}/{r['total']} {r['progress_unit']} | {r['archived_articles']} | {r['archived_indexes'] if r['archived_indexes'] is not None else '-'} | {r['review_pending_articles']} | {r['inserted_observations']} | {r['requests_today']}/{limit_text(r['daily_limit'])} |")
    lines+=['','NBS 的队列单位是检索窗口；其余来源是 URL，分母可能随已核目录发现新链接而增加。原稿归档与 PIT 入库分开计数。','']
    for r in report['workers']:
        lines.extend([f"- **{r['source']}**：{r['current_task'] or '尚无当前任务'}；心跳 {r['heartbeat_at'] or '-'}；原始状态 `{r['recorded_status']}`。",
                      f"  请求间隔 {r['min_interval_seconds']}—{r['max_interval_seconds']} 秒；单次上限 {limit_text(r['run_limit'])}；截止 {r['deadline'] or '-'}。"])
        if r['last_error']:lines.append(f"  最近错误/暂停原因：{r['last_error']}")
        if r['blocked_hosts']:lines.append(f"  受阻站点：{json.dumps(r['blocked_hosts'],ensure_ascii=False)}")
    lines+=['','PBOC/SAFE 当前只归档、不写主库。NBS 等待额度时进程仍可存活；SOURCE_BLOCKED 和队列完成均不代表数据已完整。',
            '此文件由监控进程定时刷新；若顶部时间不再变化，请运行监控脚本重新核对进程。']
    return '\n'.join(lines)+'\n'


def write_report(report):
    OUT.mkdir(parents=True,exist_ok=True)
    for name,text in [('latest.json',json.dumps(report,ensure_ascii=False,indent=2)),('latest.md',render(report))]:
        path=OUT/name;tmp=path.with_suffix(path.suffix+'.tmp')
        tmp.write_text(text,encoding='utf-8');os.replace(tmp,path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',type=float,default=0,help='Refresh interval in seconds; 0 prints once')
    parser.add_argument('--json',action='store_true')
    parser.add_argument('--quiet',action='store_true',help='Update latest reports without console output')
    args=parser.parse_args()
    if args.watch and args.watch<2:parser.error('--watch must be >=2 seconds')
    lock=BASE/'monitor.lock'
    owns_reports=bool(args.watch and args.quiet)
    if owns_reports:
        BASE.mkdir(parents=True,exist_ok=True)
        with lock.open('x',encoding='utf-8') as f:json.dump({'pid':os.getpid()},f)
    try:
        while True:
            report=snapshot()
            # The watcher owns shared report files; one-shot inspection stays safe while it runs.
            if owns_reports or (not args.watch and not lock.exists()):write_report(report)
            if not args.quiet:print(json.dumps(report,ensure_ascii=False,indent=2) if args.json else render(report),flush=True)
            if not args.watch or (owns_reports and (BASE/'monitor.stop').exists()):break
            time.sleep(args.watch)
    finally:
        if owns_reports:lock.unlink()


if __name__=='__main__':main()
