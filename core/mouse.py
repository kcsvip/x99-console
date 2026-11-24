# -*- coding: utf-8 -*-
"""SMAILWOLF M3 鼠标（A8A5:2255 USB Receiver）厂商通道控制

协议来源：官方网页驱动 https://f0a91.yjx2012.com/detail?productName=USB+Receiver
反编译其 webpack chunk（515-e903656abff6cee3.js）里的 device 类：
  报文 64 字节，buf[0]=0xF0（report id），buf[1]=命令号
  部分命令带子头 A5 0B 2E（读）/ AE 0A 2F（写）
  回包走 input report，raw[0]=0xF0、raw[1]=命令号（网页端会先剥掉 F0，所以网页代码用 t[0] 判断）

真机用 Win32 通道（hidapi 在该复合设备上 open 失败，CreateFile 反而正常）：
  CreateFileW(share=READ|WRITE) + 重叠 WriteFile/ReadFile

实测（2026-11-18，本机 M3）
  0x04 → F0 04 ... "YJX-20260320V2201"（字节间夹 0x2E，取偶数位还原）
  0x52 → F0 52 ... raw[9..] "20251225190600-F189-3311"
  0x30 → raw[8]=100 电量, raw[9]=0 充电中标志
  0x0E → raw[9]=灯效, raw[10]-1=回报率档, raw[11]=DPI 档数, raw[12]-1=当前档,
         raw[13..24]=6 组 DPI（低字节在前，800/1600/2400/3200/4000/8000）
"""
import ctypes
import json
import os
import time
from ctypes import wintypes

import hid  # 只用它做设备枚举

VID = 0xA8A5
PID = 0x2255
PAGE = 0xFF01
USAGE = 0x10
REPORT_ID = 0xF0

CMD_VERSION = 0x04
CMD_GET_KEYS = 0x08
CMD_SET_KEYS = 0x09
CMD_GET_CFG = 0x0E
CMD_SET_CFG = 0x0F
CMD_LIGHT = 0x21
CMD_BATTERY = 0x30
CMD_INFO = 0x52
CMD_STATUS = 0xED

# 官方页面里回报率只有四档（125/250/500/1000），index 即档位号
RATE_LIST = [125, 250, 500, 1000]

# 官方页面的灯效取值（7 项，value 0..6）
LIGHT_NAMES = ["波浪", "霓虹", "跑马灯", "溜溜球", "单向流光", "环绕呼吸", "关闭灯光"]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
GENERIC_RW = 0x80000000 | 0x40000000
FILE_SHARE_RW = 0x1 | 0x2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997

k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
k32.CreateEventW.restype = wintypes.HANDLE
k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
k32.CloseHandle.argtypes = [wintypes.HANDLE]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.POINTER(ctypes.c_ulong)),
                ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


class HidWin(object):
    """单条通道的 Win32 收发"""

    def __init__(self, path):
        self.path = path
        self.h = None
        self.event = None
        self.rbuf = (ctypes.c_ubyte * 128)()
        self.wbuf = (ctypes.c_ubyte * 64)()
        self.err = ""

    def open(self):
        self.close()
        h = k32.CreateFileW(self.path, GENERIC_RW, FILE_SHARE_RW, None,
                            OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if not h or h == wintypes.HANDLE(-1).value:
            self.err = "CreateFile 失败 err=%d" % ctypes.get_last_error()
            return False
        self.h = h
        self.event = k32.CreateEventW(None, True, False, None)
        return True

    def close(self):
        try:
            if self.h:
                k32.CloseHandle(self.h)
            if self.event:
                k32.CloseHandle(self.event)
        except Exception:
            pass
        self.h = None
        self.event = None

    def _wait(self, nbytes, timeout):
        ov = _OVERLAPPED()
        ov.hEvent = self.event
        k32.ResetEvent(self.event)
        return ov

    def write(self, buf):
        if self.h is None and not self.open():
            return False
        for i, v in enumerate((list(buf) + [0] * 64)[:64]):
            self.wbuf[i] = v & 0xFF
        ov = _OVERLAPPED()
        ov.hEvent = self.event
        k32.ResetEvent(self.event)
        n = wintypes.DWORD(0)
        ok = k32.WriteFile(self.h, self.wbuf, 64, ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            e = ctypes.get_last_error()
            if e != ERROR_IO_PENDING:
                self.err = "WriteFile err=%d" % e
                return False
            if k32.WaitForSingleObject(self.event, 800) != 0:
                k32.CancelIoEx(self.h, ctypes.byref(ov))
                self.err = "写超时"
                return False
            if not k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False):
                self.err = "写完成失败 err=%d" % ctypes.get_last_error()
                return False
        return True

    def read(self, timeout_ms=600):
        if self.h is None:
            return None
        ov = _OVERLAPPED()
        ov.hEvent = self.event
        k32.ResetEvent(self.event)
        n = wintypes.DWORD(0)
        ok = k32.ReadFile(self.h, self.rbuf, 96, ctypes.byref(n), ctypes.byref(ov))
        if not ok:
            e = ctypes.get_last_error()
            if e != ERROR_IO_PENDING:
                self.err = "ReadFile err=%d" % e
                return None
            if k32.WaitForSingleObject(self.event, timeout_ms) != 0:
                k32.CancelIoEx(self.h, ctypes.byref(ov))
                self.err = "读超时"
                return None
            if not k32.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(n), False):
                self.err = "读完成失败 err=%d" % ctypes.get_last_error()
                return None
        if n.value:
            return [self.rbuf[i] for i in range(n.value)]
        return None


def _u16(v):
    v = int(v)
    return v & 0xFF, (v >> 8) & 0xFF


class Mouse(object):
    def __init__(self, data_dir):
        self.data_dir = data_dir
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            pass
        self.cfg_path = os.path.join(data_dir, "mouse.json")
        self.io = None
        self.path = None
        self.detect_note = ""
        self.last_error = ""
        self.last_ok = 0.0
        self.state = {
            "rate_index": 3,
            "dpi_index": 5,
            "dpi_count": 6,
            "dpi": [800, 1600, 2400, 3200, 4000, 8000],
            "light_mode": 0,
            "lod": 1,
            "key_respond": 8,
            "sleep_light": 10,
            "highspeed": 0,
            "wakeup": 1,
            "move_light": 0,
            "scroll": 0,
            "sensor": 53,
            "battery": None,
            "charge": 0,
            "version": "",
            "serial": "",
        }
        self._load()

    # ------------------------------------------------------------ 配置持久化
    def _load(self):
        try:
            if os.path.exists(self.cfg_path):
                d = json.load(open(self.cfg_path, "r", encoding="utf-8"))
                for k in self.state:
                    if k in d and d[k] is not None:
                        self.state[k] = d[k]
        except Exception:
            pass

    def save(self):
        try:
            tmp = self.cfg_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.cfg_path)
        except Exception:
            pass

    # ------------------------------------------------------------ 连接
    def detect(self):
        self.path = None
        try:
            for d in hid.enumerate(VID, PID):
                if (d.get("usage_page") or 0) == PAGE and (d.get("usage") or 0) == USAGE:
                    self.path = d["path"]
                    break
        except Exception as e:
            self.detect_note = "枚举失败：%s" % e
        if self.path is None:
            self.detect_note = "未发现鼠标接收器（A8A5:2255）"
            return False
        if isinstance(self.path, bytes):
            self.path = self.path.decode("utf-8", "ignore")
        return True

    def open(self):
        if self.io is not None and self.io.h:
            return True
        if not self.detect():
            self.last_error = self.detect_note
            return False
        io = HidWin(self.path)
        if not io.open():
            self.io = None
            self.last_error = "打不开鼠标通道（%s）" % io.err
            return False
        self.io = io
        self.last_error = ""
        return True

    def close(self):
        if self.io is not None:
            self.io.close()
        self.io = None

    # ------------------------------------------------------------ 收发
    def _xfer(self, payload, expect=None, timeout=0.6, retries=2):
        if not self.open():
            return None
        buf = (list(payload) + [0] * 64)[:64]
        for attempt in range(max(1, retries)):
            if not self.io.write(buf):
                self.last_error = self.io.err or "写入失败"
                self.close()
                if attempt + 1 < retries:
                    time.sleep(0.15)
                    continue
                return None
            t0 = time.time()
            while time.time() - t0 < timeout:
                r = self.io.read(int(max(60, (timeout - (time.time() - t0)) * 1000)))
                if r is None:
                    if self.io.err and "超时" not in self.io.err:
                        self.last_error = self.io.err
                        self.close()
                        break
                    continue
                cmd = r[1] if len(r) > 1 and r[0] == REPORT_ID else r[0]
                if expect is None or cmd == expect:
                    self.last_error = ""
                    self.last_ok = time.time()
                    return r
            if attempt + 1 < retries:
                time.sleep(0.15)
                if self.io is None or not self.io.h:
                    self.open()
        self.last_error = "鼠标无应答（命令 0x%02X）" % payload[1]
        return None

    def _payload(self, r):
        """剥掉 report id（若首字节是 0xF0）"""
        if r and r[0] == REPORT_ID:
            return r[1:]
        return r

    # ------------------------------------------------------------ 读
    def read_version(self):
        r = self._xfer([REPORT_ID, CMD_VERSION], expect=CMD_VERSION)
        if not r:
            return ""
        chars = []
        for b in r[8:60]:
            if b in (0, 0x2E):
                continue
            if 32 <= b < 127:
                chars.append(chr(b))
            elif chars:
                break
        v = "".join(chars)
        if v:
            self.state["version"] = v
        return self.state.get("version", "")

    def read_info(self):
        r = self._xfer([REPORT_ID, CMD_INFO], expect=CMD_INFO)
        if not r:
            return ""
        p = self._payload(r)
        raw = bytes(p[8:32]).decode("ascii", "ignore").strip("\x00 ")
        if raw:
            self.state["serial"] = raw
        return self.state["serial"]

    def read_battery(self):
        r = self._xfer([REPORT_ID, CMD_BATTERY, 0xA5, 0x0B, 0x2E, 1, 1, 1, 1, 0],
                       expect=CMD_BATTERY)
        if r:
            p = self._payload(r)
            self.state["battery"] = int(p[7])
            self.state["charge"] = int(p[8])
            return self.state["battery"], self.state["charge"]
        return None, 0

    def read_config(self):
        r = self._xfer([REPORT_ID, CMD_GET_CFG, 0xA5, 0x0B, 0x2E, 1, 1, 1, 0, 0],
                       expect=CMD_GET_CFG)
        if not r:
            return None
        p = self._payload(r)
        if len(p) < 55:
            return None
        dpi = []
        for i in range(6):
            lo, hi = p[12 + 2 * i], p[13 + 2 * i]
            v = lo | (hi << 8)
            dpi.append(v if 50 <= v <= 50000 else 800)
        cfg = {
            "light_mode": p[8],
            "rate_index": max(0, min(len(RATE_LIST) - 1, p[9] - 1)),
            "dpi_count": p[10] or 6,
            "dpi_index": max(0, p[11] - 1),
            "dpi": dpi,
            "scroll": p[47],
            "lod": p[48],
            "sensor": p[49],
            "key_respond": p[50],
            "sleep_light": p[51],
            "highspeed": p[52],
            "wakeup": (p[53] >> 4) & 0x0F,
            "move_light": p[53] & 0x0F,
        }
        for k, v in cfg.items():
            self.state[k] = v
        self.save()
        return cfg

    # ------------------------------------------------------------ 写
    def _write_cfg(self):
        s = self.state
        dpi = list(s.get("dpi") or [])[:6]
        while len(dpi) < 6:
            dpi.append(1000)
        buf = [REPORT_ID, CMD_SET_CFG, 0xAE, 0x0A, 0x2F, 1, 1, 1, 0, 0]
        buf += [s["rate_index"] + 1, s["dpi_count"], s["dpi_index"] + 1]
        for v in dpi:
            buf += list(_u16(v))
        buf += [0] * (48 - len(buf))
        buf += [s.get("scroll", 0), s.get("lod", 1),
                s.get("sensor", 53),
                s.get("key_respond", 8), s.get("sleep_light", 10),
                s.get("highspeed", 0),
                ((s.get("wakeup", 1) & 0x0F) << 4) | (s.get("move_light", 0) & 0x0F)]
        r = self._xfer(buf, expect=None, timeout=0.4, retries=1)
        self.save()
        return r is not None

    def set_rate(self, index):
        self.state["rate_index"] = max(0, min(len(RATE_LIST) - 1, int(index)))
        return self._write_cfg()

    def set_dpi_index(self, index):
        cnt = int(self.state.get("dpi_count", 6)) or 6
        self.state["dpi_index"] = max(0, min(cnt - 1, int(index)))
        return self._write_cfg()

    def set_dpi_value(self, index, value):
        value = max(50, min(50000, int(value)))
        dpi = list(self.state.get("dpi") or [])
        while len(dpi) < 6:
            dpi.append(1000)
        dpi[int(index)] = value
        self.state["dpi"] = dpi
        return self._write_cfg()

    def set_lod(self, value):
        self.state["lod"] = int(value)
        return self._write_cfg()

    def set_key_respond(self, value):
        self.state["key_respond"] = int(value)
        return self._write_cfg()

    def set_sleep_light(self, value):
        self.state["sleep_light"] = int(value)
        return self._write_cfg()

    def set_highspeed(self, on):
        self.state["highspeed"] = 1 if on else 0
        return self._write_cfg()

    def set_move_light(self, on):
        self.state["move_light"] = 1 if on else 0
        return self._write_cfg()

    def set_light_mode(self, mode):
        r = self._xfer([REPORT_ID, CMD_LIGHT, 0, 0, 3, 0, 0, 0, 0, 0, int(mode)],
                       expect=None, timeout=0.4, retries=1)
        if r is not None:
            self.state["light_mode"] = int(mode)
            self.save()
            return True
        return False

    def set_light_off(self):
        return self.set_light_mode(0)

    # ------------------------------------------------------------ 展示
    def rate_hz(self):
        i = int(self.state.get("rate_index", 3))
        return RATE_LIST[i] if 0 <= i < len(RATE_LIST) else RATE_LIST[3]

    def light_name(self, mode=None):
        m = self.state.get("light_mode", 0) if mode is None else int(mode)
        return LIGHT_NAMES[m] if 0 <= m < len(LIGHT_NAMES) else "模式 %d" % m

    def info(self):
        s = self.state
        return {
            "found": self.path is not None,
            "connected": bool(self.io is not None and self.io.h),
            "model": "SMAILWOLF M3",
            "version": s.get("version") or "—",
            "serial": s.get("serial") or "—",
            "battery": s.get("battery"),
            "charge": s.get("charge", 0),
            "rate": self.rate_hz(),
            "rate_index": s.get("rate_index", 3),
            "dpi_index": s.get("dpi_index", 0),
            "dpi": list(s.get("dpi") or []),
            "light_mode": s.get("light_mode", 0),
            "light": self.light_name(),
            "lod": s.get("lod", 1),
            "key_respond": s.get("key_respond", 8),
            "sleep_light": s.get("sleep_light", 10),
            "highspeed": s.get("highspeed", 0),
            "wakeup": s.get("wakeup", 1),
            "move_light": s.get("move_light", 0),
            "error": self.last_error,
            "last_ok": self.last_ok,
        }
