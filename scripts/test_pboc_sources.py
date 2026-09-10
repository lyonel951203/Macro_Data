"""Finite foreground source tests, with background crawlers stopped."""
from dataclasses import asdict
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from macro_pit.sources.base import decode_content
from pull_source_archive import ROOT,Worker,WorkerClient,atomic,now

CASES=[
 ('article','https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/jjckb/201001/t20100118_261144.htm'),
 ('index','https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/jjckb/'),
 ('search','https://search.mof.gov.cn/was5/web/search?channelid=295890&searchword=%E9%87%91%E8%9E%8D%E7%BB%9F%E8%AE%A1&searchscope=doctitle&perpage=10&page=1')]

def main():
    os.chdir(ROOT)
    for lock in ['data/history_backfill/nbs_price_batch.lock',
                 'data/history_backfill/source_workers/safe/worker.lock',
                 'data/history_backfill/source_workers/pboc/worker.lock']:
        assert not Path(lock).exists(),f'Stop background task first: {lock}'
    w=Worker('PBOC',True)
    out=ROOT/'reports/v2/pboc_reprints';out.mkdir(parents=True,exist_ok=True)
    prior=out/'probe_state.json'
    if prior.exists():
        old=json.loads(prior.read_text(encoding='utf-8'))
        w.state['session_requests']=max(w.state['session_requests'],old['session_requests'])
        w.state['last_request_at']=max(w.state.get('last_request_at',''),old.get('last_request_at',''))
    w.policy['max_retries']=0
    w.save=lambda:atomic(out/'tested_usage.json',dict(session_requests=w.state['session_requests'],last_request_at=w.state.get('last_request_at')))
    clients={};results=[]
    lock=w.directory/'source_test.lock'
    with lock.open('x') as f:json.dump({'pid':os.getpid()},f)
    try:
        for kind,url in CASES:
            host=urlparse(url).hostname
            client=clients.setdefault(host,None)
            if client is None:client=clients[host]=WorkerClient(w,host)
            offset=len(client.events)
            try:
                fetched=client.fetch(url)
                soup=BeautifulSoup(decode_content(fetched.content),'lxml')
                body=soup.get_text(' ',strip=True)
                good=('2009年' in body and '3798' in body and '27.68' in body) if kind=='article' else bool(soup.find_all('a',href=True))
                results.append(dict(kind=kind,url=url,status='PASS' if good else 'CONTENT_REVIEW_REQUIRED',artifact=asdict(fetched.artifact),title=soup.title.get_text() if soup.title else '',text_excerpt=body[:250]))
            except Exception as exc:
                results.append(dict(kind=kind,url=url,status='FAILED',error=f'{type(exc).__name__}: {exc}'))
            finally:
                with (w.directory/'crawl_events.jsonl').open('a',encoding='utf-8') as f:
                    for event in client.events[offset:]:f.write(json.dumps(asdict(event),default=str)+'\n')
                atomic(out/'source_tests.json',dict(at=now().isoformat(),results=results))
                print(json.dumps(results[-1],ensure_ascii=False,default=str),flush=True)
    finally:
        for client in clients.values():client.close()
        lock.unlink()

if __name__=='__main__':main()
