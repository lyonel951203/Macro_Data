import importlib.util,json,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('background_parse',Path(__file__).resolve().parents[1]/'scripts/history/parse_archives_background.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def test_timeout_does_not_stop_next_and_resume(tmp_path,monkeypatch):
 from types import SimpleNamespace
 monkeypatch.setattr(m,'signature',lambda:'frozen')
 monkeypatch.setattr(m,'manifest',lambda source:[{'url':'first','item':{}},{'url':'second','item':{}}])
 calls=[]
 def run(command,**kwargs):
  doc=Path(command[command.index('--one')+1]);e=m.read(doc/'input.json');calls.append(e['url'])
  if e['url']=='first':raise subprocess.TimeoutExpired(command,1)
  m.save(doc/'result.json',dict(status='NO_ROWS',rows=0,url=e['url']))
 monkeypatch.setattr(m.subprocess,'run',run)
 a=SimpleNamespace(run=str(tmp_path),source='NBS',retry_from=None,timeout=1)
 m.work(a);p=m.read(tmp_path/'nbs/progress.json')
 assert p['processed']==2 and p['counts']=={'TIMEOUT':1,'NO_ROWS':1}
 m.work(a);assert calls==['first','second']
def test_error_is_recorded(tmp_path):
 m.execute_document('PBOC',{'url':'bad','item':{'artifact':{}}},tmp_path)
 result=m.read(tmp_path/'result.json');assert result['status']=='FAILED' and 'traceback' in result
