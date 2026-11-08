# -*- coding: utf-8 -*-
"""把 custom/ 里的音频批量归一化：切掉首尾的静音，输出 16bit wav。

    python tools/normalize_sounds.py [--dry]

为什么不直接放着 mp3 用：
  - wav 走系统低延迟通道，点击/拖动这种即时反馈更跟手
  - 下载来的素材经常头尾各带零点几秒静音，按下去要等一下才响

原文件会挪到 custom/_orig/，不删。
"""

import os
import shutil
import sys
import wave

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CUSTOM = os.path.join(BASE, "assets", "sounds", "custom")
ORIG = os.path.join(CUSTOM, "_orig")
AUDIO_EXT = (".mp3", ".ogg", ".m4a", ".flac", ".aac", ".wav")

PRE_PAD = 0.020     # 起音前留一点，别切掉瞬态
POST_PAD = 0.060    # 收尾多留一点，保住余韵
FADE_OUT = 0.030
FADE_IN = 0.004
THRESH = 0.02       # 阈值 = 峰值 * 该比例
FLOOR = 0.0025      # 阈值下限，避免把底噪当内容


def decode(paths, on_item):
    """按顺序解码，全部完成后再退。on_item(path, array, rate, ch)。"""
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

    app = QApplication.instance() or QApplication(sys.argv[:1])
    state = {"i": 0, "dec": None, "chunks": [], "info": {}}

    def on_buffer():
        buf = state["dec"].read()
        if not buf.isValid():
            return
        f = buf.format()
        state["info"] = {"rate": f.sampleRate(), "ch": f.channelCount(),
                         "fmt": f.sampleFormat()}
        state["chunks"].append(bytes(buf.data()))

    def to_int16():
        raw = b"".join(state["chunks"])
        info = state["info"]
        fmt = info["fmt"]
        if fmt == QAudioFormat.SampleFormat.Float:
            a = np.clip(np.frombuffer(raw, dtype=np.float32), -1, 1) * 32767.0
        elif fmt == QAudioFormat.SampleFormat.Int16:
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        elif fmt == QAudioFormat.SampleFormat.Int32:
            a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0 * 32767.0
        elif fmt == QAudioFormat.SampleFormat.UInt8:
            a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
        else:
            return None, 0, 0
        ch = max(1, info["ch"])
        return np.clip(a.reshape(-1, ch), -32768, 32767).astype(np.int16), info["rate"], ch

    def on_finished():
        a, rate, ch = to_int16()
        on_item(paths[state["i"]], a, rate, ch)
        state["i"] += 1
        QTimer.singleShot(0, step)

    def step():
        if state["i"] >= len(paths):
            app.quit()
            return
        state["chunks"] = []
        dec = QAudioDecoder()
        state["dec"] = dec
        dec.setSource(QUrl.fromLocalFile(paths[state["i"]]))
        dec.bufferReady.connect(on_buffer)
        dec.finished.connect(on_finished)
        dec.error.connect(lambda e: (print("  解码失败 %s" % dec.errorString()),
                                     on_finished()))
        dec.start()

    QTimer.singleShot(0, step)
    app.run if False else None
    app.exec()


def find_span(a, rate):
    """返回 (起, 止) 的采样下标，去掉首尾静音。"""
    mono = a.astype(np.float64).mean(axis=1) / 32767.0
    win = max(1, int(0.01 * rate))
    n = len(mono) // win
    if n == 0:
        return 0, len(a)
    rms = np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1))
    th = max(rms.max() * THRESH, FLOOR)
    idx = np.nonzero(rms > th)[0]
    if len(idx) == 0:
        return 0, len(a)
    s = max(0, int((idx[0] * 0.01 - PRE_PAD) * rate))
    e = min(len(a), int((idx[-1] * 0.01 + 0.01 + POST_PAD) * rate))
    return s, e


def shape(out, rate):
    out = out.astype(np.float32)
    n = int(FADE_OUT * rate)
    if 0 < n < len(out):
        out[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
    m = min(int(FADE_IN * rate), len(out))
    if m > 1:
        out[:m] *= np.linspace(0.0, 1.0, m, dtype=np.float32)[:, None]
    return np.clip(out, -32768, 32767).astype(np.int16)


def main():
    dry = "--dry" in sys.argv
    os.makedirs(ORIG, exist_ok=True)

    names = sorted(f for f in os.listdir(CUSTOM)
                   if f.lower().endswith(AUDIO_EXT) and os.path.isfile(os.path.join(CUSTOM, f)))
    if not names:
        print("custom/ 里没有音频文件")
        return

    paths = [os.path.join(CUSTOM, f) for f in names]
    rows = []

    def on_item(path, a, rate, ch):
        try:
            _handle(path, a, rate, ch)
        except Exception as e:          # 单个文件出问题不要卡住整批
            print("  处理失败 %s: %s" % (os.path.basename(path), e))

    def _handle(path, a, rate, ch):
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        if a is None:
            print("跳过（不认识的格式）:", name)
            return
        s, e = find_span(a, rate)
        out = shape(a[s:e], rate)
        orig_dur = len(a) / rate
        new_dur = len(out) / rate
        rows.append((name, orig_dur, new_dur))

        if dry:
            print("%-14s %6.2fs -> %5.2fs   [干跑]" % (name, orig_dur, new_dur))
            return

        dst = os.path.join(CUSTOM, stem + ".wav")
        with wave.open(dst, "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(out.tobytes())

        # 原文件只备份、不删（解码器还占着句柄，删不掉也不该删）
        if name.lower() != os.path.basename(dst).lower():
            backup = os.path.join(ORIG, name)
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
            try:
                os.remove(path)
            except Exception:
                pass    # 删不掉就留着，resolve 时 .wav 优先级更高，不影响
        print("%-14s %6.2fs -> %5.2fs   %s" % (name, orig_dur, new_dur, os.path.basename(dst)))

    decode(paths, on_item)

    print()
    print("%-14s %8s %8s" % ("文件", "原始", "处理后"))
    for name, o, nw in rows:
        print("%-14s %7.2fs %7.2fs" % (name, o, nw))


if __name__ == "__main__":
    main()
