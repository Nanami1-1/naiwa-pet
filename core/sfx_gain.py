# -*- coding: utf-8 -*-
"""音效增益：不改系统音量，把素材本身调轻。

winsound.PlaySound 没有音量参数，想改只能改样本。所以第一次播放前把 wav
逐样本乘增益，写到 %APPDATA%\\NaiwaPet\\sfx_cache，之后直接播缓存。

同时做两件事：

1. 响度对齐：RMS 高于 -14 dBFS 的压到 -14，峰值高于 -1 dBFS 的再压一点。
   只降不升 —— 本来就轻的音效（比如拖动声）原样保留，不会突然变大。
   这一步是必需的：素材之间差得很多（最响的 land 是 -3.2 dBFS RMS，
   最轻的 drag 是 -28.9），只乘一个统一系数的话，响的还是刺耳、轻的还是听不见。

2. 总体音量：再统一乘 master（config.SFX_VOLUME）。

缓存文件名由「原文件指纹 + 音量 + 算法版本」算出，换素材、换音量、
改算法都会自动生成新文件，不会播到旧的。
"""

import array
import hashlib
import math
import os
import threading
import wave

from core import diag

# 响度目标与峰值上限（dBFS）
TARGET_RMS_DB = -14.0
PEAK_CEIL_DB = -1.0

# 算法改了就改这个数，旧缓存自动作废
ALGO_VERSION = 1

_lock = threading.Lock()
_ready = {}          # (路径, 音量) -> 缓存路径，省掉重复 stat


def cache_dir() -> str:
    d = os.path.join(diag.log_dir(), "sfx_cache")
    os.makedirs(d, exist_ok=True)
    return d


def prepare(path: str, master: float = 1.0) -> str:
    """返回该音量下可播放的 wav 路径。失败时原样返回，绝不因为处理音效报错。"""
    if not path or not path.lower().endswith(".wav"):
        return path
    try:
        master = max(0.0, min(1.0, float(master)))
    except Exception:
        master = 1.0

    try:
        st = os.stat(path)
    except OSError:
        return path

    key = (os.path.abspath(path), st.st_size, int(st.st_mtime), master)
    got = _ready.get(key)
    if got and os.path.exists(got):
        return got

    name = hashlib.md5(
        ("%s|%d|%d|%.3f|%d|%.1f|%.1f"
         % (key[0], key[1], key[2], master, ALGO_VERSION, TARGET_RMS_DB, PEAK_CEIL_DB)
         ).encode("utf-8")
    ).hexdigest()
    out = os.path.join(cache_dir(), name + ".wav")
    if os.path.exists(out):
        _ready[key] = out
        return out

    with _lock:
        if os.path.exists(out):
            _ready[key] = out
            return out
        try:
            _process(path, out, master)
        except Exception:
            return path
    _ready[key] = out
    return out


def analyze(path: str):
    """返回 (峰值 dBFS, RMS dBFS)，给测试和调参用。"""
    with wave.open(path, "rb") as w:
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    samples = _decode(raw, sw)
    if not samples:
        return 0.0, -120.0
    full = float(1 << (8 * sw - 1))
    return _levels(samples, full)


# ------------------------------------------------------------------ 内部
def _levels(samples, full):
    peak = max(max(samples), -min(samples))
    step = 4 if len(samples) > 500000 else 1
    sub = samples[::step]          # C 层切片，比逐个循环快
    ss = 0
    for v in sub:
        ss += v * v
    rms = math.sqrt(ss / float(len(sub))) if sub else 0.0
    db = lambda x: 20 * math.log10(x / full) if x > 0 else -120.0
    return db(float(peak)), db(rms)


def _gain(samples, full, master):
    peak_db, rms_db = _levels(samples, full)
    g = 1.0
    if rms_db > -120.0:
        g = min(g, 10 ** ((TARGET_RMS_DB - rms_db) / 20.0))
    if peak_db > -120.0:
        g = min(g, 10 ** ((PEAK_CEIL_DB - peak_db) / 20.0))
    return g * master


def _decode(data, sw):
    """PCM 字节 → 有符号整数数组。只处理未压缩 PCM，其它情况抛异常让上层回落。"""
    if sw == 1:                     # 8 位是无符号，中心 128
        return array.array("i", (b - 128 for b in data))
    if sw == 2:
        h = array.array("h")
        h.frombytes(data)
        return array.array("i", h)
    if sw == 3:                     # 24 位没有原生类型，只能手工拼
        n = len(data) // 3
        return array.array(
            "i", [int.from_bytes(data[i * 3:i * 3 + 3], "little", signed=True) for i in range(n)]
        )
    if sw == 4:
        a = array.array("i")
        a.frombytes(data)
        return a
    raise ValueError("不支持的采样宽度: %d" % sw)


def _encode(samples, sw, gain):
    if sw == 1:
        return bytes(int(v * gain) + 128 for v in samples)
    if sw == 2:
        return array.array("h", (int(v * gain) for v in samples)).tobytes()
    if sw == 3:
        out = bytearray()
        for v in samples:
            out += int(v * gain).to_bytes(3, "little", signed=True)
        return bytes(out)
    return array.array("i", (int(v * gain) for v in samples)).tobytes()


def _process(src, dst, master):
    with wave.open(src, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)

    samples = _decode(raw, sw)
    if not samples:
        raise ValueError("空文件")
    full = float(1 << (8 * sw - 1))
    gain = _gain(samples, full, master)
    body = _encode(samples, sw, gain)

    tmp = dst + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(sw)
        w.setframerate(rate)
        w.writeframes(body)
    os.replace(tmp, dst)            # 原子替换：别的线程不会读到半个文件
