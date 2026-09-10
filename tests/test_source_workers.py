from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pull_source_archive as pull
from macro_pit.errors import CrawlSafetyError
from macro_pit.timeutils import SHANGHAI
from monitor_source_progress import effective_status,process_alive


def test_safe_queue_starts_with_early_samples_then_oldest_indexes():
    q=pull.initial_queue('SAFE',{'seeds':[{'url':'early','kind':'article'}],'index_pages_descending_from':64})
    assert len(q)==65 and q[1]['url'].endswith('index_64.html')
    assert q[-1]['url'].endswith('/index.html') and not any(x['url'].endswith('index_1.html') for x in q)


def test_discovery_rejects_external_hosts_queries_and_irrelevant_links():
    item={'url':'https://www.safe.gov.cn/safe/sjjd/index_64.html'}
    content='''<a href="/safe/2010/0608/4902.html">银行代客结售汇数据</a>
    <a href="https://evil.example/safe/2010/0608/4903.html">外汇储备</a>
    <a href="/safe/2010/0608/4904.html">招聘公告</a>
    <a href="/safe/2010/0608/4905.html?token=x">外汇储备</a>'''.encode()
    found=pull.discovered_links('SAFE',item,content,'raw.html',{'www.safe.gov.cn'})
    assert len(found)==1 and found[0]['evidence']=='raw.html' and found[0]['url'].endswith('/4902.html')


def test_pboc_does_not_follow_blocked_chinese_statistics_paths():
    content='''<a href="/diaochatongjisi/index.html">Financial statistics</a>
    <a href="/english/release/index.html">Financial statistics report</a>'''.encode()
    found=pull.discovered_links('PBOC',{'url':'https://www.pbc.gov.cn/english/x.html'},content,'raw.html',{'www.pbc.gov.cn'})
    assert len(found)==1 and '/english/' in found[0]['url']


@pytest.mark.parametrize('status,alive,age,expected',[
    ('RUNNING',False,0,'PROCESS_EXITED'),('WAITING_NEXT_DAY_BUDGET',True,30,'WAITING_NEXT_DAY_BUDGET'),
    ('RUNNING',True,901,'STALE_HEARTBEAT'),('RAW_QUEUE_COMPLETE_REVIEW_PENDING',False,901,'RAW_QUEUE_COMPLETE_REVIEW_PENDING'),
    ('NOT_STARTED',False,None,'NOT_STARTED')])
def test_monitor_distinguishes_process_death_completion_and_wait(status,alive,age,expected):
    assert effective_status(status,alive,age)==expected


def owner(tmp_path,monkeypatch):
    monkeypatch.setattr(pull,'ROOT',tmp_path)
    return SimpleNamespace(source='SAFE',allow_network=False,directory=tmp_path/'owned',
        policy=dict(concurrency=1,max_requests_per_day=3,max_requests_per_run=3,min_interval_seconds=0,jitter_seconds=0),
        state={'session_requests':0},save=lambda:None)


def test_budget_adds_legacy_and_dedicated_ledgers_without_modifying_legacy(tmp_path,monkeypatch):
    o=owner(tmp_path,monkeypatch);day=datetime.now(SHANGHAI).date().isoformat()
    path=tmp_path/'data/audit/request_budget'/f'{day}.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'SAFE':2,'NBS':184}))
    before=path.read_bytes();client=pull.WorkerClient(o,'www.safe.gov.cn')
    try:
        client._reserve_budget()
        with pytest.raises(CrawlSafetyError,match='combined daily'):client._reserve_budget()
        assert path.read_bytes()==before and o.state['session_requests']==1
    finally:client.close()


def test_multiple_host_clients_share_one_run_budget(tmp_path,monkeypatch):
    o=owner(tmp_path,monkeypatch);o.policy.update(max_requests_per_run=1,max_requests_per_day=100)
    one=pull.WorkerClient(o,'one.example');two=pull.WorkerClient(o,'two.example')
    try:
        one._reserve_budget()
        with pytest.raises(CrawlSafetyError,match='shared per-run'):two._reserve_budget()
    finally:one.close();two.close()


def test_monitor_can_detect_its_own_process():
    import os
    assert process_alive(os.getpid()) and not process_alive(None)


def test_unlimited_workers_keep_usage_across_hosts_and_clear_old_wait(tmp_path,monkeypatch):
    o=owner(tmp_path,monkeypatch)
    o.policy.update(max_requests_per_run=None,max_requests_per_day=None)
    o.state.update(session_requests=500,resume_at='2099-01-01T00:00:00+08:00',
                   last_error='SAFE shared per-run request budget exhausted')
    assert pull.Worker.wait_budget(o)
    assert 'resume_at' not in o.state and 'last_error' not in o.state
    assert o.state['session_requests']==500
    day=datetime.now(SHANGHAI).date().isoformat()
    legacy=tmp_path/'data/audit/request_budget'/f'{day}.json'
    legacy.parent.mkdir(parents=True);legacy.write_text('{"SAFE":900}')
    before=legacy.read_bytes()
    one=pull.WorkerClient(o,'one.example');two=pull.WorkerClient(o,'two.example')
    try:
        one._reserve_budget();two._reserve_budget()
        assert o.state['session_requests']==502
        assert pull.read_usage(o.directory/'budget'/f'{day}.json','SAFE')==2
        assert legacy.read_bytes()==before
    finally:one.close();two.close()


def test_foreground_watch_coexists_with_background_report_writer(tmp_path,monkeypatch):
    import monitor_source_progress as monitor
    lock=tmp_path/'monitor.lock';lock.write_text('{"pid":123}')
    monkeypatch.setattr(monitor,'BASE',tmp_path)
    monkeypatch.setattr(sys,'argv',['monitor','--watch','2','--json'])
    monkeypatch.setattr(monitor,'snapshot',lambda:{'workers':[]})
    monkeypatch.setattr(monitor,'write_report',lambda report:pytest.fail('Foreground watch must not write reports'))
    def interrupt(seconds):raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time,'sleep',interrupt)
    with pytest.raises(KeyboardInterrupt):monitor.main()
    assert lock.exists()


def windows_file_error(code=5):
    error=PermissionError('Windows file replacement denied')
    error.winerror=code
    return error


def test_atomic_retries_transient_windows_denial_without_exposing_partial_state(tmp_path,monkeypatch):
    path=tmp_path/'state.json';path.write_text('{"old":true}')
    original=path.read_bytes();replace=pull.os.replace;calls=[];delays=[]
    def flaky(source,target):
        calls.append(source)
        assert path.read_bytes()==original
        assert json.loads(source.read_text(encoding='utf-8'))=={'new':'complete'}
        if len(calls)<3:raise windows_file_error(32)
        replace(source,target)
    monkeypatch.setattr(pull.os,'replace',flaky)
    monkeypatch.setattr(pull.time,'sleep',delays.append)
    pull.atomic(path,{'new':'complete'})
    assert json.loads(path.read_text())=={'new':'complete'}
    assert len(calls)==3 and delays==[0.05,0.1]
    assert not list(tmp_path.glob('state.json.*.tmp'))


def test_atomic_exhaustion_keeps_old_checkpoint_and_unique_recovery_files(tmp_path,monkeypatch):
    path=tmp_path/'state.json';path.write_text('{"old":true}')
    original=path.read_bytes();calls=[];delays=[]
    def denied(source,target):
        calls.append(source)
        raise windows_file_error()
    monkeypatch.setattr(pull.os,'replace',denied)
    monkeypatch.setattr(pull.time,'sleep',delays.append)
    for sequence in [1,2]:
        with pytest.raises(PermissionError):pull.atomic(path,{'sequence':sequence})
    assert path.read_bytes()==original and len(calls)==16 and len(delays)==14
    pending=list(tmp_path.glob('state.json.*.tmp'))
    assert len(pending)==2
    assert sorted(json.loads(p.read_text())['sequence'] for p in pending)==[1,2]


def test_atomic_does_not_retry_unrelated_io_error(tmp_path,monkeypatch):
    path=tmp_path/'state.json';calls=[]
    def no_space(source,target):
        calls.append(source)
        raise OSError(28,'No space left')
    monkeypatch.setattr(pull.os,'replace',no_space)
    monkeypatch.setattr(pull.time,'sleep',lambda _:pytest.fail('Unrelated IO failures must not retry'))
    with pytest.raises(OSError,match='No space'):pull.atomic(path,{'value':1})
    assert len(calls)==1


def test_worker_releases_lock_even_when_final_checkpoint_fails(tmp_path):
    worker=pull.Worker.__new__(pull.Worker)
    worker.source='PBOC';worker.directory=tmp_path;worker.clients={}
    worker.config_path=tmp_path/'config.json';worker.config_path.write_text('{}')
    worker.config={'max_days':7}
    worker.state=dict(queue=[],results={},blocked_hosts={})
    def denied():raise windows_file_error()
    worker.save=denied
    with pytest.raises(PermissionError):worker.run()
    assert not (tmp_path/'worker.lock').exists()
