# -*- coding: utf-8 -*-
"""头顶的对话气泡 + 状态小药丸。

独立的一个透明小窗口，鼠标穿透，永远不会挡住桌面操作。
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

import config as C

PAD_X, PAD_Y = 13, 9
MAX_W = 196
RADIUS = 14
TAIL_H = 9


def heart_path(cx, cy, r):
    p = QPainterPath()
    p.moveTo(cx, cy + r * 0.78)
    p.cubicTo(cx - r * 1.35, cy - r * 0.20, cx - r * 0.50, cy - r * 1.18, cx, cy - r * 0.34)
    p.cubicTo(cx + r * 0.50, cy - r * 1.18, cx + r * 1.35, cy - r * 0.20, cx, cy + r * 0.78)
    p.closeSubpath()
    return p


class Overlay(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.font = QFont(C.FONT)
        self.font.setPixelSize(13)
        self.font.setWeight(QFont.Weight.Medium)

        self.msg = ""
        self.msg_t = 0.0
        self.msg_life = 2.6
        self.alpha = 0.0
        self.status = None          # (satiety, affection)
        self.status_t = 0.0
        self.tail_x = 0.0
        self._w = 0
        self._h = 0
        self._bubble_rect = QRectF()
        self._pill_rect = QRectF()
        self._text_rect = QRectF()

    # ---------------------------------------------------------------- 外部
    def say(self, text):
        if not text:
            return
        self.msg = text
        self.msg_t = self.msg_life
        self.alpha = 0.0
        self._measure()
        self.update()

    def show_status(self, satiety, affection, dur=2.6):
        self.status = (satiety, affection)
        self.status_t = dur
        self._measure()
        self.update()

    def clear(self):
        self.msg = ""
        self.msg_t = 0.0
        self.status = None
        self.status_t = 0.0
        self.hide()

    # ---------------------------------------------------------------- 尺寸
    def _measure(self):
        fm = QFontMetrics(self.font)
        show_bubble = bool(self.msg) and self.msg_t > 0
        show_pill = self.status is not None and self.status_t > 0

        bw = bh = 0
        if show_bubble:
            br = fm.boundingRect(
                0, 0, MAX_W, 1000,
                int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignHCenter),
                self.msg,
            )
            tw = max(br.width(), 22)
            th = br.height()
            bw = int(tw + PAD_X * 2)
            bh = int(th + PAD_Y * 2)

        pw = 158
        ph = 28 if show_pill else 0

        w = max(bw, pw if show_pill else 0)
        h = bh + (ph + 8 if (show_pill and show_bubble) else ph)
        if show_bubble:
            h += TAIL_H
        w = max(w, 40)
        self._w, self._h = int(w), int(h)

        self._bubble_rect = QRectF(0, 0, bw, bh) if show_bubble else QRectF()
        self._text_rect = QRectF(PAD_X, PAD_Y, bw - PAD_X * 2, bh - PAD_Y * 2) if show_bubble else QRectF()
        if show_pill:
            y = bh + (8 if show_bubble else 0)
            self._pill_rect = QRectF(0, y, pw, ph)
        else:
            self._pill_rect = QRectF()
        self.resize(self._w, self._h)

    # ---------------------------------------------------------------- 每帧
    def tick(self, dt, head_point: QPointF, screen_rect):
        if self.msg_t > 0:
            self.msg_t -= dt
            target = 1.0 if self.msg_t > 0.45 else max(0.0, self.msg_t / 0.45)
            self.alpha += (target - self.alpha) * min(1.0, dt * 12)
        else:
            self.alpha += (0.0 - self.alpha) * min(1.0, dt * 10)

        if self.status_t > 0:
            self.status_t -= dt
            if self.status_t <= 0:
                self.status = None
                self._measure()

        if self.alpha < 0.02 and self.msg_t <= 0 and not self.status:
            if self.isVisible():
                self.hide()
            return

        # 定位：气泡底边贴着头顶
        win_x = int(head_point.x() - self._w / 2)
        win_y = int(head_point.y() - self._h - 4)
        if win_y < screen_rect.top() + 4:
            win_y = int(head_point.y() + 26)   # 顶部放不下就翻到脚边
        win_x = max(screen_rect.left() + 4, min(screen_rect.right() - self._w - 4, win_x))

        self.tail_x = head_point.x() - win_x
        self.tail_x = max(20.0, min(self._w - 20.0, self.tail_x))

        if self.pos().x() != win_x or self.pos().y() != win_y:
            self.move(win_x, win_y)
        if not self.isVisible():
            self.show()
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, e):
        if self._w <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setOpacity(max(0.0, min(1.0, self.alpha)))

        if self._bubble_rect.width() > 0:
            self._paint_bubble(p)
        if self._pill_rect.width() > 0:
            self._paint_pill(p)
        p.end()

    def _bubble_path(self):
        r = self._bubble_rect
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        tail = QPainterPath()
        tx = max(r.left() + 18, min(r.right() - 18, self.tail_x))
        base = r.bottom() - 1
        tail.moveTo(tx - 8, base)
        tail.lineTo(tx + 8, base)
        tail.lineTo(tx - 1, base + TAIL_H)
        tail.closeSubpath()
        return path.united(tail)

    def _paint_bubble(self, p: QPainter):
        path = self._bubble_path()
        # 投影：偏移一版淡色，比高斯阴影便宜
        p.save()
        p.translate(0, 2.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(96, 72, 40, 26))
        p.drawPath(path)
        p.restore()

        p.setBrush(QColor(*C.CREAM, 250))
        p.setPen(QPen(QColor(*C.CREAM_EDGE, 190), 1.0))
        p.drawPath(path)

        p.setPen(QColor(*C.INK))
        p.setFont(self.font)
        p.drawText(self._text_rect, int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignHCenter), self.msg)

    def _paint_pill(self, p: QPainter):
        r = self._pill_rect
        p.save()
        p.translate(0, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(96, 72, 40, 22))
        p.drawRoundedRect(r, 14, 14)
        p.restore()

        p.setBrush(QColor(*C.CREAM, 245))
        p.setPen(QPen(QColor(*C.CREAM_EDGE, 170), 1.0))
        p.drawRoundedRect(r, 14, 14)

        sat, aff = self.status
        cy = r.center().y()

        # 饱食度
        ix = r.left() + 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(*C.FOOD))
        p.drawEllipse(QPointF(ix + 4, cy), 4.4, 4.4)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(ix + 2.8, cy - 1.6), 1.5, 1.5)
        self._bar(p, QRectF(ix + 13, cy - 3.2, 44, 6.4), sat / 100.0, C.FOOD)

        # 好感度
        hx = r.left() + 78
        p.setBrush(QColor(*C.HEART))
        p.drawPath(heart_path(hx + 4.5, cy + 0.5, 4.6))
        self._bar(p, QRectF(hx + 13, cy - 3.2, 44, 6.4), aff / 100.0, C.HEART)

    def _bar(self, p: QPainter, rect: QRectF, frac, color):
        frac = max(0.0, min(1.0, frac))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(*C.BAR_BG))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if frac > 0.01:
            w = max(rect.height(), rect.width() * frac)
            r2 = QRectF(rect.left(), rect.top(), w, rect.height())
            p.setBrush(QColor(*color))
            p.drawRoundedRect(r2, rect.height() / 2, rect.height() / 2)
