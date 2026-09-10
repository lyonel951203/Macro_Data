"""Start one hidden worker per requested source plus a file-only monitor."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from monitor_source_progress import process_alive,read_json

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/history_backfill/source_workers'


def launch(name,args,lock,stop):
    if stop.exists():raise RuntimeError(f'Stop marker exists: {stop}')
    if lock.exists():
        info=read_json(lock)
        if process_alive(info.get('pid')):
            print(f'{name}: already alive PID={info["pid"]}');return info['pid']
        raise RuntimeError(f'Stale lock requires inspection: {lock}')
    out=ROOT/'reports/v2/source_monitor/logs';out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    env=os.environ.copy();env.update(PYTHONPATH=str(ROOT/'src'),PYTHONIOENCODING='utf-8')
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
    with (out/f'{name}_{stamp}.stdout.log').open('ab') as stdout,(out/f'{name}_{stamp}.stderr.log').open('ab') as stderr:
        p=subprocess.Popen([sys.executable,'-u',*args],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=flags)
    print(f'{name}: started hidden process PID={p.pid}')
    return p.pid


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',nargs='*',choices=['PBOC','SAFE'],default=['PBOC','SAFE'])
    parser.add_argument('--monitor',action='store_true')
    args=parser.parse_args()
    BASE.mkdir(parents=True,exist_ok=True)
    registry=read_json(BASE/'registry.json')
    for source in dict.fromkeys(args.sources):
        directory=BASE/source.lower()
        pid=launch(source,['scripts/pull_source_archive.py','--source',source,'--allow-network'],directory/'worker.lock',directory/'stop')
        registry[source]={'pid':pid,'launched_at':datetime.now().isoformat()}
    if args.monitor:
        pid=launch('MONITOR',['scripts/monitor_source_progress.py','--watch','10','--quiet'],BASE/'monitor.lock',BASE/'monitor.stop')
        registry['MONITOR']={'pid':pid,'launched_at':datetime.now().isoformat()}
    (BASE/'registry.json').write_text(json.dumps(registry,indent=2),encoding='utf-8')
