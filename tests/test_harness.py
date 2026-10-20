from __future__ import annotations

import unittest

from yanhai.harness import (
    CircuitBreaker,
    IdempotencyCache,
    IdempotencyConflict,
    MetricsRegistry,
    RuntimeConfig,
)


class RuntimeConfigTests(unittest.TestCase):
    def test_remote_binding_fails_closed_without_authentication(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires YANHAI_API_TOKEN"):
            RuntimeConfig(host="0.0.0.0").validate()

    def test_remote_binding_allows_token_or_explicit_local_demo_override(self) -> None:
        RuntimeConfig(host="0.0.0.0", api_token="secret").validate()
        RuntimeConfig(
            host="0.0.0.0",
            allow_remote_without_token=True,
        ).validate()

    def test_bearer_token_comparison(self) -> None:
        config = RuntimeConfig(api_token="demo-secret")
        self.assertTrue(config.authorized("Bearer demo-secret"))
        self.assertFalse(config.authorized("Bearer wrong"))
        self.assertFalse(config.authorized(None))


class HarnessPrimitiveTests(unittest.TestCase):
    def test_idempotency_replays_only_the_same_request(self) -> None:
        cache = IdempotencyCache(ttl_seconds=60)
        cache.put(
            "demo-key-123",
            "fingerprint-a",
            status=200,
            payload={"run_id": "run-1"},
            headers={"X-Run-ID": "run-1"},
        )
        replay = cache.get("demo-key-123", "fingerprint-a")
        self.assertEqual(replay, (200, {"run_id": "run-1"}, {"X-Run-ID": "run-1"}))
        with self.assertRaises(IdempotencyConflict):
            cache.get("demo-key-123", "fingerprint-b")

    def test_metrics_track_failures_latency_and_events(self) -> None:
        metrics = MetricsRegistry()
        metrics.request_started()
        metrics.request_finished(
            method="POST",
            route="/api/run",
            status=504,
            latency_ms=40.0,
        )
        metrics.increment("task_timeout")
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["requests_total"], 1)
        self.assertEqual(snapshot["requests_failed"], 1)
        self.assertEqual(snapshot["in_flight"], 0)
        self.assertEqual(snapshot["events"]["task_timeout"], 1)
        self.assertEqual(
            snapshot["routes"]["POST /api/run"]["status_counts"]["504"],
            1,
        )

    def test_circuit_breaker_opens_and_recovers_through_half_open(self) -> None:
        breaker = CircuitBreaker(failure_threshold=2, reset_seconds=0)
        self.assertTrue(breaker.allow_request())
        breaker.record_failure()
        self.assertTrue(breaker.allow_request())
        breaker.record_failure()
        self.assertEqual(breaker.snapshot()["state"], "open")
        self.assertTrue(breaker.allow_request())
        self.assertFalse(breaker.allow_request())
        breaker.record_success()
        self.assertEqual(breaker.snapshot()["state"], "closed")
        self.assertTrue(breaker.allow_request())


if __name__ == "__main__":
    unittest.main()
