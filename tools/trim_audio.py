# -*- coding: utf-8 -*-
"""从音频里截一段出来，输出 16bit wav。

    python tools/trim_audio.py 输入 输出 [起始秒] [时长秒]
    python tools/trim_audio.py assets/sounds/custom/tap.mp3 assets/sounds/custom/tap.wav 0 2

mp3/ogg/m4a 走 Qt 的解码器，wav 直接读。末尾会自动加 40ms 淡出，
避免咔嚓一声。
"""

import os
import sys
import wave

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

FADE_MS = 40


def decode(path):
    """返回 (int16 数组 shape=(n, ch), 采样率, 通道数)。"""
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    dec = QAudioDecoder()
    dec.setSource(QUrl.fromLocalFile(path))

    chunks = []
    info = {"rate": 0, "ch": 0, "fmt": None}

    def on_buffer():
        buf = dec.read()
        if not buf.isValid():
            return
        f = buf.format()
        info["rate"] = f.sampleRate()
        info["ch"] = f.channelCount()
        info["fmt"] = f.sampleFormat()
        data = bytes(buf.data())
        chunks.append(data)

    def on_finished():
        app.quit()

    dec.bufferReady.connect(on_buffer)
    dec.finished.connect(on_finished)
    dec.error.connect(lambda e: (print("解码失败:", dec.errorString()), app.quit()))

    dec.start()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(30000, app.quit)   # 兜底，别卡死
    app.exec()

    if not chunks:
        raise SystemExit("没解出音频数据: %s" % path)

    raw = b"".join(chunks)
    ch = max(1, info["ch"])
    fmt = info["fmt"]

    if fmt == QAudioFormat.SampleFormat.Float:
        a = np.frombuffer(raw, dtype=np.float32)
        a = np.clip(a, -1.0, 1.0) * 32767.0
    elif fmt == QAudioFormat.SampleFormat.Int16:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif fmt == QAudioFormat.SampleFormat.Int32:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0 * 32767.0
    elif fmt == QAudioFormat.SampleFormat.UInt8:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    else:
        raise SystemExit("不认识的采样格式: %s" % fmt)

    a = a.reshape(-1, ch)
    return np.clip(a, -32768, 32767).astype(np.int16), info["rate"], ch


def trim(a, rate, start, dur, fade_ms=FADE_MS):
    s = int(round(start * rate))
    e = int(round((start + dur) * rate)) if dur else a.shape[0]
    out = a[s:e].astype(np.float32)

    n = int(round(fade_ms / 1000.0 * rate))
    if 0 < n < out.shape[0]:
        ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
        out[-n:] *= ramp

    # 起手也做 5ms 淡入，防止爆音
    m = min(int(0.005 * rate), out.shape[0])
    if m > 1:
        out[:m] *= np.linspace(0.0, 1.0, m, dtype=np.float32)[:, None]

    return np.clip(out, -32768, 32767).astype(np.int16)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    dur = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0

    a, rate, ch = decode(src)
    print("源文件: %.2f 秒, %d Hz, %d 通道" % (a.shape[0] / rate, rate, ch))

    out = trim(a, rate, start, dur)
    with wave.open(dst, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())

    peak = int(np.abs(out).max())
    print("输出: %s  %.2f 秒  峰值 %d/32767" % (dst, out.shape[0] / rate, peak))


if __name__ == "__main__":
    main()
