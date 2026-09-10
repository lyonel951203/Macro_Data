"""Archive a small set of government reprint routes using the PBOC pacing ledger."""
from dataclasses import asdict
import json
import os
from pathlib import Path
from pull_source_archive import Worker,WorkerClient,atomic,now

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
w=Worker('PBOC',True)
assert not (w.directory/'worker.lock').exists(),'PBOC worker already active'
out=ROOT/'reports/v2/pboc_reprints';out.mkdir(parents=True,exist_ok=True)
# Persist probe counts separately; leave the terminal queue and blocked routes intact.
w.save=lambda:atomic(out/'probe_state.json',w.state)
routes=[
 ('www.gov.cn','https://www.gov.cn/gzdt/2012-02/10/content_2063618.htm'),
 ('search.mof.gov.cn','https://search.mof.gov.cn/was5/web/search?channelid=295890&searchword=%E9%87%91%E8%9E%8D%E7%BB%9F%E8%AE%A1&searchscope=doctitle&perpage=10&page=1'),
 ('www.mof.gov.cn','https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/jjckb/201001/t20100118_261144.htm')]
results=[]
for host,url in routes:
    client=WorkerClient(w,host)
    try:
        fetched=client.fetch(url)
        results.append(dict(url=url,status='ARCHIVED',artifact=asdict(fetched.artifact)))
    except Exception as exc:
        results.append(dict(url=url,status='FAILED',error=f'{type(exc).__name__}: {exc}'))
    finally:
        with (w.directory/'crawl_events.jsonl').open('a',encoding='utf-8') as f:
            for event in client.events:f.write(json.dumps(asdict(event),default=str)+'\n')
        client.close()
        atomic(out/'probe.json',dict(at=now().isoformat(),results=results))
        print(json.dumps(results[-1],default=str),flush=True)
