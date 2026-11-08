# -*- coding: utf-8 -*-
"""从精灵图里剪出脑袋，做成多尺寸 .ico。

    python tools/make_icon.py
"""

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(BASE, "assets")

S = 512                    # 母版尺寸
REF_W = 124                # 参考宽度：头部大致占多少源图像素，用来定缩放基准
ANCHOR = (104, 36)         # 构图锚点（源图像素）：大概在额头中央
FILL = 0.58                # 缩放后头部占画布的比例
ANCHOR_Y = 0.40            # 锚点落在画布的哪个高度

SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def circle_bg(size, top=(255, 249, 235), bottom=(255, 228, 190)):
    """上浅下深的暖色圆底，带一点点内阴影。"""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx = cy = size / 2.0
    r = size / 2.0 - 2
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    cover = np.clip((r - dist) * 1.6, 0, 1)

    t = np.clip(yy / size, 0, 1)[..., None]
    grad = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t

    # 底部内阴影，让圆有点立体
    shade = np.clip((dist - r * 0.55) / (r * 0.55), 0, 1)[..., None] * 0.10
    grad = grad * (1 - shade * (yy / size)[..., None])

    rgba = np.dstack([np.clip(grad, 0, 255), cover * 255]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def build(size=S):
    # 整张贴进去，不裁剪。这样唯一的边界就是圆形，不会出现直线切口。
    base = Image.open(os.path.join(ASSETS, "pet_base.png")).convert("RGBA")
    scale = (size * FILL) / REF_W
    big = base.resize((max(1, int(base.width * scale)), max(1, int(base.height * scale))),
                      Image.LANCZOS)

    canvas = circle_bg(size)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hx = int(size / 2 - ANCHOR[0] * scale)
    hy = int(size * ANCHOR_Y - ANCHOR[1] * scale)
    layer.paste(big, (hx, hy), big)

    # 把脑袋裁进圆里，避免溢出边缘
    mask = canvas.split()[3]
    layer.putalpha(Image.composite(layer.split()[3], Image.new("L", (size, size), 0), mask))
    canvas.alpha_composite(layer)

    # 外圈描边
    d = ImageDraw.Draw(canvas)
    d.ellipse([1, 1, size - 2, size - 2], outline=(226, 200, 160, 210), width=max(2, size // 128))
    return canvas


def main():
    master = build(S)
    ico = os.path.join(ASSETS, "pet.ico")
    master.save(ico, format="ICO", sizes=SIZES)

    # 预览：浅底一行、深底一行
    prev = Image.new("RGBA", (1100, 340), (245, 243, 238, 255))
    d = ImageDraw.Draw(prev)
    d.rectangle([0, 170, 1100, 340], fill=(38, 40, 46, 255))
    x = 20
    for s in (256, 128, 64, 48, 32, 24, 16):
        im = master.resize((s, s), Image.LANCZOS)
        prev.alpha_composite(im, (x, 20 + (256 - s) // 2))
        prev.alpha_composite(im, (x, 190 + (256 - s) // 2))
        x += s + 18
    prev.convert("RGB").save(os.path.join(ASSETS, "_icon_preview.png"))
    print("写出", ico)


if __name__ == "__main__":
    main()
