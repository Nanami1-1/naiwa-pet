# -*- coding: utf-8 -*-
"""桌宠启动入口。

    python main.py

只允许跑一只。再点一次图标不会再冒出第二只。
关掉就直接退，右键桌宠有完整操作菜单。
"""

import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from config import SINGLETON
from version import VERSION
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication




def _already_running() -> bool:
    from PySide6.QtNetwork import QLocalSocket

    s = QLocalSocket()
    s.connectToServer(SINGLETON)
    ok = s.waitForConnected(200)
    if ok:
        s.disconnectFromServer()
    return ok


def _fatal(msg):
    """打包后没有控制台，出错必须弹窗，不然表现就是「双击没反应」。"""
    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("桌宠启动失败")
    box.setText(msg)
    box.exec()
    return 1


def main():
    from core.diag import log, setup

    setup(VERSION)
    log("启动，参数 %s" % (sys.argv[1:] or "无"))

    # 助手模式：不建窗口、不建 QApplication，纯粹做文件替换
    if "--apply-update" in sys.argv:
        from core.updater import run_updater

        return run_updater(sys.argv)

    app = QApplication(sys.argv)
    app.setApplicationName("Blobby")
    app.setQuitOnLastWindowClosed(True)

    if _already_running():
        return 0

    from PySide6.QtNetwork import QLocalServer

    server = QLocalServer()
    QLocalServer.removeServer(SINGLETON)   # 清掉上次异常退出留下的名字
    server.listen(SINGLETON)

    try:
        from ui.window import PetWindow

        pet = PetWindow()
    except SystemExit as e:
        return _fatal(str(e))
    except Exception as e:                       # noqa: BLE001
        import traceback

        return _fatal("%s\n\n%s" % (e, traceback.format_exc(limit=3)))

    pet.show()
    code = app.exec()
    server.close()

    # PySide6 6.12 在「窗口 + 发过网络请求」之后退出时，析构阶段会原生崩溃
    # （access violation，没有 Python 栈，用户看到的就是关掉时报错或直接消失）。
    # 普通 QWidget 不崩，只有这个带遮罩的透明窗口会崩，根因没找到。
    # 状态文件都是即时写盘的，没有需要 flush 的东西，直接结束进程绕开析构。
    from core.diag import log as _log

    _log("事件循环结束，硬退出（code=%s）" % code)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
