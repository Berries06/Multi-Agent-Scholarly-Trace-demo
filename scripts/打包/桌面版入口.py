"""PyInstaller 的入口脚本：把 `yanhai.desktop.main` 交出去。

单独放一个文件是因为 PyInstaller 需要一个「脚本」而不是包内模块当入口；
`desktop.py` 本身仍在 `src/yanhai/` 里，源码运行时可以直接 `python src/yanhai/desktop.py`。
"""

from yanhai.desktop import main


if __name__ == "__main__":
    raise SystemExit(main())
