"""在生产服务器本机通过公网入口验证登录门禁与免费 DeepSeek 完整链路。"""

from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request

from yanhai.resources import database_path
from yanhai.storage import AppRepository


BASE_URL = "https://snowsong.top/AgentDemo/start"
QUESTION = (
    "在科研知识图谱构建中，使用多智能体的提出—质疑—裁决流程，"
    "相比单次抽取可能减少哪些类型的错误？请基于可追溯证据回答，"
    "并明确证据不足之处。"
)


def request_json(
    opener: urllib.request.OpenerDirector,
    path: str,
    payload: dict[str, object] | None = None,
    *,
    timeout: int = 240,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def request_stream(
    opener: urllib.request.OpenerDirector,
    path: str,
    payload: dict[str, object],
    *,
    timeout: int = 300,
) -> tuple[int, list[tuple[str, dict[str, object]]]]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        events: list[tuple[str, dict[str, object]]] = []
        for block in raw.split("\n\n"):
            lines = [line for line in block.splitlines() if line]
            event_line = next((line for line in lines if line.startswith("event:")), "")
            data_line = next((line for line in lines if line.startswith("data:")), "")
            if event_line and data_line:
                events.append(
                    (
                        event_line.removeprefix("event:").strip(),
                        json.loads(data_line.removeprefix("data:").strip()),
                    )
                )
        return response.status, events


def main() -> None:
    suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
    email = f"acceptance-{suffix}@snowsong.top"
    password = "Mat!" + secrets.token_urlsafe(18)
    AppRepository(database_path()).register_user(email, f"验收-{suffix}", password)

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    health_status, health = request_json(opener, "/api/health")
    ready_status, ready = request_json(opener, "/api/ready")
    unauth_status, unauth = request_json(
        opener,
        "/api/run",
        {"query": QUESTION, "include_ablation": False},
    )
    assert health_status == 200 and health["status"] == "ok"
    assert ready_status == 200 and ready["status"] == "ready"
    assert unauth_status == 401
    assert unauth["error"]["code"] == "login_required"

    login_status, login = request_json(
        opener,
        "/api/auth/login",
        {"identifier": email, "password": password},
    )
    assert login_status == 200 and login["authenticated"] is True

    providers_status, providers = request_json(opener, "/api/providers")
    assert providers_status == 200
    free_provider = next(item for item in providers if item["id"] == "free-deepseek")
    assert free_provider["available"] is True

    run_status, stream_events = request_stream(
        opener,
        "/api/run/stream",
        {
            "profile_id": "my-profile",
            "query": QUESTION,
            "domain_id": "scientific-ie-kg",
            "include_ablation": False,
            "llm": {
                "provider": "free-deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "",
                "timeout_seconds": 180,
            },
        },
    )
    assert run_status == 200
    progress = [event[1]["progress"] for event in stream_events if event[0] == "progress"]
    completed = [event[1]["result"] for event in stream_events if event[0] == "completed"]
    assert len(completed) == 1, stream_events[-3:]
    result = completed[0]
    assert [item["sequence"] for item in progress] == list(range(1, len(progress) + 1))
    artifact_events = [item for item in progress if item.get("details")]
    artifact_kinds = {
        detail["kind"]
        for item in artifact_events
        for detail in item["details"]
    }
    assert {"query", "question", "evidence", "claim", "review", "metric"}.issubset(
        artifact_kinds
    ), artifact_kinds
    assert any(item.get("content_origin") == "model" for item in artifact_events)
    assert any(item.get("content_origin") == "retrieval" for item in artifact_events)
    provider_run = result["provider_run"]
    assert provider_run["mode"] == "live_llm", provider_run
    assert provider_run.get("degraded") is not True
    assert len(provider_run["calls"]) == 3, provider_run["calls"]
    assert all(call.get("finish_reason") == "stop" for call in provider_run["calls"])
    paper_ids = {paper["paper_id"] for paper in result["papers"]}
    assert all(
        evidence_id in paper_ids
        for claim in result["claims"]
        for evidence_id in claim["evidence_ids"]
    )

    print(
        json.dumps(
            {
                "public_health": health["status"],
                "public_ready": ready["status"],
                "login_gate": unauth["error"]["code"],
                "login": "ok",
                "free_deepseek": "available",
                "run_mode": provider_run["mode"],
                "stages": [
                    {
                        "role": call["role"],
                        "finish_reason": call["finish_reason"],
                        "attempts": call["attempts"],
                        "total_tokens": call["usage"]["total_tokens"],
                    }
                    for call in provider_run["calls"]
                ],
                "papers": len(result["papers"]),
                "claims": len(result["claims"]),
                "citations_valid": True,
                "history_saved": result.get("persistence", {}).get("saved") is True,
                "progress_events": len(progress),
                "artifact_events": len(artifact_events),
                "artifact_kinds": sorted(artifact_kinds),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
