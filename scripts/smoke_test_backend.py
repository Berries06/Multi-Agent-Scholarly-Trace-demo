from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request_headers = dict(headers or {})
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=request_headers,
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
        return result, dict(response.headers.items())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Yanhai backend and idempotency contract."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    try:
        health, _ = request_json(args.base_url, "/api/health")
        readiness, _ = request_json(args.base_url, "/api/ready")
        domains, _ = request_json(args.base_url, "/api/domains")
        key = f"smoke-{uuid.uuid4()}"
        run_payload = {
            "profile_id": "undergraduate_ai",
            "query": "知识图谱如何帮助理解科研论文脉络？",
        }
        first, first_headers = request_json(
            args.base_url,
            "/api/run",
            payload=run_payload,
            headers={"Idempotency-Key": key},
        )
        second, second_headers = request_json(
            args.base_url,
            "/api/run",
            payload=run_payload,
            headers={"Idempotency-Key": key},
        )
        metrics, _ = request_json(args.base_url, "/api/metrics")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1

    first_run = first.get("observability", {}).get("run_id")
    second_run = second.get("observability", {}).get("run_id")
    checks = {
        "health_ok": health.get("status") == "ok",
        "ready": readiness.get("status") == "ready",
        "three_core_agents": health.get("core_agents") == 3,
        "five_system_agents": health.get("system_agents") == 5,
        "three_vertical_domains": (
            health.get("domains") == 3
            and len(domains.get("domains", [])) == 3
        ),
        "run_traceable": bool(first_run and first_headers.get("X-Run-ID")),
        "idempotency_replayed": (
            first_run == second_run
            and second_headers.get("Idempotency-Replayed") == "true"
        ),
        "metrics_available": metrics.get("requests_total", 0) >= 4,
    }
    print(
        json.dumps(
            {
                "status": "passed" if all(checks.values()) else "failed",
                "checks": checks,
                "run_id": first_run,
                "papers": health.get("papers"),
                "domains": health.get("domains"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
