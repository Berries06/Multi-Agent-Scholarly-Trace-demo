"""把 exe 和说明装成两份能直接发给别人的压缩包。

用法（仓库根目录，先跑过 `构建桌面版.py`）：

    .venv\\Scripts\\python.exe scripts/打包/发布包.py

产物：

- `release/研海寻踪-V3.1-电脑版.zip`：exe + 电脑版说明
- `release/研海寻踪-V3.1-手机版.zip`：exe + `启动手机版.bat` + 手机版说明

两个包里的 exe 是同一份文件（比对 sha256 会一致），区别只在附带哪些说明与启动脚本。
不把 exe 只放进电脑版那个包，是因为手机版单独发给别人时，对方也得有个能跑起来的服务。
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "release"
HERE = ROOT / "scripts" / "打包"
EXE = RELEASE / "研海寻踪.exe"
STAGE = RELEASE / "发布"
VERSION = "V3.1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_dir(name: str, files: list[tuple[Path, str]]) -> Path:
    folder = STAGE / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for source, target in files:
        destination = folder / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return folder


def make_zip(folder: Path, output: Path) -> Path:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    return output


def main() -> int:
    if not EXE.is_file():
        print("[没过] release/研海寻踪.exe 不存在，先跑 构建桌面版.py。")
        return 1

    launcher = ROOT / "启动手机版.bat"
    if not launcher.is_file():
        print("[没过] 根目录没有 启动手机版.bat。")
        return 1

    desktop = stage_dir(
        "电脑版",
        [
            (EXE, "研海寻踪.exe"),
            (HERE / "说明_电脑版.md", "使用说明.md"),
        ],
    )
    mobile = stage_dir(
        "手机版",
        [
            (EXE, "研海寻踪.exe"),
            (HERE / "说明_手机版.md", "使用说明.md"),
            (launcher, "启动手机版.bat"),
        ],
    )

    packages = [
        make_zip(desktop, RELEASE / f"研海寻踪-{VERSION}-电脑版.zip"),
        make_zip(mobile, RELEASE / f"研海寻踪-{VERSION}-手机版.zip"),
    ]

    exe_hash = sha256(EXE)
    print(f"exe  {EXE.stat().st_size / 1024 / 1024:.1f} MB  sha256 {exe_hash[:16]}…")
    for package in packages:
        print(f"[通过] {package.relative_to(ROOT).as_posix()}  {package.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
