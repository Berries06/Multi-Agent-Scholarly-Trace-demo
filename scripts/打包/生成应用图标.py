"""生成手机与桌面用的应用图标。

产品配色是深绿四档 + 一点金（金只给「待人判定」）。图标就用这套颜色画一张：
深绿底 + 一个三节点的关系图，中间那个节点用金色——一眼能认出是「带证据的图谱」。

同一个图形出五份，放进 `frontend/public/`，`vite build` 会原样拷进 `dist/`：

- `icon-192.png` / `icon-512.png`：安卓装到主屏幕用
- `icon-maskable-512.png`：安卓自适应图标，图形缩进安全区，系统裁圆角也不会切到节点
- `apple-touch-icon.png`：iOS 主屏幕图标，不透明、不留圆角（iOS 自己会裁）
- `favicon.png`：浏览器标签页

命令：`.venv\\Scripts\\python.exe scripts/打包/生成应用图标.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "frontend" / "public"

DEEP = (30, 57, 50, 255)  # #1E3932 深绿底
GREEN = (0, 98, 65, 255)  # #006241 连线
LIGHT = (0, 117, 74, 255)  # #00754A 外围节点
GOLD = (203, 162, 88, 255)  # #CBA258 中心节点

# 图形按 1024 画再缩小，缩小时自带抗锯齿；安全区按 Android maskable 的要求留 20%。
CANVAS = 1024
SAFE = 0.80


def _draw_mark(draw: ImageDraw.ImageDraw, scale: float) -> None:
    """在 1024 画布上画三节点关系图，`scale` 控制整体缩放（maskable 要缩进安全区）。"""
    center = CANVAS / 2
    hub = center, center
    node_radius = 96 * scale

    # 三个外围节点围成三角形，角度避开 0°/120°/240°，让图形看起来是「正在生长」而不是静态符号
    import math

    spokes = []
    for angle in (198, 318, 78):
        radians = math.radians(angle)
        distance = 300 * scale
        spokes.append((center + distance * math.cos(radians), center + distance * math.sin(radians)))

    for point in spokes:
        draw.line([hub, point], fill=GREEN, width=int(46 * scale))
    for point in spokes:
        draw.ellipse(
            [point[0] - 62 * scale, point[1] - 62 * scale, point[0] + 62 * scale, point[1] + 62 * scale],
            fill=LIGHT,
        )
    draw.ellipse(
        [hub[0] - node_radius, hub[1] - node_radius, hub[0] + node_radius, hub[1] + node_radius],
        fill=GOLD,
    )


def _flat_icon(size: int, *, scale: float, background: bool) -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), DEEP if background else (0, 0, 0, 0))
    _draw_mark(ImageDraw.Draw(image), scale)
    return image.resize((size, size), Image.LANCZOS)


def _rounded_icon(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """圆角版本：给浏览器标签页和桌面快捷方式用，避免在白底上糊成一个方块。"""
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, CANVAS - 1, CANVAS - 1],
        radius=int(CANVAS * radius_ratio),
        fill=255,
    )
    icon = _flat_icon(CANVAS, scale=1.0, background=True)
    icon.putalpha(mask)
    return icon.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "icon-192.png": _flat_icon(192, scale=1.15, background=True),
        "icon-512.png": _flat_icon(512, scale=1.15, background=True),
        "icon-maskable-512.png": _flat_icon(512, scale=SAFE / 1.0 * 0.92, background=True),
        "apple-touch-icon.png": _flat_icon(180, scale=0.92, background=True),
        "favicon.png": _rounded_icon(64),
    }
    for name, image in outputs.items():
        path = OUT_DIR / name
        image.save(path, format="PNG", optimize=True)
        print(f"{path.relative_to(ROOT).as_posix()}  {path.stat().st_size} 字节  {image.size[0]}x{image.size[1]}")

    # exe 的图标只认 .ico，PyInstaller 不会帮你转 PNG
    ico_path = ROOT / "scripts" / "打包" / "研海寻踪.ico"
    _flat_icon(256, scale=1.15, background=True).save(
        ico_path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print(f"{ico_path.relative_to(ROOT).as_posix()}  {ico_path.stat().st_size} 字节  ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
