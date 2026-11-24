# -*- coding: utf-8 -*-
"""
JIGUANG ARGB V2 控制器驱动（精粤 JGINYUE 等国产 X99/B 系主板的板载 ARGB MCU）

两路通道：
  1) HID  —— 设备发现、硬件灯效模式、静态色（64 字节报文）
  2) CDC  —— 逐颗灯珠实时数据流（Direct 模式，串口批量写，延迟远低于 HID）

协议来源：OpenRGB 上游 JGINYUEInternalUSBV2Controller
"""

import threading
import time

import hid

VID = 0x1A86
PID = 0xE30B
USAGE_PAGE = 0xFF00

# ---- HID 命令 ----
HID_HDR = 0x01
REQ_STATUS = 0x0F
REQ_ARGB_SETTING = 0x11
DL_ARGB_SETTING = 0x01

# ---- CDC 命令 ----
CDC_HDR = 0x10
CDC_FUNC_ARGB = 0x01
CDC_SUB = 0x20

# ---- 硬件灯效模式 ----
MODE_SYNC = 0x0F
MODE_OFF = 0x10
MODE_STATIC = 0x11
MODE_BREATHING = 0x12
MODE_CYCLING = 0x14
MODE_RANDOM = 0x15
MODE_SPRING = 0x16
MODE_WAVE = 0x17
MODE_WATER = 0x19
MODE_RAINBOW = 0x1A
MODE_MC_WAVE = 0x1B
MODE_MC_CYCLING = 0x1C
MODE_SUNRISE = 0x1D
MODE_ROTATE_STAR = 0x1E
MODE_METEOR = 0x1F
MODE_DIRECT = 0x20
MODE_CYCLING_BREATHING = 0x21
MODE_CYCLING_RAINING = 0x22
MODE_MC_WATER2 = 0x23
MODE_MC_WATER1 = 0x24
MODE_HOURGLASS = 0x25

HW_MODES = {
    MODE_OFF: "关闭",
    MODE_STATIC: "静态单色",
    MODE_BREATHING: "呼吸",
    MODE_CYCLING: "循环",
    MODE_RANDOM: "随机",
    MODE_WAVE: "波浪",
    MODE_WATER: "流水",
    MODE_RAINBOW: "彩虹",
    MODE_MC_WAVE: "多彩波浪",
    MODE_MC_CYCLING: "多彩循环",
    MODE_SUNRISE: "日出",
    MODE_ROTATE_STAR: "旋转星芒",
    MODE_METEOR: "流星",
    MODE_CYCLING_BREATHING: "循环呼吸",
    MODE_CYCLING_RAINING: "落雨",
    MODE_MC_WATER1: "多彩流水 1",
    MODE_MC_WATER2: "多彩流水 2",
    MODE_HOURGLASS: "沙漏",
}
# 每路模式吃几个颜色：0=设备自带配色, 8=多色, 3=三色, 1=单色
HW_MULTI_COLOR = {MODE_MC_WAVE, MODE_MC_CYCLING, MODE_SUNRISE, MODE_ROTATE_STAR,
                  MODE_CYCLING_BREATHING, MODE_CYCLING_RAINING,
                  MODE_MC_WATER1, MODE_MC_WATER2}
HW_NO_COLOR = {MODE_OFF, MODE_CYCLING, MODE_RANDOM, MODE_RAINBOW}
HW_THREE_COLOR = {MODE_HOURGLASS}


def hw_color_count(mode):
    if mode in HW_NO_COLOR:
        return 0
    if mode in HW_MULTI_COLOR:
        return 8
    if mode in HW_THREE_COLOR:
        return 3
    return 1

AREA_NAMES = {
    0x01: "ARGB 灯带 1",
    0x02: "ARGB 灯带 2",
    0x04: "ARGB 风扇 1",
    0x08: "ARGB 风扇 2",
    0x10: "ARGB 风扇 3",
    0x20: "ARGB 风扇 4",
    0x40: "ARGB 风扇 5",
}


def _log(*a):
    pass


class ArgbDevice:
    """线程安全的设备句柄。所有硬件写操作串行化，避免 HID/CDC 报文交错。"""

    def __init__(self):
        self.lock = threading.RLock()
        self._hid = None
        self._serial = None
        self.port = None
        self.path = None
        self.product = ""
        self.zones = []          # [{'area':int, 'max_leds':int, 'name':str}]
        self.last_error = ""
        self.connected = False
        self.write_stalled = False
        self.port_error = ""

    # ------------------------------------------------------------------ 发现
    @staticmethod
    def _enum():
        out = []
        for d in hid.enumerate(VID, PID):
            if d.get("usage_page") == USAGE_PAGE:
                out.append(d)
        return out

    @staticmethod
    def _find_port():
        try:
            from serial.tools import list_ports
        except Exception:
            return None
        for p in list_ports.comports():
            hwid = (p.hwid or "").upper()
            did = (p.device_id if hasattr(p, "device_id") else "") or ""
            if "1A86:E30B" in hwid or "VID_1A86&PID_E30B" in hwid:
                return p.device
        return None

    def open(self):
        """连接设备并完成握手。返回是否成功。"""
        with self.lock:
            self.close()
            self.write_stalled = False
            self.port_error = ""
            try:
                devs = self._enum()
                if not devs:
                    self.last_error = "未找到 ARGB 控制器（JIGUANG ARGB V2）—— 检查控制器 USB 线是否插好"
                    self.connected = False
                    return False
                d = devs[0]
                self.path = d["path"].decode("utf-8", "replace") if isinstance(d["path"], bytes) else str(d["path"])
                self.product = d.get("product_string") or "JIGUANG ARGB V2"
                h = hid.device()
                h.open_path(d["path"])
                h.set_nonblocking(False)
                self._hid = h
                self.port = self._find_port()
                if self.port:
                    try:
                        import serial
                        self._serial = serial.Serial(self.port, 115200, timeout=0.02, write_timeout=0.5)
                    except Exception as e:
                        self.port_error = "串口 %s 打不开（%s）" % (self.port, e.__class__.__name__)
                if not self._handshake():
                    if self.port_error:
                        self.last_error = "%s；%s" % (self.last_error, self.port_error)
                    self.close()
                    return False
                if self._serial is None:
                    self.last_error = self.port_error or "没找到 CDC 串口，无法下发逐颗颜色"
                    self.close()
                    return False
                self.connected = True
                return True
            except Exception as e:
                self.last_error = "连接失败：%s" % e
                self.close()
                return False

    def close(self):
        with self.lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            if self._hid is not None:
                try:
                    self._hid.close()
                except Exception:
                    pass
                self._hid = None
            self.connected = False

    # ------------------------------------------------------------- HID 基础
    def _xfer(self, payload, timeout=800):
        """写 64 字节并读取应答。payload 首字节为 HID_HDR。"""
        buf = bytearray(64)
        n = min(len(payload), 64)
        buf[:n] = payload[:n]
        with self.lock:
            w = self._hid.write(bytes(buf))
            if w is not None and w < 0:
                # 写入被系统拒绝：控制器没在收数据（典型是重启后固件卡住，需要重新枚举）
                self.write_stalled = True
                return []
            self.write_stalled = False
            time.sleep(0.02)
            r = self._hid.read(64, timeout)
        return list(r) if r else []

    def _handshake(self):
        self.write_stalled = False
        r = self._xfer([HID_HDR, REQ_STATUS])
        if not r or len(r) < 13 or r[1] != REQ_STATUS:
            if self.write_stalled:
                self.last_error = ("控制器没接收数据（USB 写入被拒绝）。把控制器那根 USB 拔下重插一次；"
                                   "不好拔就直接关机再开机（用「重启」不行，软重启不会给 USB 断电）。"
                                   "弄好之后点界面上的「重新连接」。")
            else:
                self.last_error = "设备无应答（握手失败）"
            return False
        mask = r[4]
        self.zones = []
        for i in range(8):
            if mask & (1 << i):
                area = 1 << i
                self.zones.append({
                    "area": area,
                    "max_leds": r[5 + i] if r[5 + i] else 100,
                    "name": AREA_NAMES.get(area, "ARGB 排针 0x%02X" % area),
                })
        if not self.zones:
            self.last_error = "设备未上报任何 ARGB 排针"
            return False
        return True

    def read_zone(self, area):
        r = self._xfer([HID_HDR, REQ_ARGB_SETTING, area])
        if not r or len(r) < 11 or r[1] != REQ_ARGB_SETTING or r[2] != area:
            return None
        n_color = min(r[5] & 0x0F, 8)
        colors = []
        for i in range(n_color):
            colors.append((r[8 + i * 3], r[9 + i * 3], r[10 + i * 3]))
        return {
            "area": area,
            "mode": r[3],
            "leds": r[4],
            "direction": (r[5] & 0x10) >> 4,
            "speed": r[6],
            "brightness": r[7],
            "colors": colors,
        }

    # ------------------------------------------------------------ 硬件模式
    def set_hw_mode(self, area, mode, num_led, colors=None, speed=0x80,
                    brightness=0xFF, direction=0):
        """
        写入硬件灯效。colors 为 [(r,g,b), ...]，最多 8 个。
        设备端会自己跑动画，CPU 占用为零。
        """
        colors = colors or []
        payload = [HID_HDR, DL_ARGB_SETTING, area, mode,
                   max(0, min(255, int(num_led))),
                   (min(len(colors), 8) & 0x0F) | ((direction & 0x01) << 4),
                   max(0, min(255, int(speed))),
                   max(0, min(255, int(brightness)))]
        for i, c in enumerate(colors[:8]):
            payload += [int(c[0]), int(c[1]), int(c[2])]
        with self.lock:
            self._xfer(payload, timeout=200)
            time.sleep(0.01)
        return True

    # ------------------------------------------------------------ 直通数据
    def direct(self, area, colors):
        """
        Direct 模式逐颗写：CDC 串口批量发送。
        colors = [(r,g,b), ...]，最多 100 颗。
        """
        if self._serial is None:
            raise IOError("CDC 串口不可用，无法逐颗控制")
        n = min(len(colors), 100)
        buf = bytearray(512)
        buf[0] = CDC_HDR
        buf[1] = CDC_FUNC_ARGB
        buf[2] = area
        buf[3] = CDC_SUB
        buf[4] = n
        for i in range(n):
            c = colors[i]
            buf[8 + i * 3 + 0] = int(c[0])
            buf[8 + i * 3 + 1] = int(c[1])
            buf[8 + i * 3 + 2] = int(c[2])
        tx = 10 + n * 3
        if tx % 64 == 0:
            tx += 2
        with self.lock:
            self._serial.write(bytes(buf[:tx]))

    def enter_direct(self, area, num_led, brightness=0xFF):
        """把某路切到 Direct（软件逐颗）模式"""
        return self.set_hw_mode(area, MODE_DIRECT, num_led, [], 0x80, brightness, 0)
