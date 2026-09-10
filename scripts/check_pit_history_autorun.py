"""Offline replay of the automatic evidence gate against the existing NBS archive."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pandas as pd
from macro_pit.archive import RawArtifact
from macro_pit.db import get_connection
from macro_pit.sources.cn_nbs import NBSSource
from macro_pit.timeutils import SHANGHAI
from pit_autorun_validation import verify
from lxml import html

out=Path('reports/v2/pit_history_autorun'); out.mkdir(parents=True,exist_ok=True)
with get_connection('macro_pit_v2.duckdb',read_only=True) as conn:
    baseline=conn.sql("SELECT * FROM observation_vintage WHERE source='NBS'").df()
targets=set(pd.read_csv('reports/v2/pit_34_backfill/tasks.csv').query("source=='NBS'").indicator)
source=NBSSource(allow_network=False)
verified=0; mismatches=[]; failures=[]; groups=baseline.groupby(['raw_file','raw_sha256'])
try:
    for i,((path,sha),group) in enumerate(groups,1):
        content=Path(path).read_bytes(); row=group.iloc[0]
        artifact=RawArtifact('NBS',row.source_url,path,sha,'text/html',row.retrieved_at.to_pydatetime(),len(content))
        title=html.fromstring(content.decode('utf-8')).xpath('string(//title)')
        try:
            parsed=source.parse(content,artifact)
            accepted,held=verify(content,artifact,title,row.available_at.tz_convert('Asia/Shanghai').date().isoformat(),parsed,targets)
        except Exception as exc:
            failures.append(dict(path=path,error=str(exc))); continue
        for candidate,proof in accepted:
            existing=group[group.canonical_series_id.eq(candidate['canonical_series_id']) & group.period.eq(candidate['period'])]
            if len(existing) and not existing.value.eq(candidate['value']).any():
                mismatches.append(dict(path=path,id=candidate['canonical_series_id'],period=candidate['period']))
            verified+=1
        if i%75==0: print(f'Checked evidence gate against {i}/{len(groups)} archives',flush=True)
finally:
    source.close()
result=dict(status='PASS' if not mismatches and not failures and verified>0 else 'FAIL',archives=len(groups),
            independently_verified_rows=verified,mismatches=mismatches,failures=failures,at=datetime.now(SHANGHAI).isoformat(),
            sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('scripts/pit_autorun_validation.py'),Path('scripts/run_pit_history_autorun.py'),*Path('src/macro_pit').rglob('*.py')]})
(out/'preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='sha256'},ensure_ascii=False,indent=2))
assert result['status']=='PASS'
