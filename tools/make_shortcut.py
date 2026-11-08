# -*- coding: utf-8 -*-
"""在桌面放一个带头像图标的快捷方式。

    python tools/make_shortcut.py

Windows 的 .bat 本身不能挂自定义图标（这是系统限制，图标属于 exe/lnk/ico），
所以桌面上放的是 .lnk，指向项目里的 run.bat，双击行为完全一样。
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_BAT = os.path.join(BASE, "run.bat")
ICON = os.path.join(BASE, "assets", "pet.ico")
NAME = "桌宠"


def desktop_dir() -> str:
    """优先用注册表里记录的桌面位置（兼容 OneDrive 重定向）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        path = os.path.expandvars(val)
        if os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    import pylnk3

    if not os.path.exists(RUN_BAT):
        raise SystemExit("找不到 %s" % RUN_BAT)
    if not os.path.exists(ICON):
        raise SystemExit("找不到图标 %s，先跑 tools/make_icon.py" % ICON)

    desk = desktop_dir()
    lnk = os.path.join(desk, NAME + ".lnk")
    if os.path.exists(lnk):
        os.remove(lnk)

    pylnk3.for_file(
        RUN_BAT,
        lnk,
        description="黄色桌宠",
        icon_file=ICON,
        icon_index=0,
        work_dir=BASE,
        window_mode=pylnk3.WINDOW_MINIMIZED,
    )

    # 回读校验
    link = pylnk3.parse(lnk)
    print("桌面目录 :", desk)
    print("快捷方式 :", lnk, "存在" if os.path.exists(lnk) else "没生成")
    print("指向     :", link.link_info.local_base_path if link.link_info else "?")
    print("工作目录 :", link.work_dir)
    print("图标     :", link.icon, "index", link.icon_index)


if __name__ == "__main__":
    main()
