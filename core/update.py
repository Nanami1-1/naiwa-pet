# -*- coding: utf-8 -*-
"""检查有没有新版本。

一期只做「发现 + 提示 + 打开下载页」，不下载、不替换任何文件。
所有网络请求都是异步的，失败一律静默——查不到更新不该影响桌宠正常用。

两个源按顺序试：
  1. GitHub Releases API   （信息最全，但国内可能连不上）
  2. jsDelivr 上的 version.json （国内通常可达，作为兜底）
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from version import REPO, VERSION

API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
CDN_URL = "https://cdn.jsdelivr.net/gh/%s@main/version.json" % REPO
RAW_URL = "https://raw.githubusercontent.com/%s/main/version.json" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO

# finished 收到它，表示「所有源都没连上」，不是「没有新版本」
FAILED = object()

CHECK_INTERVAL = 24 * 3600      # 一天最多自动查一次
NET_TIMEOUT = 8                 # 单次请求超时（秒）

# 网络一律走后台线程 + urllib，不用 QNetworkAccessManager。
#
# 原因不是偏好：这个透明窗口 + QNetworkAccessManager 的组合，在 PySide6 6.12 下
# 会在原生层崩溃（access violation / 堆损坏），有时发生在收到回复的当下，
# 有时发生在退出析构时。对照实验：同样的窗口，网络换成线程 + urllib 之后，
# 连续多次运行全部干净退出，一次都没崩；换成 Qt 网络则每次必崩。
#
# 副作用是好的：Qt 走系统代理、urllib 走环境变量（Windows 下也会读注册表代理），
# 以前两套栈表现不一致的问题也一并消失了。


# ---------------------------------------------------------------- 版本比较

def parse_version(text: str) -> tuple:
    """"v1.2.3" / "1.2" / "1.2.3-beta" → (1, 2, 3)。认不出的部分当 0。"""
    s = (text or "").strip().lstrip("vV")
    parts = []
    for chunk in s.split(".")[:3]:
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str = VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


# ---------------------------------------------------------------- 数据结构

@dataclass
class UpdateInfo:
    version: str = ""
    url: str = ""
    notes: str = ""
    asset_url: str = ""
    asset_size: int = 0
    asset_digest: str = ""

    @property
    def display(self) -> str:
        return "v%s" % self.version.lstrip("vV")

    @property
    def downloadable(self) -> bool:
        """有没有可以直接下载的安装包。没有就只能开网页手动下。"""
        return bool(self.asset_url) and self.asset_size > 0


# ---------------------------------------------------------------- 本地状态

def _state_path() -> str:
    # 不用 QStandardPaths：它取的是 QCoreApplication.applicationName，
    # 建 QApplication 之前调用会退化成 "python"，路径不稳定。写死目录最省事。
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "NaiwaPet")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "update_state.json")


def load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(state: dict):
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def seconds_since_check(state: dict) -> float:
    try:
        return time.time() - float(state.get("last_check", 0))
    except Exception:
        return 1e9


# ---------------------------------------------------------------- 检查器

def _fetch_json(url, timeout=NET_TIMEOUT):
    req = urllib.request.Request(url, headers={
        "User-Agent": "NaiwaPet/%s" % VERSION,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class UpdateChecker(QObject):
    """查一次新版本。结果通过 finished 发出：UpdateInfo 表示有新版本，None 表示没有。

    跑在后台线程里，finished 从工作线程发出，Qt 会自动排队到界面线程执行。
    """

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._done = False

    def start(self):
        self._done = False
        threading.Thread(target=self._work, name="update-check", daemon=True).start()

    # -------------------------------------------------- 内部
    def _work(self):
        from core import diag

        # 第三项表示「权威源」：只有它说没更新才是真的没更新。
        # 兜底源有缓存（jsDelivr 可能还是上一个版本），它说不新时必须继续问下一个，
        # 否则一个新版本会被旧缓存压住整整一个缓存周期。
        from config import UPDATE_MIRROR

        sources = []
        if UPDATE_MIRROR:
            # 自建镜像放最前：国内能连上的话，一次就够了
            sources.append((UPDATE_MIRROR, self._parse_cdn, False))
        sources += [
            (API_URL, self._parse_api, True),     # 信息最全，但共享出口 IP 容易被限流
            (CDN_URL, self._parse_cdn, False),    # 国内可达，但有缓存延迟
            (RAW_URL, self._parse_cdn, False),    # 实时，最后兜底
        ]

        answered = False
        for url, parser, authoritative in sources:
            if self._done:
                return
            diag.log("请求更新源: %s" % url)
            try:
                info = parser(_fetch_json(url))
            except Exception as e:
                diag.log("  请求失败: %r" % (e,))
                continue

            diag.log("  得到: %s" % (info.version if info else "解析不出"))
            if info is None:
                continue
            answered = True
            if is_newer(info.version):
                self._finish(info)
                return
            if authoritative:
                # 权威源说没有更新，那就是没有，不必再麻烦兜底源
                self._finish(None)
                return
            # 兜底源给的是旧数据，继续问下一个

        # 一个源都没回答（全被墙/断网）和「确实没有新版本」必须分开，
        # 否则界面会说「已经是最新的啦」，而且会把 last_check 写下去，
        # 接下来 24 小时都不再重试。
        self._finish(None if answered else FAILED)

    def _finish(self, info):
        if self._done:
            return
        self._done = True
        self.finished.emit(info)

    # -------------------------------------------------- 解析
    @staticmethod
    def _parse_api(d: dict) -> UpdateInfo:
        tag = (d.get("tag_name") or "").strip()
        if not tag:
            return None
        asset = {}
        for a in d.get("assets") or []:
            if (a.get("name") or "").lower().endswith(".zip"):
                asset = a
                break
        return UpdateInfo(
            version=tag,
            url=(d.get("html_url") or RELEASES_URL).strip(),
            notes=(d.get("body") or "").strip()[:400],
            asset_url=(asset.get("browser_download_url") or "").strip(),
            asset_size=int(asset.get("size") or 0),
            asset_digest=(asset.get("digest") or "").strip(),
        )

    @staticmethod
    def _parse_cdn(d: dict) -> UpdateInfo:
        ver = (d.get("version") or "").strip()
        if not ver:
            return None
        return UpdateInfo(
            version=ver,
            url=(d.get("url") or RELEASES_URL).strip(),
            notes=(d.get("notes") or "").strip()[:400],
            asset_url=(d.get("asset_url") or "").strip(),
            asset_size=int(d.get("asset_size") or 0),
            asset_digest=("sha256:" + d["asset_sha256"]) if d.get("asset_sha256") else "",
        )


class UpdateDownloader(QObject):
    """把安装包下到 staging。带进度，可取消。同样跑在后台线程。"""

    progress = Signal("qlonglong", "qlonglong")   # 已下载字节, 总字节
    finished = Signal(str, str)                   # 错误说明（空串表示成功）, 本地文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._cancelled = False

    def start(self, info) -> bool:
        from core.updater import staging_root

        if not info.asset_url:
            self.finished.emit("这个版本没有可下载的安装包", "")
            return False

        try:
            root = staging_root()
            os.makedirs(root, exist_ok=True)
            self._path = os.path.join(root, "package.zip")
        except Exception as e:
            self.finished.emit("没有写入权限：%s" % e, "")
            return False

        self._cancelled = False
        threading.Thread(target=self._work, args=(info,),
                         name="update-download", daemon=True).start()
        return True

    def cancel(self):
        # 只置标志：工作线程最多再读完一个 256KB 块就停
        self._cancelled = True

    # -------------------------------------------------- 内部
    def _work(self, info):
        from core import diag
        from core.updater import verify_zip

        req = urllib.request.Request(info.asset_url, headers={
            "User-Agent": "NaiwaPet/%s" % VERSION,
        })
        got = 0
        total = int(info.asset_size or 0)
        diag.log("下载开始: %s" % info.asset_url[:70])
        try:
            with urllib.request.urlopen(req, timeout=30) as r, open(self._path, "wb") as f:
                total = int(r.headers.get("Content-Length") or total or 0)
                last = 0.0
                while True:
                    if self._cancelled:
                        break
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.1:          # 别把进度信号刷爆
                        last = now
                        self.progress.emit(got, total)
        except Exception as e:
            diag.log("下载失败: %r" % (e,))
            self._cleanup_partial()
            self.finished.emit("下载失败：%s" % (e or "网络错误"), "")
            return

        if self._cancelled:
            self._cleanup_partial()
            self.finished.emit("已取消", "")
            return

        diag.log("下载完成 %d 字节，开始校验" % got)
        self.progress.emit(got, total or got)

        bad = verify_zip(self._path, info.asset_size, info.asset_digest)
        if bad:
            self._cleanup_partial()
            self.finished.emit("安装包校验失败：%s" % bad, "")
            return

        self.finished.emit("", self._path)

    def _cleanup_partial(self):
        try:
            if self._path and os.path.exists(self._path):
                os.remove(self._path)
        except Exception:
            pass
