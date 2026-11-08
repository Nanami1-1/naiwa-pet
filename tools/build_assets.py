# -*- coding: utf-8 -*-
"""把一张白底渲染图加工成桌宠可用的素材。

做的事：
  1. 从边缘泛洪填充识别背景（不靠亮度阈值，避免把纯黑瞳孔抠穿）
  2. 边缘羽化，输出透明 PNG，裁到主体包围盒
  3. 检测眼睛：近处那只按绿色虹膜定位，远处那只按竖直暗缝定位
  4. 给近眼做"抹掉瞳孔"的虹膜底板，供运行时叠加可动瞳孔实现视线跟随
  5. 预烘焙表情变体（眨眼 / 开心 / 生气），运行时交叉淡化即可，不用逐帧画
  6. 合成提示音 wav（不依赖外部音频文件）

用法：
  python tools/build_assets.py [源图路径]
"""

from __future__ import annotations

import json
import math
import os
import sys
import wave
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OUT_H = 460  # 输出精灵图高度，运行时再缩到屏幕尺寸


# ---------------------------------------------------------------- 抠图

def flood_background(cand: np.ndarray) -> np.ndarray:
    """从四边向内泛洪，返回真正的背景掩码。构建期一次性使用。"""
    h, w = cand.shape
    seen = np.zeros((h, w), dtype=bool)
    dq: deque = deque()

    def push(y, x):
        if cand[y, x] and not seen[y, x]:
            seen[y, x] = True
            dq.append((y, x))

    for x in range(w):
        push(0, x)
        push(h - 1, x)
    for y in range(h):
        push(y, 0)
        push(y, w - 1)

    while dq:
        y, x = dq.popleft()
        if y > 0:
            push(y - 1, x)
        if y + 1 < h:
            push(y + 1, x)
        if x > 0:
            push(y, x - 1)
        if x + 1 < w:
            push(y, x + 1)
    return seen


def cutout(src: str) -> Image.Image:
    img = Image.open(src).convert("RGB")
    W, H = img.size

    # 半分辨率做泛洪，快 4 倍，边界误差 1px 在缩放到 460 高后不可见
    half = img.resize((W // 2, H // 2), Image.BILINEAR)
    a = np.asarray(half).astype(np.float32)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    val = mx / 255.0

    # 背景候选要放宽到能穿过脚下那层投影（投影是低饱和的棕灰色），
    # 同时把高饱和/很暗的区域钉死成"主体"，泛洪不许穿过，
    # 否则两腿之间那块会被腿和投影封死，泛洪进不去，留下白块。
    cand = (sat < 0.42) & (val > 0.52)
    sure_body = (sat > 0.52) | (val < 0.45)
    cand = cand & ~sure_body
    bg_small = flood_background(cand)

    bg = Image.fromarray((bg_small * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(0.8))
    b = np.asarray(bg).astype(np.float32) / 255.0

    alpha = 1.0 - np.clip((b - 0.42) / 0.24, 0.0, 1.0)
    alpha = alpha * alpha * (3 - 2 * alpha)  # smoothstep 收一下硬边

    out = img.convert("RGBA")
    arr = np.asarray(out).copy()
    arr[..., 3] = (alpha * 255).astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")

    bbox = out.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
    out = out.crop(bbox)

    ratio = OUT_H / out.height
    out = out.resize((max(1, round(out.width * ratio)), OUT_H), Image.LANCZOS)
    return out


# ---------------------------------------------------------------- 连通域

def find_blobs(mask: np.ndarray, min_area: int = 30):
    """四连通分量，返回 [(x0, y0, x1, y1, area)]。"""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    boxes = []
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if not row[x] or seen[y, x]:
                continue
            dq = deque([(y, x)])
            seen[y, x] = True
            x0 = x1 = x
            y0 = y1 = y
            area = 0
            while dq:
                cy, cx = dq.popleft()
                area += 1
                if cx < x0: x0 = cx
                if cx > x1: x1 = cx
                if cy < y0: y0 = cy
                if cy > y1: y1 = cy
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        dq.append((ny, nx))
            if area >= min_area:
                boxes.append((x0, y0, x1, y1, area))
    return boxes


# ---------------------------------------------------------------- 眼睛

def detect_eyes(sprite: Image.Image):
    rgb = np.asarray(sprite.convert("RGB")).astype(np.float32)
    alpha = np.asarray(sprite.split()[3]).astype(np.float32) / 255.0
    h, w, _ = rgb.shape
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    val = mx / 255.0

    head = np.zeros((h, w), dtype=bool)
    head[: max(8, int(h * 0.16))] = True  # 只留眼部那一条，避开嘴巴

    eyes = []

    # --- 近眼：绿色虹膜
    green = head & (g > r * 1.02) & (g > b * 1.30) & (sat > 0.16) & (g > 45) & (alpha > 0.5)
    gb = sorted(find_blobs(green, 40), key=lambda t: -t[4])
    if gb:
        x0, y0, x1, y1, _ = gb[0]
        iris_px = rgb[y0:y1 + 1, x0:x1 + 1][green[y0:y1 + 1, x0:x1 + 1]]
        iris_col = np.median(iris_px, axis=0) if len(iris_px) else np.array([122, 145, 96.0])
        eyes.append({
            "name": "near", "iris_box": [x0, y0, x1, y1],
            "iris": [int(round(c)) for c in iris_col], "gaze": True,
        })

    # --- 暗区：近眼瞳孔 + 远处那道竖缝
    dark = (val < 0.32) & (alpha > 0.5) & head
    darkb = [t for t in find_blobs(dark, 20)]
    darkb.sort(key=lambda t: -t[4])
    near_box = eyes[0]["iris_box"] if eyes else None

    if near_box and darkb:
        # 近眼瞳孔优先取落在虹膜框内/近旁的最大暗块
        def in_near(t):
            cx = (t[0] + t[2]) / 2
            cy = (t[1] + t[3]) / 2
            return near_box[0] - 4 <= cx <= near_box[2] + 4 and near_box[1] - 4 <= cy <= near_box[3] + 4
        cand = [t for t in darkb if in_near(t)]
        if cand:
            x0, y0, x1, y1, area = cand[0]
            pr = max(2.5, math.sqrt(area / math.pi))
            eyes[0]["pupil"] = [round((x0 + x1) / 2 + 0.0, 2), round((y0 + y1) / 2 + 0.0, 2), round(pr, 2)]
            darkb = [t for t in darkb if t is not cand[0]]

    for t in darkb:
        x0, y0, x1, y1, area = t
        bw = x1 - x0 + 1
        bh = y1 - y0 + 1
        if bh / max(bw, 1) < 1.4:  # 只要竖长条，排除嘴巴那种横线
            continue
        if near_box and x0 >= near_box[0]:
            continue
        pr = max(2.0, math.sqrt(area / math.pi))
        eyes.append({
            "name": "far", "iris_box": [x0, y0, x1, y1],
            "iris": [40, 44, 30], "gaze": False,
            "pupil": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2), round(pr, 2)],
        })
        break

    if not eyes:
        raise SystemExit("没能定位到眼睛，检查一下源图")

    # 补齐外框（虹膜框外扩成眼睛方块）
    for e in eyes:
        x0, y0, x1, y1 = e["iris_box"]
        pad = 3
        e["box"] = [max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad + 1), min(h, y1 + pad + 1)]
        if "pupil" not in e:
            bw = x1 - x0 + 1
            bh = y1 - y0 + 1
            e["pupil"] = [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2), round(min(bw, bh) * 0.35, 2)]

    return eyes, rgb, alpha, sat, val


def local_skin(rgb: np.ndarray, alpha: np.ndarray, box, px=0.55) -> np.ndarray:
    """取眼睛周围一圈的皮肤色，用作眼睑填色。"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx = (x1 - x0) * 1.15
    ry = (y1 - y0) * 1.15
    h, w, _ = rgb.shape
    xs = np.arange(max(0, int(cx - rx * 1.6)), min(w, int(cx + rx * 1.6)))
    ys = np.arange(max(0, int(cy - ry * 1.6)), min(h, int(cy + ry * 1.6)))
    if len(xs) == 0 or len(ys) == 0:
        return np.array([230, 180, 45.0])
    patch = rgb[np.ix_(ys, xs)]
    mask = alpha[np.ix_(ys, xs)] > 0.9
    # 排除眼睛本身：离中心太近的不要
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    far = ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 > 1.6
    m = mask & far
    if m.sum() < 20:
        m = mask
    return np.median(patch[m], axis=0)


def ellipse_mask(shape, cx, cy, rx, ry, feather=1.6) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    d = ((xx - cx) / max(rx, 1e-6)) ** 2 + ((yy - cy) / max(ry, 1e-6)) ** 2
    m = np.clip((1.0 - d) * 3.0, 0.0, 1.0)
    if feather > 0:
        m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(feather))).astype(np.float32) / 255.0
    return m


def _inpaint(crop: np.ndarray, mask: np.ndarray, passes=7, radius=1.7) -> np.ndarray:
    """横向插值 + 轻扩散。

    每一行都拿孔洞左右两边的皮肤色做线性过渡，所以头部原有的上下明暗会被完整保留，
    不会像等向扩散那样糊成一块发灰的补丁。
    """
    h, w = mask.shape
    out = crop.copy()
    ys = np.nonzero(mask.any(axis=1))[0]
    for y in ys:
        xs = np.nonzero(mask[y])[0]
        if len(xs) == 0:
            continue
        x0, x1 = int(xs[0]), int(xs[-1])
        left = out[y, x0 - 1] if x0 - 1 >= 0 else None
        right = out[y, x1 + 1] if x1 + 1 < w else None
        if left is None and right is None:
            continue
        if left is None:
            left = right
        if right is None:
            right = left
        n = x1 - x0 + 1
        t = ((np.arange(n) + 1.0) / (n + 1.0))[:, None]
        out[y, x0:x1 + 1] = left[None, :] * (1 - t) + right[None, :] * t

    for _ in range(passes):
        im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
        blur = np.asarray(im.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32)
        out = np.where(mask[..., None], blur, crop)
    return out


def paint_lid(img: Image.Image, eye, frac=1.0, mode="closed") -> Image.Image:
    """盖眼睑。frac=1 全闭；0.5 左右是半眯。皮肤用插值修补，跟着头像的明暗走。"""
    arr = np.asarray(img).astype(np.float32)
    alpha = arr[..., 3] / 255.0
    rgb = arr[..., :3]
    h, w, _ = rgb.shape
    x0, y0, x1, y1 = eye["box"]

    pad = 14
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)
    crop = rgb[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    # 覆盖范围直接框住整只眼（含深色眼框），不用椭圆去猜
    bx0, by0 = (x0 - 2) - cx0, (y0 - 2) - cy0
    bx1, by1 = (x1 + 2) - cx0, (y1 + 2) - cy0
    yy, xx = np.mgrid[0:ch, 0:cw]
    rect = ((xx >= bx0) & (xx <= bx1) & (yy >= by0) & (yy <= by1)).astype(np.float32)
    rect = np.asarray(
        Image.fromarray((rect * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.2))
    ).astype(np.float32) / 255.0

    cut = (y0 + (y1 - y0) * frac + 1) - cy0
    ramp = np.clip((cut - yy) / 2.2 + 0.5, 0, 1)
    m = rect * ramp

    filled = _inpaint(crop, m > 0.5)
    crop[:] = crop * (1 - m[..., None]) + filled * m[..., None]
    rgb[cy0:cy1, cx0:cx1] = crop

    out = Image.fromarray(np.dstack([rgb, arr[..., 3]]).astype(np.uint8), "RGBA")

    if mode == "squint":
        return out.filter(ImageFilter.GaussianBlur(0.25))

    # 闭眼弧线 / 瞪眼线
    d = ImageDraw.Draw(out)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2 + (y1 - y0) * 0.02
    rw = (x1 - x0) * 0.40
    rh = (y1 - y0) * 0.17
    lw = max(2, int(round((x1 - x0) * 0.085)))
    col = (58, 52, 30, 220) if mode != "sleep" else (64, 58, 34, 195)

    if mode == "glare":
        # 内低外高的一道粗线，两头收尖，读起来就是"瞪"
        ax, ay = cx - rw * 1.05, cy + rh * 0.46
        bx, by = cx + rw * 1.05, cy - rh * 0.55
        th = (lw + 2.6)
        d.polygon([(ax, ay - th * 0.42), (bx, by - th * 0.20),
                   (bx, by + th * 0.20), (ax, ay + th * 0.42)], fill=col)
        return out.filter(ImageFilter.GaussianBlur(0.4))

    if mode == "happy":
        d.arc([cx - rw, cy - rh, cx + rw, cy + rh], 195, 345, fill=col, width=lw)
    elif mode == "sleep":
        d.arc([cx - rw, cy - rh * 0.6, cx + rw, cy + rh * 1.4], 12, 168, fill=col, width=lw)
    else:
        d.arc([cx - rw, cy - rh * 1.1, cx + rw, cy + rh * 0.9], 16, 164, fill=col, width=lw)

    return out.filter(ImageFilter.GaussianBlur(0.35))


def paint_brows(img: Image.Image, eyes) -> Image.Image:
    """皱眉：用压暗的皮肤色，做两头尖中间粗的一笔。"""
    arr = np.asarray(img).astype(np.float32)
    alpha = arr[..., 3] / 255.0
    rgb = arr[..., :3]
    h, w, _ = rgb.shape
    for e in eyes:
        x0, y0, x1, y1 = e["box"]
        bw = max(1, x1 - x0)
        bh = max(1, y1 - y0)
        if e["name"] == "near":
            inner = (x0 + bw * 0.04, y0 - bh * 0.10)
            outer = (x1 + bw * 0.00, y0 - bh * 0.40)
        else:
            inner = (x1 - bw * 0.02, y0 - bh * 0.06)
            outer = (x0 + bw * 0.04, y0 - bh * 0.34)

        m = np.zeros((h, w), dtype=np.float32)
        steps = 30
        for i in range(steps):
            t = i / (steps - 1)
            px = inner[0] + (outer[0] - inner[0]) * t
            py = inner[1] + (outer[1] - inner[1]) * t
            taper = math.sin(math.pi * (0.12 + 0.76 * t))
            m += ellipse_mask((h, w), px, py,
                              max(1.0, bw * 0.075 * taper),
                              max(0.8, bh * 0.045 * taper), feather=0.7)
        m = np.clip(m * 0.85, 0, 1) * np.clip(alpha * 2.0, 0, 1)

        sample = rgb[int(max(0, outer[1])):int(min(h, inner[1] + 2)),
                     int(max(0, min(inner[0], outer[0]))):int(min(w, max(inner[0], outer[0]) + 1))]
        base = np.median(sample.reshape(-1, 3), axis=0) if sample.size else np.array([214, 168, 44.0])
        brow = base * 0.50
        for c in range(3):
            rgb[..., c] = rgb[..., c] * (1 - m) + brow[c] * m
    out = Image.fromarray(np.dstack([rgb, arr[..., 3]]).astype(np.uint8), "RGBA")
    return out.filter(ImageFilter.GaussianBlur(0.45))


def build_eye_plate(sprite: Image.Image, eye) -> Image.Image:
    """近眼虹膜底板：把瞳孔抹成虹膜色，运行时再画可动瞳孔。"""
    x0, y0, x1, y1 = eye["box"]
    crop = sprite.crop((x0, y0, x1, y1)).convert("RGBA")
    arr = np.asarray(crop).astype(np.float32)
    rgb = arr[..., :3]
    val = rgb.max(axis=2) / 255.0

    px, py, pr = eye["pupil"]
    cx, cy = px - x0, py - y0
    hh, ww, _ = rgb.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    pupil = np.clip((pr * 1.18 - dist), 0, 1)  # 1px 软边
    iris = np.array(eye["iris"], dtype=np.float32)
    # 虹膜本身有径向明暗，补一点层次
    shade = 1.12 - 0.34 * np.clip(dist / max(pr * 2.2, 1), 0, 1)
    fill = np.clip(iris[None, None, :] * shade[..., None], 0, 255)
    for c in range(3):
        rgb[..., c] = rgb[..., c] * (1 - pupil) + fill[..., c] * pupil

    plate = Image.fromarray(np.dstack([rgb, arr[..., 3]]).astype(np.uint8), "RGBA")
    # 外圈轻微羽化，避免缩放时出现方块接缝
    m = np.asarray(Image.fromarray((np.ones((hh, ww)) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(1.0))).astype(np.float32) / 255.0
    inner = ellipse_mask((hh, ww), ww / 2, hh / 2, ww / 2, hh / 2, feather=1.2)
    a = arr[..., 3] * np.clip(inner * 1.3, 0, 1)
    arr2 = np.asarray(plate).copy()
    arr2[..., 3] = a.astype(np.uint8)
    return Image.fromarray(arr2, "RGBA")


# ---------------------------------------------------------------- 音效

SR = 22050


def tone(freq, dur, vol=0.5, decay=6.0, sweep=1.0, kind="sine"):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = freq * (1 + (sweep - 1) * t / max(dur, 1e-6))
    phase = 2 * np.pi * np.cumsum(f) / SR
    if kind == "sine":
        s = np.sin(phase)
    elif kind == "tri":
        s = 2 * np.abs(2 * ((phase / (2 * np.pi)) % 1) - 1) - 1
    else:
        s = np.sign(np.sin(phase))
    env = np.exp(-decay * t / dur) * np.minimum(1.0, t / 0.004)
    return (s * env * vol)


def noise_burst(dur, vol=0.25, decay=9.0, lowpass=0.25):
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    s = rng.normal(0, 1, n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += lowpass * (s[i] - acc)
        out[i] = acc
    t = np.arange(n) / SR
    out = out * np.exp(-decay * t / dur) * vol
    peak = np.abs(out).max()
    return out / peak * vol if peak > 0 else out


def mix(*tracks):
    n = max(len(t) for t in tracks)
    buf = np.zeros(n)
    for t in tracks:
        buf[: len(t)] += np.asarray(t, dtype=np.float32)
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.82
    return (buf * 32767).astype(np.int16)


def silence(dur):
    return np.zeros(int(SR * dur))


def write_wav(name, data):
    path = os.path.join(ASSETS, "sounds", name)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(data.tobytes())


def build_sounds():
    """内置兜底音。文件名和 core/sfx.py 的事件名一一对应。"""
    os.makedirs(os.path.join(ASSETS, "sounds"), exist_ok=True)

    # 点击：上扬的小啵
    write_wav("tap.wav", mix(tone(880, 0.09, vol=0.5, decay=8, sweep=1.5),
                             tone(1320, 0.07, vol=0.25, decay=12, sweep=1.2)))
    # 连点抗议：往下掉的短音
    write_wav("tap_many.wav", mix(tone(520, 0.12, vol=0.4, decay=4, sweep=0.55),
                                  tone(390, 0.16, vol=0.3, decay=6, sweep=0.7)))
    # 拎起来：一声轻飘的whoosh
    write_wav("drag.wav", mix(noise_burst(0.22, vol=0.22, decay=5, lowpass=0.10),
                              tone(300, 0.18, vol=0.16, decay=5, sweep=1.9)))
    # 落地：闷响
    write_wav("land.wav", mix(noise_burst(0.13, vol=0.6, decay=7),
                              tone(120, 0.1, vol=0.3, decay=10, sweep=0.6)))
    # 摸摸：柔和的双音
    write_wav("pet.wav", mix(tone(660, 0.12, vol=0.4, decay=5, sweep=1.25),
                             np.concatenate([silence(0.07), tone(990, 0.14, vol=0.35, decay=5)])))
    # 喂食：两口咀嚼
    write_wav("feed.wav", mix(tone(300, 0.07, vol=0.45, decay=9, kind="tri"),
                              np.concatenate([silence(0.09), tone(260, 0.07, vol=0.4, decay=9, kind="tri")]),
                              np.concatenate([silence(0.04), noise_burst(0.05, vol=0.12)])))
    # 饿了：委屈的下滑音
    write_wav("hungry.wav", tone(440, 0.3, vol=0.32, decay=4, sweep=0.72))
    # 睡着：轻鼾
    write_wav("sleep.wav", mix(noise_burst(0.5, vol=0.16, decay=3, lowpass=0.06),
                               tone(90, 0.5, vol=0.12, decay=3)))
    # 醒来：短促上扬
    write_wav("wake.wav", mix(tone(520, 0.08, vol=0.35, decay=7, sweep=1.6),
                              np.concatenate([silence(0.06), tone(780, 0.10, vol=0.3, decay=7, sweep=1.3)])))
    # 转圈：三个上行音
    write_wav("spin.wav", mix(tone(660, 0.07, vol=0.32, decay=6),
                              np.concatenate([silence(0.06), tone(880, 0.07, vol=0.32, decay=6)]),
                              np.concatenate([silence(0.12), tone(1180, 0.10, vol=0.30, decay=6)])))


# ---------------------------------------------------------------- 主流程

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "source.jpg")
    os.makedirs(ASSETS, exist_ok=True)
    if not os.path.exists(src):
        raise SystemExit("找不到源图: %s" % src)

    sprite = cutout(src)
    sprite.save(os.path.join(ASSETS, "pet_base.png"))

    eyes, rgb, alpha, sat, val = detect_eyes(sprite)
    eyes.sort(key=lambda e: 0 if e["name"] == "near" else 1)

    # 近眼底板
    for e in eyes:
        if e["gaze"]:
            e["plate"] = "pet_eye_near.png"
            build_eye_plate(sprite, e).save(os.path.join(ASSETS, e["plate"]))
        else:
            e["plate"] = None

    variants = {
        "pet_base.png": sprite,
        "pet_blink.png": None,
        "pet_happy.png": None,
        "pet_sleep.png": None,
        "pet_angry.png": None,
    }
    v_blink = sprite
    for e in eyes:
        v_blink = paint_lid(v_blink, e, 1.0, "closed")
    variants["pet_blink.png"] = v_blink
    variants["pet_sleep.png"] = v_blink

    v_happy = sprite
    for e in eyes:
        v_happy = paint_lid(v_happy, e, 1.0, "happy")
    variants["pet_happy.png"] = v_happy

    v_angry = sprite
    for e in eyes:
        v_angry = paint_lid(v_angry, e, 1.0, "glare")
    variants["pet_angry.png"] = v_angry

    for name, im in variants.items():
        if im is not None and name != "pet_base.png":
            im.save(os.path.join(ASSETS, name))

    build_sounds()

    meta = {
        "width": sprite.width, "height": sprite.height,
        "eyes": eyes,
        "variants": {k.replace("pet_", "").replace(".png", ""): k for k in variants},
    }
    with open(os.path.join(ASSETS, "eyes.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("精灵图 %dx%d" % (sprite.width, sprite.height))
    for e in eyes:
        print("  %-4s box=%s pupil=%s gaze=%s" % (e["name"], e["box"], e["pupil"], e["gaze"]))
    print("表情变体:", [k for k in variants if variants[k] is not None])
    print("素材已写入", ASSETS)


if __name__ == "__main__":
    main()
