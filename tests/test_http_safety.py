from __future__ import annotations

import random

import httpx
import pytest

from macro_pit.archive import RawArchive, UrlCache
from macro_pit.errors import CrawlSafetyError, NetworkDisabledError
from macro_pit.http import PoliteHttpClient


def policy(**overrides):
    values = {
        "concurrency": 1,
        "user_agent": "macro-pit-test/1",
        "connect_timeout_seconds": 1,
        "read_timeout_seconds": 1,
        "respect_robots_txt": False,
        "min_interval_seconds": 0,
        "jitter_seconds": 0,
        "max_requests_per_run": 5,
        "max_requests_per_day": 5,
        "max_consecutive_failures": 3,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
        "block_statuses": [401, 403, 407, 429],
    }
    values.update(overrides)
    return values


def client(tmp_path, transport, *, allow_network):
    return PoliteHttpClient(
        source="NBS",
        policy=policy(),
        allow_network=allow_network,
        archive=RawArchive(tmp_path / "raw"),
        cache=UrlCache(tmp_path / "cache"),
        budget_root=tmp_path / "budget",
        transport=transport,
        rng=random.Random(1),
    )


def test_network_is_disabled_by_default(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"unexpected"))
    with client(tmp_path, transport, allow_network=False) as http:
        with pytest.raises(NetworkDisabledError):
            http.fetch("https://data.stats.gov.cn/test")


def test_cache_first_archives_and_avoids_second_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b'{"ok":true}', headers={"content-type": "application/json"})

    with client(tmp_path, httpx.MockTransport(handler), allow_network=True) as http:
        first = http.fetch("https://data.stats.gov.cn/test", refresh=True)
        second = http.fetch("https://data.stats.gov.cn/test")
        third = http.fetch("https://data.stats.gov.cn/test", refresh=True)
        assert first.from_cache is False
        assert second.from_cache is True
        assert third.from_cache is True
        assert first.artifact.sha256 == second.artifact.sha256
        assert first.artifact.retrieved_at == third.artifact.retrieved_at
        assert first.artifact.path.endswith(".json")
        assert len(calls) == 2
        assert http.events[0].raw_file == first.artifact.path


def test_form_post_is_cache_first_and_body_is_part_of_cache_key(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.method, request.content))
        return httpx.Response(200, content=b'{"ok":true}', headers={"content-type": "application/json"})

    with client(tmp_path, httpx.MockTransport(handler), allow_network=True) as http:
        first = http.fetch_form("https://data.stats.gov.cn/query/s", {"page": 1, "qt": "CPI"})
        second = http.fetch_form("https://data.stats.gov.cn/query/s", {"qt": "CPI", "page": 1})
        third = http.fetch_form("https://data.stats.gov.cn/query/s", {"page": 2, "qt": "CPI"})

    assert first.from_cache is False
    assert second.from_cache is True
    assert third.from_cache is False
    assert [method for method, _ in calls] == ["POST", "POST"]
    assert b"page=1" in calls[0][1]
    assert "page=1" in http.events[1].url


def test_403_opens_circuit_without_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(403, content=b"blocked")

    with client(tmp_path, httpx.MockTransport(handler), allow_network=True) as http:
        with pytest.raises(CrawlSafetyError, match="HTTP 403"):
            http.fetch("https://data.stats.gov.cn/test", refresh=True)
        with pytest.raises(CrawlSafetyError, match="circuit is open"):
            http.fetch("https://data.stats.gov.cn/other", refresh=True)
    assert len(calls) == 1


def test_404_is_not_retried_and_does_not_open_circuit(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404, content=b"not found")

    with client(tmp_path, httpx.MockTransport(handler), allow_network=True) as http:
        with pytest.raises(httpx.HTTPStatusError):
            http.fetch("https://data.stats.gov.cn/missing-one", refresh=True)
        with pytest.raises(httpx.HTTPStatusError):
            http.fetch("https://data.stats.gov.cn/missing-two", refresh=True)
    assert len(calls) == 2


def test_concurrency_above_one_is_refused(tmp_path):
    with pytest.raises(CrawlSafetyError, match="concurrency"):
        PoliteHttpClient(
            source="NBS",
            policy=policy(concurrency=2),
            allow_network=False,
            budget_root=tmp_path / "budget",
        )


def test_unlimited_counts_keep_ledger_and_http_circuit_breaker(tmp_path):
    import json
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429 if request.url.path=='/blocked' else 200,content=b'ok')
    with client(tmp_path,httpx.MockTransport(handler),allow_network=True) as http:
        http.policy.update(max_requests_per_run=None,max_requests_per_day=None)
        for i in range(8):
            http.fetch(f'https://data.stats.gov.cn/test-{i}')
        with pytest.raises(CrawlSafetyError,match='HTTP 429'):
            http.fetch('https://data.stats.gov.cn/blocked')
        with pytest.raises(CrawlSafetyError,match='circuit is open'):
            http.fetch('https://data.stats.gov.cn/after')
        assert http._request_count==9 and len(calls)==9
    ledger=next((tmp_path/'budget').glob('*.json'))
    assert json.loads(ledger.read_text())['NBS']==9


@pytest.mark.parametrize('limits',[(1,None),(None,1)])
def test_each_remaining_finite_limit_still_enforced(tmp_path,limits):
    with client(tmp_path,httpx.MockTransport(lambda r:httpx.Response(200)),allow_network=True) as http:
        http.policy.update(max_requests_per_run=limits[0],max_requests_per_day=limits[1])
        http._reserve_budget()
        with pytest.raises(CrawlSafetyError,match='budget exhausted'):
            http._reserve_budget()


def test_unlimited_manifest_still_checks_allowed_hosts():
    from macro_pit.pipeline import _validate_manifest
    rules={'allowed_hosts':['www.stats.gov.cn'],'max_requests_per_run':None}
    _validate_manifest(['https://www.stats.gov.cn/x']*1000,rules)
    with pytest.raises(CrawlSafetyError,match='outside configured'):
        _validate_manifest(['https://example.com/x'],rules)


def test_transient_robots_error_retries_and_still_checks_rules(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            if calls.count(str(request.url)) == 1:
                return httpx.Response(503, text="temporary error")
            return httpx.Response(200, text="User-agent: *\nDisallow: /blocked\n")
        return httpx.Response(200, text="ok")

    with client(tmp_path, httpx.MockTransport(handler), allow_network=True) as http:
        http.policy.update(
            respect_robots_txt=True,
            robots_retries=2,
            robots_retry_backoff_seconds=0,
        )
        http.sleep = lambda seconds: None
        assert http.fetch("https://data.stats.gov.cn/allowed").status_code == 200
        with pytest.raises(CrawlSafetyError, match="robots.txt disallows"):
            http.fetch("https://data.stats.gov.cn/blocked")
    assert len([url for url in calls if url.endswith("/robots.txt")]) == 2
    assert not any(url.endswith("/blocked") for url in calls)
