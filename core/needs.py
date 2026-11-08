# -*- coding: utf-8 -*-
"""需求与情绪。数值都在 0-100。"""

import random

import config as C


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


class Needs:
    def __init__(self):
        self.satiety = 72.0
        self.affection = 55.0
        self.energy = 80.0
        self.last_change = 0.0  # 用于 HUD 显示时长

    # ---------------------------------------------------------------- 时间
    def tick(self, dt, sleeping=False):
        self.satiety = _clamp(self.satiety - C.SATIETY_DECAY * dt / 60.0)
        self.affection = _clamp(self.affection - C.AFFECTION_DECAY * dt / 60.0)
        if sleeping:
            self.energy = _clamp(self.energy + C.ENERGY_REGEN * dt / 60.0)
        else:
            self.energy = _clamp(self.energy - C.ENERGY_DECAY * dt / 60.0)

    # ---------------------------------------------------------------- 行为
    def feed(self):
        self.satiety = _clamp(self.satiety + 26)
        self.affection = _clamp(self.affection + 3)
        self.last_change = 2.6

    def pet(self):
        self.affection = _clamp(self.affection + 12)
        self.last_change = 2.2

    def scold(self):
        self.affection = _clamp(self.affection - 2)
        self.last_change = 1.4

    # ---------------------------------------------------------------- 状态
    @property
    def hungry(self):
        return self.satiety < 28

    @property
    def tired(self):
        return self.energy < 22

    @property
    def mood(self):
        """返回 (名称, 颜色)，用于气泡描边和 HUD。"""
        if self.hungry:
            return "饿", (226, 150, 90)
        if self.tired:
            return "困", (150, 158, 200)
        if self.affection > 75:
            return "黏人", (231, 102, 106)
        if self.affection > 40:
            return "还好", (120, 170, 130)
        return "冷", (140, 140, 150)

    def speech(self, key):
        return random.choice(C.LINES.get(key, ["……"]))
