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
import threading
import time
import wave

from config import SOUNDS, CUSTOM_SOUNDS, SFX_VOLUME, SFX_VOLUME_LEGACY
from core import diag, sfx_gain

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac")

# 播放优先级。数字大的不会被小的打断；没列出的按 DEFAULT_PRIORITY 算。
PRIORITY = {
    "tap": 10,          # 普通单击，最容易被顶掉
    "land": 20,
    "pet": 20,
    "drag": 25,
    "feed": 30,
    "spin": 30,
    "wake": 95,         # 叫醒：睡着时任何操作都只响这一声，播完之前谁都不许插进来
    "sleep": 40,
    "hungry": 40,
    "tap_many": 90,     # 连点抗议：可以盖掉别人，自己播完之前谁都不许插进来
}
DEFAULT_PRIORITY = 10

# 达到这个优先级的音效，播放期间独占声道（按音频实际时长）
GUARD_PRIORITY = 90

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


def _settings_path() -> str:
    return os.path.join(diag.log_dir(), "settings.json")


def _load_volume() -> float:
    """音量存在 settings.json 里，跟着用户走；没有就用 config 的默认值。"""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            v = json.load(f).get("sfx_volume")
        if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0:
            v = float(v)
            # 档位整体调小过，把旧值换成对应的新档，菜单的勾才对得上
            for old, new in SFX_VOLUME_LEGACY.items():
                if abs(v - old) < 0.02:
                    if abs(old - new) > 0.001:
                        _save_volume(new)
                    return new
            return v
    except Exception:
        pass
    return float(SFX_VOLUME)


def _save_volume(v: float):
    path = _settings_path()
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data["sfx_volume"] = round(float(v), 3)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class Sfx:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.volume = _load_volume()
        self._map = {}
        self._players = {}
        self._winsound = None
        try:
            import winsound  # noqa
            self._winsound = winsound
        except Exception:
            self._winsound = None
        self._dur = {}
        self._lock_until = 0.0
        self._lock_prio = 0
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
    def play(self, event) -> bool:
        """播放一个事件音效。

        True  = 真的播了
        False = 被正在播放的高优先级音效挡下来了
        None  = 没播，但原因跟抢占无关（音效被关掉、找不到文件、播放出错）

        调用方靠 False 和 None 的区别决定要不要顺带更新气泡：
        只有「被抢先」才该按兵不动，单纯关了音效不该冻住气泡。

        声道只有一个（winsound 的 SND_ASYNC 是后一个顶掉前一个），
        所以高优先级音效播放期间要独占，否则连点里那句「别戳了」会被
        第六下点击的普通音效当场切断。
        """
        if not self.enabled:
            return None

        now = time.monotonic()
        prio = PRIORITY.get(event, DEFAULT_PRIORITY)

        # 高优先级正在播，低优先级让路（不打断，也不排队重放）
        if now < self._lock_until and prio < self._lock_prio:
            return False

        path = self.resolve(event)
        if not path:
            return None
        try:
            if path.lower().endswith(".wav") and self._winsound is not None:
                # winsound 没有音量参数，只能播预先乘过增益的副本
                target = sfx_gain.prepare(path, self.volume)
                # SND_NODEFAULT: 文件坏了也别响系统提示音
                self._winsound.PlaySound(
                    target, self._winsound.SND_FILENAME | self._winsound.SND_ASYNC | self._winsound.SND_NODEFAULT
                )
            else:
                self._play_qt(event, path)
        except Exception:
            return None

        # 够级别的音效播完之前独占声音
        if prio >= GUARD_PRIORITY:
            self._lock_prio = prio
            self._lock_until = now + max(0.8, self._seconds(path))
        return True

    def _seconds(self, path) -> float:
        """音频时长（秒）。读不出来就返回 0，由调用处兜底。"""
        if path in self._dur:
            return self._dur[path]
        dur = 0.0
        if path.lower().endswith(".wav"):
            try:
                with wave.open(path, "rb") as w:
                    rate = w.getframerate() or 1
                    dur = w.getnframes() / float(rate)
            except Exception:
                dur = 0.0
        self._dur[path] = dur
        return dur

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
            pl.setAudioOutput(out)
            # QAudioOutput 必须一直被引用着：Qt 的 setAudioOutput 不接管所有权，
            # 只存局部变量的话它会被 GC 掉，播放器就哑了。
            self._players[event] = (pl, out)
        else:
            pl, out = got
        # 非 wav 走 Qt，没法逐样本处理，只能在输出端设音量
        out.setVolume(max(0.0, min(1.0, self.volume)))
        pl.stop()
        pl.setSource(QUrl.fromLocalFile(path))
        pl.play()

    def preload(self, events=None):
        """提前建好 Qt 播放器、算好 wav 增益，避免首次播放卡一下。"""
        if not self.enabled:
            return
        todo = list(events or EVENTS)
        for ev in todo:
            p = self.resolve(ev)
            if p and not p.lower().endswith(".wav"):
                self._play_qt(ev, p)
                self._players[ev][0].stop()

        # 逐样本乘增益要几十毫秒到几百毫秒，放后台算，别卡住启动
        def warm():
            try:
                sfx_gain.prune()        # 音量档位换过之后，旧缓存会越堆越多
            except Exception:
                pass
            for ev in todo:
                p = self.resolve(ev)
                if p and p.lower().endswith(".wav"):
                    try:
                        sfx_gain.prepare(p, self.volume)
                    except Exception as e:
                        diag.log("音效预热失败 %s: %r" % (ev, e))

        threading.Thread(target=warm, daemon=True).start()

    def set_volume(self, value, save=True):
        """改总体音量。下一次播放就生效（增益按音量做缓存键，不会播到旧的）。"""
        try:
            v = max(0.0, min(1.0, float(value)))
        except Exception:
            return self.volume
        self.volume = v
        if save:
            _save_volume(v)
            diag.log("音效音量 -> %.2f" % v)
        return self.volume

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled
