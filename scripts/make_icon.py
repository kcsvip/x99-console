# -*- coding: utf-8 -*-
"""
重新生成控制台图标：去掉深色徽章底板，只保留霓虹 X 标志，背景透明。

输入：data\\icon_master_A.png（1536 RGBA 母版）
输出：assets\\icon.png（512 RGBA）、assets\\tray.ico（多尺寸 32 位带 alpha）

调试：加 --preview 只在 workspace 旁边出合成预览，不覆盖 assets。
"""

import os
import struct
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(ROOT, "data", "icon_master_A.png")
OUT_PNG = os.path.join(ROOT, "assets", "icon.png")
OUT_ICO = os.path.join(ROOT, "assets", "tray.ico")

S = 1536
C = S / 2.0

# ---- 可调参数（1536 画布上的像素值）----
HALF_W = 96         # X 条带半宽（垂直于条带方向）
HALF_L = 560        # X 条带半长
FEATHER = 5         # 核心条带边缘羽化
GLOW_BLUR = 14      # 霓虹辉光外扩模糊
PAD = 90            # 输出画布四周留白
STRIP_Y = 0.79      # 母版底部 RGB 灯条所在高度比例，整段剔除


def bar_mask(angle):
    """画一根圆角长条，绕中心旋转 angle 度。"""
    t = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(t)
    w = 2 * HALF_W
    length = 2 * HALF_L
    x0, y0 = C - length / 2, C - w / 2
    x1, y1 = C + length / 2, C + w / 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=HALF_W, fill=255)
    return t.rotate(angle, center=(C, C), resample=Image.BICUBIC)


def neon_mask(im):
    """亮霓虹 / 高饱和像素：条带边缘的青色、橙色描边和高光，辉光要保留。"""
    g = Image.new("L", (S, S), 0)
    src = im.load()
    dst = g.load()
    cutoff = int(S * STRIP_Y)
    for y in range(S):
        for x in range(S):
            if y > cutoff:
                continue
            r, gg, b, a = src[x, y]
            if a < 20:
                continue
            mx, mn = max(r, gg, b), min(r, gg, b)
            sat = 0.0 if mx == 0 else (mx - mn) / mx
            lum = 0.299 * r + 0.587 * gg + 0.114 * b
            # 只留彩色霓虹/高光；中性灰的徽章描边不进高光掩码
            if (sat > 0.4 and lum > 70) or lum > 190:
                dst[x, y] = 255
    return g.filter(ImageFilter.GaussianBlur(GLOW_BLUR))


def build_mask(im):
    core = ImageChops.lighter(bar_mask(45), bar_mask(-45))
    # 向内收缩，把条带外侧投在底板上的阴影环让出去
    core = core.filter(ImageFilter.MinFilter(13)).filter(ImageFilter.MinFilter(13))
    core = core.filter(ImageFilter.GaussianBlur(FEATHER))
    glow = neon_mask(im)
    mask = ImageChops.lighter(core, glow)
    # 整段抹掉底部 RGB 灯条
    cutoff = int(S * STRIP_Y)
    mask.paste(0, (0, cutoff, S, S))
    return mask, core, glow


def cutout():
    im = Image.open(MASTER).convert("RGBA").resize((S, S), Image.LANCZOS)
    mask, core, glow = build_mask(im)
    alpha = ImageChops.darker(im.getchannel("A"), mask)
    im.putalpha(alpha)
    # 裁到内容包围盒，再按方形留白贴回
    bbox = alpha.getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    side = max(w, h) + PAD * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def _bmp_entry(im):
    """单条 ICO 图像：32 位 BGRA XOR + 全零 AND 掩码（透明由 alpha 通道表达）。"""
    w, h = im.size
    bgra = im.tobytes("raw", "BGRA")
    row = w * 4
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        xor += bgra[y * row:(y + 1) * row]
    and_row = ((w + 31) // 32) * 4
    and_mask = bytes(and_row * h)
    dib = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0,
                      len(xor) + len(and_mask), 0, 0, 0, 0)
    return bytes(dib) + bytes(xor) + and_mask


def save_ico_manual(master, path, sizes):
    blobs = [_bmp_entry(master.resize(s, Image.LANCZOS).convert("RGBA")) for s in sizes]
    hdr = struct.pack('<HHH', 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b'', b''
    for (w, h), blob in zip(sizes, blobs):
        entries += struct.pack('<BBBBHHII', w if w < 256 else 0, h if h < 256 else 0,
                               0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    with open(path, 'wb') as f:
        f.write(hdr + entries + data)


def save_icons(master, out_png, out_ico):
    png = master.resize((512, 512), Image.LANCZOS)
    png.save(out_png)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    save_ico_manual(master, out_ico, sizes)


def preview(master, path):
    """分别贴到白底 / 深灰底上，便于检查透明边缘。"""
    side = 512
    tile = master.resize((side, side), Image.LANCZOS)
    sheet = Image.new("RGBA", (side * 2 + 20, side), (40, 40, 46, 255))
    white = Image.new("RGBA", (side, side), (245, 245, 248, 255))
    dark = Image.new("RGBA", (side, side), (18, 18, 22, 255))
    white.alpha_composite(tile)
    dark.alpha_composite(tile)
    sheet.alpha_composite(white, (0, 0))
    sheet.alpha_composite(dark, (side + 20, 0))
    sheet.convert("RGB").save(path)


if __name__ == "__main__":
    m = cutout()
    if "--preview" in sys.argv:
        out = os.path.join(os.path.dirname(ROOT), "icon_preview_transparent.png")
        # 预览落到 workspace 旁，避免污染源码目录
        out = os.path.join(os.environ.get("TEMP", ROOT), "icon_preview_transparent.png")
        preview(m, out)
        print("preview ->", out)
    else:
        save_icons(m, OUT_PNG, OUT_ICO)
        print("saved:", OUT_PNG, OUT_ICO)
