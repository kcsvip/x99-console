# -*- coding: utf-8 -*-
"""
系统信息采集（不装任何第三方库，纯 ctypes + nvidia-smi）

- CPU 占用：GetSystemTimes 差分
- CPU 实时频率：CallNtPowerInformation(ProcessorInformation)（每核 CurrentMhz）
- CPU 温度 / 主板温度 / CPU 风扇转速：读 hwmon 组件写的 data/hwmon.json
  （Windows 没有官方接口，只能靠内核驱动读 MSR / Super I/O，见 hwmon/HwMon.cs）
- 内存占用：GlobalMemoryStatusEx
- GPU 温度/占用/显存/风扇/功耗/核心频率：nvidia-smi（找不到就当没有，全部降级为 None）
- 磁盘已用/总量、开机时长
- 前台进程名：GetForegroundWindow + QueryFullProcessImageName
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import threading
import time

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_pow = ctypes.WinDLL("powrprof", use_last_error=True)

_LAST_CPU = {"idle": 0, "busy": 0}


def cpu_load():
    """返回 0..100 的 CPU 占用百分比"""
    idle = ctypes.c_ulonglong(0)
    kern = ctypes.c_ulonglong(0)
    user = ctypes.c_ulonglong(0)
    if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    # kernel 时间包含 idle
    total = kern.value + user.value
    idle_now = idle.value
    prev = _LAST_CPU
    di = idle_now - prev["idle"]
    dt = total - prev["busy"]
    _LAST_CPU["idle"] = idle_now
    _LAST_CPU["busy"] = total
    if dt <= 0:
        return 0.0
    load = (dt - di) / dt * 100.0
    return max(0.0, min(100.0, load))


class _PPI(ctypes.Structure):
    _fields_ = [("Number", wt.ULONG), ("MaxMhz", wt.ULONG), ("CurrentMhz", wt.ULONG),
                ("MhzLimit", wt.ULONG), ("MaxIdleState", wt.ULONG), ("CurrentIdleState", wt.ULONG)]


_MHZ = {"v": 0}


def cpu_mhz():
    """所有核心当前频率的平均值（MHz）

    先走 PDH「% Processor Performance」× 标称频率：Intel 平台上这是唯一反映真实倍频的来源，
    CallNtPowerInformation 的 CurrentMhz 在 Xeon 上恒为标称值（睿频解锁了也看不出来）。
    """
    try:
        from . import jixue
    except Exception:                                            # noqa: BLE001
        try:
            import core.jixue as jixue                            # noqa: F401
        except Exception:
            jixue = None
    if jixue is not None:
        try:
            p = jixue.perf_percent()
            if p:
                v = int(round(jixue.nominal_mhz() * p / 100.0))
                _MHZ["v"] = v
                return v
        except Exception:                                        # noqa: BLE001
            pass
    if _MHZ["v"]:
        return _MHZ["v"]                    # 采样抖动时沿用上次有效值，避免数字乱跳
    try:
        n = os.cpu_count() or 1
        buf = (_PPI * n)()
        rc = _pow.CallNtPowerInformation(11, None, 0, ctypes.byref(buf), ctypes.sizeof(buf))
        if rc != 0:
            return None
        vals = [b.CurrentMhz for b in buf if b.CurrentMhz]
        return int(sum(vals) / len(vals)) if vals else None
    except Exception:
        return None


def disk_info():
    """所有固定盘合计：已用百分比、总容量 GB"""
    try:
        mask = _k32.GetLogicalDrives()
        total = 0
        free = 0
        for i in range(26):
            if not (mask >> i) & 1:
                continue
            root = chr(65 + i) + ":\\"
            if _k32.GetDriveTypeW(root) != 3:      # DRIVE_FIXED
                continue
            f = ctypes.c_ulonglong(0)
            t = ctypes.c_ulonglong(0)
            t2 = ctypes.c_ulonglong(0)
            if _k32.GetDiskFreeSpaceExW(root, ctypes.byref(f), ctypes.byref(t), ctypes.byref(t2)):
                total += t.value
                free += f.value
        if not total:
            return None
        return {"used_pct": (total - free) / total * 100.0,
                "total_gb": total / (1024.0 ** 3),
                "free_gb": free / (1024.0 ** 3)}
    except Exception:
        return None


def uptime_sec():
    try:
        _k32.GetTickCount64.restype = ctypes.c_ulonglong
        return _k32.GetTickCount64() / 1000.0
    except Exception:
        return None


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem_load():
    st = _MEMSTATUS()
    st.dwLength = ctypes.sizeof(st)
    if not _k32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return None
    return float(st.dwMemoryLoad)


def foreground_exe():
    """前台窗口对应的 exe 文件名（小写），拿不到返回空串"""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        h = _k32.OpenProcess(0x0410, False, pid.value)   # QUERY_INFORMATION | VM_READ
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wt.DWORD(520)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            _k32.CloseHandle(h)
    except Exception:
        return ""


def _nvidia_smi():
    q = ("temperature.gpu,utilization.gpu,memory.used,memory.total,name,"
         "fan.speed,power.draw,clocks.current.sm")
    out = None
    for cand in ("nvidia-smi", r"C:\Windows\System32\nvidia-smi.exe"):
        try:
            r = subprocess.run([cand, "--query-gpu=" + q, "--format=csv,noheader,nounits"],
                               capture_output=True, timeout=2.0,
                               creationflags=0x08000000)
            if r.returncode == 0 and r.stdout:
                out = r.stdout.decode("utf-8", "ignore").strip().splitlines()[0]
                break
        except Exception:
            continue
    if not out:
        return None
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 8:
        return None

    def num(i):
        try:
            return float(parts[i])
        except Exception:
            return None

    return {"temp": num(0), "util": num(1), "vram_used": num(2), "vram_total": num(3),
            "name": parts[4], "fan": num(5), "power": num(6), "clock": num(7)}


def _fans(d):
    """每一路风扇的转速（按通道名，供风扇调速界面逐行显示）"""
    out = {}
    for item in (d.get("fans") or []):
        if not isinstance(item, dict):
            continue
        try:
            out[str(item.get("n") or "")] = float(item.get("v") or 0)
        except Exception:
            continue
    return out


def _controls(d):
    """hwmon.json 里的风扇 PWM 通道（含当前模式与可调范围）"""
    out = []
    for item in (d.get("controls") or []):
        if not isinstance(item, dict):
            continue
        try:
            v = float(item.get("v"))
        except Exception:
            v = -1.0
        try:
            lo = float(item.get("min", 0))
        except Exception:
            lo = 0.0
        try:
            hi = float(item.get("max", 100))
        except Exception:
            hi = 100.0
        out.append({"n": item.get("n") or "Fan", "v": v, "m": item.get("m") or "?",
                    "min": lo, "max": hi})
    return out


class SysInfo:
    """后台线程每 1.5 秒刷新一次，界面和联动逻辑都读缓存，永远不卡"""

    def __init__(self, data_dir=None):
        self.hwmon_path = os.path.join(data_dir, "hwmon.json") if data_dir else None
        self.data = {"cpu": None, "mem": None, "mhz": None, "gpu": None, "fg": "",
                     "disk": None, "uptime": None, "hw": None}
        self._stop = False
        self._t = None
        self.has_gpu = False

    def _read_hwmon(self):
        """读硬件监控组件写的 JSON；超过 15 秒没更新就当它没在跑"""
        p = self.hwmon_path
        if not p:
            return None
        try:
            if time.time() - os.path.getmtime(p) > 15:
                return None
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return None
        if not isinstance(d, dict):
            return None
        fan = None
        for item in (d.get("fans") or []):
            try:
                v = float(item.get("v"))
            except Exception:
                continue
            if v > 0:
                fan = v if fan is None else max(fan, v)
        return {"pkg": d.get("cpu_package"), "max": d.get("cpu_max"),
                "avg": d.get("cpu_avg"), "mobo": d.get("mobo"),
                "fan": fan, "ok": bool(d.get("ok")), "ts": d.get("ts"),
                "superio": d.get("superio") or "",
                "hwmon_mhz": d.get("cpu_mhz"), "hwmon_mhz_max": d.get("cpu_mhz_max"),
                "fans": _fans(d), "controls": _controls(d)}

    def start(self):
        if self._t:
            return
        self._t = threading.Thread(target=self._loop, name="sysinfo", daemon=True)
        self._t.start()

    def stop(self):
        self._stop = True

    def _loop(self):
        tick = 0
        while not self._stop:
            try:
                self.data["cpu"] = cpu_load()
                self.data["mem"] = mem_load()
                self.data["mhz"] = cpu_mhz()
                g = _nvidia_smi()
                if g:
                    self.has_gpu = True
                self.data["gpu"] = g
                self.data["fg"] = foreground_exe()
                self.data["uptime"] = uptime_sec()
                self.data["hw"] = self._read_hwmon()
                if tick % 4 == 0:            # 磁盘信息不必每次查
                    self.data["disk"] = disk_info()
                tick += 1
            except Exception:
                pass
            time.sleep(1.5)

    def get(self):
        return dict(self.data)
