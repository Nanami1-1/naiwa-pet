# -*- coding: utf-8 -*-
"""崩溃与关键事件日志。

打包后没有控制台，如果进程被外部干掉（杀软）或者原生崩溃（段错误），
用户那边只会看到「程序没了，什么都不显示」——什么线索都没有。

这里做两件事：
  faulthandler  抓原生崩溃，能把崩溃瞬间的栈写进文件
  excepthook    抓 Python 异常（槽函数里的也会经过这里）

日志在 %APPDATA%\\NaiwaPet\\app.log，用户可以直接发过来。
"""

import os
import sys
import time
import traceback

_LOG = None
_START = time.time()


def log_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "NaiwaPet")
    os.makedirs(folder, exist_ok=True)
    return folder


def log_path() -> str:
    return os.path.join(log_dir(), "app.log")


def setup(version: str = "?"):
    global _LOG
    try:
        _LOG = open(log_path(), "a", encoding="utf-8", buffering=1)
    except Exception:
        return

    _LOG.write("\n===== 启动 %s | v%s | pid=%d =====\n"
               % (time.strftime("%Y-%m-%d %H:%M:%S"), version, os.getpid()))

    # 原生崩溃（段错误等）也能留下栈
    try:
        import faulthandler

        faulthandler.enable(file=_LOG, all_threads=True)
    except Exception:
        pass

    sys.excepthook = _hook

    # 窗口化运行时 stderr 是 None，槽里抛的异常会彻底消失
    if sys.stderr is None:
        sys.stderr = _LOG


def _hook(tp, value, tb):
    try:
        if _LOG is not None:
            _LOG.write("===== 未捕获异常 %s =====\n" % time.strftime("%H:%M:%S"))
            _LOG.write("".join(traceback.format_exception(tp, value, tb)))
            _LOG.flush()
    except Exception:
        pass
    # 有控制台时照旧打出来
    try:
        sys.__excepthook__(tp, value, tb)
    except Exception:
        pass


def log(msg: str):
    """记一条普通事件。"""
    if _LOG is None:
        return
    try:
        _LOG.write("[%6.1fs] %s\n" % (time.time() - _START, msg))
    except Exception:
        pass


def open_folder():
    """在资源管理器里打开日志目录，方便用户把文件发出来。"""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir()))
