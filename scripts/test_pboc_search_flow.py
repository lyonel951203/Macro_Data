"""Test year-filtered MOF discovery and a discovered article before enabling it."""
from dataclasses import asdict
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from macro_pit.sources.base import decode_content
from pull_source_archive import ROOT,Worker,WorkerClient,atomic,now
from pboc_reprint_links import search_item,parse_search

def main(allow_network=False):
    os.chdir(ROOT)
    assert not (ROOT/'data/history_backfill/nbs_price_batch.lock').exists()
    for source in ['pboc','safe']:assert not (ROOT/f'data/history_backfill/source_workers/{source}/worker.lock').exists()
    out=ROOT/'reports/v2/pboc_reprints'
    w=Worker('PBOC',allow_network);usage=json.loads((out/'tested_usage.json').read_text(encoding='utf-8'))
    w.state.update(usage);w.policy['max_retries']=0
    w.save=lambda:atomic(out/'tested_usage.json',dict(session_requests=w.state['session_requests'],last_request_at=w.state.get('last_request_at')))
    queue=[search_item('金融运行',2005),search_item('金融统计',2010)]
    results=[];clients={};article_added=False;page_added=False
    lock=w.directory/'source_test.lock'
    with lock.open('x') as f:json.dump({'pid':os.getpid()},f)
    try:
        while queue:
            item=queue.pop(0);host=urlparse(item['url']).hostname
            client=clients.setdefault(host,None)
            if client is None:client=clients[host]=WorkerClient(w,host)
            offset=len(client.events)
            try:
                fetched=client.fetch(item['url'])
                if item['kind']=='index':
                    links,stats=parse_search(item,fetched.content,fetched.artifact.path)
                    if item['year']==2010:assert stats['total_hits']>0,'Positive control should find 2010 releases'
                    for link in links:
                        if link['kind']=='article' and not article_added:
                            queue.append(link);article_added=True
                        elif link['kind']=='index' and not page_added:
                            queue.append(link);page_added=True
                else:
                    text=BeautifulSoup(decode_content(fetched.content),'lxml').get_text(' ',strip=True)
                    assert ('人民银行' in text or '央行' in text) and any(x in text for x in ['货币','贷款','存款'])
                    stats={'body_validated':True}
                results.append(dict(item=item,status='PASS',artifact=asdict(fetched.artifact),stats=stats))
            except Exception as exc:
                results.append(dict(item=item,status='FAILED',error=f'{type(exc).__name__}: {exc}'))
            finally:
                with (w.directory/'crawl_events.jsonl').open('a',encoding='utf-8') as f:
                    for event in client.events[offset:]:f.write(json.dumps(asdict(event),default=str)+'\n')
                atomic(out/'search_flow_tests.json',dict(at=now().isoformat(),results=results))
                print(json.dumps({k:v for k,v in results[-1].items() if k!='artifact'},ensure_ascii=False),flush=True)
        assert article_added and all(r['status']=='PASS' for r in results),'Source flow not ready'
    finally:
        for client in clients.values():client.close()
        lock.unlink()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network',action='store_true')
    main(parser.parse_args().allow_network)
