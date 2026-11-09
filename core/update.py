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

    @property
    def display(self) -> str:
        return "v%s" % self.version.lstrip("vV")


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
        self._queue = [
            (API_URL, self._parse_api),
            (CDN_URL, self._parse_cdn),
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

        url, parser = self._queue.pop(0)
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "NaiwaPet/%s" % VERSION)
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setTransferTimeout(NET_TIMEOUT)

        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_reply(reply, parser))

    def _on_reply(self, reply, parser):
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

        if info is not None:
            # 请求成功就到此为止：有新版本就报，没有就不报
            self._finish(info if is_newer(info.version) else None)
        else:
            self._next()      # 这个源失败，换下一个

    # -------------------------------------------------- 解析
    @staticmethod
    def _parse_api(d: dict) -> UpdateInfo:
        tag = (d.get("tag_name") or "").strip()
        if not tag:
            return None
        return UpdateInfo(
            version=tag,
            url=(d.get("html_url") or RELEASES_URL).strip(),
            notes=(d.get("body") or "").strip()[:400],
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
        )
