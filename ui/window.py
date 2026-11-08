# -*- coding: utf-8 -*-
"""桌宠主窗口。"""

import math
import os

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import (
    QAction, QBitmap, QCursor, QGuiApplication, QImage, QPainter, QRegion,
)
from PySide6.QtWidgets import QMenu, QWidget

import config as C
from core.motion import Behavior
from core.needs import Needs
from core.sfx import Sfx
from core.sprite import SpriteSet
from ui.bubble import Overlay

MASK_ON = True          # 关掉它可以让透明区也能点，但会挡住桌面
MASK_THROTTLE = 0.12    # 秒


class PetWindow(QWidget):
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
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setMouseTracking(True)

        self.sprite = SpriteSet()
        self.needs = Needs()
        self.sfx = Sfx(enabled=True)
        self.overlay = Overlay()

        self.setFixedSize(*self.sprite.window_size())

        self.behavior = Behavior(
            self.sprite, self.needs,
            sfx=self.sfx,
            say=self._say,
        )
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.behavior.place(scr, x=scr.center().x() - 40)

        self._press_pos = None
        self._press_global = None
        self._moved = 0.0
        self._pending_click = False
        self._drag = False
        self._hover_t = 0.0
        self._status_cd = 0.0
        self._mask_key = None
        self._mask_t = 0.0

        self.clock = QElapsedTimer()
        self.clock.start()
        self._last = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / C.FPS))
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.sfx.preload()
        self._sync_pos()
        self._say("tap")

    # ---------------------------------------------------------------- 提示
    def _say(self, key):
        if isinstance(key, str) and key in C.LINES:
            self.overlay.say(self.needs.speech(key))
        elif key:
            self.overlay.say(str(key))

    def _bounds(self) -> QRect:
        p = QPoint(int(self.behavior.x), int(self.behavior.y - self.sprite.h * 0.5))
        scr = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    # ---------------------------------------------------------------- 主循环
    def _tick(self):
        now = self.clock.elapsed() / 1000.0
        dt = min(0.05, max(0.001, now - self._last))
        self._last = now

        b = self._bounds()
        cursor = QCursor.pos()
        self.behavior.update(dt, b, QPointF(cursor))

        self._sync_pos()
        self._sync_mask(dt)
        self._hover_check(dt, cursor)

        head = QPointF(self.behavior.x, self.behavior.y - self.sprite.h - 2)
        self.overlay.tick(dt, head, b)
        self.update()

    def _sync_pos(self):
        x = int(round(self.behavior.x - self.sprite.w / 2 - C.MARGIN))
        y = int(round(self.behavior.y - self.sprite.h - C.MARGIN))
        if self.pos().x() != x or self.pos().y() != y:
            self.move(x, y)

    def _hover_check(self, dt, cursor):
        local = QPointF(self.mapFromGlobal(cursor))
        if self._drag:
            self._hover_t = 0.0
            return
        if self.sprite.hit_test(local):
            self._hover_t += dt
            self._status_cd -= dt
            if self._hover_t > 0.7 and self._status_cd <= 0:
                self.overlay.show_status(self.needs.satiety, self.needs.affection)
                self._status_cd = 6.0
        else:
            self._hover_t = 0.0

    # ---------------------------------------------------------------- 遮罩
    def _sync_mask(self, dt):
        self._mask_t -= dt
        if not MASK_ON:
            if self._mask_key is not None:
                self.clearMask()
                self._mask_key = None
            return
        if self._drag:
            return
        p = self.behavior.pose()
        key = (round(p.sx, 2), round(p.sy, 2), int(p.rot // 1), p.flip)
        if key == self._mask_key or self._mask_t > 0:
            return
        self._mask_key = key
        self._mask_t = MASK_THROTTLE

        img = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        pa = QPainter(img)
        pa.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.sprite.draw(pa, p)
        pa.end()
        alpha = img.createAlphaMask()
        self.setMask(QRegion(QBitmap.fromImage(alpha)))

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, e):
        p = QPainter(self)
        self.sprite.draw(p, self.behavior.pose())
        p.end()

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if not self.sprite.hit_test(e.position()):
            e.ignore()
            return
        self.behavior.wake()
        self._drag = False
        self._moved = 0.0
        self._press_global = e.globalPosition()
        self._press_pos = e.position()
        self.behavior.press(QPointF(e.globalPosition()))
        e.accept()

    def mouseMoveEvent(self, e):
        if self._press_global is None:
            return
        if not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = e.globalPosition() - self._press_global
        self._moved = max(self._moved, math.hypot(delta.x(), delta.y()))
        if self._moved > 5 and not self._drag:
            self._drag = True
            self.clearMask()
            self._mask_key = None
        if self._drag:
            self.behavior.drag_to(QPointF(e.globalPosition()))
            self._sync_pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        self._press_global = None
        if self._drag:
            self.behavior.release(self._bounds())
            self._drag = False
            self._mask_key = None
        else:
            self._pending_click = True
            QTimer.singleShot(215, self._fire_click)

    def _fire_click(self):
        if not self._pending_click:
            return
        self._pending_click = False
        self.behavior.click()
        self.overlay.show_status(self.needs.satiety, self.needs.affection, dur=1.6)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._pending_click = False
        self.behavior.double_click()

    def wheelEvent(self, e):
        e.accept()

    # ---------------------------------------------------------------- 菜单
    def _menu(self, gpos):
        m = QMenu(self)
        m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        m.setStyleSheet("""
            QMenu {
                background: rgba(255, 251, 243, 248);
                border: 1px solid rgba(232, 218, 196, 210);
                border-radius: 12px;
                padding: 6px;
                font-family: "%s";
                font-size: 13px;
                color: rgb(58, 48, 36);
            }
            QMenu::item {
                padding: 7px 26px 7px 14px;
                border-radius: 8px;
                margin: 1px 2px;
            }
            QMenu::item:selected {
                background: rgba(240, 168, 48, 40);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(232, 218, 196, 180);
                margin: 5px 8px;
            }
        """ % C.FONT)

        a_feed = QAction("喂点东西", m)
        a_feed.triggered.connect(self._act_feed)
        m.addAction(a_feed)

        a_pet = QAction("摸摸头", m)
        a_pet.triggered.connect(self._act_pet)
        m.addAction(a_pet)

        m.addSeparator()

        a_sleep = QAction("叫醒它" if self.behavior.sleepy else "让它睡会儿", m)
        a_sleep.triggered.connect(self._act_sleep)
        m.addAction(a_sleep)

        a_walk = QAction("让它自己溜达" if self.behavior.staying else "就待在这别动", m)
        a_walk.triggered.connect(self._act_walk)
        m.addAction(a_walk)

        a_mute = QAction("关掉音效" if self.sfx.enabled else "打开音效", m)
        a_mute.triggered.connect(self._act_mute)
        m.addAction(a_mute)

        m.addSeparator()
        a_quit = QAction("退出", m)
        a_quit.triggered.connect(self._quit)
        m.addAction(a_quit)

        m.exec(gpos)

    def _act_feed(self):
        self.behavior.feed()
        self.overlay.show_status(self.needs.satiety, self.needs.affection)

    def _act_pet(self):
        self.behavior.pet_head()
        self.overlay.show_status(self.needs.satiety, self.needs.affection)

    def _act_sleep(self):
        self.behavior.toggle_sleep(self._bounds())

    def _act_walk(self):
        self.behavior.staying = not self.behavior.staying
        if self.behavior.staying and self.behavior.state == "walk":
            self.behavior.state = "idle"

    def _act_mute(self):
        self.sfx.toggle()
        self.overlay.say("静音了" if not self.sfx.enabled else "有声音了")

    def _quit(self):
        self.timer.stop()
        self.overlay.close()
        self.close()
        QGuiApplication.quit()
