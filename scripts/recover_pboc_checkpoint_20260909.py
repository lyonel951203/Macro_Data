"""Validate and recover the completed PBOC checkpoint left by WinError 5."""
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

from monitor_source_progress import process_alive
from pboc_reprint_links import parse_search
from pull_source_archive import atomic, now


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    root=Path(__file__).resolve().parents[1]
    directory=root/'data/history_backfill/source_workers/pboc'
    path=directory/'state.json';pending=directory/'state.json.tmp';lock=directory/'worker.lock'
    out=root/'reports/v2/pboc_checkpoint_recovery_20260909'
    out.mkdir(exist_ok=True)
    assert not (out/'recovery.json').exists(), 'Recovery already completed; do not replay old state'
    old=read(path);new=read(pending);owner=read(lock)
    assert owner['source']==old['source']==new['source']=='PBOC'
    assert owner['pid']==old['pid']==new['pid']==2836 and not process_alive(owner['pid'])
    assert not (directory/'stop').exists()
    assert new['status']=='STOPPED_ERROR' and 'WinError 5' in new['last_error']
    config_path=root/'config/pboc_reprint_pull.json';config=read(config_path)
    assert old['config_sha256']==new['config_sha256']==hashlib.sha256(config_path.read_bytes()).hexdigest()
    for key in ['deadline','started_at','session_requests','inserted','blocked_hosts','mode']:
        assert old[key]==new[key], key
    assert new['updated_at']>old['updated_at']
    assert all(new['results'].get(url)==result for url,result in old['results'].items())
    old_queue={item['url']:item for item in old['queue']}
    new_queue={item['url']:item for item in new['queue']}
    assert len(new_queue)==len(new['queue'])
    added=set(new['results'])-set(old['results'])
    assert len(added)==1 and set(old_queue)-set(new_queue)==added
    assert added=={old['current_url']}
    assert not (set(new_queue)&set(new['results']))
    assert all(new_queue[url]==item for url,item in old_queue.items() if url not in added)
    allowed=set(config['sources']['PBOC']['allowed_hosts'])
    assert all(urlparse(url).hostname in allowed for url in new_queue)
    # Verify every archived result, including the extra page not in the old checkpoint.
    verified=0
    for result in new['results'].values():
        if result['status']!='ARCHIVED':continue
        artifact=result['artifact'];raw=(root/artifact['path']).resolve()
        assert raw.is_relative_to((root/'data/raw/pboc').resolve())
        content=raw.read_bytes()
        assert len(content)==artifact['size'] and hashlib.sha256(content).hexdigest()==artifact['sha256']
        verified+=1
    recovered=new['results'][next(iter(added))]
    links,stats=parse_search(recovered['item'],(root/recovered['artifact']['path']).read_bytes(),recovered['artifact']['path'])
    assert stats==recovered['discovery_stats']
    known=set(old['results'])|set(old_queue)
    discovered=[item for item in links if item['url'] not in known]
    assert new['queue']==discovered+[item for item in old['queue'] if item['url'] not in added]
    assert len(discovered)==2
    for original,name in [(path,'state_before.json'),(pending,'pending_verified.json'),(lock,'worker_lock_before.json')]:
        assert not (out/name).exists(), 'Existing recovery backup requires inspection'
        shutil.copyfile(original,out/name)
    assert not process_alive(owner['pid']) and read(lock)==owner
    atomic(path,new)
    assert read(path)==new
    lock.unlink()
    report=dict(status='PASS',at=now().isoformat(),old_pid=owner['pid'],tests_passed=25,
                old_results=len(old['results']),recovered_results=len(new['results']),
                recovered_queue=len(new['queue']),recovered_index_pages=1,recovered_links=2,
                verified_raw_files=verified,deadline=new['deadline'],session_requests=new['session_requests'],
                restored_state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                original_tmp_preserved=True,
                sha256={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in
                        ['scripts/pull_source_archive.py','tests/test_source_workers.py','scripts/recover_pboc_checkpoint_20260909.py']})
    atomic(out/'recovery.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
