"""Bounded live replay of the failed NBS page, isolated from production state/DB."""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlparse

from macro_pit.config import source_policy
from macro_pit.http import PoliteHttpClient
from macro_pit.nbs_search import discover_nbs_legacy
from macro_pit.timeutils import SHANGHAI
from monitor_source_progress import process_alive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network', action='store_true', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state_path = root / 'data/history_backfill/pit_history_autorun.json'
    worker = json.loads(state_path.read_text(encoding='utf-8'))
    assert not process_alive(worker.get('pid')), 'Stop NBS before a live source test'
    assert not (root / 'data/history_backfill/nbs_price_batch.lock').exists()
    out = root / 'reports/v2/nbs_search_recovery_20260909'
    out.mkdir(exist_ok=True)
    source_state = root / 'reports/v2/pit_history_autorun/discovery/2014_3/search_state.json'
    cache_path = root / 'data/http_cache/nbs/cb6273f3e9148d5c901852e31ed20b3435b22cd268a1e75b7121d1835efa34ee.json'
    for original, name in [(state_path, 'worker_before.json'), (source_state, 'search_before.json'),
                           (cache_path, 'cache_before.json')]:
        if not (out / name).exists():
            shutil.copyfile(original, out / name)
    cache = json.loads((out / 'cache_before.json').read_text(encoding='utf-8'))
    params = parse_qs(urlparse(cache['url']).query, keep_blank_values=True)
    assert params['qt'] == ['经济运行'] and params['page'] == ['9']
    test_state = out / 'search_state.json'
    if not test_state.exists():
        shutil.copyfile(source_state, test_state)
    policy = dict(source_policy('NBS'))
    policy.update(max_requests_per_run=3, max_retries=0)
    client = PoliteHttpClient(source='NBS', policy=policy, allow_network=args.allow_network)
    report = dict(at=datetime.now(SHANGHAI).isoformat(), status='FAIL', request=params)
    try:
        result = discover_nbs_legacy(
            out / 'probe.duckdb', terms=['经济运行'], start_date='2014-01-01', end_date='2014-12-31',
            state_path=test_state, output_dir=out / 'candidates', allow_network=True,
            max_network_pages=1, client=client,
        )
        item = result['items']['经济运行']
        report.update(search_status=result['status'], last_page=item.get('last_page'),
                      next_page=item['next_page'], total_hits=item.get('total_hits'),
                      last_current_hits=item.get('last_current_hits'), last_error=result.get('last_error'))
        assert item.get('last_page') == 9 and item['next_page'] == 10, report
        assert not item.get('empty_query_retry'), report
        assert source_state.read_bytes() == (out / 'search_before.json').read_bytes()
        assert state_path.read_bytes() == (out / 'worker_before.json').read_bytes()
        report['status'] = 'PASS'
    finally:
        report['events'] = [asdict(event) for event in client.events]
        client.close()
        (out / 'live_probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'events'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
