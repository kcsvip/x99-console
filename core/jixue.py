# -*- coding: utf-8 -*-
"""
鸡血 BIOS（E5 v3 全核睿频解锁）支持模块

本模块**不读写 SPI、不刷写固件**，只做四件事：
  1. 识别平台（CPU / 主板 / BIOS 版本，纯 winreg，无第三方库）
  2. 校验随程序发布的官方 BIOS 包（精粤 X9MPS007 的「原版」与「鸡血」两套）
  3. 把官方 U 盘自刷包（EFI\\BOOT + AFUDOS/AfuEfix64 + 启动脚本）铺到指定 U 盘
  4. 跑多线程负载，采全核频率，判断是否已经解锁（以及刷前/刷后对比）

固件写入一律由用户在 BIOS 层（U 盘启动 EFI Shell → AfuEfix64）自行完成，
程序不做任何自动刷写。
"""

import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import winreg

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- 平台常量
PLATFORM_ID = "X9MPS007"          # 精粤 X99M GAMING D3/ARGB 的 BIOS 代号
BIN_SIZE = 16777216               # 16 MB SPI 镜像
KINDS = {
    "jixue": {"dir": "鸡血BIOS", "title": "鸡血 BIOS", "desc": "全核睿频解锁"},
    "stock": {"dir": "原版BIOS", "title": "原版 BIOS", "desc": "官方原厂，用于回滚"},
}

# 基准参考：E5-2673 v3 原厂全核 2.4GHz / 单核睿频 3.1GHz
BASE_MHZ = 2400
TURBO_MHZ = 3100
UNLOCK_MHZ = 2950      # 满载平均频率超过这个值就认为已解锁

BENCH_JSON = "bench.json"


# ---------------------------------------------------------------- 资源定位
def resource_root():
    """assets 目录（源码模式在工程里，打包后在 _internal）"""
    cands = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(meipass)
    here = os.path.abspath(os.path.dirname(__file__))
    cands.append(os.path.dirname(here))       # core 的上一级 = 工程根
    if getattr(sys, "frozen", False):
        cands.append(os.path.dirname(sys.executable))
    for base in cands:
        p = os.path.join(base, "assets", "bios")
        if os.path.isdir(p):
            return p
    return os.path.join(cands[-1], "assets", "bios")


def package_dir(kind):
    return os.path.join(resource_root(), PLATFORM_ID, KINDS[kind]["dir"])


def bin_path(kind):
    return os.path.join(package_dir(kind), "EFI", "BOOT", PLATFORM_ID + ".bin")


# ---------------------------------------------------------------- 平台识别
def _reg(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except Exception:
        return ""


def platform_info():
    """CPU / 主板 / BIOS，全部来自注册表，不触发任何硬件访问"""
    bios = r"HARDWARE\DESCRIPTION\System\BIOS"
    cpu = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    name = _reg(cpu, "ProcessorNameString").strip()
    mhz = BASE_MHZ
    # "Intel(R) Xeon(R) CPU E5-2673 v3 @ 2.40GHz"
    if "@" in name:
        tail = name.split("@")[-1].strip().lower().replace("ghz", "").replace("mhz", "")
        try:
            v = float(tail)
            mhz = int(v * 1000) if "ghz" in name.lower() else int(v)
        except Exception:
            pass
    return {
        "cpu": name or "未知 CPU",
        "cores": os.cpu_count() or 0,
        "base_mhz": mhz,
        "board": (_reg(bios, "BaseBoardManufacturer") + " " +
                  _reg(bios, "BaseBoardProduct")).strip() or "未知主板",
        "bios_vendor": _reg(bios, "BIOSVendor"),
        "bios_version": _reg(bios, "BIOSVersion"),
        "bios_date": _reg(bios, "BIOSReleaseDate"),
        "match": _board_match(),
    }


def _board_match():
    """主板型号是否就是这套 BIOS 包对应的板子"""
    prod = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct").upper()
    if "GAMING D3" in prod or "X99M" in prod:
        return True
    return False


# ---------------------------------------------------------------- 包校验
def verify_package(kind):
    """校验官方包：bin 存在、大小 16MB、内部含型号串、返回 sha256"""
    d = package_dir(kind)
    p = bin_path(kind)
    res = {"kind": kind, "dir": d, "bin": p, "ok": False, "why": "", "size": 0,
           "sha256": "", "model_hit": False, "boot_files": 0, "pdf": ""}
    if not os.path.isdir(d):
        res["why"] = "缺少官方包目录：%s" % d
        return res
    boot = os.path.join(d, "EFI", "BOOT")
    if os.path.isdir(boot):
        res["boot_files"] = len([f for f in os.listdir(boot) if os.path.isfile(os.path.join(boot, f))])
    for f in os.listdir(d):
        if f.lower().endswith(".pdf"):
            res["pdf"] = os.path.join(d, f)
            break
    if not os.path.isfile(p):
        res["why"] = "缺少固件镜像 %s.bin" % PLATFORM_ID
        return res
    size = os.path.getsize(p)
    res["size"] = size
    if size != BIN_SIZE:
        res["why"] = "镜像大小异常：%d 字节（应为 %d）" % (size, BIN_SIZE)
        return res
    h = hashlib.sha256()
    hit = False
    with open(p, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            if not hit and PLATFORM_ID.encode() in chunk:
                hit = True
    res["sha256"] = h.hexdigest()[:16]
    # 型号串可能跨块，稳妥起见再整体搜一次尾部区域
    if not hit:
        with open(p, "rb") as f:
            f.seek(0x00D00000)
            hit = PLATFORM_ID.encode() in f.read(0x00200000)
    res["model_hit"] = hit
    if not hit:
        res["why"] = "镜像里找不到 %s 型号串，可能不是这块板的 BIOS" % PLATFORM_ID
        return res
    res["ok"] = res["boot_files"] >= 5
    if not res["ok"]:
        res["why"] = "EFI\\BOOT 内容不完整（%d 个文件）" % res["boot_files"]
    return res


def verify_all():
    return {k: verify_package(k) for k in KINDS}


# ---------------------------------------------------------------- U 盘
DRIVE_REMOVABLE = 2


def list_usb():
    """列出可移动盘：盘符、卷标、文件系统、剩余空间"""
    out = []
    try:
        mask = _k32.GetLogicalDrives()
    except Exception:
        return out
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        root = chr(65 + i) + ":\\"
        try:
            if _k32.GetDriveTypeW(root) != DRIVE_REMOVABLE:
                continue
        except Exception:
            continue
        label, fs = "", ""
        try:
            vol = ctypes.create_unicode_buffer(260)
            fsn = ctypes.create_unicode_buffer(64)
            ser = wt.DWORD(0)
            mcl = wt.DWORD(0)
            flags = wt.DWORD(0)
            if _k32.GetVolumeInformationW(root, vol, 260, ctypes.byref(ser),
                                         ctypes.byref(mcl), ctypes.byref(flags),
                                         fsn, 64):
                label = vol.value
                fs = fsn.value
        except Exception:
            pass
        free = total = 0
        try:
            f = ctypes.c_ulonglong(0)
            t = ctypes.c_ulonglong(0)
            t2 = ctypes.c_ulonglong(0)
            if _k32.GetDiskFreeSpaceExW(root, ctypes.byref(f), ctypes.byref(t), ctypes.byref(t2)):
                free, total = f.value, t.value
        except Exception:
            pass
        out.append({"drive": root, "label": label or "可移动磁盘",
                    "fs": fs or "?", "free_gb": free / (1024.0 ** 3),
                    "total_gb": total / (1024.0 ** 3)})
    return out


def usb_ok(drive):
    """能不能拿来刷 BIOS：FAT32 + 空间够"""
    info = None
    for d in list_usb():
        if d["drive"].upper() == drive.upper():
            info = d
            break
    if info is None:
        return False, "这个盘不是可移动磁盘（防止误写系统盘）"
    if info["fs"].upper() not in ("FAT32", "FAT"):
        return False, "文件系统是 %s，EFI 启动要求 FAT32（需先格式化为 FAT32）" % info["fs"]
    need = 26.0                                   # 一套包 EFI/BOOT 约 21MB + 余量
    if info["free_gb"] * 1024 < need:
        return False, "剩余空间不足（需 ≥%.0f MB，当前 %.0f MB）" % (need, info["free_gb"] * 1024)
    return True, ""


def write_usb(drive, kind="jixue", custom_rom=None):
    """把官方 U 盘自刷包铺到盘根，返回 (ok, 日志行列表)

    custom_rom：可选的自定义 16 MB 镜像路径（例如换了开机 LOGO 的镜像），
    会在铺完后覆盖 EFI\\BOOT 里的同名 bin，并按它的哈希回读校验。
    """
    log = []
    ok, why = usb_ok(drive)
    if not ok:
        return False, [why]
    src_root = package_dir(kind)
    if not os.path.isdir(src_root):
        return False, ["官方包缺失：%s" % src_root]
    src_efi = os.path.join(src_root, "EFI")
    if not os.path.isdir(src_efi):
        return False, ["官方包结构不对，缺少 EFI 目录"]

    src_bin = bin_path(kind)
    if custom_rom:
        if not os.path.isfile(custom_rom):
            return False, ["自定义镜像不存在：%s" % custom_rom]
        if os.path.getsize(custom_rom) != BIN_SIZE:
            return False, ["自定义镜像大小不是 16 MB，拒绝写入：%s" % custom_rom]
        src_bin = custom_rom

    dst_efi = os.path.join(drive, "EFI")
    try:
        if os.path.isdir(dst_efi):
            # 只清理 EFI\BOOT，避免动到别人放的东西
            shutil.rmtree(os.path.join(dst_efi, "BOOT"), ignore_errors=True)
            log.append("已清理旧的 EFI\\BOOT")
        shutil.copytree(src_efi, dst_efi, dirs_exist_ok=True)
        if custom_rom:
            shutil.copyfile(src_bin, os.path.join(dst_efi, "BOOT", PLATFORM_ID + ".bin"))
            log.append("已用自定义镜像覆盖 %s.bin（含新的开机 LOGO）" % PLATFORM_ID)
        n = 0
        for r, _ds, fs in os.walk(os.path.join(dst_efi, "BOOT")):
            n += len(fs)
        log.append("已写入 %s：EFI\\BOOT 共 %d 个文件" % (KINDS[kind]["title"], n))
    except Exception as e:
        return False, ["写入失败：%s" % e]

    # 教程 PDF + 步骤说明，一并放到盘根方便在别的电脑上看
    try:
        pdf = None
        for f in os.listdir(src_root):
            if f.lower().endswith(".pdf"):
                pdf = os.path.join(src_root, f)
                break
        if pdf:
            shutil.copy2(pdf, os.path.join(drive, os.path.basename(pdf)))
            log.append("已附带教程：%s" % os.path.basename(pdf))
        with open(os.path.join(drive, "刷机说明.txt"), "w", encoding="utf-8-sig") as f:
            f.write(usb_note(kind))
        log.append("已写入 刷机说明.txt")
    except Exception as e:
        log.append("附带文件写入失败（不影响刷写）：%s" % e)

    # 回读校验：大小 + 哈希必须和源文件一致（U 盘坏块最容易在这里暴露）
    try:
        p = os.path.join(drive, "EFI", "BOOT", PLATFORM_ID + ".bin")
        if os.path.getsize(p) != BIN_SIZE:
            return False, log + ["回读校验失败：镜像大小不对，建议重插 U 盘再写一次"]
        src_h = hashlib.sha256(open(src_bin, "rb").read()).hexdigest()
        dst_h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if src_h != dst_h:
            return False, log + ["回读校验失败：哈希不一致（%s vs %s），换根 U 盘重写"
                                 % (src_h[:8], dst_h[:8])]
        log.append("回读校验通过：%s.bin 16 MB，哈希 %s %s"
                   % (PLATFORM_ID, src_h[:8], "与自定义镜像一致" if custom_rom else "与官方包一致"))
    except Exception as e:
        return False, log + ["回读校验失败：%s" % e]
    return True, log


def _local_efi_root():
    """找本地自备的官方包目录（含 EFI\\BOOT 启动文件），返回路径或 None。

    合规：程序本身不分发任何 EFI 刷写器 / 固件；这里只在用户本地已自备
    官方包目录时复用其启动文件，缺目录就明确报错，不联网下载。
    """
    for k in KINDS:
        d = package_dir(k)
        if os.path.isdir(os.path.join(d, "EFI", "BOOT")):
            return d
    return None


def write_usb_custom(drive, custom_rom=None):
    """基于自选 16 MB 镜像制作 U 盘刷写盘，返回 (ok, 日志行列表)。

    custom_rom：本地自选的 16 MB 镜像（必需）。EFI\\BOOT 启动文件复用
    本地自备官方包目录；缺该目录则返回失败提示。
    """
    log = []
    ok, why = usb_ok(drive)
    if not ok:
        return False, [why]
    if not custom_rom or not os.path.isfile(custom_rom):
        return False, ["未选择自选镜像：写入前必须先在本页选择本地 16 MB BIOS 镜像"]
    if os.path.getsize(custom_rom) != BIN_SIZE:
        return False, ["自选镜像大小不是 16 MB，拒绝写入：%s" % custom_rom]

    src_root = _local_efi_root()
    if not src_root:
        return False, ["缺少本地自备的 EFI 刷写环境目录（官方包 EFI\\BOOT），"
                        "无法制作可启动刷写盘；请把自备官方包放到 assets\\bios 对应目录后再试"]
    src_efi = os.path.join(src_root, "EFI")

    dst_efi = os.path.join(drive, "EFI")
    try:
        if os.path.isdir(dst_efi):
            # 只清理 EFI\BOOT，避免动到别人放的东西
            shutil.rmtree(os.path.join(dst_efi, "BOOT"), ignore_errors=True)
            log.append("已清理旧的 EFI\\BOOT")
        shutil.copytree(src_efi, dst_efi, dirs_exist_ok=True)
        shutil.copyfile(custom_rom, os.path.join(dst_efi, "BOOT", PLATFORM_ID + ".bin"))
        log.append("已用自选镜像覆盖 %s.bin" % PLATFORM_ID)
        n = 0
        for _r, _ds, fs in os.walk(os.path.join(dst_efi, "BOOT")):
            n += len(fs)
        log.append("已写入 U 盘：EFI\\BOOT 共 %d 个文件" % n)
    except Exception as e:
        return False, ["写入失败：%s" % e]

    # 教程 PDF + 步骤说明一并放到盘根
    try:
        pdf = None
        for f in os.listdir(src_root):
            if f.lower().endswith(".pdf"):
                pdf = os.path.join(src_root, f)
                break
        if pdf:
            shutil.copy2(pdf, os.path.join(drive, os.path.basename(pdf)))
            log.append("已附带教程：%s" % os.path.basename(pdf))
        with open(os.path.join(drive, "刷机说明.txt"), "w", encoding="utf-8-sig") as f:
            f.write(usb_note_custom())
        log.append("已写入 刷机说明.txt")
    except Exception as e:
        log.append("附带文件写入失败（不影响刷写）：%s" % e)

    # 回读校验：大小 + 哈希必须与自选镜像一致
    try:
        p = os.path.join(drive, "EFI", "BOOT", PLATFORM_ID + ".bin")
        if os.path.getsize(p) != BIN_SIZE:
            return False, log + ["回读校验失败：镜像大小不对，建议重插 U 盘再写一次"]
        src_h = hashlib.sha256(open(custom_rom, "rb").read()).hexdigest()
        dst_h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if src_h != dst_h:
            return False, log + ["回读校验失败：哈希不一致，换根 U 盘重写"]
        log.append("回读校验通过：%s.bin 16 MB，哈希 %s（与自选镜像一致）"
                   % (PLATFORM_ID, src_h[:8]))
    except Exception as e:
        return False, log + ["回读校验失败：%s" % e]
    return True, log


def usb_note_custom():
    return (
        "X99 控制台 · 自选镜像刷写盘\n"
        "================================\n\n"
        "本盘固件为你自选的本地镜像；EFI 启动文件来自本地自备的官方包目录。\n\n"
        "刷写步骤：\n"
        "  1. 关机，插这块 U 盘到主板后置 USB 口\n"
        "  2. 开机连按 F11（部分 BIOS 是 F8 / F7）进启动菜单，选 U 盘\n"
        "  3. 自动进入 EFI Shell，startup.nsh 会自动执行刷写\n"
        "  4. 刷写过程中**绝对不能断电、不能按电源键**，等它自己重启\n"
        "  5. 重启后进 BIOS 恢复原来的设置（时间、启动顺序、风扇策略）\n\n"
        "注意：\n"
        "  - 这块板是单 BIOS，刷坏只能靠编程器救砖；刷之前请确认镜像型号匹配、电源稳定\n"
        "  - 镜像来源合法性与型号匹配由使用者自行负责\n"
        "  - 刷完后可在 X99 控制台的「鸡血 BIOS」页跑分，对比全核频率\n"
    )


def usb_note(kind):
    t = KINDS[kind]["title"]
    return (
        "X99 控制台 · %s 刷写盘\n"
        "================================\n\n"
        "这套文件由 X99 控制台自动铺好，来源是精粤官网 %s 的官方 BIOS 包。\n\n"
        "刷写步骤：\n"
        "  1. 关机，插这块 U 盘到主板后置 USB 口\n"
        "  2. 开机连按 F11（部分 BIOS 是 F8 / F7）进启动菜单，选 U 盘\n"
        "  3. 自动进入 EFI Shell，startup.nsh 会自动执行 AfuEfix64 刷写\n"
        "  4. 刷写过程中**绝对不能断电、不能按电源键**，等它自己重启\n"
        "  5. 重启后进 BIOS 恢复原来的设置（时间、启动顺序、风扇策略）\n\n"
        "注意：\n"
        "  - 这块板是单 BIOS，刷坏只能靠编程器救砖，所以刷之前请确认电源稳定\n"
        "  - 想回滚就用新的 U 盘包（选「原版 BIOS」重写一次）再刷一遍\n"
        "  - 刷完后可在 X99 控制台的「鸡血 BIOS」页跑分，对比全核频率\n"
    ) % (t, PLATFORM_ID)


# ---------------------------------------------------------------- 负载与频率
def _ppi_mhz():
    """老接口：CallNtPowerInformation(11) 的 CurrentMhz

    注意：在 E5 v3 这类 Xeon 上它**恒等于标称频率**（空载满载都一样），
    不能用来判断睿频是否解锁，只作 PDH 不可用时的兜底。
    """
    try:
        powrprof = ctypes.WinDLL("powrprof", use_last_error=True)

        class PPI(ctypes.Structure):
            _fields_ = [("Number", wt.ULONG), ("MaxMhz", wt.ULONG), ("CurrentMhz", wt.ULONG),
                        ("MhzLimit", wt.ULONG), ("MaxIdleState", wt.ULONG),
                        ("CurrentIdleState", wt.ULONG)]

        n = os.cpu_count() or 1
        buf = (PPI * n)()
        rc = powrprof.CallNtPowerInformation(11, None, 0, ctypes.byref(buf), ctypes.sizeof(buf))
        if rc != 0:
            return None
        vals = [b.CurrentMhz for b in buf if b.CurrentMhz]
        return int(sum(vals) / len(vals)) if vals else None
    except Exception:
        return None


# ---------------------------------------------------------------- 真实频率（PDH）
# % Processor Performance = 实际有效频率 / 标称频率 × 100（Intel 上可直接换算）
# 这是 E5 v3 上唯一能读到真实倍频的来源（hwmon 的 LHM 也是同一套口径）
_NOM = {"mhz": 0}
_PDH = {"ok": None, "api": None, "query": None, "counter": None, "val": None}
_LAST = {"t": 0.0}
_PDH_PATH = "\\Processor Information(_Total)\\% Processor Performance"


def nominal_mhz():
    """标称频率（注册表 ~MHz，X9MPS007 上是 2400/2401）"""
    if _NOM["mhz"]:
        return _NOM["mhz"]
    m = 0
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        m = int(winreg.QueryValueEx(k, "~MHz")[0])
        winreg.CloseKey(k)
    except Exception:
        m = 0
    _NOM["mhz"] = m if m > 500 else (BASE_MHZ + 1)
    return _NOM["mhz"]


def _pdh_init():
    if _PDH["ok"] is not None:
        return _PDH
    try:
        class _CV(ctypes.Structure):
            _fields_ = [("CStatus", wt.DWORD), ("doubleValue", ctypes.c_double)]

        pdh = ctypes.WinDLL("pdh", use_last_error=True)
        hq = wt.HANDLE()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(hq)) != 0:
            raise OSError("PdhOpenQuery")
        hc = wt.HANDLE()
        if pdh.PdhAddEnglishCounterW(hq, wt.LPCWSTR(_PDH_PATH), 0,
                                     ctypes.byref(hc)) != 0:
            pdh.PdhCloseQuery(hq)
            raise OSError("PdhAddEnglishCounter")
        pdh.PdhCollectQueryData(hq)
        time.sleep(0.15)                     # 速率型计数器要采两次才有值
        pdh.PdhCollectQueryData(hq)
        _LAST["t"] = time.time()
        _PDH.update(ok=True, api=pdh, query=hq, counter=hc, val=_CV())
    except Exception:
        _PDH["ok"] = False
    return _PDH


def perf_percent():
    """当前全核平均「% Processor Performance」，失败返回 None"""
    st = _pdh_init()
    if not st["ok"]:
        return None
    try:
        # 速率型计数器需要两次采集之间有像样的间隔，否则首采会给出偏低的抖动值
        gap = time.time() - _LAST["t"]
        if 0 <= gap < 0.06:
            time.sleep(0.06 - gap)
        st["api"].PdhCollectQueryData(st["query"])
        _LAST["t"] = time.time()
        v = st["val"]
        rc = st["api"].PdhGetFormattedCounterValue(st["counter"], 0x00000200, None,
                                                   ctypes.byref(v))
        if rc != 0 or v.CStatus != 0:
            return None
        val = float(v.doubleValue)
        # 采样间隔异常时速率计数器会给出荒唐值（实测出现过 496%），只认物理区间内的
        return val if 10.0 <= val <= 140.0 else None
    except Exception:
        return None


def sample_mhz(duration=0.0):
    """采一次全核平均频率（MHz）

    优先 PDH 真实倍频换算（连采 3 次取中位数，避开单次抖动）；
    PDH 不可用才退回 CallNtPowerInformation（后者在 Xeon 上给出标称值，测不出睿频）。
    """
    vals = []
    for _ in range(3):
        p = perf_percent()
        if p:
            vals.append(p)
        time.sleep(0.03)
    if vals:
        vals.sort()
        p = vals[len(vals) // 2]
        p = min(max(p, 20.0), 140.0)         # 物理上限 3.1/2.394≈130%，留一点余量
        return int(round(nominal_mhz() * p / 100.0))
    return _ppi_mhz()


def bench(seconds=8, threads=None, progress=None):
    """多线程 SHA256 负载，期间每 0.3 秒采一次全核频率

    hashlib 会释放 GIL，所以多线程是真的跑满多个核心，不需要开子进程。
    """
    threads = threads or (os.cpu_count() or 8)
    stop_at = time.time() + seconds
    state = {"bytes": 0}
    lock = threading.Lock()
    buf = b"x" * (1 << 20)            # 1 MB 一块

    def worker():
        h = hashlib.sha256()
        n = 0
        while time.time() < stop_at:
            h.update(buf)
            n += 1
        with lock:
            state["bytes"] += n * len(buf)

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in ts:
        t.start()

    samples = []
    t0 = time.time()
    while time.time() < stop_at:
        v = sample_mhz()
        if v:
            samples.append(v)
        if progress:
            try:
                progress(min(1.0, (time.time() - t0) / seconds), v or 0)
            except Exception:
                pass
        time.sleep(0.3)
    for t in ts:
        t.join(timeout=1.0)

    elapsed = max(0.1, time.time() - t0)
    mbps = state["bytes"] / (1024.0 * 1024.0) / elapsed
    samples.sort()
    avg = int(sum(samples) / len(samples)) if samples else 0
    peak = samples[-1] if samples else 0
    low = samples[0] if samples else 0
    return {"ts": int(time.time()), "seconds": int(elapsed), "threads": threads,
            "mbps": round(mbps, 1), "mhz_avg": avg, "mhz_peak": peak, "mhz_low": low,
            "samples": len(samples), "unlocked": avg >= UNLOCK_MHZ}


def unlocked_by(mhz_avg):
    try:
        return int(mhz_avg) >= UNLOCK_MHZ
    except Exception:
        return False


# ---------------------------------------------------------------- 跑分历史
def load_history(data_dir):
    p = os.path.join(data_dir, BENCH_JSON)
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, list):
            return d[-6:]
    except Exception:
        pass
    return []


def save_history(data_dir, rec):
    p = os.path.join(data_dir, BENCH_JSON)
    hist = load_history(data_dir)
    hist.append(rec)
    hist = hist[-6:]
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass
    return hist
