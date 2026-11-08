# -*- coding: utf-8 -*-
"""逐个放一遍所有音效事件，确认哪个事件落在哪个文件上、能不能出声。

    python tools/check_sound.py

每个只放 1.5 秒（有些素材本身很长），放完打印一张对照表。
"""

import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

from config import CUSTOM_SOUNDS
from core.sfx import EVENTS, Sfx

PREVIEW_MS = 1500

EVENT_PAT = re.compile(r"""(?:_sfx|sfx\.play)\(\s*["']([a-zA-Z_]+)["']""")


def scan_used_events():
    """扫源码里实际喊了哪些事件名，揪出和事件表对不上的拼写。"""
    used = {}
    for sub in ("core", "ui"):
        d = os.path.join(BASE, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    for m in EVENT_PAT.finditer(line):
                        used.setdefault(m.group(1), []).append("%s:%d" % (fn, lineno))
    return used


def check_names():
    used = scan_used_events()
    bad = {k: v for k, v in used.items() if k not in EVENTS}
    unused = [k for k in EVENTS if k not in used]
    if bad:
        print("!! 代码里调用了事件表里没有的名字，这些永远不会响：")
        for k, where in bad.items():
            print("   %-12s %s" % (k, ", ".join(where)))
        print()
    else:
        print("事件名检查：全部对得上")
    if unused:
        print("   事件表里暂未被代码调用：%s" % ", ".join(unused))
    print()


def main():
    check_names()
    app = QApplication(sys.argv[:1])
    sfx = Sfx()

    dev = QMediaDevices.defaultAudioOutput()
    print("音频输出设备:", dev.description() or "（无）")
    if not dev.description():
        print("!! 系统没有可用的音频输出设备，下面会看到全是静音")
    print()

    pl = QMediaPlayer()
    out = QAudioOutput()
    pl.setAudioOutput(out)
    out.setVolume(0.9)
    pl.errorOccurred.connect(lambda e, s: print("   [错误]", e, s))

    rows = []
    queue = list(EVENTS.items())
    state = {"i": 0}

    def step():
        i = state["i"]
        if i >= len(queue):
            print("\n%-10s %-6s %s" % ("事件", "来源", "文件"))
            print("-" * 62)
            for ev, src, path, dur in rows:
                name = os.path.basename(path) if path else "（没有）"
                print("%-10s %-6s %s  %s" % (ev, src, name, ("%.1fs" % (dur / 1000)) if dur else ""))
            print("\n以上每个事件都会放 1.5 秒。听不到声音的话先看上面的设备名。")
            app.quit()
            return

        ev, desc = queue[i]
        path = sfx.resolve(ev)
        if path:
            same = os.path.normcase(os.path.dirname(os.path.abspath(path))) == \
                   os.path.normcase(os.path.abspath(CUSTOM_SOUNDS))
            src = "自定义" if same else "内置"
        else:
            src = "-"
        print("▶ %-10s %s   %s" % (ev, desc, os.path.basename(path) if path else "（无文件）"))

        if path:
            pl.setSource(QUrl.fromLocalFile(path))
            pl.play()

        def after():
            dur = pl.duration()
            rows.append((ev, src, path, dur))
            pl.stop()
            state["i"] += 1
            QTimer.singleShot(120, step)

        QTimer.singleShot(PREVIEW_MS, after)

    QTimer.singleShot(200, step)
    app.exec()


if __name__ == "__main__":
    main()
