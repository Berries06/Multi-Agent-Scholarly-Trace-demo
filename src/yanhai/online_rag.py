from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .harness import CircuitBreaker


def _abstract_from_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words = sorted(
        (
            (position, word)
            for word, positions in index.items()
            for position in positions
        ),
        key=lambda item: item[0],
    )
    return " ".join(word for _, word in words)


def _retrieval_query(query: str) -> str:
    """Map the demo's Chinese task wording to OpenAlex search concepts."""
    if not re.search(r"[\u4e00-\u9fff]", query):
        return query
    terms = ["scientific literature"]
    if "抽取" in query:
        terms.extend(["entity extraction", "relation extraction"])
    if "知识图谱" in query or "图谱" in query:
        terms.append("knowledge graph")
    if "想法" in query or "idea" in query.casefold():
        terms.append("research idea generation")
    return " ".join(terms)


class OnlineRAG:
    """Optional OpenAlex candidate retrieval with an offline cache fallback."""

    def __init__(
        self,
        cache_path: Path,
        *,
        timeout_seconds: float = 5.0,
        retries: int = 1,
        backoff_seconds: float = 0.25,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.cache_path = cache_path
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._cache_lock = threading.Lock()

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        cache = self._load_cache()
        cache_key = f"{query.casefold()}::{limit}"
        if not allow_network:
            return {
                "query": query,
                "source": "offline-cache",
                "results": cache.get(cache_key, []),
                "network_used": False,
                "warning": "未启用联网；缓存结果只作为待解析候选，不能直接进入知识图谱。",
                "resilience": {
                    "attempts": 0,
                    "circuit": self.circuit_breaker.snapshot(),
                },
            }
        if not self.circuit_breaker.allow_request():
            return {
                "query": query,
                "source": "offline-cache",
                "results": cache.get(cache_key, []),
                "network_used": False,
                "warning": (
                    "OpenAlex 熔断器处于打开状态；本轮不再发起网络请求，"
                    "已回退本地缓存。"
                ),
                "resilience": {
                    "attempts": 0,
                    "circuit": self.circuit_breaker.snapshot(),
                },
            }
        retrieval_query = _retrieval_query(query)
        params = urlencode(
            {
                "search": retrieval_query,
                "per-page": limit,
                "select": (
                    "id,doi,title,publication_year,primary_location,"
                    "open_access,abstract_inverted_index"
                ),
            }
        )
        request = Request(
            f"https://api.openalex.org/works?{params}",
            headers={"User-Agent": "Yanhai-Scholarly-Trace/0.2"},
        )
        raw: dict[str, Any] | None = None
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(self.retries + 1):
            attempts = attempt + 1
            try:
                with urlopen(  # noqa: S310 - fixed host
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                last_error = exc
                if 400 <= exc.code < 500 and exc.code != 429:
                    break
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(self.backoff_seconds * (2**attempt))

        if raw is None:
            self.circuit_breaker.record_failure()
            return {
                "query": query,
                "source": "offline-cache",
                "results": cache.get(cache_key, []),
                "network_used": False,
                "warning": (
                    f"OpenAlex 暂不可达（{type(last_error).__name__}）；"
                    f"已尝试 {attempts} 次并回退缓存。"
                    "缓存同样只是待解析候选，不能直接进入知识图谱。"
                ),
                "resilience": {
                    "attempts": attempts,
                    "circuit": self.circuit_breaker.snapshot(),
                },
            }
        self.circuit_breaker.record_success()
        results = []
        for item in raw.get("results", []):
            location = item.get("primary_location") or {}
            source = location.get("source") or {}
            open_access = item.get("open_access") or {}
            results.append(
                {
                    "openalex_id": item.get("id", ""),
                    "doi": item.get("doi") or "",
                    "title": item.get("title") or "",
                    "year": item.get("publication_year"),
                    "venue": source.get("display_name") or "",
                    "source_url": location.get("landing_page_url") or item.get("id", ""),
                    "pdf_url": open_access.get("oa_url") or "",
                    "abstract": _abstract_from_index(
                        item.get("abstract_inverted_index")
                    ),
                    "status": "candidate_requires_local_parsing",
                }
            )
        self._store_cache_entry(cache_key, results)
        return {
            "query": query,
            "retrieval_query": retrieval_query,
            "source": "OpenAlex",
            "results": results,
            "network_used": True,
            "warning": "联网结果只扩展候选；下载并完成证据抽取与三智能体裁决后才能入图。",
            "resilience": {
                "attempts": attempts,
                "circuit": self.circuit_breaker.snapshot(),
            },
        }

    def _load_cache(self) -> dict[str, list[dict[str, Any]]]:
        with self._cache_lock:
            if not self.cache_path.exists():
                return {}
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}

    def _store_cache_entry(
        self,
        cache_key: str,
        results: list[dict[str, Any]],
    ) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_lock:
            if self.cache_path.exists():
                try:
                    cache = json.loads(
                        self.cache_path.read_text(encoding="utf-8")
                    )
                except (json.JSONDecodeError, OSError):
                    cache = {}
            else:
                cache = {}
            cache[cache_key] = results
            temporary = self.cache_path.with_suffix(
                self.cache_path.suffix + ".tmp"
            )
            temporary.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.cache_path)
