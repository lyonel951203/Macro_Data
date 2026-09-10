"""Migrate only the stopped PBOC queue after actual source flow tests pass."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from pull_source_archive import ROOT,atomic,now
from pboc_reprint_links import TERMS,parse_search,search_item
from monitor_source_progress import process_alive

def main():
    out=ROOT/'reports/v2/pboc_reprints';directory=ROOT/'data/history_backfill/source_workers/pboc'
    state_path=directory/'state.json';state=json.loads(state_path.read_text(encoding='utf-8'))
    for path in [ROOT/'data/history_backfill/nbs_price_batch.lock',ROOT/'data/history_backfill/source_workers/safe/worker.lock',directory/'worker.lock',directory/'source_test.lock']:
        assert not path.exists(),f'Stop all workers/tests first: {path}'
    assert not process_alive(state.get('pid'))
    base=ROOT/'config/source_pull_tasks.json';config_path=ROOT/'config/pboc_reprint_pull.json'
    assert not config_path.exists(),'Existing reprint config requires a new reviewed migration'
    assert state['config_sha256']==hashlib.sha256(base.read_bytes()).hexdigest()
    flow=json.loads((out/'search_flow_tests.json').read_text(encoding='utf-8'))
    assert flow['results'] and all(r['status']=='PASS' for r in flow['results'])
    assert any(r['item']['kind']=='article' for r in flow['results'])
    tests=json.loads((out/'source_tests.json').read_text(encoding='utf-8'))
    required=[r for r in tests['results'] if r['kind'] in {'article','search'}]
    assert len(required)==2 and all(r['status']=='PASS' for r in required)
    for r in flow['results']+required:
        artifact=r['artifact']
        assert hashlib.sha256((ROOT/artifact['path']).read_bytes()).hexdigest()==artifact['sha256']
    cfg=json.loads(base.read_text(encoding='utf-8'))
    cfg['sources']={'PBOC':{'allowed_hosts':['www.mof.gov.cn','search.mof.gov.cn'],
        'note':'Verified MOF reprints and official year-filtered search; raw-only; original/hosting dates reviewed separately.',
        'seeds':[]}}
    seeds=[]
    for r in required:
        if r['kind']=='article':seeds.append(dict(url=r['url'],title=r['title'].strip(),kind='article',evidence=str(out/'source_tests.json')))
        else:
            item=dict(url=r['url'],kind='index',discovery='mof_search',term='金融统计',year=None,page=1)
            links,stats=parse_search(item,(ROOT/r['artifact']['path']).read_bytes(),r['artifact']['path'])
            seeds.extend(x for x in links if x['kind']=='article')
    seeds.extend(search_item(term,year) for year in range(2005,2027) for term in TERMS)
    unique={x['url']:x for x in seeds}
    cfg['sources']['PBOC']['seeds']=list(unique.values())
    before=out/'before_activation';before.mkdir(exist_ok=False)
    (before/'state.json').write_bytes(state_path.read_bytes())
    (before/'source_pull_tasks.json').write_bytes(base.read_bytes())
    updated=deepcopy(state)
    known=set(updated['results'])|{x['url'] for x in updated['queue']}
    added=[x for x in unique.values() if x['url'] not in known]
    assert added and all(urlparse(x['url']).hostname not in updated['blocked_hosts'] for x in added)
    atomic(config_path,cfg)
    updated['queue'].extend(added)
    updated.update(config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),status='READY_REPRINT_QUEUE',updated_at=now().isoformat())
    usage=json.loads((out/'tested_usage.json').read_text(encoding='utf-8'))
    updated['session_requests']=max(updated['session_requests'],usage['session_requests'])
    updated['last_request_at']=max(updated.get('last_request_at',''),usage.get('last_request_at',''))
    updated.setdefault('migrations',[]).append(dict(at=now().isoformat(),reason='User requested tested alternative sources before restart',added=len(added),tests=str(out/'search_flow_tests.json')))
    atomic(state_path,updated)
    atomic(out/'activation.json',dict(at=now().isoformat(),added_urls=len(added),search_windows=sum(x['kind']=='index' for x in added),
        config_sha256=updated['config_sha256'],preserved_results=len(state['results']),preserved_blocked_hosts=state['blocked_hosts'],
        strict_observations_inserted=0,backup=str(before)))
    print(json.dumps({'added':len(added),'search_windows':sum(x['kind']=='index' for x in added)},indent=2))

if __name__=='__main__':main()
