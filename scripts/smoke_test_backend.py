"""统一产品后端的无副作用冒烟检查。"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_json(url: str) -> dict[str, object]:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 FastAPI 健康状态和登录门禁")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    try:
        health = read_json(f"{base}/api/health")
        ready = read_json(f"{base}/api/ready")
        login_required = False
        try:
            read_json(f"{base}/api/domains")
        except HTTPError as exc:
            login_required = exc.code == 401
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    checks = {
        "health_ok": health.get("status") == "ok",
        "ready": ready.get("status") == "ready",
        "fastapi_service": health.get("service") == "yanhai-api",
        "login_gate": login_required,
        "three_core_agents": health.get("core_agents") == 3,
    }
    print(json.dumps({"status": "passed" if all(checks.values()) else "failed", "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
