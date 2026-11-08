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

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

SINGLETON = "blobby-pet-single-instance"


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
    return code


if __name__ == "__main__":
    sys.exit(main())
