# -*- coding: utf-8 -*-
"""AMI Aptio 开机 LOGO 替换后端（纯逻辑，图像转换用 Qt，函数内延迟导入）

原理：X9MPS007 固件里开机画面是 FFS 文件 GUID 7BB28B99-61BB-11D5-9A5D-0090273FC14D，
内含一个 GUID_DEFINED(98584EEE-…) section，数据是 LZMA-alone 压缩的
  [4 字节前缀][800x600 8bpp BI_RGB BMP（54 头 + 1024 调色板 + 480000 像素）][56 字节元信息]
替换时整段重压、重建 section/FFS，并把 FV 内后续模块整体后移（占尾部空闲 FF 区）。
"""
from __future__ import annotations

import hashlib
import lzma
import os
import struct

LOGO_GUID = bytes.fromhex("998bb27bbb61d5119a5d0090273fc14d")   # 7BB28B99-61BB-11D5-9A5D-0090273FC14D
SEC_GUID = bytes.fromhex("98584eee143959429d6edc7bd79403cf")    # EE4E5898-3914-4259-9D6E-DC7BD79403CF
PREFIX_LEN = 4
TAIL_LEN = 56
FFS_HDR = 24
SEC_HDR = 24
ERASED = 0xFF


# ---------------------------------------------------------------- 定位
def locate(rom: bytes) -> dict:
    """在 16 MB 镜像里定位开机 logo，返回偏移与原始数据"""
    hit = rom.find(LOGO_GUID)
    if hit < 0:
        raise ValueError("这份镜像里没找到开机 LOGO 模块（GUID 7BB28B99…）")
    ffs = hit
    ffs_size = int.from_bytes(rom[ffs + 20:ffs + 23], "little")
    if not (24 <= ffs_size <= 0x400000):
        raise ValueError("LOGO 模块大小异常 0x%X" % ffs_size)
    sec = ffs + FFS_HDR
    sec_size = int.from_bytes(rom[sec:sec + 3], "little")
    if rom[sec + 3] != 0x02 or sec_size < SEC_HDR:
        raise ValueError("LOGO 模块结构不是预期的 GUID_DEFINED section")
    if rom[sec + 4:sec + 20] != SEC_GUID:
        raise ValueError("LOGO section 的 GUID 不匹配（可能是别的压缩算法）")
    data_off = int.from_bytes(rom[sec + 20:sec + 22], "little")
    payload = rom[sec + data_off:sec + sec_size]
    raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    bmp = raw[PREFIX_LEN:]
    offbits = struct.unpack("<I", bmp[10:14])[0]
    w, h = struct.unpack("<ii", bmp[18:26])
    bpp = struct.unpack("<H", bmp[28:30])[0]
    comp = struct.unpack("<I", bmp[30:34])[0]
    if comp != 0:
        raise ValueError("LOGO 像素格式不是未压缩 8bpp（comp=%d），本工具暂不处理" % comp)
    fsize = struct.unpack("<I", bmp[2:6])[0]
    return {
        "ffs": ffs, "ffs_size": ffs_size, "sec": sec, "sec_size": sec_size,
        "data_off": data_off, "payload": payload, "raw": raw,
        "prefix": raw[:PREFIX_LEN], "bmp": bmp[:fsize], "tail": raw[PREFIX_LEN + fsize:],
        "w": w, "h": h, "bpp": bpp, "offbits": offbits,
        "budget": len(payload),
    }


def fv_bounds(rom: bytes, inside: int) -> tuple[int, int]:
    """找包含指定偏移的 FV 的 [start, end)"""
    p = inside
    while p > 0:
        p = rom.rfind(b"_FVH", 0, p + 4)
        if p < 0:
            break
        start = p - 0x28
        if start < 0:
            continue
        try:
            fvlen = struct.unpack("<Q", rom[start + 0x20:start + 0x28])[0]
        except Exception:
            continue
        if start <= inside < start + fvlen and 0x10000 <= fvlen <= len(rom):
            return start, start + fvlen
    raise ValueError("找不到包含 LOGO 的固件卷（FV）")


# ---------------------------------------------------------------- 图像
def load_bmp_from_rom(rom: bytes) -> bytes:
    return locate(rom)["bmp"]


def convert_image(path: str, w: int, h: int) -> bytes:
    """任意图片 → w×h 未压缩 8bpp BMP（保持比例居中，黑底）"""
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QImage, QPainter, QColor

    src = QImage(path)
    if src.isNull():
        raise ValueError("这张图打不开（支持 PNG / JPG / BMP / WebP）")
    if src.hasAlphaChannel():
        canvas = QImage(w, h, QImage.Format_ARGB32)
        canvas.fill(QColor(0, 0, 0, 255))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        painter.end()
    else:
        canvas = QImage(w, h, QImage.Format_RGB32)
        canvas.fill(QColor(0, 0, 0))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = src.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
        painter.end()

    idx = canvas.convertToFormat(QImage.Format_Indexed8, Qt.ThresholdDither)  # 关抖动：避免背景噪点
    table = idx.colorTable()                       # list[int] ARGB
    cols = [(0xFF000000 | (c & 0x00FFFFFF)) for c in table]
    cols = cols[:256] + [0xFF000000] * (256 - min(256, len(cols)))

    # 转成像素字节（QImage 内部是 top-down，BMP 需要 bottom-up）
    data = bytearray(w * h)
    for y in range(h):
        line = idx.constScanLine(y)
        data[y * w:(y + 1) * w] = bytes(line)[:w]
    data_bu = bytearray(w * h)
    for y in range(h):
        data_bu[y * w:(y + 1) * w] = data[(h - 1 - y) * w:(h - y) * w]

    pal = bytearray()
    for c in cols:
        pal += bytes((c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, 0x00))

    hdr = bytearray(54)
    offbits = 54 + len(pal)
    struct.pack_into("<2sIHHI", hdr, 0, b"BM", offbits + len(data_bu), 0, 0, offbits)
    struct.pack_into("<IiiHHIIiiII", hdr, 14, 40, w, h, 1, 8, 0, len(data_bu), 2835, 2835, 256, 0)
    return bytes(hdr) + bytes(pal) + bytes(data_bu)


def bmp_pixmap(bmp: bytes, w: int, h: int):
    """BMP 字节 → QPixmap（界面预览，保持比例）"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap
    img = QImage.fromData(bmp)
    if img.isNull():
        return QPixmap()
    return QPixmap.fromImage(img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))


def preview_png(bmp: bytes, out_path: str, max_w: int = 320) -> bool:
    from PySide6.QtGui import QImage
    try:
        tmp = out_path + ".tmp.bmp"
        open(tmp, "wb").write(bmp)
        img = QImage(tmp)
        os.remove(tmp)
        if img.isNull():
            return False
        if img.width() > max_w:
            img = img.scaledToWidth(max_w)
        return img.save(out_path)
    except Exception:
        return False


# ---------------------------------------------------------------- 打包
def _fix_hdr(hdr: bytearray) -> None:
    """FFS 头校验：name(16)+hdrsum+type+attr+size(3) 之和为 0；byte17 与 state 不计入"""
    hdr[16] = 0
    total = sum(hdr[0:16]) + sum(hdr[18:23])
    hdr[16] = (0x100 - (total + 0x00) % 0x100) % 0x100


def make_rom(rom: bytes, new_bmp: bytes) -> tuple[bytes, dict]:
    """把新 BMP 写回镜像，返回 (新镜像, 信息)"""
    loc = locate(rom)
    if len(new_bmp) < 54:
        raise ValueError("BMP 数据异常")
    raw = loc["prefix"] + new_bmp + loc["tail"]

    comp = lzma.compress(raw, format=lzma.FORMAT_ALONE, preset=9 | lzma.PRESET_EXTREME)
    # 用和原包一致的 LZMA 参数（dict 16 MB / lc3 lp0 pb2）
    comp = lzma.compress(raw, format=lzma.FORMAT_ALONE,
                         filters=[{"id": lzma.FILTER_LZMA1, "preset": 9 | lzma.PRESET_EXTREME,
                                   "dict_size": 1 << 24}])
    if len(comp) > 4 * 1024 * 1024:
        raise ValueError("LOGO 数据过大（%d 字节）" % len(comp))

    sec_size = SEC_HDR + len(comp)
    ffs_size = FFS_HDR + sec_size

    # section
    sec = bytearray(SEC_HDR)
    struct.pack_into("<I", sec, 0, sec_size)         # 3 字节小端 + type
    sec[0:3] = (sec_size & 0xFFFFFF).to_bytes(3, "little")
    sec[3] = 0x02
    sec[4:20] = SEC_GUID
    struct.pack_into("<H", sec, 20, SEC_HDR)
    struct.pack_into("<H", sec, 22, 0x0001)

    # FFS 头
    hdr = bytearray(rom[loc["ffs"]:loc["ffs"] + FFS_HDR])
    hdr[16] = 0x00
    hdr[17] = 0xAA                                   # 与原厂一致（文件校验不启用）
    hdr[20:23] = ffs_size.to_bytes(3, "little")
    hdr[23] = 0xF8                                   # 该 FV 为 erase-polarity=1 的有效态
    _fix_hdr(hdr)

    new_file = bytes(hdr) + bytes(sec) + comp

    fv_start, fv_end = fv_bounds(rom, loc["ffs"])
    old_end = loc["ffs"] + loc["ffs_size"]
    next_off = (old_end + 7) & ~7                    # 原下一个模块起点
    new_end = loc["ffs"] + len(new_file)
    new_next = (new_end + 7) & ~7
    pad = new_next - new_end

    tail_block = bytearray(rom[next_off:fv_end])
    delta = new_next - next_off                      # >0 文件变大
    if delta > 0:
        cut = tail_block[-delta:]
        if len(cut) < delta or any(b != ERASED for b in cut):
            raise ValueError("固件卷尾部空闲空间不足（需要 %d 字节，尾部不是空白）" % delta)
        del tail_block[-delta:]
    elif delta < 0:
        tail_block += bytes([ERASED]) * (-delta)

    new_fv_area = new_file + bytes([ERASED]) * pad + bytes(tail_block)
    if len(new_fv_area) != fv_end - loc["ffs"]:
        raise ValueError("固件卷长度核算不一致（内部错误）")

    new_rom = rom[:loc["ffs"]] + new_fv_area + rom[fv_end:]
    if len(new_rom) != len(rom):
        raise ValueError("输出镜像长度异常（%d vs %d）" % (len(new_rom), len(rom)))

    info = {
        "old_size": loc["ffs_size"], "new_size": len(new_file), "delta": delta,
        "comp": len(comp), "raw": len(raw), "budget": loc["budget"],
        "new_sha": hashlib.sha256(new_rom).hexdigest()[:8],
        "ffs": loc["ffs"], "w": loc["w"], "h": loc["h"],
    }
    return new_rom, info


def recheck(new_rom: bytes) -> dict:
    """重新解析生成结果，确认能解回同尺寸图片、其余区域未被破坏"""
    loc = locate(new_rom)
    return {"ffs": loc["ffs"], "ffs_size": loc["ffs_size"], "w": loc["w"], "h": loc["h"],
            "bmp_len": len(loc["bmp"]), "comp": len(loc["payload"])}


def diff_report(a: bytes, b: bytes) -> dict:
    """新旧镜像差异统计（字节级）"""
    if len(a) != len(b):
        return {"same_len": False}
    diff = sum(1 for x, y in zip(a, b) if x != y)
    return {"same_len": True, "diff_bytes": diff, "pct": round(diff / len(a) * 100, 3)}
