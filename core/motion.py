# -*- coding: utf-8 -*-
"""行为与物理。

坐标约定：self.x / self.y 是「脚底中心」在屏幕上的全局逻辑坐标。
窗口位置由它反推，所有挤压旋转都绕脚底发生。
"""

import math
import random

import config as C
from core.sprite import Pose

IDLE, WALK, DRAG, AIR, SLEEP = "idle", "walk", "drag", "air", "sleep"


class Spring:
    """一维弹簧，用来做挤压回弹。"""

    def __init__(self, k=190.0, c=15.0):
        self.v = 0.0
        self.vv = 0.0
        self.k = k
        self.c = c

    def push(self, amount):
        self.vv += amount

    def update(self, dt):
        a = -self.k * self.v - self.c * self.vv
        self.vv += a * dt
        self.v += self.vv * dt
        if abs(self.v) < 1e-4 and abs(self.vv) < 1e-3:
            self.v = 0.0
            self.vv = 0.0


class Behavior:
    def __init__(self, sprite, needs, sfx=None, say=None):
        self.sprite = sprite
        self.needs = needs
        self.sfx = sfx
        self.say = say or (lambda *a, **k: None)

        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0

        self.state = IDLE
        self.facing_right = False
        self.squash = Spring()
        self.lean = 0.0

        self.t = 0.0
        self.idle_t = random.uniform(C.IDLE_MIN, C.IDLE_MAX)
        self.walk_t = 0.0
        self.walk_dir = -1.0

        self.blink_t = random.uniform(C.BLINK_MIN, C.BLINK_MAX)
        self.blink_anim = 0.0

        self.emote = None
        self.emote_t = 0.0
        self.spin_t = -1.0
        self.click_streak = 0
        self.click_timer = 0.0

        self.gaze = (0.0, 0.0)
        self.contact = 1.0
        self.dragging = False
        self.drag_off = (0.0, 0.0)
        self.drag_hist = []
        self.sleepy = False
        self.staying = False

    # ---------------------------------------------------------------- 工具
    def _sfx(self, name):
        """播放音效。返回 False 说明被高优先级音效挡下来了。"""
        if self.sfx:
            return self.sfx.play(name)
        return None

    def place(self, bounds, x=None):
        self.y = float(bounds.bottom())
        self.x = float(x if x is not None else bounds.center().x() + random.uniform(-100, 100))
        self.vx = self.vy = 0.0
        self.state = IDLE

    def _grounded(self, bounds):
        return self.y >= bounds.bottom() - 0.5

    # ---------------------------------------------------------------- 外部事件
    def press(self, pos):
        self.dragging = True
        self.drag_off = (self.x - pos.x(), self.y - pos.y())
        self.drag_hist = [(pos.x(), pos.y(), self.t)]
        self.state = DRAG
        self.vx = self.vy = 0.0
        self.squash.push(1.6)

    def drag_to(self, pos):
        nx = pos.x() + self.drag_off[0]
        ny = pos.y() + self.drag_off[1]
        inst_x = (nx - self.x) / max(C.DT, 1e-4)
        inst_y = (ny - self.y) / max(C.DT, 1e-4)
        self.vx = inst_x * 0.45 + self.vx * 0.55
        self.vy = inst_y * 0.45 + self.vy * 0.55
        self.x = nx
        self.y = ny
        self.drag_hist.append((pos.x(), pos.y(), self.t))
        if len(self.drag_hist) > 6:
            self.drag_hist.pop(0)

    def release(self, bounds):
        self.dragging = False
        vx = vy = 0.0
        if len(self.drag_hist) >= 2:
            x0, y0, t0 = self.drag_hist[0]
            x1, y1, t1 = self.drag_hist[-1]
            dt = max(1e-3, t1 - t0)
            vx = (x1 - x0) / dt
            vy = (y1 - y0) / dt
        self.vx = max(-2400.0, min(2400.0, vx)) * C.THROW_SCALE
        self.vy = max(-2400.0, min(2400.0, vy)) * C.THROW_SCALE
        self.state = AIR
        self.squash.push(-2.2)
        self._sfx("drag")

    def click(self):
        self.click_streak += 1
        self.click_timer = 1.3
        if self.click_streak >= 5:
            self.click_streak = 0
            self._emote("angry", 1.7)
            self.needs.scold()
            self._sfx("tap_many")
            self.say("tap_many")
            self.squash.push(2.6)
        else:
            if self._grounded_once():
                self.vy = -560.0
                self.state = AIR
            self.squash.push(-3.4)
            played = self._sfx("tap")
            # 上一下的特殊语音还在放，气泡也别换，不然看着像被打断了
            if played is not False:
                self.say("tap")

    def _grounded_once(self):
        return self.state not in (AIR, DRAG)

    def double_click(self):
        self.spin_t = 0.0
        self._emote("happy", 0.9)
        self._sfx("spin")
        self.say("spin")

    def feed(self):
        self.needs.feed()
        self._emote("happy", 1.6)
        self.squash.push(2.4)
        self._sfx("feed")
        self.say("feed")

    def pet_head(self):
        self.needs.pet()
        self._emote("happy", 1.4)
        self.squash.push(1.6)
        self._sfx("pet")
        self.say("pet")

    def toggle_sleep(self, bounds):
        if self.sleepy:
            self.sleepy = False
            self.state = IDLE
            self._sfx("wake")
            self.say("wake")
        else:
            self.sleepy = True
            self.vx = self.vy = 0.0
            self.y = float(bounds.bottom())
            self.state = SLEEP
            self._sfx("sleep")
            self.say("sleep")

    def wake(self):
        if self.sleepy:
            self.sleepy = False
            self.state = IDLE
            self._sfx("wake")
            self.say("wake")

    def _emote(self, name, dur):
        self.emote = name
        self.emote_t = dur

    # ---------------------------------------------------------------- 每帧
    def update(self, dt, bounds, cursor):
        self.t += dt
        self.squash.update(dt)

        if self.click_timer > 0:
            self.click_timer -= dt
            if self.click_timer <= 0:
                self.click_streak = 0

        if self.emote_t > 0:
            self.emote_t -= dt
            if self.emote_t <= 0 and self.emote:
                self.emote = None

        if self.spin_t >= 0:
            self.spin_t += dt / 0.62
            if self.spin_t >= 1.0:
                self.spin_t = -1.0

        self.needs.tick(dt, sleeping=(self.state == SLEEP))

        if self.state == DRAG:
            self.vx *= 0.88
            self.vy *= 0.88
        elif self.state == SLEEP:
            self.vx = self.vy = 0.0
            if self.y < bounds.bottom():
                self.y = float(bounds.bottom())
        else:
            self._physics(bounds, dt)
            if self.state == WALK:
                self._walk_step(bounds, dt)
            elif self.state == IDLE:
                self._idle_step(dt)

        if self.needs.hungry and random.random() < dt * 0.07 and self.state != SLEEP:
            self.say("hungry")
            self._sfx("hungry")

        self._update_blink(dt)
        self._update_gaze(cursor)
        self.contact = self._contact(bounds)

    # ---------------------------------------------------------------- 物理
    def _physics(self, bounds, dt):
        grounded = self._grounded(bounds)
        if not grounded or self.vy < -1:
            self.vy += C.GRAVITY * dt

        self.vx *= C.AIR_DRAG
        self.x += self.vx * dt
        self.y += self.vy * dt

        half = self.sprite.w * 0.34
        left = bounds.left() + half
        right = bounds.right() - half
        if self.x < left:
            self.x = left
            if self.vx < -220:
                self.squash.push(-1.2)
                self._sfx("land")
            self.vx = abs(self.vx) * C.WALL_BOUNCE
            self.facing_right = True
        elif self.x > right:
            self.x = right
            if self.vx > 220:
                self.squash.push(-1.2)
                self._sfx("land")
            self.vx = -abs(self.vx) * C.WALL_BOUNCE
            self.facing_right = False

        if self.y >= bounds.bottom():
            impact = self.vy
            self.y = float(bounds.bottom())
            if impact > 320:
                self.vy = -impact * C.GROUND_BOUNCE
                self.squash.push(min(8.0, impact / 150.0))
                self._sfx("land")
                if random.random() < 0.4:
                    self.say("land")
            else:
                self.vy = 0.0
                self.vx *= C.FRICTION
                if abs(self.vx) < 16:
                    self.vx = 0.0
                    if self.state == AIR:
                        self.state = IDLE
                        self.idle_t = random.uniform(0.5, 1.8)

    def _walk_step(self, bounds, dt):
        self.x += self.walk_dir * C.WALK_SPEED * dt
        self.y = float(bounds.bottom())
        half = self.sprite.w * 0.30
        if self.x <= bounds.left() + half:
            self.x = bounds.left() + half
            self.walk_dir = 1.0
            self.facing_right = True
        elif self.x >= bounds.right() - half:
            self.x = bounds.right() - half
            self.walk_dir = -1.0
            self.facing_right = False
        self.walk_t -= dt
        if self.walk_t <= 0:
            self.state = IDLE
            self.idle_t = random.uniform(C.IDLE_MIN, C.IDLE_MAX)

    def _idle_step(self, dt):
        if self.staying or self.needs.tired:
            return
        self.idle_t -= dt
        if self.idle_t > 0:
            return
        r = random.random()
        if r < 0.42:
            self.state = WALK
            self.walk_t = random.uniform(C.WALK_MIN, C.WALK_MAX)
            self.walk_dir = random.choice((-1.0, 1.0))
            self.facing_right = self.walk_dir > 0
        elif r < 0.55:
            self.vy = -random.uniform(340, 500)
            self.state = AIR
            self.squash.push(-2.4)
        else:
            self.idle_t = random.uniform(C.IDLE_MIN, C.IDLE_MAX)

    # ---------------------------------------------------------------- 细节
    def _update_blink(self, dt):
        if self.blink_anim > 0:
            self.blink_anim -= dt
            return
        self.blink_t -= dt
        if self.blink_t <= 0:
            self.blink_anim = C.BLINK_DUR
            self.blink_t = random.uniform(C.BLINK_MIN, C.BLINK_MAX)
            if random.random() < 0.2:
                self.blink_t = 0.24

    def _update_gaze(self, cursor):
        if cursor is None:
            self.gaze = (0.0, 0.0)
            return
        ox = self.x
        oy = self.y - self.sprite.h * 0.88
        dx = cursor.x() - ox
        dy = cursor.y() - oy
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            self.gaze = (0.0, 0.0)
            return
        k = 0.45 + 0.55 * min(1.0, 120.0 / max(dist, 1.0))
        self.gaze = (dx / dist * k, dy / dist * k)
        target = max(-C.MAX_LEAN, min(C.MAX_LEAN, self.gaze[0] * C.MAX_LEAN))
        self.lean += (target - self.lean) * 0.10

    def _contact(self, bounds):
        if self.state == DRAG:
            return 0.3
        gap = max(0.0, bounds.bottom() - self.y)
        return max(0.0, 1.0 - gap / 130.0)

    # ---------------------------------------------------------------- 出 pose
    def pose(self) -> Pose:
        p = Pose()
        breathe = math.sin(self.t * 1.9) * 0.010 if self.state in (IDLE,) else 0.0
        if self.state == SLEEP:
            breathe = math.sin(self.t * 1.15) * 0.020

        sy = 1.0 + self.squash.v * 0.032 + breathe
        sx = 1.0 - self.squash.v * 0.024 - breathe * 0.5

        if self.state == WALK:
            ph = self.t * 9.0
            sy += math.sin(ph * 2) * 0.013
            sx -= math.sin(ph * 2) * 0.009
        if self.state == DRAG:
            speed = math.hypot(self.vx, self.vy)
            stretch = min(0.085, speed / 11000.0)
            sy += stretch
            sx -= stretch * 0.65
        if self.state == SLEEP:
            sy *= 0.96
            sx *= 1.03

        p.sy = sy
        p.sx = sx
        p.flip = self.facing_right
        p.contact = self.contact
        p.gaze = self.gaze

        rot = self.lean
        if self.state == DRAG:
            rot += max(-1.6, min(1.6, self.vx * 0.0035))
        elif self.state == WALK:
            rot += math.sin(self.t * 9.0) * 0.7

        if self.spin_t >= 0:
            e = 1 - (1 - self.spin_t) ** 3
            p.rot = 360.0 * e * (1 if not self.facing_right else -1)
        else:
            p.rot = max(-C.MAX_ROT, min(C.MAX_ROT, rot)) * (1 if not self.facing_right else -1)

        variant, a = None, 0.0
        if self.state == SLEEP:
            variant, a = "sleep", 1.0
        elif self.emote == "angry":
            variant, a = "angry", min(1.0, self.emote_t / 0.2)
        elif self.emote == "happy":
            variant, a = "happy", min(1.0, self.emote_t / 0.2)
        elif self.blink_anim > 0:
            k = 1.0 - abs(self.blink_anim / C.BLINK_DUR - 0.5) * 2.0
            variant, a = "blink", max(0.0, min(1.0, k * 1.5))
        p.variant = variant
        p.variant_a = a
        return p
