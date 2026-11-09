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
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from version import REPO, VERSION

API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
CDN_URL = "https://cdn.jsdelivr.net/gh/%s@main/version.json" % REPO
RAW_URL = "https://raw.githubusercontent.com/%s/main/version.json" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO

CHECK_INTERVAL = 24 * 3600      # 一天最多自动查一次
NET_TIMEOUT = 5000              # 单次请求超时（毫秒）


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

class UpdateChecker(QObject):
    """异步查一次。结果通过 finished 发出：UpdateInfo 表示有新版本，None 表示没有。"""

    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._queue = []
        self._done = False

    def start(self):
        self._done = False
        # 第三项表示「权威源」：只有它说没更新才是真的没更新。
        # 兜底源有缓存（jsDelivr 可能还是上一个版本），它说不新时必须继续问下一个，
        # 否则一个新版本会被旧缓存压住整整一个缓存周期。
        self._queue = [
            (API_URL, self._parse_api, True),    # 信息最全，但共享出口 IP 容易被限流
            (CDN_URL, self._parse_cdn, False),   # 国内可达，但有缓存延迟
            (RAW_URL, self._parse_cdn, False),   # 实时，最后兜底
        ]
        self._next()

    # -------------------------------------------------- 内部
    def _finish(self, info):
        if self._done:
            return
        self._done = True
        self.finished.emit(info)

    def _next(self):
        if self._done:
            return
        if not self._queue:
            self._finish(None)
            return

        url, parser, authoritative = self._queue.pop(0)
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "NaiwaPet/%s" % VERSION)
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setTransferTimeout(NET_TIMEOUT)

        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_reply(reply, parser, authoritative))

    def _on_reply(self, reply, parser, authoritative=False):
        info = None
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll()).decode("utf-8", "replace")
                info = parser(json.loads(raw))
        except Exception:
            info = None
        finally:
            reply.deleteLater()

        if self._done:
            return

        if info is not None and is_newer(info.version):
            self._finish(info)
            return
        if info is not None and authoritative:
            # 权威源说没有更新，那就是没有，不必再麻烦兜底源
            self._finish(None)
            return
        # 请求失败，或兜底源给的是旧数据 —— 继续问下一个源
        self._next()

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
    """把安装包下到 staging。带进度，可取消。"""

    progress = Signal("qlonglong", "qlonglong")   # Qt 的 downloadProgress 是 qint64
    finished = Signal(str, str)      # 错误说明（空串表示成功）, 本地文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply = None
        self._fh = None
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
            self._fh = open(self._path, "wb")
        except Exception as e:
            self.finished.emit("没有写入权限：%s" % e, "")
            return False

        req = QNetworkRequest(QUrl(info.asset_url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "NaiwaPet/%s" % VERSION)
        req.setTransferTimeout(30000)
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )

        self._cancelled = False
        self._reply = self._nam.get(req)
        self._reply.readyRead.connect(self._on_read)
        self._reply.downloadProgress.connect(self.progress)
        self._reply.finished.connect(lambda: self._on_done(info))
        return True

    def cancel(self):
        self._cancelled = True
        if self._reply is not None:
            self._reply.abort()

    # -------------------------------------------------- 内部
    def _on_read(self):
        if self._fh is None:
            return
        try:
            self._fh.write(bytes(self._reply.readAll()))
        except Exception:
            self.cancel()

    def _close_file(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def _on_done(self, info):
        self._close_file()

        if self._cancelled:
            self._cleanup_partial()
            self.finished.emit("已取消", "")
            return

        reply = self._reply
        err = ""
        if reply is not None and reply.error() != QNetworkReply.NetworkError.NoError:
            err = reply.errorString() or "网络错误"
        if reply is not None:
            reply.deleteLater()
            self._reply = None

        if err:
            self._cleanup_partial()
            self.finished.emit("下载失败：%s" % err, "")
            return

        from core.updater import verify_zip

        bad = verify_zip(self._path, info.asset_size, info.asset_digest)
        if bad:
            self._cleanup_partial()
            self.finished.emit("安装包校验失败：%s" % bad, "")
            return

        self.finished.emit("", self._path)

    def _cleanup_partial(self):
        self._close_file()
        try:
            if self._path and os.path.exists(self._path):
                os.remove(self._path)
        except Exception:
            pass
