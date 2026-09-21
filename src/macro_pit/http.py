from __future__ import annotations

import json
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .archive import RawArchive, RawArtifact, UrlCache
from .errors import CrawlSafetyError, NetworkDisabledError
from .timeutils import SHANGHAI, UTC, ensure_aware


@dataclass
class CrawlEvent:
    crawl_id: str
    source: str
    url: str
    requested_at: datetime
    completed_at: datetime
    http_status: int | None
    success: bool
    from_cache: bool
    content_type: str | None
    response_bytes: int
    raw_file: str | None
    raw_sha256: str | None
    error_type: str | None
    error_message: str | None
    runtime_seconds: float


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    artifact: RawArtifact
    status_code: int
    from_cache: bool


class PoliteHttpClient:
    """Single-threaded, cache-first HTTP client with conservative circuit breakers."""

    def __init__(
        self,
        *,
        source: str,
        policy: dict,
        allow_network: bool = False,
        archive: RawArchive | None = None,
        cache: UrlCache | None = None,
        budget_root: str | Path = "data/audit/request_budget",
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if int(policy.get("concurrency", 1)) != 1:
            raise CrawlSafetyError("government-source concurrency must remain 1")
        self.source = source.upper()
        self.policy = policy
        self.allow_network = allow_network
        self.archive = archive or RawArchive()
        self.cache = cache or UrlCache()
        self.budget_root = Path(budget_root)
        self.sleep = sleep
        self.monotonic = monotonic
        self.rng = rng or random.Random()
        self.events: list[CrawlEvent] = []
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | bool] = {}
        self._request_count = 0
        self._consecutive_failures = 0
        self._circuit_open = False
        timeout = httpx.Timeout(
            connect=float(policy.get("connect_timeout_seconds", 15)),
            read=float(policy.get("read_timeout_seconds", 45)),
            write=float(policy.get("read_timeout_seconds", 45)),
            pool=float(policy.get("connect_timeout_seconds", 15)),
        )
        self._client = httpx.Client(
            headers={"User-Agent": str(policy.get("user_agent", "macro-pit-research/0.1"))},
            follow_redirects=True,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteHttpClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        *,
        refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        return self._fetch(
            url,
            refresh=refresh,
            headers=headers,
            method="GET",
            form_data=None,
            cache_key=url,
        )

    def fetch_form(
        self,
        url: str,
        data: dict[str, str | int],
        *,
        refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """POST a deterministic form while retaining normal crawl safeguards.

        The canonicalized form is part of the cache key so separate search
        pages cannot overwrite one another.  It is also written to the crawl
        event URL, making the archived response reproducible without storing
        request bodies in a separate audit table.
        """
        form_data = {str(key): str(value) for key, value in data.items()}
        cache_key = f"{url}?{urlencode(sorted(form_data.items()))}"
        return self._fetch(
            url,
            refresh=refresh,
            headers=headers,
            method="POST",
            form_data=form_data,
            cache_key=cache_key,
        )

    def _fetch(
        self,
        url: str,
        *,
        refresh: bool,
        headers: dict[str, str] | None,
        method: str,
        form_data: dict[str, str] | None,
        cache_key: str,
    ) -> FetchResult:
        cached = self.cache.get(self.source, cache_key)
        if cached and not refresh:
            cached_result = self._from_cache(cached)
            if cached_result:
                self._record_cache_event(cache_key, cached_result)
                return cached_result
        if not self.allow_network:
            raise NetworkDisabledError(
                "network access is disabled; use archived raw files or explicitly pass --allow-network"
            )
        if self._circuit_open:
            raise CrawlSafetyError(f"{self.source} circuit is open; stop this run and inspect logs")

        if bool(self.policy.get("respect_robots_txt", True)):
            self._assert_robots_allowed(url)

        request_headers: dict[str, str] = dict(headers or {})
        if cached and method == "GET":
            if cached.get("etag"):
                request_headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                request_headers["If-Modified-Since"] = cached["last_modified"]

        max_retries = int(self.policy.get("max_retries", 2))
        for attempt in range(max_retries + 1):
            try:
                response = self._request(
                    url,
                    headers=request_headers,
                    method=method,
                    data=form_data,
                    event_url=cache_key,
                )
                if response.status_code == 304 and cached:
                    cached_result = self._from_cache(cached)
                    if cached_result:
                        self.events[-1].from_cache = True
                        self.events[-1].raw_file = cached_result.artifact.path
                        self.events[-1].raw_sha256 = cached_result.artifact.sha256
                        self._consecutive_failures = 0
                        return cached_result
                    raise CrawlSafetyError("server returned 304 but cached raw file is missing")
                self._check_status(response)
                retrieved_at = datetime.now(UTC)
                artifact = self.archive.store(
                    source=self.source,
                    url=str(response.url),
                    content=response.content,
                    content_type=response.headers.get("content-type"),
                    retrieved_at=retrieved_at,
                )
                self.events[-1].raw_file = artifact.path
                self.events[-1].raw_sha256 = artifact.sha256
                self.events[-1].content_type = artifact.content_type
                self.events[-1].response_bytes = artifact.size
                if cached and cached.get("raw_sha256") == artifact.sha256:
                    # Some official servers ignore conditional headers and return
                    # 200 for unchanged bytes. Preserve the original first-seen
                    # artifact so PIT_D rows remain idempotent.
                    cached["etag"] = response.headers.get("etag") or cached.get("etag")
                    cached["last_modified"] = response.headers.get("last-modified") or cached.get("last_modified")
                    self.cache.put(self.source, cache_key, cached)
                    cached_result = self._from_cache(cached)
                    if cached_result:
                        self.events[-1].from_cache = True
                        self.events[-1].raw_file = cached_result.artifact.path
                        self.events[-1].raw_sha256 = cached_result.artifact.sha256
                        self._consecutive_failures = 0
                        return FetchResult(
                            cached_result.content,
                            cached_result.artifact,
                            response.status_code,
                            True,
                        )
                self.cache.put(
                    self.source,
                    cache_key,
                    {
                        "url": cache_key,
                        "resolved_url": str(response.url),
                        "raw_file": artifact.path,
                        "raw_sha256": artifact.sha256,
                        "content_type": artifact.content_type,
                        "retrieved_at": artifact.retrieved_at.isoformat(),
                        "size": artifact.size,
                        "etag": response.headers.get("etag"),
                        "last_modified": response.headers.get("last-modified"),
                    },
                )
                self._consecutive_failures = 0
                return FetchResult(response.content, artifact, response.status_code, False)
            except CrawlSafetyError:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500:
                    # Retrying a deterministic bad query adds load without any
                    # chance of recovery. Block statuses were already handled
                    # above; ordinary 4xx is returned to the pipeline as a
                    # coverage/query error and does not open the circuit.
                    raise
                self._consecutive_failures += 1
                if self._consecutive_failures >= int(self.policy.get("max_consecutive_failures", 3)):
                    self._circuit_open = True
                    raise CrawlSafetyError(
                        f"{self.source} stopped after {self._consecutive_failures} consecutive failures"
                    ) from exc
                if attempt >= max_retries:
                    raise
                backoff = float(self.policy.get("retry_backoff_seconds", 60)) * (2**attempt)
                self.sleep(backoff + self.rng.uniform(0, float(self.policy.get("jitter_seconds", 10))))
        raise AssertionError("unreachable")

    def _from_cache(self, cached: dict) -> FetchResult | None:
        path = Path(str(cached.get("raw_file", "")))
        if not path.is_file():
            return None
        content = path.read_bytes()
        artifact = RawArtifact(
            source=self.source,
            url=str(cached.get("resolved_url") or cached.get("url")),
            path=path.as_posix(),
            sha256=str(cached["raw_sha256"]),
            content_type=str(cached.get("content_type") or "application/octet-stream"),
            retrieved_at=ensure_aware(str(cached["retrieved_at"])),
            size=len(content),
        )
        return FetchResult(content, artifact, 200, True)

    def _record_cache_event(self, url: str, result: FetchResult) -> None:
        now = datetime.now(UTC)
        self.events.append(
            CrawlEvent(
                crawl_id=str(uuid.uuid4()),
                source=self.source,
                url=url,
                requested_at=now,
                completed_at=now,
                http_status=None,
                success=True,
                from_cache=True,
                content_type=result.artifact.content_type,
                response_bytes=result.artifact.size,
                raw_file=result.artifact.path,
                raw_sha256=result.artifact.sha256,
                error_type=None,
                error_message=None,
                runtime_seconds=0.0,
            )
        )

    def _assert_robots_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        cached = self._robots.get(origin)
        if cached is None:
            robots_url = f"{origin}/robots.txt"
            try:
                retries = max(0, int(self.policy.get("robots_retries", 0)))
                for attempt in range(retries + 1):
                    try:
                        response = self._request(robots_url, headers={})
                        if response.status_code == 404:
                            self._robots[origin] = True
                            cached = True
                        else:
                            self._check_status(response)
                            parser = RobotFileParser(robots_url)
                            parser.parse(response.text.splitlines())
                            self._robots[origin] = parser
                            cached = parser
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        if (attempt >= retries or
                                (isinstance(exc, httpx.HTTPStatusError) and
                                 400 <= exc.response.status_code < 500)):
                            raise
                        self.sleep(float(self.policy.get("robots_retry_backoff_seconds", 5)) * (attempt + 1))
            except Exception as exc:
                if bool(self.policy.get("stop_on_robots_error", True)):
                    self._circuit_open = True
                    raise CrawlSafetyError(f"cannot verify robots.txt for {origin}; crawl stopped") from exc
                self._robots[origin] = True
                cached = True
        if cached is not True:
            user_agent = str(self.policy.get("user_agent", "macro-pit-research/0.1"))
            if not cached.can_fetch(user_agent, url):
                raise CrawlSafetyError(f"robots.txt disallows this URL: {url}")

    def _request(
        self,
        url: str,
        *,
        headers: dict[str, str],
        method: str = "GET",
        data: dict[str, str] | None = None,
        event_url: str | None = None,
    ) -> httpx.Response:
        self._reserve_budget()
        host = urlparse(url).netloc.lower()
        now = self.monotonic()
        last = self._last_request_at.get(host)
        if last is not None:
            min_interval = float(self.policy.get("min_interval_seconds", 20))
            jitter = self.rng.uniform(0, float(self.policy.get("jitter_seconds", 10)))
            remaining = min_interval + jitter - (now - last)
            if remaining > 0:
                self.sleep(remaining)

        requested_at = datetime.now(UTC)
        started = self.monotonic()
        response: httpx.Response | None = None
        error: Exception | None = None
        try:
            response = self._client.request(method, url, headers=headers, data=data)
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            completed_at = datetime.now(UTC)
            self._last_request_at[host] = self.monotonic()
            self.events.append(
                CrawlEvent(
                    crawl_id=str(uuid.uuid4()),
                    source=self.source,
                    url=event_url or url,
                    requested_at=requested_at,
                    completed_at=completed_at,
                    http_status=response.status_code if response is not None else None,
                    success=bool(response is not None and 200 <= response.status_code < 400),
                    from_cache=False,
                    content_type=response.headers.get("content-type") if response is not None else None,
                    response_bytes=len(response.content) if response is not None else 0,
                    raw_file=None,
                    raw_sha256=None,
                    error_type=type(error).__name__ if error else None,
                    error_message=str(error)[:1000] if error else None,
                    runtime_seconds=max(0.0, self.monotonic() - started),
                )
            )

    def _check_status(self, response: httpx.Response) -> None:
        block_statuses = {int(value) for value in self.policy.get("block_statuses", [401, 403, 407, 429])}
        if response.status_code in block_statuses:
            self._circuit_open = True
            raise CrawlSafetyError(
                f"{self.source} received HTTP {response.status_code}; no retry was attempted and the run is stopped"
            )
        response.raise_for_status()

    def _reserve_budget(self) -> None:
        run_limit = self.policy.get("max_requests_per_run", 100)
        if run_limit is not None and self._request_count >= int(run_limit):
            self._circuit_open = True
            raise CrawlSafetyError(f"{self.source} per-run request budget exhausted ({run_limit})")

        local_day = datetime.now(UTC).astimezone(SHANGHAI).date().isoformat()
        path = self.budget_root / f"{local_day}.json"
        values: dict[str, int] = {}
        if path.is_file():
            try:
                values = {key: int(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}
            except (OSError, ValueError, json.JSONDecodeError):
                raise CrawlSafetyError(f"invalid request budget ledger: {path}")
        daily_limit = self.policy.get("max_requests_per_day", 200)
        used = values.get(self.source, 0)
        if daily_limit is not None and used >= int(daily_limit):
            self._circuit_open = True
            raise CrawlSafetyError(f"{self.source} daily request budget exhausted ({daily_limit})")

        values[self.source] = used + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
        self._request_count += 1
