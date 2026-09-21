"""Offline, resumable archive replay. Per-document isolation; no database writes."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time,traceback
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from macro_pit.fileio import atomic_write_text
from macro_pit.timeutils import SHANGHAI

def save(p,x):atomic_write_text(p,json.dumps(x,ensure_ascii=False,indent=2,default=str))
def now():return datetime.now(SHANGHAI).isoformat()
def signature():
 files=sorted((ROOT/'src/macro_pit').rglob('*.py'))+sorted((ROOT/'scripts').glob('*.py'))
 return hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+p.read_bytes() for p in files)).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def execute_document(source,entry,out):
 from macro_pit.archive import RawArtifact,UrlCache
 from macro_pit.sources.cn_nbs import NBSSource
 from macro_pit.sources.cn_pboc import PBOCSource
 from macro_pit.sources.cn_safe import SAFESource
 import pandas as pd
 parser=None
 try:
  item=entry['item'];url=entry['url']
  if source=='NBS':
   c=UrlCache().get(source,url);assert c and c['raw_sha256']==item['raw_sha256'],'archive_metadata_mismatch'
   a=dict(source=source,url=url,path=item['raw_file'],sha256=item['raw_sha256'],content_type=c['content_type'],retrieved_at=c['retrieved_at'],size=c['size'])
  else:a=item['artifact'].copy()
  a['retrieved_at']=datetime.fromisoformat(a['retrieved_at']);art=RawArtifact(**a)
  content=Path(art.path).read_bytes()
  assert len(content)==art.size and hashlib.sha256(content).hexdigest()==art.sha256,'archive_integrity_failed'
  cls={'NBS':NBSSource,'PBOC':PBOCSource,'SAFE':SAFESource}[source];parser=cls(allow_network=False)
  method={'NBS':'parse','PBOC':'parse_article','SAFE':'parse_release'}[source]
  primary_error=None;fallback_used=False
  try:rows=getattr(parser,method)(content,art)
  except Exception as exc:
   primary_error=dict(error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
   from archive_format_fallbacks import parse as fallback
   try:rows=fallback(source,content,art);fallback_used=True
   except Exception as secondary:
    save(out/'primary_error.json',primary_error)
    raise ValueError(f'Primary: {primary_error["error_type"]}: {primary_error["error"]}; fallback: {type(secondary).__name__}: {secondary}') from secondary
  result=dict(status='PARSED_CANDIDATES' if rows else 'NO_ROWS',rows=len(rows),raw_file=art.path,raw_sha256=art.sha256,hash_verified=True,fallback_used=fallback_used,primary_error=primary_error)
  if rows:
   for row in rows:row['review_status']='UNVERIFIED_PARSER_CANDIDATE'
   pd.DataFrame(rows).to_parquet(out/'candidates.parquet',index=False)
  save(out/'result.json',dict(**result,url=url,finished_at=now()))
 except Exception as exc:
  save(out/'result.json',dict(status='FAILED',rows=0,url=entry['url'],error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc(),finished_at=now()))
 finally:
  if parser:parser.close()
def manifest(source):
 p=ROOT/('data/history_backfill/pit_history_autorun.json' if source=='NBS' else f'data/history_backfill/source_workers/{source.lower()}/state.json')
 state=read(p);entries=state['articles'] if source=='NBS' else state['results']
 return [dict(url=url,item=item) for url,item in entries.items() if ('raw_file' in item if source=='NBS' else item.get('status')=='ARCHIVED' and item['item']['kind']=='article')]
def work(args):
 out=Path(args.run).resolve()/args.source.lower();out.mkdir(parents=True,exist_ok=True)
 sig=signature();meta=out/'manifest.json'
 if meta.exists():
  frozen=read(meta);assert frozen['parser_sha256']==sig,'Parser changed: create a new run; use --retry-from for failures.'
  entries=frozen['entries']
 else:
  entries=manifest(args.source)
  if args.retry_from:
   prior=Path(args.retry_from)/args.source.lower()
   failed={read(p)['url'] for p in prior.glob('documents/*/result.json') if read(p)['status'] in {'FAILED','TIMEOUT','NO_ROWS'}}
   entries=[e for e in entries if e['url'] in failed]
  save(meta,dict(source=args.source,parser_sha256=sig,entries=entries,created_at=now(),retry_from=args.retry_from))
 counts={};done=0;rows=0
 def progress(status,current=None):
  save(out/'progress.json',dict(source=args.source,status=status,pid=os.getpid(),total=len(entries),processed=done,candidate_rows=rows,counts=counts,current_url=current,updated_at=now(),parser_sha256=sig,production_writes=0,network_requests=0))
 progress('RUNNING')
 for e in entries:
  key=hashlib.sha256(e['url'].encode()).hexdigest();doc=out/'documents'/key;doc.mkdir(parents=True,exist_ok=True)
  rp=doc/'result.json'
  if not rp.exists():
   save(doc/'input.json',e);progress('RUNNING',e['url'])
   command=[sys.executable,str(Path(__file__).resolve()),'--one',str(doc),'--source',args.source]
   with (doc/'stdout.log').open('wb') as stdout,(doc/'stderr.log').open('wb') as stderr:
    try:
     subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,timeout=args.timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
    except subprocess.TimeoutExpired:
     save(rp,dict(status='TIMEOUT',rows=0,url=e['url'],error_type='DocumentTimeout',error=f'Exceeded {args.timeout}s',finished_at=now()))
   if not rp.exists():save(rp,dict(status='FAILED',rows=0,url=e['url'],error_type='ChildProcessFailed',error='See stderr.log',finished_at=now()))
  result=read(rp);status=result['status'];done+=1;rows+=result.get('rows',0);counts[status]=counts.get(status,0)+1
  if status in {'FAILED','TIMEOUT','NO_ROWS'}:
   with (out/'failures.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(**result,document_dir=str(doc)),ensure_ascii=False)+'\n')
  progress('RUNNING')
 progress('FINALIZING')
 # One row per document, failure groups and combined candidates are convenience outputs.
 import pandas as pd
 results=[dict(**read(p),document_dir=str(p.parent)) for p in out.glob('documents/*/result.json')]
 if results:
  frame=pd.DataFrame(results);frame.to_csv(out/'articles.csv',index=False,encoding='utf-8-sig')
  bad=frame[frame.status.isin(['FAILED','TIMEOUT','NO_ROWS'])];bad.to_csv(out/'failed_articles.csv',index=False,encoding='utf-8-sig')
  if len(bad):bad.groupby(['status','error_type','error'],dropna=False).size().reset_index(name='articles').to_csv(out/'failure_groups.csv',index=False,encoding='utf-8-sig')
 parts=[pd.read_parquet(p.parent/'candidates.parquet') for p in out.glob('documents/*/result.json') if read(p)['status']=='PARSED_CANDIDATES']
 if parts:pd.concat(parts,ignore_index=True).to_parquet(out/'unverified_candidates.parquet',index=False)
 progress('REPLAY_COMPLETE_REVIEW_PENDING')
def main():
 os.chdir(ROOT);p=argparse.ArgumentParser();p.add_argument('--source',choices=['NBS','PBOC','SAFE'],required=True);p.add_argument('--run');p.add_argument('--retry-from');p.add_argument('--one');p.add_argument('--timeout',type=int,default=90);a=p.parse_args()
 if a.one:
  out=Path(a.one);execute_document(a.source,read(out/'input.json'),out)
 else:
  assert a.run
  try:work(a)
  except Exception:
   out=Path(a.run)/a.source.lower();out.mkdir(parents=True,exist_ok=True)
   save(out/'fatal.json',dict(status='WORKER_FAILED',pid=os.getpid(),at=now(),traceback=traceback.format_exc()));raise
if __name__=='__main__':main()
