# -*- coding: utf-8 -*-
"""精灵图加载与绘制。

一次绘制要做的事：
  身体（含表情变体交叉淡化）→ 虹膜底板 → 可动瞳孔 → 高光点 → 脚下软投影
所有绘制都在「脚底为原点」的坐标系里做，挤压拉伸就不会飘。
"""

import json
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QPainter, QPixmap, QRadialGradient, QTransform,
)

import config as C

MAX_ROT = 4.0


class Pose:
    """一帧的形变参数。"""

    __slots__ = ("sx", "sy", "rot", "flip", "gaze", "variant", "variant_a", "contact", "alpha")

    def __init__(self):
        self.sx = 1.0
        self.sy = 1.0
        self.rot = 0.0
        self.flip = False
        self.gaze = (0.0, 0.0)
        self.variant = None
        self.variant_a = 0.0
        self.contact = 1.0   # 1=脚踩地，0=腾空
        self.alpha = 1.0


def _load(path):
    img = QImage(path)
    if img.isNull():
        raise SystemExit("读不到图片: %s" % path)
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


class SpriteSet:
    def __init__(self, height=None, dpr=2.0):
        meta_path = os.path.join(C.ASSETS, "eyes.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)

        self.src_h = self.meta["height"]
        self.src_w = self.meta["width"]
        self.h = float(height or C.PET_H)
        self.scale = self.h / self.src_h          # 源图坐标 → 逻辑坐标
        self.w = round(self.src_w * self.scale)

        self.dpr = dpr
        dev_h = int(round(self.h * dpr))
        dev_w = int(round(self.w * dpr))

        self.images = {}
        for key in ("base", "blink", "happy", "angry", "sleep"):
            path = os.path.join(C.ASSETS, "pet_%s.png" % key)
            if not os.path.exists(path):
                continue
            img = _load(path).scaled(
                dev_w, dev_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            self.images[key] = pm

        if "base" not in self.images:
            raise SystemExit("缺少 assets/pet_base.png，先跑 tools/build_assets.py")

        # 近眼（会跟随鼠标的那只）
        self.near = None
        self.far = None
        for e in self.meta.get("eyes", []):
            if e.get("gaze") and e.get("plate"):
                self.near = e
            elif not e.get("gaze"):
                self.far = e

        self.plate = None
        self.plate_rect = None
        self.plate_center = None
        self.pupil_r = 0.0
        self.travel = 0.0
        if self.near:
            plate_path = os.path.join(C.ASSETS, self.near["plate"])
            if os.path.exists(plate_path):
                x0, y0, x1, y1 = self.near["box"]
                pw = max(1, int(round((x1 - x0) * self.scale * dpr)))
                ph = max(1, int(round((y1 - y0) * self.scale * dpr)))
                img = _load(plate_path).scaled(
                    pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.plate = QPixmap.fromImage(img)
                self.plate.setDevicePixelRatio(dpr)
                self.plate_rect = QRectF(
                    (x0 - self.src_w / 2) * self.scale,
                    (y0 - self.src_h) * self.scale,
                    (x1 - x0) * self.scale,
                    (y1 - y0) * self.scale,
                )
                px, py, pr = self.near["pupil"]
                self.plate_center = QPointF(
                    (px - self.src_w / 2) * self.scale,
                    (py - self.src_h) * self.scale,
                )
                self.pupil_r = max(1.4, pr * self.scale)
                iris_r = (x1 - x0) / 2.0
                self.travel = max(0.0, (iris_r - pr) * 0.85) * self.scale

        self.hit_img = _load(os.path.join(C.ASSETS, "pet_base.png"))
        self.last_transform = QTransform()

    # ---------------------------------------------------------------- 几何
    def window_size(self):
        return (self.w + 2 * C.MARGIN, int(self.h) + C.MARGIN + C.SHADOW_H)

    @property
    def feet_origin(self):
        return QPointF(self.w / 2 + C.MARGIN, self.h + C.MARGIN)

    # ---------------------------------------------------------------- 绘制
    def draw(self, painter: QPainter, pose: Pose, origin: QPointF = None):
        origin = origin or self.feet_origin
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if pose.contact > 0.02:
            self._draw_shadow(painter, pose, origin)

        t = QTransform()
        t.translate(origin.x(), origin.y())
        t.rotate(pose.rot)
        t.scale((1.0 if not pose.flip else -1.0) * pose.sx, pose.sy)
        self.last_transform = t

        painter.save()
        painter.setOpacity(pose.alpha * pose.alpha)
        painter.setTransform(t, True)

        top_left = QPointF(-self.w / 2.0, -self.h)
        painter.drawPixmap(top_left, self.images["base"])

        # 表情变体（叠加淡化）
        base_variant = pose.variant if pose.variant in self.images else None
        if base_variant and pose.variant_a > 0.001:
            painter.setOpacity(pose.alpha * pose.variant_a)
            painter.drawPixmap(top_left, self.images[base_variant])

        # 可动瞳孔（睁眼时才有）
        eye_a = pose.alpha * max(0.0, 1.0 - pose.variant_a)
        if self.plate is not None and eye_a > 0.01:
            painter.setOpacity(eye_a)
            painter.drawPixmap(self.plate_rect.topLeft(), self.plate)
            self._draw_pupil(painter, pose)

        painter.restore()
        painter.setOpacity(1.0)

    def _draw_pupil(self, painter, pose):
        # gaze 是屏幕方向，但镜像时画笔的 x 轴是反的，
        # 不取反的话瞳孔会朝相反方向看。
        gx = max(-1.0, min(1.0, pose.gaze[0])) * self.travel
        if pose.flip:
            gx = -gx
        gy = max(-1.0, min(1.0, pose.gaze[1])) * self.travel * 0.75
        c = QPointF(self.plate_center.x() + gx, self.plate_center.y() + gy)
        r = self.pupil_r * (1.0 + 0.06 * (1 - abs(pose.gaze[1])))

        grad = QRadialGradient(c, r * 1.05)
        grad.setColorAt(0.0, QColor(26, 30, 20))
        grad.setColorAt(0.82, QColor(16, 19, 12))
        grad.setColorAt(1.0, QColor(16, 19, 12, 210))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(c, r, r)

        # 高光跟着瞳孔走，眼睛才有"看"的感觉
        gr = max(1.0, r * 0.34)
        gc = QPointF(c.x() - r * 0.34, c.y() - r * 0.40)
        painter.setBrush(QColor(255, 255, 255, 225))
        painter.drawEllipse(gc, gr, gr)
        painter.setBrush(QColor(255, 255, 255, 90))
        painter.drawEllipse(QPointF(c.x() + r * 0.30, c.y() + r * 0.34), gr * 0.45, gr * 0.45)

    def _draw_shadow(self, painter, pose, origin):
        k = max(0.0, min(1.0, pose.contact))
        # 转圈时整只被压扁，影子跟着变窄，看起来才像真的在原地转
        narrow = 0.55 + 0.45 * min(1.0, max(0.0, pose.sx))
        w = self.w * (0.60 + 0.10 * (pose.sy - 1.0) * 3) * (1.0 + 0.25 * (1 - k)) * narrow
        h = max(4.0, self.w * 0.11 * (0.75 + 0.45 * k))
        cy = origin.y() - h * 0.25 + 2
        rect = QRectF(origin.x() - w / 2, cy - h / 2, w, h)

        grad = QRadialGradient(QPointF(origin.x(), cy), w / 2)
        a = int(58 * k)
        grad.setColorAt(0.0, QColor(40, 30, 16, a))
        grad.setColorAt(0.55, QColor(40, 30, 16, int(a * 0.55)))
        grad.setColorAt(1.0, QColor(40, 30, 16, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(rect)

    # ---------------------------------------------------------------- 命中
    def hit_test(self, pos: QPointF) -> bool:
        inv, ok = self.last_transform.inverted()
        if not ok:
            return False
        p = inv.map(pos)
        lx = p.x() + self.w / 2.0
        ly = p.y() + self.h
        if not (0 <= lx < self.w and 0 <= ly < self.h):
            return False
        x = int(lx * self.src_w / self.w)
        y = int(ly * self.src_h / self.h)
        if not (0 <= x < self.src_w and 0 <= y < self.src_h):
            return False
        return self.hit_img.pixelColor(x, y).alpha() > 40
