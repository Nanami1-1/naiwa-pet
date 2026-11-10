# -*- coding: utf-8 -*-
"""全局配置。想调手感基本都在这里。"""

import os
import sys

from version import REPO, VERSION

if getattr(sys, "frozen", False):
    # 打包成 exe 之后：assets 放在 exe 同级目录，方便别人直接换音效和素材
    BASE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLED = True
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    BUNDLED = False
ASSETS = os.path.join(BASE, "assets")
# 音效总体音量（0~1）。桌宠是挂在后台陪着的，比普通应用再轻一点更舒服。
# 这只是软件音量，不动系统音量；右键菜单「音效音量」可以随时调。
SFX_VOLUME = 0.35

# 右键菜单里的三档
SFX_VOLUME_CHOICES = (("小声", 0.2), ("适中", 0.35), ("大声", 0.55))

# 上一版的三档值 → 现在的值。老用户的 settings.json 里还存着 0.3/0.5/0.8，
# 不映射的话菜单里会一个勾都没有，看着像坏了。
SFX_VOLUME_LEGACY = {0.3: 0.2, 0.5: 0.35, 0.8: 0.55}

SOUNDS = os.path.join(ASSETS, "sounds")
CUSTOM_SOUNDS = os.path.join(SOUNDS, "custom")

# ---- 尺寸（逻辑像素）
PET_H = 240          # 桌宠在屏幕上的高度
MARGIN = 26          # 精灵图四周留白，给挤压/倾斜留出空间
SHADOW_H = 30        # 脚下投影区高度

# ---- 节奏
FPS = 60
MAX_ROT = 4.0        # 身体最大倾斜角度
MAX_LEAN = 1.3       # 朝鼠标偏身幅度
DT = 1.0 / FPS

# ---- 物理
GRAVITY = 2600.0     # px/s^2
AIR_DRAG = 0.985
GROUND_BOUNCE = 0.40
WALL_BOUNCE = 0.55
FRICTION = 0.86      # 落地后水平摩擦（每帧系数）
THROW_SCALE = 1.0

# ---- 行为
WALK_SPEED = 46.0        # px/s
IDLE_MIN, IDLE_MAX = 3.5, 9.0
WALK_MIN, WALK_MAX = 1.2, 3.4
BLINK_MIN, BLINK_MAX = 2.2, 6.0
BLINK_DUR = 0.13

# ---- 需求衰减（每分钟）
SATIETY_DECAY = 1.1
AFFECTION_DECAY = 0.25
ENERGY_DECAY = 0.55
ENERGY_REGEN = 2.4

# ---- 配色
INK = (58, 48, 36)
INK_SOFT = (120, 106, 88)
CREAM = (255, 251, 243)
CREAM_EDGE = (232, 218, 196)
ACCENT = (240, 168, 48)
HEART = (231, 102, 106)
FOOD = (238, 160, 62)
BAR_BG = (238, 229, 212)

# ---- 文案
LINES = {
    "tap": ["嗯？", "戳我干嘛", "在的在的", "哎哟", "干嘛呀"],
    "tap_many": ["别戳了！", "再戳要生气了", "手欠是吧", "……"],
    "drag": ["哇啊啊", "放我下来", "要去哪"],
    "land": ["噗", "到了", "站稳了", "呼——"],
    "pet": ["嘿嘿", "舒服", "再摸摸", "唔……"],
    "feed": ["好次！", "还有吗", "谢谢～", "满意"],
    "hungry": ["咕……", "饿饿", "有吃的吗", "肚子空了"],
    "sleep": ["困了……", "眯一会儿", "Zzz"],
    "wake": ["唔……醒了", "睡饱了", "啊——"],
    "spin": ["转圈圈！", "看我表演", "嘿！"],
}

SINGLETON = "blobby-pet-single-instance"

FONT = "Microsoft YaHei UI"

# ---- 更新提示（{ver} 会被替换成新版本号）
UPDATE_LINE = "我学会新本事了（{ver}），右键我看看"
UPDATE_LATEST = "已经是最新的啦"
UPDATE_FAILED = "联网失败，等会儿再试"
