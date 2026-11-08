# -*- coding: utf-8 -*-
"""端到端验证：找到桌宠、按住拖动、松手看它飞出去落地。

会真的移动鼠标，结束后把光标放回原处。
"""

import ctypes
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "assets")

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from PIL import Image, ImageGrab

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def find_pet(im):
    """在截图下半部分找黄色主体。"""
    w, h = im.size
    px = im.load()
    xs = []
    ys = []
    step = 4
    for y in range(int(h * 0.45), h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y][:3]
            if r > 195 and g > 130 and b < 130 and (r - b) > 90:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def main():
    orig = ctypes.windll.user32.GetCursorPos  # noqa
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p0 = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p0))

    proc = subprocess.Popen([sys.executable, os.path.join(BASE, "main.py")],
                            cwd=BASE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2.2)
        im = ImageGrab.grab()
        box = find_pet(im)
        if not box:
            print("没找到桌宠")
            return
        x0, y0, x1, y1 = box
        cx = (x0 + x1) // 2
        head = (cx, y0 + int((y1 - y0) * 0.30))
        print("桌宠包围盒", box, "抓取点", head)

        im.crop((x0 - 60, y0 - 80, x1 + 60, y1 + 40)).save(os.path.join(OUT, "_t0_idle.png"))

        ctypes.windll.user32.SetCursorPos(*head)
        time.sleep(0.25)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.12)

        tx, ty = head[0] - 260, head[1] - 300
        steps = 14
        for i in range(1, steps + 1):
            ctypes.windll.user32.SetCursorPos(
                int(head[0] + (tx - head[0]) * i / steps),
                int(head[1] + (ty - head[1]) * i / steps))
            time.sleep(0.018)
        time.sleep(0.10)
        im = ImageGrab.grab()
        im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(os.path.join(OUT, "_t1_dragging.png"))

        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.22)
        im = ImageGrab.grab()
        im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(os.path.join(OUT, "_t2_thrown.png"))

        time.sleep(1.6)
        im = ImageGrab.grab()
        box2 = find_pet(im)
        print("落地后包围盒", box2)
        im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(
            os.path.join(OUT, "_t3_landed.png"))
        if box2:
            im.crop((box2[0] - 90, box2[1] - 90, box2[2] + 90, min(im.height, box2[3] + 70))).save(
                os.path.join(OUT, "_t3_zoom.png"))
        print("截图已写入 assets/_t*.png")
    finally:
        proc.terminate()
        time.sleep(0.3)
        ctypes.windll.user32.SetCursorPos(p0.x, p0.y)


if __name__ == "__main__":
    main()
