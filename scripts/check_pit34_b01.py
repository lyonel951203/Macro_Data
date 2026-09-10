"""Record checks and exact parser/test hashes before B01 append."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from macro_pit.timeutils import SHANGHAI

out=Path('reports/v2/pit_34_backfill/b01')
result=subprocess.run([sys.executable,'-m','pytest','-q'],capture_output=True,text=True,encoding='utf-8')
(out/'test_output.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
print(result.stdout,result.stderr,flush=True)
paths=[*Path('src/macro_pit').rglob('*.py'),*Path('tests').rglob('*.py')]
report=dict(status='PASS' if result.returncode==0 else 'FAIL',exit_code=result.returncode,at=datetime.now(SHANGHAI).isoformat(),
            sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(out/'test_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
assert result.returncode==0
subprocess.run([sys.executable,'scripts/review_pit34_b01.py','--regress'],check=True)
