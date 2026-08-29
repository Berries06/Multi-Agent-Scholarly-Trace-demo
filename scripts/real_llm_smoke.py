"""真实 LLM 冒烟：用已配置的任一供应商发一次最小结构化调用。

用法：
  python scripts/real_llm_smoke.py

行为：
- 从项目 .env 读取 Key（DEEPSEEK/KIMI/ZHIPU_API_KEY），缺 Key 显式退出（exit 2）；
- 用第一个可用的供应商发一次 complete_json 冒烟，打印模型、token、耗时；
- 任何失败非零退出并打印完整错误；绝不静默回退规则模型。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.providers import ProviderError, create_provider, load_config_from_env  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    candidate = []
    for provider in ("deepseek", "kimi", "zhipu"):
        if os.environ.get(f"{provider.upper()}_API_KEY", "").strip():
            candidate.append(provider)
    if not candidate:
        print(
            "未找到任何可用 Key（.env 中 DEEPSEEK/KIMI/ZHIPU_API_KEY 均为空）。"
            "本脚本不做静默回退，请先配置 Key。",
            file=sys.stderr,
        )
        return 2

    provider = candidate[0]
    config = load_config_from_env(provider)
    client = create_provider(config)
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    started = time.perf_counter()
    try:
        data, usage = client.complete_json(
            "你是冒烟测试助手。",
            "请只回复 {\"status\": \"ok\"}。",
            schema_name="smoke",
            schema=schema,
        )
    except ProviderError as exc:
        print(f"冒烟失败（{provider}/{config.model}）：{exc}", file=sys.stderr)
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"provider={provider} model={config.model}")
    print(f"response={data}")
    print(f"usage={usage.public_dict() if hasattr(usage, 'public_dict') else usage}")
    print(f"elapsed_ms={elapsed_ms:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
