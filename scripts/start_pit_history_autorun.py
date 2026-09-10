"""Start the resumable worker without a visible console or a PowerShell script policy change."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
out=root/'reports/v2/pit_history_autorun'
for marker in ['nbs_price_batch.lock','pit_history_autorun.stop']:
    if (root/'data/history_backfill'/marker).exists():
        raise SystemExit(f'{marker} exists; inspect current worker/stop intent before restarting')
env=os.environ.copy()
env['PYTHONPATH']=str(root/'src')
env['PYTHONIOENCODING']='utf-8'
stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
with (out/f'{stamp}.stdout.log').open('ab') as stdout, (out/f'{stamp}.stderr.log').open('ab') as stderr:
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0
    worker=subprocess.Popen([sys.executable,'-u','scripts/run_pit_history_autorun.py','--allow-network'],cwd=root,env=env,
                            stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=flags)
print(f'Started hidden PIT history worker PID={worker.pid}; logs={out}')
