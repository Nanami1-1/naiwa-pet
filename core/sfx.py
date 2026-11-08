# -*- coding: utf-8 -*-
"""音效播放。

查找顺序：
  1. assets/sounds/custom/sounds.json 里给该事件指定的文件
  2. assets/sounds/custom/<事件名>.(wav|mp3|ogg|m4a|flac)
  3. assets/sounds/<事件名>.wav （内置合成音，兜底）

.wav 走 winsound，延迟最低；其余格式走 QtMultimedia。
任何一步失败都静默跳过，绝不因为音效把程序搞崩。
"""

import json
import os

from config import SOUNDS, CUSTOM_SOUNDS

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac")

# 事件清单：键是程序内部名字，值是给人看的中文说明
EVENTS = {
    "tap": "单击桌宠",
    "tap_many": "连点太多次（抗议）",
    "drag": "开始拖动",
    "land": "落地 / 撞墙",
    "pet": "摸摸头",
    "feed": "喂食",
    "hungry": "饿了冒气泡",
    "sleep": "睡着",
    "wake": "被叫醒",
    "spin": "双击转圈",
}

# 允许直接拿中文名当文件名，省得还要写 json
ALIASES = {
    "tap": ("点击", "戳", "单击"),
    "tap_many": ("生气", "抗议", "连点"),
    "drag": ("拖动", "拎起"),
    "land": ("落地", "掉下"),
    "pet": ("摸头", "摸摸", "抚摸"),
    "feed": ("喂食", "吃", "吃东西"),
    "hungry": ("饿", "饿了"),
    "sleep": ("睡觉", "睡着"),
    "wake": ("起床", "叫醒"),
    "spin": ("转圈", "转圈圈"),
}


class Sfx:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self._map = {}
        self._players = {}
        self._winsound = None
        try:
            import winsound  # noqa
            self._winsound = winsound
        except Exception:
            self._winsound = None
        self._load_map()

    # ---------------------------------------------------------------- 索引
    def _load_map(self):
        cfg = os.path.join(CUSTOM_SOUNDS, "sounds.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    if isinstance(v, str) and v.strip():
                        self._map[k] = v.strip()
            except Exception:
                pass

    def resolve(self, event):
        """返回该事件最终使用的文件路径，没有则 None。"""
        if event in self._map:
            p = self._map[event]
            if not os.path.isabs(p):
                p = os.path.join(CUSTOM_SOUNDS, p)
            if os.path.exists(p):
                return p
        for name in (event,) + ALIASES.get(event, ()):
            for ext in AUDIO_EXT:
                p = os.path.join(CUSTOM_SOUNDS, name + ext)
                if os.path.exists(p):
                    return p
        p = os.path.join(SOUNDS, event + ".wav")
        return p if os.path.exists(p) else None

    def using_custom(self):
        """当前有哪些事件用的是自定义音效。"""
        out = {}
        for ev in EVENTS:
            p = self.resolve(ev)
            if p and os.path.dirname(p) == os.path.abspath(CUSTOM_SOUNDS):
                out[ev] = p
        return out

    # ---------------------------------------------------------------- 播放
    def play(self, event):
        if not self.enabled:
            return
        path = self.resolve(event)
        if not path:
            return
        try:
            if path.lower().endswith(".wav") and self._winsound is not None:
                # SND_NODEFAULT: 文件坏了也别响系统提示音
                self._winsound.PlaySound(
                    path, self._winsound.SND_FILENAME | self._winsound.SND_ASYNC | self._winsound.SND_NODEFAULT
                )
            else:
                self._play_qt(event, path)
        except Exception:
            pass

    def _play_qt(self, event, path):
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtCore import QUrl
        except Exception:
            return
        got = self._players.get(event)
        if got is None:
            pl = QMediaPlayer()
            out = QAudioOutput()
            out.setVolume(0.85)
            pl.setAudioOutput(out)
            # QAudioOutput 必须一直被引用着：Qt 的 setAudioOutput 不接管所有权，
            # 只存局部变量的话它会被 GC 掉，播放器就哑了。
            self._players[event] = (pl, out)
        else:
            pl, out = got
        pl.stop()
        pl.setSource(QUrl.fromLocalFile(path))
        pl.play()

    def preload(self, events=None):
        """提前建好 Qt 播放器，避免首次播放卡一下。"""
        if not self.enabled:
            return
        for ev in events or EVENTS:
            p = self.resolve(ev)
            if p and not p.lower().endswith(".wav"):
                self._play_qt(ev, p)
                self._players[ev][0].stop()

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled
