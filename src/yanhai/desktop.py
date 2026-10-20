"""桌面版与手机版的启动器。

打包后的软件是「一个窗口都点不出来的 exe」——双击之后它在后台把 FastAPI 起在本机，
再用默认浏览器把界面打开。这样做的原因很实在：V3.1 的界面是 React 写的，
用浏览器渲染最稳；换成 Qt 壳子等于把界面重写一遍，两边还会越走越远。

命令行：

- `研海寻踪.exe`：只开本机，`http://127.0.0.1:8766`。
- `研海寻踪.exe --lan`：开在局域网上，手机连同一个 WiFi 就能打开。地址会打在窗口里。
- `研海寻踪.exe --port 9000`：换端口；被占用时会自动往后找空位。
- `研海寻踪.exe --no-browser`：不自动开浏览器。
- `研海寻踪.exe --check`：自检，起服务、打一遍关键接口、退出。打包后验收用。

数据放哪：优先 exe 旁边的 `用户数据/`（绿色版，整个文件夹拷走就换了台机器）；
那里写不进去（比如装在 Program Files）就退到 `%LOCALAPPDATA%\\研海寻踪`。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
APP_NAME = "研海寻踪"
DEFAULT_PORT = 8766


def resource_root() -> Path:
    """打包后是解包目录，源码运行时是仓库根目录。"""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen).resolve()
    return Path(__file__).resolve().parents[2]


def writable_data_root(root: Path) -> Path:
    """运行时状态（账号、项目、会话）往哪儿写。

    打包成单文件之后解包目录是临时目录，进程一退就没了，所以绝不能把 SQLite 放在
    那里，否则每关一次软件账号和项目就全丢。
    """
    configured = os.environ.get("YANHAI_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "用户数据")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(Path(local_appdata) / APP_NAME)
    candidates.append(root / "outputs" / "runtime")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    raise SystemExit("找不到可写的目录，没法保存数据。")


def pick_port(preferred: int, host: str) -> int:
    """从 preferred 往后找第一个能绑上的端口。"""
    for port in range(preferred, preferred + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise SystemExit(f"从 {preferred} 往后 40 个端口都被占用了，换台机器或加 --port 再试。")


def lan_addresses() -> list[str]:
    from yanhai.api import local_ipv4_addresses

    return local_ipv4_addresses()


def wait_until_ready(url: str, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def run_self_check(base: str) -> int:
    """打包后没有浏览器可点，用这个把关键路径打一遍。

    需要登录的接口只有在设了 `YANHAI_CHECK_LOGIN=邮箱:密码` 时才验——
    打包验证时用真实账号跑一遍，平时不用把密码摆在环境里。
    """
    checks: list[tuple[str, str, bool, str]] = []
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(_cookie_jar())
    )
    for label, path, needed in (
        ("健康检查", "/api/health", "status"),
        ("登录状态", "/api/auth/status", "has_users"),
        ("本机地址", "/api/system/access", "lan_enabled"),
        ("界面首页", "/", "<div id=\"root\">"),
        ("界面清单", "/manifest.webmanifest", "\"short_name\""),
        ("离线外壳", "/sw.js", "yanhai-shell"),
        ("应用图标", "/icon-192.png", ""),
    ):
        try:
            with opener.open(base + path, timeout=10) as response:
                body = response.read().decode("utf-8", "replace")
            checks.append((label, path, response.status == 200 and needed in body, f"HTTP {response.status}"))
        except (urllib.error.URLError, OSError) as exc:
            checks.append((label, path, False, str(exc)))

    credentials = os.environ.get("YANHAI_CHECK_LOGIN", "").strip()
    if credentials and ":" in credentials:
        identifier, password = credentials.split(":", 1)
        payload = json.dumps({"identifier": identifier, "password": password}).encode("utf-8")
        request = urllib.request.Request(
            base + "/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with opener.open(request, timeout=15) as response:
                logged_in = response.status == 200 and b"authenticated" in response.read()
            checks.append(("登录一次", "/api/auth/login", logged_in, "HTTP 200" if logged_in else "登录失败"))
        except (urllib.error.URLError, OSError) as exc:
            checks.append(("登录一次", "/api/auth/login", False, str(exc)))
        if checks[-1][2]:
            for label, path, needed in (
                ("知识库概况", "/api/knowledge-store/summary", "domains"),
                ("课题列表", "/api/projects", "projects"),
            ):
                try:
                    with opener.open(base + path, timeout=15) as response:
                        body = response.read().decode("utf-8", "replace")
                    checks.append((label, path, response.status == 200 and needed in body, f"HTTP {response.status}"))
                except (urllib.error.URLError, OSError) as exc:
                    checks.append((label, path, False, str(exc)))

    ok = True
    for label, path, passed, detail in checks:
        ok = ok and passed
        print(f"[{'通过' if passed else '没过'}] {label} {path} — {detail}")
    return 0 if ok else 1


def _cookie_jar() -> "http.cookiejar.CookieJar":
    import http.cookiejar

    return http.cookiejar.CookieJar()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="研海寻踪桌面版／手机版启动器")
    parser.add_argument("--lan", action="store_true", help="开在局域网上，手机可以连进来")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--check", action="store_true", help="自检：起服务、验接口、退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    root = resource_root()
    data_root = writable_data_root(root)
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    port = pick_port(args.port, host)
    probe_host = "127.0.0.1"

    # 必须赶在 yanhai 任何模块算路径之前写好这几个环境变量：
    # `resources.runtime_data_root()` 就是照它们定位 SQLite 的。
    os.environ["YANHAI_DATA_DIR"] = str(data_root)
    os.environ["YANHAI_BIND_HOST"] = host
    os.environ["YANHAI_BIND_PORT"] = str(port)
    # 源码运行时 `yanhai` 还没在 import 路径上；打包后它本来就在包里，这一行多余也无害。
    source_dir = root / "src"
    if source_dir.is_dir():
        sys.path.insert(0, str(source_dir))

    import uvicorn

    from yanhai.api import create_app

    app = create_app(root=root)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    worker = threading.Thread(target=server.run, name="yanhai-api", daemon=True)
    worker.start()

    base = f"http://{probe_host}:{port}"
    if not wait_until_ready(f"{base}/api/health"):
        print("服务没起来，请把窗口里的报错发给维护的人。")
        return 1

    interface = f"{base}/"
    print("=" * 56)
    print(f"  {APP_NAME} 已启动")
    print("=" * 56)
    print(f"  本机打开：{interface}")
    if args.lan:
        addresses = lan_addresses()
        if addresses:
            for address in addresses:
                print(f"  手机打开：http://{address}:{port}")
            print("  手机和电脑连同一个 WiFi，打开上面的网址，")
            print("  浏览器菜单里选「添加到主屏幕」，之后从桌面图标进来就是全屏的。")
        else:
            print("  没读到本机在局域网里的地址，先确认这台电脑连着 WiFi 或有线网。")
    else:
        print("  手机版：关掉这个窗口，用「启动手机版.bat」重新开一次。")
    print(f"  数据目录：{data_root}")
    print("  关掉这个窗口就停止服务。")
    print("=" * 56)

    if args.check:
        code = run_self_check(base)
        server.should_exit = True
        worker.join(timeout=10)
        return code

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(interface)), daemon=True).start()

    try:
        while worker.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("正在停止…")
    finally:
        server.should_exit = True
        worker.join(timeout=10)
    print("已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
