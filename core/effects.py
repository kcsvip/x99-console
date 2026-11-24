# -*- coding: utf-8 -*-
"""
软件特效引擎：纯 Python 逐帧计算每颗灯珠颜色，通过 CDC 直写硬件。

设计要点：
  * 所有特效返回 [(r,g,b), ...]，长度 = 该路实际灯珠数
  * 支持"联排"：5 路排针按位置偏移拼成一条长灯带，效果跨排针连续流动
  * 不依赖 numpy，单帧 500 颗灯珠的运算量在 40fps 下 CPU 占用可忽略
"""

import math
import random

TAU = math.pi * 2.0

# ------------------------------------------------------------------ 颜色工具
def hsv_to_rgb(h, s, v):
    """h: 0-360, s/v: 0-1 -> (r,g,b) 0-255"""
    h = h % 360.0
    c = v * s
    x = c * (1 - abs(((h / 60.0) % 2) - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))


def lerp_color(a, b, t):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def scale(c, k):
    k = 0.0 if k < 0 else (1.0 if k > 1 else k)
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def palette_at(colors, pos):
    """在调色板上按 0..1 位置取色（首尾循环插值）"""
    if not colors:
        return (0, 0, 0)
    if len(colors) == 1:
        return colors[0]
    p = (pos % 1.0) * len(colors)
    i = int(p)
    return lerp_color(colors[i % len(colors)], colors[(i + 1) % len(colors)], p - i)


# ------------------------------------------------------------------ 参数换算
def _rate(speed):
    """0..100 -> 0.05..1.4 每秒周期数"""
    return 0.05 + (max(0.0, min(100.0, speed)) / 100.0) * 1.35


def _bri(brightness):
    return max(0.0, min(100.0, brightness)) / 100.0


# ------------------------------------------------------------------ 特效实现
def fx_solid(n, off, total, t, colors, speed, brightness, cfg):
    c = colors[0] if colors else (255, 255, 255)
    k = _bri(brightness)
    return [scale(c, k)] * n


def fx_gradient(n, off, total, t, colors, speed, brightness, cfg):
    """静态渐变，沿联排方向铺开"""
    k = _bri(brightness)
    base = (off / max(1, total - 1))
    span = n / max(1, total - 1)
    return [scale(palette_at(colors, base + span * (i / max(1, n - 1))), k) for i in range(n)]


def fx_rainbow(n, off, total, t, colors, speed, brightness, cfg):
    """彩虹滚动"""
    k = _bri(brightness)
    deg = 30.0 + max(0.0, min(100.0, speed)) * 4.5
    phase = t * deg
    shift = off * 360.0 / max(1, total)
    step = 360.0 / max(1, total)
    return [scale(hsv_to_rgb(phase + shift + i * step, 1.0, 1.0), k) for i in range(n)]


def fx_breathing(n, off, total, t, colors, speed, brightness, cfg):
    """呼吸：整体亮度正弦起伏"""
    c = colors[0] if colors else (0, 160, 255)
    k = _bri(brightness)
    f = _rate(speed)
    v = 0.10 + 0.90 * (0.5 - 0.5 * math.cos(TAU * t * f))
    return [scale(c, k * v)] * n


def fx_wave(n, off, total, t, colors, speed, brightness, cfg):
    """波浪：亮度波峰沿灯带推进"""
    c = colors[0] if colors else (0, 200, 255)
    k = _bri(brightness)
    f = _rate(speed)
    wavelen = max(8.0, total / 3.0)
    for_i = []
    for i in range(n):
        p = (off + i) / wavelen * TAU - TAU * t * f
        v = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(p))
        for_i.append(scale(c, k * v))
    return for_i


def fx_comet(n, off, total, t, colors, speed, brightness, cfg):
    """彗星：拖着渐隐尾巴的光点循环跑"""
    c = colors[0] if colors else (255, 40, 60)
    k = _bri(brightness)
    f = _rate(speed) * 0.8
    head = (t * f) % 1.0
    tail = max(6.0, n / 4.0)
    out = []
    for i in range(n):
        pos = (off + i) / max(1, total)
        d = (head - pos) % 1.0
        d = d * total
        v = math.exp(-d / tail) if d < total * 0.5 else 0.0
        out.append(scale(c, k * v))
    return out


def fx_chase(n, off, total, t, colors, speed, brightness, cfg):
    """跑马灯：色块沿灯带移动"""
    k = _bri(brightness)
    f = _rate(speed)
    seg = max(3, int(cfg.get("seg", 8)))
    pos = (off + int(t * f * total)) % (seg * 2)
    a = colors[0] if colors else (255, 255, 255)
    b = colors[1] if len(colors) > 1 else (0, 0, 0)
    return [scale(a if ((i + pos) % (seg * 2)) < seg else b, k) for i in range(n)]


def fx_sparkle(n, off, total, t, colors, speed, brightness, cfg):
    """星点闪烁：每颗灯珠独立相位随机明灭"""
    k = _bri(brightness)
    base = colors[0] if colors else (255, 220, 160)
    f = _rate(speed) * 1.6
    out = []
    for i in range(n):
        seed = (off + i) * 2654435761 % 1000 / 1000.0
        v = math.sin((t * f + seed) * TAU * 1.5)
        v = v * v * v * 2.2
        out.append(scale(base, k * min(1.0, max(0.0, v))))
    return out


def fx_dual(n, off, total, t, colors, speed, brightness, cfg):
    """双色对流：两个色块反向奔跑"""
    k = _bri(brightness)
    f = _rate(speed)
    a = colors[0] if colors else (0, 200, 255)
    b = colors[1] if len(colors) > 1 else (255, 60, 90)
    span = max(1, total)
    p1 = (t * f) % 1.0
    p2 = (1.0 - (t * f * 0.8) % 1.0) % 1.0
    tail = max(4.0, total / 8.0)
    out = []
    for i in range(n):
        pos = (off + i) / span
        d1 = abs((pos - p1 + 0.5) % 1.0 - 0.5) * span
        d2 = abs((pos - p2 + 0.5) % 1.0 - 0.5) * span
        out.append((int((a[0] * math.exp(-d1 / tail) + b[0] * math.exp(-d2 / tail)) * k),
                    int((a[1] * math.exp(-d1 / tail) + b[1] * math.exp(-d2 / tail)) * k),
                    int((a[2] * math.exp(-d1 / tail) + b[2] * math.exp(-d2 / tail)) * k)))
    return out


def fx_sunrise(n, off, total, t, colors, speed, brightness, cfg):
    """日出：暖色光晕自下而上缓慢抬升"""
    k = _bri(brightness)
    f = _rate(speed) * 0.45
    p = (t * f) % 1.0
    a = colors[0] if colors else (255, 120, 30)
    b = colors[1] if len(colors) > 1 else (255, 220, 140)
    out = []
    for i in range(n):
        pos = (off + i) / max(1, total)
        d = abs(pos - p)
        glow = math.exp(-(d * 3.2) ** 2)
        out.append(scale(lerp_color(a, b, 1.0 - min(1.0, d * 2)), k * (0.08 + 0.92 * glow)))
    return out


def fx_starfield(n, off, total, t, colors, speed, brightness, cfg):
    """星空：深底 + 随机星点缓慢闪烁"""
    k = _bri(brightness)
    base = colors[0] if colors else (10, 12, 40)
    star = colors[1] if len(colors) > 1 else (220, 235, 255)
    f = _rate(speed) * 0.6
    out = []
    for i in range(n):
        rnd = random.Random((off + i) * 7919)
        amp = rnd.random()
        ph = rnd.random()
        v = 0.5 - 0.5 * math.cos(TAU * (t * f * (0.5 + amp) + ph))
        out.append(scale(base, k * 0.55) if v < 0.55 else scale(star, k * v))
    return out


def fx_ppm(n, off, total, t, colors, speed, brightness, cfg):
    """水平仪/电平条：整条色带随呼吸上下扫"""
    k = _bri(brightness)
    f = _rate(speed) * 0.5
    level = 0.5 - 0.5 * math.cos(TAU * t * f)
    for_i = []
    for i in range(n):
        pos = i / max(1, n - 1)
        for_i.append(palette_at(colors, pos) if pos <= level else scale(palette_at(colors, pos), k * 0.06))
    # 亮度整体缩放
    return [scale(c, k) for c in for_i]


EFFECTS = {
    "solid":     {"name": "静态常亮", "fn": fx_solid,     "colors": (1, 1), "desc": "整条亮一个颜色"},
    "gradient":  {"name": "渐变",     "fn": fx_gradient,  "colors": (2, 5), "desc": "多色沿灯带平滑过渡"},
    "rainbow":   {"name": "彩虹流动",  "fn": fx_rainbow,   "colors": (0, 0), "desc": "七彩循环滚动"},
    "breathing": {"name": "呼吸",     "fn": fx_breathing, "colors": (1, 1), "desc": "明暗缓慢起伏"},
    "wave":      {"name": "波浪",     "fn": fx_wave,      "colors": (1, 1), "desc": "光波沿灯带推进"},
    "comet":     {"name": "彗星",     "fn": fx_comet,     "colors": (1, 1), "desc": "带拖尾的光点奔跑"},
    "chase":     {"name": "跑马灯",   "fn": fx_chase,     "colors": (1, 2), "desc": "色块逐段推进"},
    "sparkle":   {"name": "星点闪烁",  "fn": fx_sparkle,   "colors": (1, 1), "desc": "随机灯珠明灭闪烁"},
    "dual":      {"name": "双色对流",  "fn": fx_dual,      "colors": (2, 2), "desc": "两色反向追逐"},
    "sunrise":   {"name": "日出",     "fn": fx_sunrise,   "colors": (1, 2), "desc": "暖光自下而上抬升"},
    "starfield": {"name": "星空",     "fn": fx_starfield, "colors": (1, 2), "desc": "深色底 + 闪烁星点"},
    "ppm":       {"name": "电平条",   "fn": fx_ppm,       "colors": (2, 5), "desc": "色带随节奏上下扫"},
}


def render(effect, n, off, total, t, colors, speed, brightness, cfg=None):
    cfg = cfg or {}
    spec = EFFECTS.get(effect)
    if not spec:
        spec = EFFECTS["solid"]
    fn = spec["fn"]
    return fn(n, off, total, t, colors, speed, brightness, cfg)
