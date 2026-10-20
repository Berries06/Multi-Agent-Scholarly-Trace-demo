"""打一个能直接双击运行的研海寻踪 exe。

用法（在仓库根目录）：

    .venv\\Scripts\\python.exe scripts/打包/构建桌面版.py

它会先用 PyInstaller 读 `scripts/打包/研海寻踪.spec`，产物落在 `release/` 下。
`release/` 和 `build/` 都在 `.gitignore` 里，不会被提交。

前提：`frontend/dist` 得是先构建过的（`cd frontend; npm run build`）。
这里不替你把前端构建一遍——前端构建失败时应该看见前端的报错，而不是一个
「界面文件缺失」的二级错误。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "scripts" / "打包" / "研海寻踪.spec"
ICONS = ROOT / "scripts" / "打包" / "生成应用图标.py"
DIST = ROOT / "release"
WORK = ROOT / ".tmp" / "pyinstaller"
MAX_PAYLOAD_BYTES = 400 * 1024 * 1024


def fail(message: str) -> int:
    print(f"[没过] {message}")
    return 1


def estimate_payload() -> int:
    """按 spec 的口径数一遍要打进包的数据有多大（不包含 Python 运行时本身）。"""
    total = 0
    trees = [
        ROOT / "frontend" / "dist",
        ROOT / "config",
        ROOT / "data" / "knowledge",
        ROOT / "data" / "profiles",
        ROOT / "data" / "examples",
    ]
    for tree in trees:
        if tree.is_dir():
            total += sum(path.stat().st_size for path in tree.rglob("*") if path.is_file())
    vertical_kb = ROOT / "data" / "vertical_kb"
    if vertical_kb.is_dir():
        for path in vertical_kb.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(vertical_kb).as_posix()
            if relative.startswith("search_cache/"):
                continue
            total += path.stat().st_size
    domains = ROOT / "outputs" / "domains"
    if domains.is_dir():
        total += sum(path.stat().st_size for path in domains.rglob("*-knowledge.db"))
    for name in ("fulltext-knowledge.db", "vertical-knowledge.db"):
        candidate = ROOT / "outputs" / name
        if candidate.is_file():
            total += candidate.stat().st_size
    return total


def main() -> int:
    index = ROOT / "frontend" / "dist" / "index.html"
    if not index.is_file():
        return fail("frontend/dist/index.html 不存在，先在 frontend 目录跑一次 npm run build。")

    manifest = ROOT / "frontend" / "dist" / "manifest.webmanifest"
    if not manifest.is_file():
        return fail("frontend/dist 里没有 manifest.webmanifest，手机上装不了主屏幕图标，先重建前端。")

    icon = ROOT / "scripts" / "打包" / "研海寻踪.ico"
    if not icon.is_file():
        print("先生成图标…")
        code = subprocess.call([sys.executable, str(ICONS)])
        if code != 0:
            return fail("图标生成失败。")

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return fail("这个环境里没有 PyInstaller，先 pip install pyinstaller。")

    knowledge_dbs = sorted((ROOT / "outputs" / "domains").glob("*-knowledge.db"))
    if not knowledge_dbs:
        print("[提醒] outputs/domains 下没有全文知识库，打出来的软件「全文知识库」页会是空的。")

    # 体积先算一遍再打。2026-10-19 第一次打包时 spec 写成了「整个 outputs/domains 带走」，
    # 把 7.5 GB 实验缓存塞进单文件归档，压缩跑了 20 多分钟还没完；这条检查就是为了不再发生。
    payload = estimate_payload()
    print(f"[预检] 要打进包的数据 {payload / 1024 / 1024:.1f} MB")
    if payload > MAX_PAYLOAD_BYTES:
        return fail(
            f"要打进包的数据有 {payload / 1024 / 1024:.0f} MB，超过 {MAX_PAYLOAD_BYTES // 1024 // 1024} MB 上限。"
            " 先看 scripts/打包/研海寻踪.spec 的 collect_knowledge_stores 是不是又把实验缓存带进去了。"
        )

    DIST.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
    ]
    print("开始打包：", " ".join(command[-6:]))
    started = time.monotonic()
    code = subprocess.call(command)
    if code != 0:
        return fail(f"PyInstaller 返回 {code}。")

    exe = DIST / "研海寻踪.exe"
    if not exe.is_file():
        return fail("没找到 release/研海寻踪.exe。")

    # 单文件 exe 旁边不要再留旧的一堆库文件，免得双击错东西
    stale = DIST / "研海寻踪"
    if stale.is_dir():
        shutil.rmtree(stale, ignore_errors=True)

    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"[通过] {exe.relative_to(ROOT).as_posix()}  {size_mb:.1f} MB  用时 {time.monotonic() - started:.0f} 秒")
    print("下一步自检：release\\研海寻踪.exe --check --no-browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
