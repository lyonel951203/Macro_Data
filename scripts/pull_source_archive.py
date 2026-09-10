"""Independent source workers: archive raw evidence, never open the main database.

Dedicated ledgers prevent cross-source JSON races. Daily usage includes the
legacy shared ledger plus this worker's ledger; only one worker per source runs.
"""
import argparse
from dataclasses import asdict
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import random
import time
import tempfile
from urllib.parse import urljoin,urlparse
from bs4 import BeautifulSoup
import httpx
from macro_pit.config import source_policy
from macro_pit.errors import CrawlSafetyError
from macro_pit.http import PoliteHttpClient
from macro_pit.sources.base import decode_content
from macro_pit.timeutils import SHANGHAI

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/history_backfill/source_workers'


def now(): return datetime.now(SHANGHAI)


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(value,ensure_ascii=False,indent=2,default=str)
    # Readers and virus scanners on Windows can briefly deny replacement.
    # Keep a complete, unique recovery file if bounded retries are exhausted.
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                     prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
        temporary=Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    for attempt in range(8):
        try:
            os.replace(temporary,path)
            return
        except OSError as exc:
            if getattr(exc,'winerror',None) not in {5,32,33} or attempt==7:
                raise
            time.sleep(min(0.05*(2**attempt),1.0))


def read_usage(path,source):
    return int(json.loads(path.read_text(encoding='utf-8')).get(source,0)) if path.exists() else 0


def initial_queue(source,spec):
    queue=[dict(s) for s in spec['seeds']]
    if source=='SAFE':
        for page in range(spec['index_pages_descending_from'],1,-1):
            queue.append(dict(url=f'https://www.safe.gov.cn/safe/sjjd/index_{page}.html',title=f'SAFE historical listing {page}',
                              kind='index',evidence='Bounded pagination from official first-page tail link'))
        queue.append(dict(url='https://www.safe.gov.cn/safe/sjjd/index.html',title='SAFE listing first page',kind='index',evidence='Official listing'))
    return queue


def discovered_links(source,item,content,raw_file,allowed_hosts):
    soup=BeautifulSoup(decode_content(content),'lxml'); found={}
    for a in soup.find_all('a',href=True):
        url=urljoin(item['url'],a['href']).split('#')[0]
        parsed=urlparse(url); title=' '.join(a.get_text(' ',strip=True).split())
        if parsed.scheme not in {'https','http'} or parsed.hostname not in allowed_hosts or parsed.query: continue
        if source=='SAFE':
            if not re.fullmatch(r'/safe/20\d{2}/\d{4}/\d+\.html',parsed.path): continue
            if not any(x in title for x in ['银行结售汇','银行代客结售汇','涉外收付款','外汇储备']): continue
        else:
            # Government copies are a sealed seed list; broad government navigation is not crawled.
            if parsed.hostname!='www.pbc.gov.cn' or not parsed.path.startswith('/english/'): continue
            if not any(x in title.lower() for x in ['financial statistics','financial industry','aggregate financing','money supply','financing to the real economy']): continue
        found[url]=dict(url=url,title=title,kind='article',evidence=raw_file,discovered_from=item['url'])
    return sorted(found.values(),key=lambda x:x['url'])


class WorkerClient(PoliteHttpClient):
    def __init__(self,owner,host):
        self.owner=owner
        policy=dict(owner.policy,allowed_hosts=[host])
        # A MOF-hosted copy retains MOF's slower host pacing as well.
        if host=='www.mof.gov.cn':
            policy['min_interval_seconds']=max(policy['min_interval_seconds'],75)
            policy['jitter_seconds']=max(policy['jitter_seconds'],30)
        super().__init__(source=owner.source,policy=policy,allow_network=owner.allow_network,budget_root=owner.directory/'budget')

    def _reserve_budget(self):
        worker=self.owner
        day=now().date().isoformat()
        legacy=read_usage(ROOT/'data/audit/request_budget'/f'{day}.json',worker.source)
        owned=read_usage(worker.directory/'budget'/f'{day}.json',worker.source)
        daily_limit=worker.policy['max_requests_per_day']
        run_limit=worker.policy['max_requests_per_run']
        if daily_limit is not None and legacy+owned>=int(daily_limit):
            raise CrawlSafetyError(f'{worker.source} combined daily request budget exhausted')
        if run_limit is not None and worker.state['session_requests']>=int(run_limit):
            raise CrawlSafetyError(f'{worker.source} shared per-run request budget exhausted')
        if worker.state.get('last_request_at'):
            interval=random.uniform(worker.policy['min_interval_seconds'],worker.policy['min_interval_seconds']+worker.policy['jitter_seconds'])
            delay=interval-(now()-datetime.fromisoformat(worker.state['last_request_at'])).total_seconds()
            if delay>0:time.sleep(delay)
        super()._reserve_budget()
        worker.state['session_requests']+=1
        worker.state['last_request_at']=now().isoformat()
        worker.save()


class Worker:
    def __init__(self,source,allow_network):
        self.source=source;self.allow_network=allow_network
        dedicated=ROOT/'config/pboc_reprint_pull.json'
        self.config_path=dedicated if source=='PBOC' and dedicated.exists() else ROOT/'config/source_pull_tasks.json'
        self.config=json.loads(self.config_path.read_text(encoding='utf-8'))
        self.spec=self.config['sources'][source];self.policy=source_policy(source)
        self.directory=BASE/source.lower();self.path=self.directory/'state.json'
        self.clients={}
        self.state=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(
            queue=initial_queue(source,self.spec),results={},blocked_hosts={},session_requests=0,inserted=0)
        self.state['source']=source

    def save(self):
        self.state['updated_at']=now().isoformat()
        atomic(self.path,self.state)

    def stop_requested(self):
        return (self.directory/'stop').exists() or now()>=datetime.fromisoformat(self.state['deadline'])

    def wait_budget(self):
        # A reviewed policy change can resolve an old wait without resetting usage.
        if all(self.policy[key] is None for key in ('max_requests_per_day','max_requests_per_run')):
            self.state.pop('resume_at',None)
            if 'budget exhausted' in self.state.get('last_error',''):
                self.state.pop('last_error')
            return True
        self.state['status']='WAITING_NEXT_DAY_BUDGET'
        self.state.setdefault('resume_at',datetime.combine(now().date()+timedelta(days=1),datetime.min.time(),tzinfo=SHANGHAI).isoformat())
        while now()<datetime.fromisoformat(self.state['resume_at']):
            if self.stop_requested(): return False
            self.save();time.sleep(30)
        for client in self.clients.values():client.close()
        self.clients={};self.state['session_requests']=0
        self.state.pop('resume_at',None);self.state.pop('last_error',None)
        return True

    def run(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        lock=self.directory/'worker.lock'
        with lock.open('x',encoding='utf-8') as handle: json.dump(dict(pid=os.getpid(),source=self.source),handle)
        try:
            digest=hashlib.sha256(self.config_path.read_bytes()).hexdigest()
            assert self.state.get('config_sha256',digest)==digest,'Queue config changed; review checkpoint before migration'
            if self.state.get('status') in {'SOURCE_BLOCKED','QUEUE_COMPLETE_WITH_BLOCKED_ROUTES'}:
                raise RuntimeError('Blocked routes require review; no automatic retry')
            self.state.update(pid=os.getpid(),config_sha256=digest,mode='RAW_ONLY_NO_MAIN_DB_WRITES')
            self.state.setdefault('started_at',now().isoformat())
            self.state.setdefault('deadline',(now()+timedelta(days=self.config['max_days'])).isoformat())
            if self.state.get('resume_at') and not self.wait_budget():
                self.state['status']='STOPPED';return
            while self.state['queue']:
                if self.stop_requested(): self.state['status']='STOPPED';return
                item=self.state['queue'][0];url=item['url'];host=urlparse(url).hostname
                assert host in self.spec['allowed_hosts']
                if url in self.state['results']:
                    self.state['queue'].pop(0);continue
                if host in self.state['blocked_hosts']:
                    self.state['results'][url]=dict(status='SKIPPED_BLOCKED_HOST',item=item)
                    self.state['queue'].pop(0);continue
                self.state.update(status='RUNNING',current_url=url,current_title=item['title'])
                self.save()
                client=self.clients.setdefault(host,None)
                if client is None:
                    client=self.clients[host]=WorkerClient(self,host)
                offset=len(client.events)
                try:
                    fetched=client.fetch(url,refresh=False)
                    artifact=asdict(fetched.artifact)
                    self.state['results'][url]=dict(status='ARCHIVED',item=item,artifact=artifact,from_cache=fetched.from_cache,
                        hosting_organization=host,statistical_source=self.source,pit_review='PENDING',at=now().isoformat())
                    self.state['queue'].pop(0)
                    if 'html' in fetched.artifact.content_type.lower():
                        if self.source=='PBOC' and item.get('discovery')=='mof_search':
                            from pboc_reprint_links import parse_search
                            try:
                                links,stats=parse_search(item,fetched.content,fetched.artifact.path)
                                self.state['results'][url]['discovery_stats']=stats
                            except ValueError as exc:
                                links=[]
                                self.state['results'][url]['discovery_review']=str(exc)
                        else:
                            links=discovered_links(self.source,item,fetched.content,fetched.artifact.path,set(self.spec['allowed_hosts']))
                        known=set(self.state['results'])|{x['url'] for x in self.state['queue']}
                        new=[x for x in links if x['url'] not in known]
                        remaining=self.config['max_urls_per_source']-len(known)
                        if len(new)>max(0,remaining): self.state['queue_limit_reached']=True
                        self.state['queue'][0:0]=new[:max(0,remaining)]
                    self.state.pop('last_error',None)
                except CrawlSafetyError as exc:
                    self.state['last_error']=str(exc)
                    if 'budget exhausted' in str(exc):
                        self.save()
                        if not self.wait_budget():self.state['status']='STOPPED';return
                    else:
                        self.state['blocked_hosts'][host]=str(exc)
                        self.state['results'][url]=dict(status='ROUTE_BLOCKED',item=item,error=str(exc))
                        self.state['queue'].pop(0)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {404,410}: raise
                    self.state['results'][url]=dict(status='HTTP_NOT_FOUND',item=item,error=str(exc))
                    self.state['queue'].pop(0)
                finally:
                    if client.events[offset:]:
                        with (self.directory/'crawl_events.jsonl').open('a',encoding='utf-8') as log:
                            for event in client.events[offset:]: log.write(json.dumps(asdict(event),ensure_ascii=False,default=str)+'\n')
                    self.save()
            self.state['status']='QUEUE_COMPLETE_WITH_BLOCKED_ROUTES' if self.state['blocked_hosts'] else 'RAW_QUEUE_COMPLETE_REVIEW_PENDING'
            if self.state['blocked_hosts'] and not any(r['status']=='ARCHIVED' for r in self.state['results'].values()):
                self.state['status']='SOURCE_BLOCKED'
        except Exception as exc:
            self.state.update(status='STOPPED_ERROR',last_error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            try:
                for client in self.clients.values():client.close()
                self.save()
            finally:
                # A checkpoint failure must not leave a dead worker lock behind.
                lock.unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,choices=['PBOC','SAFE'])
    p.add_argument('--allow-network',action='store_true')
    args=p.parse_args();os.chdir(ROOT);Worker(args.source,args.allow_network).run()
