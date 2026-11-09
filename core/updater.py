# -*- coding: utf-8 -*-
"""下载、校验、解压、替换、回滚。

一期只提示，这里是二期：真的把新版本换上去。

Windows 有两个绕不开的限制：
  1. 正在运行的 exe 不能被覆盖 —— 所以要有一个「助手进程」等主程序退出后再动手
  2. 助手进程自己也在被换的目录里 —— 所以它跑在 staging 里，替换完由新程序负责清理

助手就是新版本的 exe 本身，用 --apply-update 参数启动，不创建窗口。
这样不用额外打包一个 Updater.exe。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile

STAGING = "_update"
PKG_DIR = "pkg"
EXE_NAME = "Blobby.exe"
BAK_SUFFIX = ".bak"

# 用户可能改过自己的音效，更新时不覆盖已存在的文件
USER_SOUNDS = os.path.join("assets", "sounds", "custom")


# ---------------------------------------------------------------- 路径

def install_root() -> str:
    """程序所在目录。打包后是 exe 同级目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def staging_root() -> str:
    return os.path.join(install_root(), STAGING)


def can_write(path: str) -> bool:
    """能不能往这个目录写。装在 Program Files 里就会失败。"""
    probe = os.path.join(path, ".naiwa_write_test")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 校验

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_zip(path: str, expect_size: int = 0, expect_sha256: str = "") -> str:
    """返回空串表示通过，否则返回错误说明。"""
    if not os.path.exists(path):
        return "文件不存在"
    size = os.path.getsize(path)
    if expect_size and size != expect_size:
        return "大小不对（%d，应为 %d）" % (size, expect_size)
    if expect_sha256:
        digest = sha256_file(path)
        if digest.lower() != expect_sha256.lower().replace("sha256:", ""):
            return "校验和不匹配"
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            if bad:
                return "压缩包里 %s 已损坏" % bad
    except Exception as e:
        return "不是有效的压缩包：%s" % e
    return ""


# ---------------------------------------------------------------- 解压

def extract(path: str) -> str:
    """解压到 staging，返回真正的程序目录（zip 里通常套了一层 Blobby/）。"""
    root = staging_root()
    pkg = os.path.join(root, PKG_DIR)
    if os.path.isdir(pkg):
        shutil.rmtree(pkg, ignore_errors=True)
    os.makedirs(pkg, exist_ok=True)

    with zipfile.ZipFile(path) as z:
        z.extractall(pkg)

    entries = [e for e in os.listdir(pkg) if not e.startswith("__MACOSX")]
    if len(entries) == 1 and os.path.isdir(os.path.join(pkg, entries[0])):
        return os.path.join(pkg, entries[0])
    return pkg


# ---------------------------------------------------------------- 拷贝

def copy_tree(src: str, dst: str, skip_user_sounds: bool = True) -> int:
    """把 src 覆盖到 dst。返回写了多少个文件。"""
    written = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(out, name)
            relfile = os.path.normpath(os.path.join(rel, name))
            if skip_user_sounds and relfile.startswith(USER_SOUNDS) and os.path.exists(d):
                continue          # 用户自己的音效，留着
            shutil.copy2(s, d)
            written += 1
    return written


# ---------------------------------------------------------------- 助手模式

def _pid_alive(pid: int) -> bool:
    """进程还活着吗。用 WaitForSingleObject 查，比 tasklist 可靠也不受编码影响。"""
    if pid <= 0:
        return False
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def _wait_port_free(port_name: str, timeout: float) -> None:
    """等单实例锁释放，否则新程序会以为自己已经跑起来了，直接退出。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            from PySide6.QtNetwork import QLocalSocket
            s = QLocalSocket()
            s.connectToServer(port_name)
            if not s.waitForConnected(200):
                s.abort()
                return
            s.disconnectFromServer()
            s.abort()
        except Exception:
            return
        time.sleep(0.3)


def run_updater(argv) -> int:
    """助手进程入口：等主程序退出 → 备份 → 覆盖 → 拉起 → 不行就回滚。"""
    def arg(name, default=""):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
        return default

    target = arg("--target", install_root())
    src = arg("--src", "")
    try:
        old_pid = int(arg("--pid", "0"))
    except Exception:
        old_pid = 0
    lock = arg("--lock", "blobby-pet-single-instance")

    _log = _make_logger(target)

    if not src or not os.path.isdir(src):
        _log("源目录不存在: %r" % src)
        return 2

    _log("等待主程序退出 (pid=%d)" % old_pid)
    deadline = time.time() + 90
    while _pid_alive(old_pid) and time.time() < deadline:
        time.sleep(0.4)
    time.sleep(0.6)
    _wait_port_free(lock, 10)
    _log("主程序已退出，开始替换")

    exe = os.path.join(target, EXE_NAME)
    bak = exe + BAK_SUFFIX
    if os.path.exists(exe):
        try:
            shutil.copy2(exe, bak)
        except Exception as e:
            _log("备份失败（继续）: %s" % e)

    try:
        n = copy_tree(src, target)
        _log("写入 %d 个文件" % n)
    except Exception as e:
        _log("替换失败，回滚: %s" % e)
        _restore(exe, bak)
        _launch(exe, target)
        return 3

    proc = _launch(exe, target)
    if not _still_alive(proc, 8):
        _log("新版本没起来，回滚")
        _restore(exe, bak)
        _launch(exe, target)
        return 4

    _log("更新完成")
    return 0


def _make_logger(target):
    path = os.path.join(target, "update.log")

    def log(msg):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
        except Exception:
            pass

    return log


def _restore(exe, bak):
    try:
        if os.path.exists(bak):
            shutil.copy2(bak, exe)
            os.remove(bak)
    except Exception:
        pass


def _launch(exe, cwd):
    try:
        return subprocess.Popen([exe], cwd=cwd)
    except Exception:
        return None


def _still_alive(proc, seconds) -> bool:
    if proc is None:
        return False
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        time.sleep(0.3)
    return True


# ---------------------------------------------------------------- 清理

def cleanup_leftovers(keep_bak: bool = True) -> None:
    """新版本启动后调用：删掉 staging 和上次留下的 .bak。"""
    root = staging_root()
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    if not keep_bak:
        for name in os.listdir(install_root()):
            if name.endswith(BAK_SUFFIX):
                try:
                    os.remove(os.path.join(install_root(), name))
                except Exception:
                    pass
