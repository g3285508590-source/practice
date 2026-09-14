# -*- coding: utf-8 -*-
"""
愤怒的小鸟（Angry Birds）—— pygame + pymunk 物理引擎实现的小游戏

运行：  python angry_birds.py
依赖：  pip install pygame pymunk

操作：
    鼠标按住小鸟向后拉伸 → 松手发射（拉伸越远，飞得越快）
    飞行中点击鼠标 / 按空格 → 触发小鸟技能（黄鸟加速、黑鸟爆炸）
    R 重玩本关    N 下一关    ESC 退出
"""
from __future__ import annotations

import array
import math
import os
import random

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
import pymunk

# ----------------------------------------------------------------- 基础常量
W, H = 1280, 720                 # 窗口尺寸
GROUND_Y = 620                   # 地面在屏幕上的 y 坐标
GRAVITY = -1150.0                # 重力加速度（物理坐标 y 轴向上）
SLING = (196.0, 158.0)           # 弹弓皮兜位置（物理坐标）
MAX_PULL = 118.0                 # 最大拉伸距离
LAUNCH_K = 9.8                   # 拉伸距离 → 初速度（满拉 ≈ 1156 px/s）
BIRD_R = 17
FPS = 60

# 碰撞类型
CT_BIRD, CT_PIG, CT_BLOCK, CT_GROUND = 1, 2, 3, 4

# 伤害模型
IMPACT_MIN = 450.0               # 小鸟撞击的最小有效冲量
BIRD_DMG = 0.022                 # 小鸟撞击伤害系数
FALL_MIN = 380.0                 # 结构互撞的最小相对速度
FALL_DMG = 0.11                  # 结构互撞伤害系数
PIG_SCALE = 1.5                  # 小猪受到的伤害倍率

PIG_R = 24


# ----------------------------------------------------------------- 坐标转换
def to_screen(x, y):
    """物理坐标 -> 屏幕坐标"""
    return (x, GROUND_Y - y)


def to_world(sx, sy):
    """屏幕坐标 -> 物理坐标"""
    return (sx, GROUND_Y - sy)


# ----------------------------------------------------------------- 素材定义
MATERIALS = {
    "wood": {
        "color": (200, 140, 76), "edge": (142, 92, 42), "hp": 70.0,
        "mass_k": 0.0045, "friction": 0.85, "elasticity": 0.12, "score": 500,
    },
    "ice": {
        "color": (150, 216, 250), "edge": (86, 168, 220), "hp": 40.0,
        "mass_k": 0.0030, "friction": 0.25, "elasticity": 0.20, "score": 500,
    },
    "stone": {
        "color": (158, 158, 166), "edge": (104, 104, 114), "hp": 165.0,
        "mass_k": 0.0110, "friction": 0.95, "elasticity": 0.08, "score": 800,
    },
}

BIRDS = {
    "red":    {"color": (214, 45, 45),  "dark": (150, 24, 24), "mass": 6.0, "ability": None,    "name": "红鸟"},
    "yellow": {"color": (246, 197, 17), "dark": (188, 143, 6), "mass": 5.2, "ability": "boost", "name": "黄鸟"},
    "black":  {"color": (52, 52, 62),   "dark": (24, 24, 32),  "mass": 7.5, "ability": "bomb",  "name": "黑鸟"},
}

# 每关：blocks = (x, y, w, h, 材质, 角度)，pigs = (x, y, 半径)
# 物理坐标：地面 y = 0，y 轴向上
LEVELS = [
    {
        "name": "第 1 关 · 木屋",
        "birds": ["red", "red", "yellow"],
        "blocks": [
            (830, 55, 22, 110, "wood", 0),
            (970, 55, 22, 110, "wood", 0),
            (900, 121, 200, 22, "wood", 0),
            (1150, 40, 80, 80, "ice", 0),
        ],
        "pigs": [(900, 25, 24), (900, 156, 22)],
    },
    {
        "name": "第 2 关 · 双塔",
        "birds": ["red", "yellow", "black", "red"],
        "blocks": [
            (720, 50, 20, 100, "ice", 0),
            (840, 50, 20, 100, "ice", 0),
            (780, 111, 170, 20, "wood", 0),
            (780, 146, 40, 40, "wood", 0),
            (1020, 50, 22, 100, "stone", 0),
            (1140, 50, 22, 100, "stone", 0),
            (1080, 111, 170, 20, "wood", 0),
        ],
        "pigs": [(780, 25, 24), (1080, 25, 24), (780, 191, 20)],
    },
    {
        "name": "第 3 关 · 双子堡",
        "birds": ["red", "yellow", "black", "red", "yellow"],
        "blocks": [
            # 左堡：石头柱子 + 木头房顶（房顶是弱点）
            (830, 70, 26, 140, "stone", 0),
            (990, 70, 26, 140, "stone", 0),
            (910, 151, 240, 20, "wood", 0),
            (910, 176, 40, 30, "wood", 0),
            # 右堡：冰块柱子 + 石头房顶（柱子是弱点）
            (1070, 60, 24, 120, "ice", 0),
            (1230, 60, 24, 120, "ice", 0),
            (1150, 131, 200, 20, "stone", 0),
        ],
        "pigs": [(910, 25, 24), (910, 216, 22), (1150, 25, 24), (1150, 161, 20)],
    },
]


# ----------------------------------------------------------------- 音效合成
def _make_sound(freq=440.0, dur=0.2, vol=0.35, sweep=0.0, noise=0.0):
    """用标准库合成简单音效（不需要 numpy）"""
    init = pygame.mixer.get_init()
    if not init:
        return None
    sr = init[0]
    n = max(1, int(sr * dur))
    buf = array.array("h")
    for i in range(n):
        t = i / sr
        env = (1.0 - i / n) ** 2
        v = math.sin(2.0 * math.pi * freq * (1.0 + sweep * t) * t)
        if noise:
            v = v * (1.0 - noise) + random.uniform(-1.0, 1.0) * noise
        buf.append(int(max(-1.0, min(1.0, v * env * vol)) * 32000))
    try:
        return pygame.mixer.Sound(buffer=buf.tobytes())
    except Exception:
        return None


class Sounds:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self.map = {}
        if not self.enabled or not pygame.mixer.get_init():
            self.enabled = False
            return
        try:
            self.map["launch"] = _make_sound(320, 0.22, 0.30, sweep=1.6, noise=0.45)
            self.map["hit"] = _make_sound(150, 0.10, 0.30, sweep=-0.4, noise=0.25)
            self.map["break"] = _make_sound(240, 0.20, 0.30, sweep=-0.7, noise=0.55)
            self.map["pig"] = _make_sound(700, 0.16, 0.32, sweep=0.9)
            self.map["win"] = _make_sound(620, 0.45, 0.28, sweep=0.8)
            self.map["lose"] = _make_sound(300, 0.50, 0.28, sweep=-0.6)
            self.map["boost"] = _make_sound(900, 0.14, 0.25, sweep=0.7)
            self.map["bomb"] = _make_sound(90, 0.40, 0.40, sweep=-0.5, noise=0.85)
        except Exception:
            self.enabled = False

    def play(self, name):
        if self.enabled and self.map.get(name):
            try:
                self.map[name].play()
            except Exception:
                pass


# ----------------------------------------------------------------- 字体
_FONT_CACHE = {}


def load_font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    paths = []
    if bold:
        paths += ["C:/Windows/Fonts/msyhbd.ttc"]
    paths += ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "C:/Windows/Fonts/simsun.ttc", "/System/Library/Fonts/PingFang.ttc"]
    font = None
    for p in paths:
        if os.path.exists(p):
            try:
                font = pygame.font.Font(p, size)
                break
            except Exception:
                font = None
    if font is None:
        try:
            font = pygame.font.SysFont("microsoftyahei,simhei,arial", size, bold=bold)
        except Exception:
            font = pygame.font.Font(None, size)
    _FONT_CACHE[key] = font
    return font


# ----------------------------------------------------------------- 背景
def _cloud(surf, cx, cy, s):
    for (dx, dy, r) in ((0, 0, 46), (42, 8, 34), (-44, 10, 32), (16, -18, 30), (-14, -14, 26)):
        pygame.draw.circle(surf, (255, 255, 255), (int(cx + dx * s), int(cy + dy * s)), int(r * s))


def make_background():
    surf = pygame.Surface((W, H))
    for y in range(H):
        t = y / H
        c = (int(126 + 74 * t), int(196 + 42 * t), int(238 + 14 * t))
        pygame.draw.line(surf, c, (0, y), (W, y))
    pygame.draw.circle(surf, (255, 246, 196), (1120, 110), 60)
    pygame.draw.circle(surf, (255, 252, 226), (1120, 110), 47)
    for (cx, cy, s) in ((200, 118, 1.0), (560, 76, 0.75), (890, 152, 0.6)):
        _cloud(surf, cx, cy, s)
    pygame.draw.ellipse(surf, (150, 205, 150), (-220, 440, 940, 330))
    pygame.draw.ellipse(surf, (128, 190, 134), (430, 480, 980, 300))
    pygame.draw.ellipse(surf, (150, 205, 150), (940, 450, 720, 320))
    pygame.draw.rect(surf, (126, 198, 88), (0, GROUND_Y, W, 26))
    pygame.draw.rect(surf, (108, 176, 74), (0, GROUND_Y + 20, W, 10))
    pygame.draw.rect(surf, (146, 106, 68), (0, GROUND_Y + 28, W, H - GROUND_Y - 28))
    for i in range(0, W, 17):
        x = i + (i * 7 % 11)
        pygame.draw.line(surf, (142, 212, 104), (x, GROUND_Y), (x + (i % 3), GROUND_Y - 7), 2)
    for i in range(0, W, 63):
        pygame.draw.circle(surf, (128, 92, 58), (i + 20, GROUND_Y + 60), 4)
        pygame.draw.circle(surf, (132, 96, 60), (i + 44, GROUND_Y + 84), 3)
    return surf


# ----------------------------------------------------------------- 实体
class Entity:
    kind = "entity"

    def __init__(self):
        self.hp = 1.0
        self.max_hp = 1.0
        self.dead = False
        self.flash = 0.0

    def take_damage(self, dmg):
        if self.dead or dmg <= 0:
            return
        self.hp -= dmg
        self.flash = 0.14
        if self.hp <= 0:
            self.dead = True

    @property
    def hp_ratio(self):
        return max(0.0, min(1.0, self.hp / self.max_hp))


class Block(Entity):
    kind = "block"

    def __init__(self, space, x, y, w, h, mat, angle=0.0):
        super().__init__()
        self.mat = mat
        self.m = MATERIALS[mat]
        self.w, self.h = float(w), float(h)
        self.hp = self.max_hp = self.m["hp"]
        mass = max(0.6, self.m["mass_k"] * w * h)
        body = pymunk.Body(mass, pymunk.moment_for_box(mass, (self.w, self.h)))
        body.position = (float(x), float(y))
        body.angle = math.radians(angle)
        body.angular_damping = 0.55
        shape = pymunk.Poly.create_box(body, (self.w, self.h), radius=1.0)
        shape.friction = self.m["friction"]
        shape.elasticity = self.m["elasticity"]
        shape.collision_type = CT_BLOCK
        shape.entity = self
        space.add(body, shape)
        self.body, self.shape = body, shape
        self._img = self._build_image()
        self._dmg_cache = {}

    def _build_image(self):
        w, h = int(self.w), int(self.h)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(surf, self.m["color"], (0, 0, w, h), border_radius=3)
        if self.mat == "wood":
            for yy in range(6, h - 4, 14):
                pygame.draw.line(surf, self.m["edge"], (4, yy), (w - 4, yy + 2), 1)
        elif self.mat == "ice":
            hl = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(hl, (255, 255, 255, 90), (3, 3, w - 6, max(2, h // 5)), border_radius=3)
            surf.blit(hl, (0, 0))
        else:
            for _ in range(int(w * h / 400)):
                px = random.randint(3, max(4, w - 4))
                py = random.randint(3, max(4, h - 4))
                pygame.draw.circle(surf, self.m["edge"], (px, py), 2)
        pygame.draw.rect(surf, self.m["edge"], (0, 0, w, h), width=3, border_radius=3)
        return surf

    def image(self):
        if self.hp >= self.max_hp:
            return self._img
        bucket = int((1.0 - self.hp_ratio) * 3)
        if bucket not in self._dmg_cache:
            img = self._img.copy()
            ov = pygame.Surface((int(self.w), int(self.h)), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 40 + 40 * bucket))
            img.blit(ov, (0, 0))
            w, h = int(self.w), int(self.h)
            cuts = [(0.2, 0.1, 0.45, 0.9), (0.55, 0.05, 0.35, 0.75), (0.7, 0.25, 0.9, 0.95)]
            for i in range(min(bucket + 1, len(cuts))):
                x1, y1, x2, y2 = cuts[i]
                pygame.draw.line(img, (60, 40, 26), (w * x1, h * y1), (w * x2, h * y2), 2)
            self._dmg_cache[bucket] = img
        return self._dmg_cache[bucket]


class Pig(Entity):
    kind = "pig"

    def __init__(self, space, x, y, r=PIG_R):
        super().__init__()
        self.r = float(r)
        self.hp = self.max_hp = 45.0
        mass = 3.0 + r * 0.06
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, self.r))
        body.position = (float(x), float(y))
        body.angular_damping = 0.55
        shape = pymunk.Circle(body, self.r)
        shape.friction = 0.7
        shape.elasticity = 0.25
        shape.collision_type = CT_PIG
        shape.entity = self
        space.add(body, shape)
        self.body, self.shape = body, shape
        self._imgs = {}

    def image(self):
        b = int((1.0 - self.hp_ratio) * 2.99)
        if b not in self._imgs:
            r = self.r
            s = int(r * 2.6)
            surf = pygame.Surface((s, s), pygame.SRCALPHA)
            c = (s // 2, s // 2)
            pygame.draw.circle(surf, (108, 186, 92), (int(c[0] - r * 0.62), int(c[1] - r * 0.78)), int(r * 0.30))
            pygame.draw.circle(surf, (108, 186, 92), (int(c[0] + r * 0.62), int(c[1] - r * 0.78)), int(r * 0.30))
            body_col = (128, 210, 104) if b == 0 else (150, 196, 96)
            pygame.draw.circle(surf, body_col, c, int(r))
            pygame.draw.circle(surf, (96, 174, 82), c, int(r), 3)
            pygame.draw.ellipse(surf, (176, 228, 148),
                                pygame.Rect(int(c[0] - r * 0.6), int(c[1] + r * 0.05), int(r * 1.2), int(r * 0.95)))
            nx, ny = c[0], c[1] + r * 0.18
            pygame.draw.ellipse(surf, (110, 196, 90),
                                pygame.Rect(int(nx - r * 0.42), int(ny - r * 0.28), int(r * 0.84), int(r * 0.58)))
            pygame.draw.circle(surf, (60, 120, 52), (int(nx - r * 0.17), int(ny)), max(2, int(r * 0.09)))
            pygame.draw.circle(surf, (60, 120, 52), (int(nx + r * 0.17), int(ny)), max(2, int(r * 0.09)))
            for sx in (-1, 1):
                ex, ey = c[0] + sx * r * 0.34, c[1] - r * 0.32
                pygame.draw.circle(surf, (255, 255, 255), (int(ex), int(ey)), max(3, int(r * 0.22)))
                pygame.draw.circle(surf, (30, 30, 30), (int(ex + sx * r * 0.05), int(ey)), max(2, int(r * 0.11)))
            if b >= 1:
                pygame.draw.line(surf, (70, 60, 40), (int(c[0] - r * 0.6), int(c[1] - r * 0.62)),
                                 (int(c[0] - r * 0.16), int(c[1] - r * 0.5)), 3)
                pygame.draw.line(surf, (70, 60, 40), (int(c[0] + r * 0.6), int(c[1] - r * 0.62)),
                                 (int(c[0] + r * 0.16), int(c[1] - r * 0.5)), 3)
            if b >= 2:
                ov = pygame.Surface((s, s), pygame.SRCALPHA)
                ov.fill((150, 60, 80, 120))
                surf.blit(ov, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            self._imgs[b] = surf
        return self._imgs[b]


class Bird(Entity):
    kind = "bird"

    def __init__(self, kind, x, y):
        super().__init__()
        self.bird_kind = kind
        self.cfg = BIRDS[kind]
        self.hp = self.max_hp = 999.0
        self.used_ability = False
        self.launched = False
        mass = self.cfg["mass"]
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, BIRD_R))
        body.position = (float(x), float(y))
        body.angular_damping = 1.2
        shape = pymunk.Circle(body, BIRD_R)
        shape.friction = 0.6
        shape.elasticity = 0.4
        shape.collision_type = CT_BIRD
        shape.entity = self
        self.body, self.shape = body, shape
        self._img = self._build_image()

    def _build_image(self):
        r = BIRD_R
        s = int(r * 3.2)
        surf = pygame.Surface((s, s), pygame.SRCALPHA)
        c = (s // 2, s // 2)
        col, dark = self.cfg["color"], self.cfg["dark"]
        pygame.draw.polygon(surf, dark, [(c[0] - r * 0.9, c[1] - r * 0.2), (c[0] - r * 1.5, c[1] - r * 0.8),
                                         (c[0] - r * 1.5, c[1] + r * 0.5)])
        pygame.draw.circle(surf, col, c, int(r))
        pygame.draw.circle(surf, dark, c, int(r), 3)
        pygame.draw.ellipse(surf, (255, 236, 214),
                            pygame.Rect(int(c[0] - r * 0.5), int(c[1] + r * 0.12), int(r * 1.0), int(r * 0.8)))
        if self.bird_kind == "black":
            pygame.draw.circle(surf, (200, 90, 40), (c[0], c[1]), max(3, int(r * 0.28)))
        for sx in (-1, 1):
            ex, ey = c[0] + sx * r * 0.30, c[1] - r * 0.34
            pygame.draw.circle(surf, (255, 255, 255), (int(ex), int(ey)), max(4, int(r * 0.29)))
            pygame.draw.circle(surf, (25, 25, 25), (int(ex + sx * r * 0.06), int(ey)), max(2, int(r * 0.14)))
        pygame.draw.line(surf, (40, 30, 24), (int(c[0] - r * 0.62), int(c[1] - r * 0.76)),
                         (int(c[0] - r * 0.06), int(c[1] - r * 0.52)), 4)
        pygame.draw.line(surf, (40, 30, 24), (int(c[0] + r * 0.10), int(c[1] - r * 0.54)),
                         (int(c[0] + r * 0.64), int(c[1] - r * 0.72)), 4)
        pygame.draw.polygon(surf, (250, 168, 26), [(c[0] + r * 0.30, c[1] + r * 0.06),
                                                   (c[0] + r * 1.25, c[1] + r * 0.26),
                                                   (c[0] + r * 0.30, c[1] + r * 0.52)])
        return surf


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "life", "max_life", "size")

    def __init__(self, x, y, color, size=4):
        self.x, self.y = x, y
        ang = random.uniform(0, math.tau)
        spd = random.uniform(60, 380)
        self.vx = math.cos(ang) * spd
        self.vy = math.sin(ang) * spd
        self.color = color
        self.size = size
        self.max_life = random.uniform(0.4, 0.9)
        self.life = self.max_life

    def step(self, dt):
        self.vy -= 900 * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        return self.life > 0


# ----------------------------------------------------------------- 游戏主体
class Game:
    def __init__(self, headless=False, level=0, sound=True):
        self.headless = headless
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
        try:
            pygame.mixer.pre_init(22050, -16, 1, 512)
        except Exception:
            pass
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("愤怒的小鸟 · Angry Birds (Python)")
        self.clock = pygame.time.Clock()
        self.font_big = load_font(44, bold=True)
        self.font = load_font(24)
        self.font_small = load_font(18)
        self.sounds = Sounds(enabled=sound)
        self.bg = make_background()
        self.total_score = 0
        self.running = True
        self.debug = os.environ.get("AB_DEBUG", "") not in ("", "0")
        self.max_impulse = 0.0
        self.load_level(level)

    # ---------------------------------------------------------- 关卡
    def load_level(self, index):
        self.level_index = max(0, min(index, len(LEVELS) - 1))
        lv = LEVELS[self.level_index]
        self.level_name = lv["name"]
        space = pymunk.Space()
        space.gravity = (0.0, GRAVITY)
        space.damping = 0.98
        space.sleep_time_threshold = 0.6
        space.idle_speed_threshold = 12.0
        space.on_collision(pre_solve=self.on_pre_solve, post_solve=self.on_post_solve)
        self.space = space

        ground = pymunk.Segment(space.static_body, (-600, 0), (W + 600, 0), 8)
        ground.friction = 1.0
        ground.elasticity = 0.25
        ground.collision_type = CT_GROUND
        space.add(ground)

        self.blocks = [Block(space, b[0], b[1], b[2], b[3], b[4], b[5]) for b in lv["blocks"]]
        self.pigs = [Pig(space, p[0], p[1], p[2]) for p in lv["pigs"]]
        self.particles = []
        self.pops = []
        self.trail = []
        self.birds_queue = list(lv["birds"])
        self.score = 0
        self.state = "aim"                 # aim / fly / settle / win / lose / allwin
        self.aiming = False
        self.drag = SLING
        self.flight_timer = 0.0
        self.settle_timer = 0.0
        self.current_bird = None
        self.show_hint = True
        self.time = 0.0
        self.ready_bird()

    def ready_bird(self):
        if self.birds_queue:
            self.current_bird = Bird(self.birds_queue.pop(0), SLING[0], SLING[1])
            self.drag = SLING
        else:
            self.current_bird = None
        self.trail = []
        self.flight_timer = 0.0
        self.state = "aim"

    # ---------------------------------------------------------- 物理回调
    def on_pre_solve(self, arbiter, space, data):
        a, b = arbiter.shapes
        try:
            rel = (a.body.velocity - b.body.velocity).length
        except Exception:
            rel = 0.0
        a._rel = rel
        b._rel = rel

    def on_post_solve(self, arbiter, space, data):
        a, b = arbiter.shapes
        ea = getattr(a, "entity", None)
        eb = getattr(b, "entity", None)
        if ea is None and eb is None:
            return
        impulse = arbiter.total_impulse.length
        if impulse > self.max_impulse:
            self.max_impulse = impulse
        by_bird = (getattr(ea, "kind", None) == "bird") or (getattr(eb, "kind", None) == "bird")
        if by_bird:
            base = max(0.0, impulse - IMPACT_MIN) * BIRD_DMG
            if base > 0:
                for e in (ea, eb):
                    if e is not None and e.kind in ("pig", "block"):
                        e.take_damage(base * (PIG_SCALE if e.kind == "pig" else 1.0))
                if self.debug:
                    print("bird impact impulse=%.0f dmg=%.1f" % (impulse, base))
            return
        if CT_GROUND in (a.collision_type, b.collision_type):
            return
        rel = max(getattr(a, "_rel", 0.0), getattr(b, "_rel", 0.0))
        if rel <= FALL_MIN:
            return
        masses = [s.body.mass for s in (a, b) if s.body.body_type == pymunk.Body.DYNAMIC]
        factor = min(2.0, (max(masses) if masses else 0.0) / 3.0)
        dmg = (rel - FALL_MIN) * FALL_DMG * factor
        for e in (ea, eb):
            if e is not None and e.kind in ("pig", "block"):
                e.take_damage(dmg * (PIG_SCALE if e.kind == "pig" else 1.0))

    # ---------------------------------------------------------- 发射
    def pull_vector(self):
        dx = SLING[0] - self.drag[0]
        dy = SLING[1] - self.drag[1]
        d = math.hypot(dx, dy)
        if d > MAX_PULL:
            k = MAX_PULL / d
            dx, dy = dx * k, dy * k
            d = MAX_PULL
        return dx, dy, d

    def launch(self, vx, vy):
        bird = self.current_bird
        if bird is None:
            return False
        self.space.add(bird.body, bird.shape)
        bird.body.velocity = (vx, vy)
        bird.launched = True
        self.state = "fly"
        self.flight_timer = 0.0
        self.trail = []
        self.show_hint = False
        self.sounds.play("launch")
        return True

    def release(self):
        dx, dy, d = self.pull_vector()
        self.aiming = False
        if d < 16:
            return False
        return self.launch(dx * LAUNCH_K, dy * LAUNCH_K)

    def fire_vector(self, vx, vy):
        """给测试 / 脚本用的直接发射接口"""
        if self.state != "aim" or self.current_bird is None:
            return False
        return self.launch(vx, vy)

    def use_ability(self):
        bird = self.current_bird
        if bird is None or self.state != "fly" or bird.used_ability:
            return
        ability = bird.cfg["ability"]
        if ability == "boost":
            v = bird.body.velocity
            if v.length > 1:
                bird.body.velocity = v * 1.9
            bird.used_ability = True
            self.sounds.play("boost")
            self.spawn_particles(bird.body.position, (255, 236, 120), 12, 4)
        elif ability == "bomb":
            bird.used_ability = True
            self.sounds.play("bomb")
            pos = bird.body.position
            self.spawn_particles(pos, (255, 190, 60), 40, 6)
            self.explode(pos, radius=150.0, power=2600.0, damage=170.0)
            self.end_shot()

    def explode(self, pos, radius, power, damage):
        for ent in list(self.blocks) + list(self.pigs):
            if ent.dead:
                continue
            d = (ent.body.position - pos).length
            if d > radius:
                continue
            falloff = 1.0 - (d / radius)
            direction = ent.body.position - pos
            if direction.length < 1:
                direction = (0, 1)
            ent.body.velocity = ent.body.velocity + direction.normalized() * (power * falloff / max(1.0, ent.body.mass))
            ent.take_damage(damage * falloff)

    # ---------------------------------------------------------- 每帧更新
    def remove_bird(self):
        bird = self.current_bird
        if bird is not None and bird.body in self.space.bodies:
            self.space.remove(bird.body, bird.shape)
        self.current_bird = None

    def spawn_particles(self, pos, color, count, size=4):
        for _ in range(count):
            self.particles.append(Particle(pos[0], pos[1], color, size))

    def world_calm(self):
        vmax = 0.0
        for ent in self.blocks + self.pigs:
            if ent.dead:
                continue
            vmax = max(vmax, ent.body.velocity.length)
        if self.current_bird is not None and self.current_bird.body in self.space.bodies:
            vmax = max(vmax, self.current_bird.body.velocity.length)
        return vmax < 34.0

    def update(self, dt):
        self.time += dt
        if self.state in ("aim", "fly", "settle"):
            for _ in range(2):
                self.space.step(dt / 2.0)

        for ent in list(self.pigs):
            if ent.dead:
                self.pigs.remove(ent)
                pos = ent.body.position
                if ent.body in self.space.bodies:
                    self.space.remove(ent.body, ent.shape)
                self.score += 5000
                self.spawn_particles(pos, (140, 220, 110), 26, 5)
                self.pops.append(["+5000", to_screen(pos[0], pos[1]), 1.0])
                self.sounds.play("pig")
        for ent in list(self.blocks):
            if ent.dead:
                self.blocks.remove(ent)
                pos = ent.body.position
                if ent.body in self.space.bodies:
                    self.space.remove(ent.body, ent.shape)
                self.score += ent.m["score"]
                self.spawn_particles(pos, ent.m["color"], 16, 4)
                self.pops.append(["+%d" % ent.m["score"], to_screen(pos[0], pos[1]), 0.9])
                self.sounds.play("break")

        if self.state == "fly" and self.current_bird is not None:
            body = self.current_bird.body
            self.trail.append((body.position.x, body.position.y, 0.0))
            if len(self.trail) > 90:
                self.trail.pop(0)
            spd = body.velocity.length
            if body.position.x > W + 400 or body.position.x < -400 or body.position.y < -400:
                self.end_shot()
            elif spd < 32:
                self.flight_timer += dt
                if self.flight_timer > 0.7:
                    self.end_shot()
            elif spd < 150 and body.position.y < BIRD_R * 2.4:
                # 在地上滚来滚去的小鸟不要拖时间
                self.flight_timer += dt
                if self.flight_timer > 1.0:
                    self.end_shot()
            else:
                self.flight_timer = 0.0

        # 任何时候小猪死光了都算过关（倒塌可能发生在回合结束后）
        if not self.pigs and self.state in ("aim", "fly", "settle"):
            self.win_level()

        if self.state == "settle":
            self.settle_timer += dt
            if self.settle_timer > 0.5 and (self.world_calm() or self.settle_timer > 3.5):
                if not self.pigs:
                    self.win_level()
                elif not self.birds_queue and self.current_bird is None:
                    self.lose_level()
                else:
                    self.ready_bird()

        self.particles = [p for p in self.particles if p.step(dt)]
        for pop in self.pops:
            pop[2] -= dt
        self.pops = [p for p in self.pops if p[2] > 0]
        self.trail = [(x, y, a + dt) for (x, y, a) in self.trail if a < 1.2]
        for ent in self.blocks + self.pigs:
            if ent.flash > 0:
                ent.flash = max(0.0, ent.flash - dt)

    def end_shot(self):
        self.remove_bird()
        self.state = "settle"
        self.settle_timer = 0.0

    def win_level(self):
        bonus = 10000 * len(self.birds_queue)
        self.score += bonus
        self.total_score += self.score
        self.state = "allwin" if self.level_index >= len(LEVELS) - 1 else "win"
        self.sounds.play("win")

    def lose_level(self):
        self.state = "lose"
        self.sounds.play("lose")

    # ---------------------------------------------------------- 输入
    def sling_screen(self):
        return to_screen(SLING[0], SLING[1])

    def on_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.running = False
            elif e.key == pygame.K_r:
                self.load_level(self.level_index)
            elif e.key == pygame.K_n:
                if self.state == "win":
                    self.load_level(self.level_index + 1)
                elif self.state == "allwin":
                    self.total_score = 0
                    self.load_level(0)
            elif e.key == pygame.K_SPACE:
                self.use_ability()
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.state == "win":
                self.load_level(self.level_index + 1)
            elif self.state == "allwin":
                self.total_score = 0
                self.load_level(0)
            elif self.state == "fly":
                self.use_ability()
            elif self.state == "aim" and self.current_bird is not None:
                ax, ay = self.sling_screen()
                if math.hypot(e.pos[0] - ax, e.pos[1] - ay) < 300:
                    self.aiming = True
                    self.drag = to_world(e.pos[0], e.pos[1])
        elif e.type == pygame.MOUSEMOTION and self.aiming:
            self.drag = to_world(e.pos[0], e.pos[1])
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.aiming:
            self.release()

    # ---------------------------------------------------------- 绘制
    def blit_rot(self, surf, world_pos, angle_deg):
        img = pygame.transform.rotate(surf, angle_deg)
        rect = img.get_rect(center=to_screen(world_pos[0], world_pos[1]))
        self.screen.blit(img, rect)

    def draw_sling(self, front=True):
        bx, by = to_screen(SLING[0], SLING[1])
        base_y = GROUND_Y
        if not front:
            pygame.draw.line(self.screen, (94, 60, 34), (bx + 8, base_y), (bx + 6, by - 6), 11)
            pygame.draw.line(self.screen, (120, 78, 44), (bx + 8, base_y), (bx + 6, by - 6), 6)
        else:
            pygame.draw.line(self.screen, (94, 60, 34), (bx - 8, base_y), (bx - 6, by - 6), 11)
            pygame.draw.line(self.screen, (120, 78, 44), (bx - 8, base_y), (bx - 6, by - 6), 6)
            pygame.draw.line(self.screen, (74, 46, 26), (bx - 13, base_y + 4), (bx + 13, base_y + 4), 13)

    def draw_entity(self, ent):
        img = ent.image()
        if ent.flash > 0:
            img = img.copy()
            ov = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            ov.fill((255, 255, 255, 90))
            img.blit(ov, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        self.blit_rot(img, ent.body.position, -math.degrees(ent.body.angle))

    def popup(self, text, pos, color=(255, 245, 200), size=26):
        f = load_font(size, bold=True)
        img = f.render(text, True, (0, 0, 0))
        img2 = f.render(text, True, color)
        rect = img2.get_rect(center=(int(pos[0]), int(pos[1])))
        self.screen.blit(img, (rect.x + 2, rect.y + 2))
        self.screen.blit(img2, rect)

    def draw(self):
        s = self.screen
        s.blit(self.bg, (0, 0))
        self.draw_sling(front=False)

        for ent in self.blocks:
            self.draw_entity(ent)
        for ent in self.pigs:
            self.draw_entity(ent)

        for p in self.particles:
            a = max(0, min(255, int(255 * (p.life / p.max_life))))
            col = pygame.Color(p.color[0], p.color[1], p.color[2], a)
            pygame.draw.circle(s, col, (int(p.x), GROUND_Y - int(p.y)),
                               max(1, int(p.size * (p.life / p.max_life) + 1)))

        if self.state == "aim" and self.current_bird is not None:
            dx, dy, d = self.pull_vector()
            pos = (SLING[0] - dx, SLING[1] - dy)
            bx, by = to_screen(SLING[0], SLING[1])
            bx2, by2 = to_screen(pos[0], pos[1])
            pygame.draw.line(s, (70, 44, 26), (bx - 7, by - 6), (bx2 + 6, by2), 9)
            pygame.draw.line(s, (70, 44, 26), (bx + 7, by - 6), (bx2 + 6, by2), 9)
            self.blit_rot(self.current_bird._img, pos, math.degrees(math.atan2(-dy, dx)))
        elif self.state == "fly" and self.current_bird is not None:
            self.blit_rot(self.current_bird._img, self.current_bird.body.position,
                          -math.degrees(self.current_bird.body.angle))

        for i, (tx, ty, ta) in enumerate(self.trail):
            if i % 3:
                continue
            a = max(0.0, 1.0 - ta / 1.2)
            pygame.draw.circle(s, (255, 255, 255), to_screen(tx, ty), max(1, int(4 * a)))

        self.draw_sling(front=True)
        for (text, pos, life) in self.pops:
            self.popup(text, (pos[0], pos[1] - (1.0 - life) * 40))
        self.draw_hud()
        self.draw_overlay()

    def draw_trajectory(self, pos):
        dx, dy, d = self.pull_vector()
        if d < 16:
            return
        vx, vy = dx * LAUNCH_K, dy * LAUNCH_K
        for i in range(1, 26):
            t = i * 0.055
            x = pos[0] + vx * t
            y = pos[1] + vy * t + 0.5 * GRAVITY * t * t
            if y < -50 or x > W:
                break
            pygame.draw.circle(self.screen, (255, 255, 255), to_screen(x, y), 4 if i % 3 == 0 else 3)
            pygame.draw.circle(self.screen, (120, 160, 200), to_screen(x, y), 4 if i % 3 == 0 else 3, 1)

    def draw_hud(self):
        s = self.screen
        bar = pygame.Surface((W, 54), pygame.SRCALPHA)
        bar.fill((20, 30, 50, 90))
        s.blit(bar, (0, 0))
        txt = self.font.render("分数  %d" % self.score, True, (255, 255, 255))
        s.blit(txt, (18, 12))
        txt = self.font.render(self.level_name, True, (255, 255, 255))
        s.blit(txt, (W // 2 - txt.get_width() // 2, 12))
        x = W - 40
        for kind in reversed(self.birds_queue):
            pygame.draw.circle(s, BIRDS[kind]["color"], (x, 27), 12)
            pygame.draw.circle(s, BIRDS[kind]["dark"], (x, 27), 12, 2)
            x -= 30
        if self.current_bird is not None:
            pygame.draw.circle(s, BIRDS[self.current_bird.bird_kind]["color"], (x, 27), 12)
            pygame.draw.circle(s, (255, 255, 255), (x, 27), 12, 2)
            x -= 30
        tip = self.font_small.render("剩余小鸟", True, (240, 245, 255))
        s.blit(tip, (x - tip.get_width() - 10, 18))
        if self.show_hint:
            msg = "按住小鸟向后拉伸 → 松手发射！飞行中点击鼠标可释放技能"
            img = self.font.render(msg, True, (255, 255, 255))
            bx = W // 2 - img.get_width() // 2
            bg = pygame.Surface((img.get_width() + 26, 38), pygame.SRCALPHA)
            bg.fill((20, 30, 50, 130))
            s.blit(bg, (bx - 13, GROUND_Y + 44))
            s.blit(img, (bx, GROUND_Y + 52))
        else:
            msg = "鼠标左键发射 / 技能     R 重玩     N 下一关     ESC 退出"
            img = self.font_small.render(msg, True, (255, 255, 255))
            s.blit(img, (W // 2 - img.get_width() // 2, GROUND_Y + 56))

    def draw_overlay(self):
        if self.state not in ("win", "lose", "allwin"):
            return
        s = self.screen
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((10, 16, 30, 150))
        s.blit(ov, (0, 0))
        if self.state == "win":
            title, color = "过关！", (140, 240, 120)
            lines = ["本关得分  %d" % self.score, "按 N 进入下一关     R 重玩本关"]
        elif self.state == "allwin":
            title, color = "全部通关！", (255, 220, 90)
            lines = ["总分  %d" % self.total_score, "你已经是弹弓大师了！", "按 N 或点击屏幕重新开始"]
        else:
            title, color = "小鸟用光了…", (255, 130, 120)
            lines = ["还剩下 %d 只小猪" % len(self.pigs), "按 R 再来一次"]
        t = load_font(72, bold=True).render(title, True, color)
        s.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 150))
        y = H // 2 - 40
        for line in lines:
            img = self.font.render(line, True, (255, 255, 255))
            s.blit(img, (W // 2 - img.get_width() // 2, y))
            y += 42

    # ---------------------------------------------------------- 主循环
    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for e in pygame.event.get():
                self.on_event(e)
            self.update(min(dt, 1 / 30.0))
            self.draw()
            pygame.display.flip()
        pygame.quit()

    # ---------------------------------------------------------- 测试辅助
    def step_frames(self, n, dt=1 / 60.0):
        for _ in range(n):
            self.update(dt)

    def snapshot(self, path):
        self.draw()
        pygame.image.save(self.screen, path)
        return path


def main():
    game = Game(headless=False)
    game.run()


if __name__ == "__main__":
    main()
    print("Git测试")
