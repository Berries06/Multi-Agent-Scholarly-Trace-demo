"""将透明品牌母版裁切、居中并压缩为网页资产。"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def build_web_asset(source: Path, destination: Path, size: int, padding: int) -> None:
    image = Image.open(source).convert("RGBA")
    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("输入图片不包含可见像素。")

    cropped = image.crop(bounds)
    content_size = max(1, size - padding * 2)
    scale = min(content_size / cropped.width, content_size / cropped.height)
    resized = cropped.resize(
        (max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=True, compress_level=9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--padding", type=int, default=20)
    args = parser.parse_args()
    if args.size < 64:
        parser.error("--size 不能小于 64。")
    if args.padding < 0 or args.padding * 2 >= args.size:
        parser.error("--padding 必须小于图片尺寸的一半。")
    build_web_asset(args.source, args.destination, args.size, args.padding)


if __name__ == "__main__":
    main()
