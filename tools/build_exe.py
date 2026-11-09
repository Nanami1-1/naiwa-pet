# -*- coding: utf-8 -*-
"""打包成免安装的 Windows 程序。

    python tools/build_exe.py

产物：
    dist/Blobby/Blobby.exe      双击即用，不需要装 Python
    dist/Blobby/assets/         素材和音效，可以随时替换
    dist/Blobby-win64.zip       整个文件夹打包好，发这个给别人

用 onedir（文件夹）而不是 onefile（单文件），原因：
  - 启动快，onefile 每次都要把 Qt 解压到临时目录，要等好几秒
  - 素材是独立文件夹，别人想换音效直接丢进去就行
"""

import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:          # 脚本在 tools/ 下，要能 import 到根目录的 version
    sys.path.insert(0, BASE)
DIST = os.path.join(BASE, "dist")
BUILD = os.path.join(BASE, "build")
APP_NAME = "Blobby"

EXCLUDE = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtSensors", "PySide6.QtSpatialAudio", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtMultimediaWidgets", "PySide6.QtSvgWidgets",
    "tkinter", "unittest", "pydoc", "doctest", "email", "http", "xmlrpc", "pdb",
]

README_TXT = """Blobby 桌宠
================

双击 Blobby.exe 就会出现，站在屏幕底部。

能干什么
  按住拖动        拎着它走，甩出去会飞、会砸在地上弹
  单击            蹦一下，有话说
  双击            原地转圈
  连点五下以上    生气
  鼠标靠近        眼睛跟着你转
  右键            喂食 / 摸摸头 / 睡觉 / 别乱跑 / 静音 / 退出

想退出
  右键它 → 退出

换音效
  把 wav 或 mp3 丢进 assets\\sounds\\custom\\，文件名对应事件：
  tap 单击 / tap_many 连点生气 / drag 拖动 / land 落地 / pet 摸头
  feed 喂食 / hungry 饿了 / sleep 睡觉 / wake 叫醒 / spin 转圈
  中文名也行：点击、生气、拖动、落地、摸头、喂食、饿、睡觉、起床、转圈
  没放的会回落到 assets\\sounds\\ 里的默认音。

打不开 / 没反应
  1. 先在任务栏上沿、屏幕底部找找，可能已经在跑但被挡住了
     （同一时间只能有一只，重复打开不会再冒第二只）
  2. 提示缺文件的话，确认 assets 文件夹和 Blobby.exe 在一起

Windows 10 / 11 64 位
"""


def run(cmd):
    print(">", " ".join(cmd))
    p = subprocess.run(cmd, cwd=BASE)
    if p.returncode != 0:
        raise SystemExit("构建失败，返回码 %d" % p.returncode)


def copy_assets(dst_root):
    src = os.path.join(BASE, "assets")
    dst = os.path.join(dst_root, "assets")

    def ignore(dirpath, names):
        drop = []
        for n in names:
            if n in ("_orig", "__pycache__"):
                drop.append(n)
            elif n.startswith("_"):
                drop.append(n)
        return drop

    if os.path.exists(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, ignore=ignore)
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(dst) for f in fs)
    print("素材已复制: %.1f MB" % (total / 1024 / 1024))


def set_version(ver: str):
    """改写 version.py 里的 VERSION。必须赶在 PyInstaller 之前，否则打进 exe 的还是旧号。"""
    path = os.path.join(BASE, "version.py")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    import re
    # 用 subn 的命中次数判断，不能用「替换后文本有没有变」——
    # 想设的版本和现有版本相同时文本不变，会被误判成没找到
    new, hits = re.subn(r'(?m)^VERSION\s*=\s*"[^"]*"', 'VERSION = "%s"' % ver, text)
    if hits == 0:
        raise SystemExit("version.py 里没找到 VERSION 行")
    if new != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        print("版本号已改为 %s" % ver)
    else:
        print("版本号已经是 %s" % ver)


def write_version_json(ver: str):
    """给 jsDelivr 兜底源用的清单，发布前记得一起提交。

    必须自带附件地址和 sha256：GitHub API 被限流（共享出口 IP 很容易 403）时
    客户端会走这里，没有这些字段就只能降级成手动下载。
    """
    import json
    import hashlib

    from version import REPO

    zip_path = os.path.join(DIST, APP_NAME + "-win64.zip")
    size, digest = 0, ""
    if os.path.exists(zip_path):
        h = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        size, digest = os.path.getsize(zip_path), h.hexdigest()

    tag = "v" + ver
    data = {
        "version": ver,
        "url": "https://github.com/%s/releases/tag/%s" % (REPO, tag),
        "notes": "",
        "asset_url": "https://github.com/%s/releases/download/%s/%s-win64.zip"
                     % (REPO, tag, APP_NAME),
        "asset_size": size,
        "asset_sha256": digest,
    }
    path = os.path.join(BASE, "version.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("已生成 version.json（%.2f MB, sha256 %s…）" % (size / 1024 / 1024, digest[:12]))


def main():
    ver_arg = None
    for i, a in enumerate(sys.argv):
        if a == "--version" and i + 1 < len(sys.argv):
            ver_arg = sys.argv[i + 1].strip().lstrip("vV")
    if ver_arg:
        set_version(ver_arg)

    import importlib
    import version as ver_mod
    importlib.reload(ver_mod)
    VERSION = ver_mod.VERSION

    if not os.path.exists(os.path.join(BASE, "assets", "pet.ico")):
        raise SystemExit("缺少 assets/pet.ico，先跑 tools/make_icon.py")

    if "--no-clean" not in sys.argv:
        for d in (DIST, BUILD):
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", APP_NAME,
        "--icon", os.path.join(BASE, "assets", "pet.ico"),
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtNetwork",
    ]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    cmd.append("main.py")
    run(cmd)

    app_dir = os.path.join(DIST, APP_NAME)
    copy_assets(app_dir)
    with open(os.path.join(app_dir, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README_TXT)

    exe = os.path.join(app_dir, APP_NAME + ".exe")
    print("\n程序: %s (%.1f MB)" % (exe, os.path.getsize(exe) / 1024 / 1024))
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(app_dir) for f in fs)
    print("整个文件夹: %.1f MB" % (total / 1024 / 1024))

    zip_base = os.path.join(DIST, APP_NAME + "-win64")
    shutil.make_archive(zip_base, "zip", DIST, APP_NAME)
    print("压缩包: %s.zip (%.1f MB)" % (zip_base, os.path.getsize(zip_base + ".zip") / 1024 / 1024))

    write_version_json(VERSION)
    print("\n版本 %s 打包完成。发布流程：" % VERSION)
    print("  1. 提交 version.py / version.json")
    print("  2. 打 tag 并推送:  git tag v%s && git push --tags" % VERSION)
    print("  3. 网页建 Release，附件传上面的 zip")


if __name__ == "__main__":
    main()
