# -*- coding: utf-8 -*-
"""桌宠主窗口。"""

import math
import os
import subprocess
import time

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRect, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction, QActionGroup, QBitmap, QCursor, QDesktopServices, QGuiApplication, QImage,
    QPainter, QRegion,
)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

import config as C
from core import diag
from core import update as updater_net
from core import updater
from core.motion import Behavior
from core.needs import Needs
from core.sfx import Sfx
from core.sprite import SpriteSet
from ui.bubble import Overlay
from ui.update_progress import UpdateProgress
from version import VERSION

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

        # 更新检查：启动 5 秒后再查，别和开场动画抢时间
        self._update_info = None
        self._checker = None
        self._manual_check = False
        self._downloader = None
        self._update_progress = None
        self._download_info = None
        self._update_finishing = False
        QTimer.singleShot(5000, self._auto_check_update)

        # 上次更新完可能留下 _update/ 和 .bak，等助手进程退出后再清
        QTimer.singleShot(25000, self._cleanup_after_update)

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
        # 转圈时宽度变化很快，遮罩跟不上就会被窗口边缘切掉一块，
        # 看起来像「一卡一卡地变宽」——所以转圈期间每帧都重建。
        spinning = self.behavior.spin_t >= 0
        if key == self._mask_key or (self._mask_t > 0 and not spinning):
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

    # ---------------------------------------------------------------- 更新
    def _auto_check_update(self):
        """启动后自动查一次，一天最多查一次。"""
        state = updater_net.load_state()
        if updater_net.seconds_since_check(state) < updater_net.CHECK_INTERVAL:
            return
        self._manual_check = False
        self._start_update_check()

    def _start_update_check(self):
        if self._checker is not None:
            return
        self._checker = updater_net.UpdateChecker(self)
        self._checker.finished.connect(self._on_update_result)
        self._checker.start()

    def _on_update_result(self, info):
        diag.log("检查结果: %s" % (info.display if info else "无更新"))
        state = updater_net.load_state()
        state["last_check"] = time.time()
        updater_net.save_state(state)

        if self._checker is not None:
            self._checker.deleteLater()
            self._checker = None

        manual = self._manual_check
        self._manual_check = False

        if info is not None:
            self._update_info = info
            state["found"] = info.version
            updater_net.save_state(state)
            if state.get("skipped") != info.version or manual:
                self.overlay.say(C.UPDATE_LINE.format(ver=info.display))
        elif manual:
            self.overlay.say(C.UPDATE_LATEST)

    def _act_update(self):
        """菜单里点「更新到 x」。能下载就自动更新，不能就开网页。"""
        if self._downloader is not None or self._update_finishing:
            if self._update_progress is not None:
                self._update_progress.show_progress()
            return
        info = self._update_info
        diag.log("菜单：更新（info=%s）" % (info.display if info else "无"))
        if not info:
            self._manual_check = True
            self.overlay.say("我去问问……")
            self._start_update_check()
            return

        if not info.downloadable or not updater.can_write(updater.install_root()):
            # 没有安装包，或者装在只读目录 —— 退回手动下载
            if info.url:
                QDesktopServices.openUrl(QUrl(info.url))
            self.overlay.say("去网页下载吧")
            return

        if self._ask_update(info):
            self._start_download(info)

    def _ask_update(self, info) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("发现新版本")
        box.setText("发现新版本 %s" % info.display)
        extra = "要现在更新吗？更新会重启奶蛙，大概十几秒。"
        if info.notes:
            extra += "\n\n" + info.notes.strip()[:220]
        box.setInformativeText(extra)
        yes = box.addButton("现在更新", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后再说", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _start_download(self, info):
        if self._downloader is not None or self._update_finishing:
            return
        self.overlay.say("开始下载……")
        self._download_info = info
        if self._update_progress is None:
            self._update_progress = UpdateProgress(self)
        self._update_progress.begin(info.display, info.asset_size)
        self._update_progress.show_progress()
        self._downloader = updater_net.UpdateDownloader(self)
        self._downloader.progress.connect(self._on_download_progress)
        self._downloader.stage_changed.connect(self._on_download_stage)
        self._downloader.finished.connect(self._on_download_done)
        self._downloader.start(info)

    @Slot("qlonglong", "qlonglong")
    def _on_download_progress(self, got, total):
        if self._update_progress is not None:
            self._update_progress.set_progress(got, total)

    @Slot(str)
    def _on_download_stage(self, text):
        if self._update_progress is not None:
            self._update_progress.set_stage(text)

    @Slot(str, str)
    def _on_download_done(self, error, path):
        info = self._download_info
        if self._downloader is not None:
            self._downloader.deleteLater()
            self._downloader = None

        if error or not path:
            self._update_progress.fail(error or "没有收到安装包，请重试。")
            self.overlay.say("更新失败，等会儿再试")
            return

        self._update_finishing = True
        try:
            self._finish_download(info, path)
        finally:
            self._update_finishing = False

    def _finish_download(self, info, path):
        self._update_progress.set_stage("校验通过，正在解压安装包……")
        self._update_progress.repaint()
        try:
            src = updater.extract(path)
        except Exception as e:
            self._update_progress.fail("安装包解压失败：%s" % e)
            self.overlay.say("安装包解不开")
            return

        self._update_progress.hide()
        if not self._ask_restart(info):
            self.overlay.say("下载好了，想更新时右键我")
            return

        self._apply_update(src)

    def _ask_restart(self, info) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("准备就绪")
        box.setText("%s 已经下载好了" % info.display)
        box.setInformativeText("现在重启奶蛙，换上新的？")
        yes = box.addButton("马上重启", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("待会儿", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _apply_update(self, src):
        """启动助手进程去换文件，然后自己退出。"""
        exe = os.path.join(src, updater.EXE_NAME)
        if not os.path.exists(exe):
            self.overlay.say("安装包不完整")
            return

        try:
            subprocess.Popen(
                [exe, "--apply-update",
                 "--target", updater.install_root(),
                 "--src", src,
                 "--pid", str(os.getpid()),
                 "--lock", C.SINGLETON],
                cwd=src,
                close_fds=True,
            )
        except Exception:
            self.overlay.say("更新启动失败")
            return

        self.overlay.say("换新版本啦，一会儿见")
        QTimer.singleShot(350, self._quit_hard)

    def _quit_hard(self):
        QApplication.instance().quit()

    def _cleanup_after_update(self):
        """更新完的残局：删 staging 和 .bak。占用中就下次再说。"""
        if self._downloader is not None:
            return
        try:
            updater.cleanup_leftovers(keep_bak=True)
        except Exception:
            pass

    def _act_skip_version(self):
        if not self._update_info:
            return
        state = updater_net.load_state()
        state["skipped"] = self._update_info.version
        updater_net.save_state(state)
        self.overlay.say("好吧，这次不升")

    # ---------------------------------------------------------------- 菜单
    def _menu(self, gpos):
        self._build_menu().exec(gpos)

    def _build_menu(self) -> QMenu:
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

        a_hello = QAction("打招呼", m)
        a_hello.triggered.connect(self._act_hello)
        m.addAction(a_hello)

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

        a_vol = m.addMenu("音效音量")
        group = QActionGroup(a_vol)
        group.setExclusive(True)
        for label, val in C.SFX_VOLUME_CHOICES:
            act = QAction(label, a_vol)
            act.setCheckable(True)
            act.setChecked(abs(self.sfx.volume - val) < 0.05)
            act.triggered.connect(lambda _c=False, v=val, l=label: self._act_volume(v, l))
            group.addAction(act)
            a_vol.addAction(act)

        m.addSeparator()

        info = self._update_info
        updating = self._downloader is not None or self._update_finishing
        update_label = "更新到 %s" % info.display if info else "检查更新"
        a_up = QAction("查看更新进度" if updating else update_label, m)
        a_up.triggered.connect(self._act_update)
        m.addAction(a_up)

        if info:
            a_skip = QAction("这次不更新", m)
            a_skip.triggered.connect(self._act_skip_version)
            m.addAction(a_skip)

        a_ver = QAction("奶蛙 v%s" % VERSION, m)
        a_ver.setEnabled(False)
        m.addAction(a_ver)

        a_log = QAction("打开日志文件夹", m)
        a_log.triggered.connect(diag.open_folder)
        m.addAction(a_log)

        m.addSeparator()
        a_quit = QAction("退出", m)
        a_quit.triggered.connect(self._quit)
        m.addAction(a_quit)

        return m

    def _act_hello(self):
        self.behavior.wake()
        self.behavior._emote("happy", 1.6)
        self.overlay.say("你好呀！")

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

    def _act_volume(self, value, label=""):
        self.sfx.set_volume(value)
        self.overlay.say("音量调成%s了" % label if label else "音量调好了")
        # 立刻放一声让人听效果
        self.behavior._sfx("tap")

    def _quit(self):
        self.timer.stop()
        self.overlay.close()
        self.close()
        QGuiApplication.quit()
