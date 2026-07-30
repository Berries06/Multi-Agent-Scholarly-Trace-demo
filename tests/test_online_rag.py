from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError

from yanhai.harness import CircuitBreaker
from yanhai.online_rag import OnlineRAG


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class OnlineRAGResilienceTests(unittest.TestCase):
    def test_transient_failure_retries_then_atomically_caches_success(self) -> None:
        with TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cache.json"
            rag = OnlineRAG(
                cache_path,
                retries=1,
                backoff_seconds=0,
            )
            raw = {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Evidence-grounded extraction",
                        "publication_year": 2026,
                        "primary_location": {
                            "landing_page_url": "https://example.test/paper",
                            "source": {"display_name": "Test Venue"},
                        },
                        "open_access": {"oa_url": ""},
                    }
                ]
            }
            with patch(
                "yanhai.online_rag.urlopen",
                side_effect=[URLError("temporary"), _Response(raw)],
            ) as mocked:
                result = rag.search("knowledge graph", allow_network=True)
            self.assertEqual(mocked.call_count, 2)
            self.assertTrue(result["network_used"])
            self.assertEqual(result["resilience"]["attempts"], 2)
            self.assertEqual(result["resilience"]["circuit"]["state"], "closed")
            self.assertTrue(cache_path.is_file())
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(len(next(iter(cached.values()))), 1)

    def test_open_circuit_skips_network_and_falls_back(self) -> None:
        with TemporaryDirectory() as directory:
            breaker = CircuitBreaker(failure_threshold=1, reset_seconds=60)
            rag = OnlineRAG(
                Path(directory) / "cache.json",
                retries=0,
                backoff_seconds=0,
                circuit_breaker=breaker,
            )
            with patch(
                "yanhai.online_rag.urlopen",
                side_effect=URLError("offline"),
            ) as mocked:
                first = rag.search("knowledge graph", allow_network=True)
                second = rag.search("knowledge graph", allow_network=True)
            self.assertEqual(mocked.call_count, 1)
            self.assertFalse(first["network_used"])
            self.assertEqual(first["resilience"]["circuit"]["state"], "open")
            self.assertFalse(second["network_used"])
            self.assertEqual(second["resilience"]["attempts"], 0)
            self.assertIn("熔断器", second["warning"])


if __name__ == "__main__":
    unittest.main()
