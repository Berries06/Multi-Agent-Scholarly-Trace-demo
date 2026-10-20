# -*- mode: python ; coding: utf-8 -*-
"""研海寻踪的 PyInstaller 打包描述（单文件 exe）。

打进去的东西，以及为什么：

- `frontend/dist`：V3.1 的界面。`api.py` 是在 `<解包目录>/frontend/dist` 找它的。
- `data/knowledge`、`data/profiles`、`data/examples`、`data/vertical_kb`（除了 12 MB 的
  ACL 全量题录缓存）：领域词表、示例画像、语料清单。
- `outputs/domains/*.db`、`outputs/*-knowledge.db`：全文知识库只读视图，
  界面上的「全文知识库」页全靠它。
- `config`：路由与提示词配置。

刻意不打进去的：

- `papers/`（1 GB 的开放获取 PDF）与 `outputs/` 其它产物：体积大，而且界面不需要。
- `data/evaluation/`：里面有人工标注答案，只该留在内网，不跟着软件发出去。
- `secret/`：任何密钥都不进包。
- `docling` / `mlflow` / `PyQt6`：前者几 GB 的可选解析器，中间那个是实验记录，
  最后一个属于老的桌面客户端，V3.1 不需要。少一个都是几十上百 MB。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

HERE = ROOT / "scripts" / "打包"
ENTRY = HERE / "桌面版入口.py"


def collect_tree(source: Path, target: str, skip: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """把一个目录按原样挂到包里的 `target` 下；`skip` 里的是相对路径前缀。"""
    if not source.is_dir():
        return []
    items: list[tuple[str, str]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        relative_posix = relative.as_posix()
        if any(relative_posix == prefix or relative_posix.startswith(prefix + "/") for prefix in skip):
            continue
        destination = target if relative.parent == Path(".") else f"{target}/{relative.parent.as_posix()}"
        items.append((str(path), destination))
    return items


def collect_knowledge_stores() -> list[tuple[str, str]]:
    """全文知识库的 SQLite 都在 `outputs/` 下，但 `outputs/` 其它东西不能进包。

    **只挑 `*-knowledge.db`**。2026-10-19 第一次打包时这里写成了「把 outputs/domains
    整个目录带走」，结果把 7.5 GB 的实验缓存（`*-sections-cache-df2.json` 一个就
    100 MB）全塞进单文件归档：压缩跑了 20 多分钟还没完，产出的 exe 也不可能小。
    """
    items: list[tuple[str, str]] = []
    domains = ROOT / "outputs" / "domains"
    if domains.is_dir():
        for path in sorted(domains.rglob("*-knowledge.db")):
            relative = path.relative_to(domains)
            destination = (
                "outputs/domains"
                if relative.parent == Path(".")
                else f"outputs/domains/{relative.parent.as_posix()}"
            )
            items.append((str(path), destination))
    for name in ("fulltext-knowledge.db", "vertical-knowledge.db"):
        candidate = ROOT / "outputs" / name
        if candidate.is_file():
            items.append((str(candidate), "outputs"))
    return items


datas: list[tuple[str, str]] = []
datas += collect_tree(ROOT / "frontend" / "dist", "frontend/dist")
datas += collect_tree(ROOT / "config", "config")
datas += collect_tree(ROOT / "data" / "knowledge", "data/knowledge")
datas += collect_tree(ROOT / "data" / "profiles", "data/profiles")
datas += collect_tree(ROOT / "data" / "examples", "data/examples")
datas += collect_tree(ROOT / "data" / "vertical_kb", "data/vertical_kb", skip=("search_cache",))
datas += collect_knowledge_stores()

hiddenimports = [
    name for name in collect_submodules("yanhai") if name != "yanhai.qt_app"
] + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
]

EXCLUDES = [
    "docling",
    "mlflow",
    "PyQt6",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "torch",
    "sklearn",
    "IPython",
    "notebook",
    "tkinter",
    "PIL",
    "pytest",
    "pip",
    "setuptools",
]


a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

# 两种打法（`YANHAI_BUILD_MODE=onedir` 切换）：
#   onefile：一个 exe，拷给别人最省事，代价是每次启动都要把内容解到临时目录；
#   onedir：exe 加一个 `_internal/` 文件夹，启动快，分发时整个文件夹打成 zip。
# 单文件那一步要把几十兆数据压进一个归档，机器慢的时候会跑十几分钟。
MODE = os.environ.get("YANHAI_BUILD_MODE", "onefile").strip().lower()
COMMON = dict(
    name="研海寻踪",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=str(HERE / "研海寻踪.ico"),
)

if MODE == "onedir":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        runtime_tmpdir=None,
        **COMMON,
    )
    COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="研海寻踪",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        runtime_tmpdir=None,
        **COMMON,
    )
