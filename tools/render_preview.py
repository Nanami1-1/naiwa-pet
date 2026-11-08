# -*- coding: utf-8 -*-
"""不开窗口，把关键姿态渲染成一张对照图，用来检查形变和表情。

    python tools/render_preview.py out.png
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

import config as C
from core.motion import AIR, IDLE, SLEEP, WALK, Behavior
from core.needs import Needs
from core.sprite import SpriteSet
from ui.bubble import Overlay


def build_pose(b, name):
    b.state = IDLE
    b.squash.v = 0.0
    b.squash.vv = 0.0
    b.blink_anim = 0.0
    b.emote = None
    b.emote_t = 0.0
    b.spin_t = -1.0
    b.contact = 1.0
    b.gaze = (0.0, 0.0)
    b.facing_right = False

    if name == "idle":
        b.t = 0.0
    elif name == "blink":
        b.blink_anim = C.BLINK_DUR * 0.5
    elif name == "happy":
        b.emote, b.emote_t = "happy", 1.0
    elif name == "angry":
        b.emote, b.emote_t = "angry", 1.0
    elif name == "sleep":
        b.state = SLEEP
    elif name == "land":
        b.squash.v = 5.5
    elif name == "stretch":
        b.contact = 0.1
        b.squash.v = -3.4
    elif name == "walk":
        b.state = WALK
        b.facing_right = True
        b.t = 0.18
    elif name == "spin":
        b.spin_t = 0.32
    elif name == "gaze":
        b.gaze = (0.95, 0.15)
    return b.pose()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "assets", "_preview.png")
    app = QApplication(sys.argv[:1])

    sprite = SpriteSet()
    needs = Needs()
    b = Behavior(sprite, needs)
    cw, ch = sprite.window_size()
    names = ["idle", "blink", "happy", "angry", "sleep", "land", "stretch", "walk", "spin", "gaze"]
    cols = 5
    rows = (len(names) + cols - 1) // cols
    pad = 10
    label_h = 20
    W = cols * (cw + pad) + pad
    H = rows * (ch + pad + label_h) + pad + 10

    sheet = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor(238, 235, 228))

    p = QPainter(sheet)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    f = QFont(C.FONT)
    f.setPixelSize(12)
    p.setFont(f)

    for i, name in enumerate(names):
        cx = pad + (i % cols) * (cw + pad)
        cy = pad + (i // cols) * (ch + pad + label_h)
        p.setPen(QPen(QColor(210, 205, 195), 1))
        p.setBrush(QColor(246, 244, 239))
        p.drawRoundedRect(cx, cy, cw, ch, 8, 8)

        p.save()
        p.translate(cx, cy)
        pose = build_pose(b, name)
        sprite.draw(p, pose)
        p.restore()

        p.setPen(QColor(120, 108, 92))
        p.drawText(QRect(cx, cy + ch + 2, cw, label_h), Qt.AlignmentFlag.AlignCenter, name)

    p.end()
    sheet.save(out)

    # 气泡单独来一张
    ov = Overlay()
    ov.say("嘿嘿，再摸摸～")
    ov.show_status(72, 46)
    ov.alpha = 1.0
    ov.tick(0.016, QPointF(200, 200), QRect(0, 0, 1200, 900))
    ov.alpha = 1.0
    ov.resize(ov._w, ov._h)
    pm = ov.grab()
    bg = QImage(pm.width() + 40, pm.height() + 40, QImage.Format.Format_ARGB32_Premultiplied)
    bg.fill(QColor(238, 235, 228))
    q = QPainter(bg)
    q.drawPixmap(20, 20, pm)
    q.end()
    bg.save(os.path.join(BASE, "assets", "_preview_bubble.png"))
    print("写出", out, "和 _preview_bubble.png")


if __name__ == "__main__":
    main()
