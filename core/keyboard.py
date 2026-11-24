# -*- coding: utf-8 -*-
"""
键盘层：联想极光 GK10 98W（2.4G / 有线）灯效直控

协议为从官方 Provider DLL（GK10_98WProvider.dll）反汇编得到的私有帧格式：
    帧 = [00] + AA 55 CC 33 + cmd + 参数…（65 字节，首字节是 HID Report ID 0）

    cmd 0x06 0x01            握手 / 唤醒
    cmd 0x07 mode br sp color 设置灯效
        mode  0..19   20 种灯效模式
        br    0..3    亮度档（内部按 0..100 除以 33 得到）
        sp    0..2    速度档（内部按 0..100 除以 50 得到）
        color 0..7    8 个固定色位
"""

import json
import os
import threading
import time

import hid

VID = 0x1A2C
PID_WIFI = 0x8FFF          # 2.4G 接收器
PID_USB = 0xA061           # USB 有线
VENDOR_PAGE = 0xFF02

MODE_COUNT = 20
# 官方名字表（从 Lenovo Aurora 2.0.2 的 LenovoDriver.dll 里 gk1098 设备定义原样抄出）
MODE_NAMES_DEFAULT = [
    "常亮", "熄灭", "呼吸", "随按即灭", "随波逐流",
    "流光模式", "流光溢彩", "滴水涟漪", "点彩夺目", "一触即发",
    "踏雪无痕", "按键涟漪", "花开富贵", "跑马灯效", "旋转风暴",
    "蛇形跑马", "繁星点点", "川流不息", "斜拉变换", "正弦光波",
]
COLOR_COUNT = 8

MODE_NAMES = list(MODE_NAMES_DEFAULT)
NAMES_VERSION = 2      # 1 = 参考名，2 = 官方名字表

# 8 个色位：官方定义顺序是 红 绿 蓝 黄 紫 青 白 彩色（第 7 位是彩色循环，不是单色）
RAINBOW = "rainbow"
COLOR_SWATCH = ["#ff3b3b", "#33e04f", "#3b6bff", "#ffd21f",
                "#b03bff", "#2fe0e0", "#ffffff", RAINBOW]
COLOR_NAMES = ["红", "绿", "蓝", "黄", "紫", "青", "白", "彩色"]

# 校准时可选的答案（就是官方这 8 个颜色）
CAL_COLORS = list(COLOR_SWATCH)
CAL_NAMES = list(COLOR_NAMES)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def nearest_color_index(rgb):
    """把任意颜色映射到键盘 8 色位里最接近的一个（彩色循环那格不参与）"""
    best, bd = 0, 1e9
    for i, hx in enumerate(COLOR_SWATCH):
        if not hx.startswith("#"):
            continue
        r, g, b = hex_to_rgb(hx)
        d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if d < bd:
            bd, best = d, i
    return best


class Keyboard:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or os.getcwd()
        self.cfg_path = os.path.join(self.data_dir, "keyboard.json")
        self.lock = threading.RLock()
        self.dev = None
        self.path = None
        self.path_raw = b""
        self.product = ""
        self.conn = ""
        self.pid = 0
        self.last_error = ""
        self.last_ok = 0.0
        self.state = {
            "mode": 0,
            "brightness": 100,
            "speed": 50,
            "color": 0,
            "on": True,
            "linked": False,     # 跟随主板 ARGB 主色联动
            "keep": True,        # 定时重发，防止键盘自己回落到内置灯效
            "palette": list(COLOR_SWATCH),   # 每个色位「真机上是什么颜色」，校准后写入
            "calibrated": False,
            "mode_names": list(MODE_NAMES_DEFAULT),   # 20 个模式的中文名，可改
            "names_version": 0,
        }
        self._load()
        # 旧版本存的是「参考名」，升级到官方名字表时重置一次
        if int(self.state.get("names_version", 0) or 0) < NAMES_VERSION:
            self.state["mode_names"] = list(MODE_NAMES_DEFAULT)
            self.state["names_version"] = NAMES_VERSION
            self.save()

    # ---------------------------------------------------------------- 配置
    def _load(self):
        try:
            if os.path.exists(self.cfg_path):
                data = json.load(open(self.cfg_path, "r", encoding="utf-8"))
                for k in self.state:
                    if k in data:
                        self.state[k] = data[k]
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

    # ---------------------------------------------------------------- 检测
    def detect(self):
        """找键盘厂商灯效通道；找不到返回 False"""
        found = None
        for pid in (PID_WIFI, PID_USB):
            for d in hid.enumerate(VID, pid):
                if (d.get("usage_page") or 0) == VENDOR_PAGE:
                    found = (pid, d)
                    break
            if found:
                break
        if not found:
            self.path = None
            self.path_raw = b""
            self.product = ""
            self.conn = ""
            self.pid = 0
            return False
        pid, d = found
        self.pid = pid
        p = d.get("path")
        self.path_raw = p if isinstance(p, bytes) else str(p).encode("utf-8")
        self.path = p.decode("utf-8", "ignore") if isinstance(p, bytes) else str(p)
        self.product = d.get("product_string") or "GK10 98W"
        self.conn = "2.4G 无线" if pid == PID_WIFI else "USB 有线"
        return True

    # ---------------------------------------------------------------- 连接
    def open(self):
        with self.lock:
            self.close()
            if not self.detect():
                self.last_error = "没找到键盘灯效通道（键盘可能没连上）"
                return False
            try:
                dev = hid.device()
                dev.open_path(self.path_raw)
                self.dev = dev
                self._write_raw([0x06, 0x01])       # 握手
                time.sleep(0.05)
                self.last_error = ""
                return True
            except Exception as e:
                self.dev = None
                self.last_error = "打开键盘通道失败：%s" % e
                return False

    def close(self):
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None

    # ---------------------------------------------------------------- 发帧
    def _write_raw(self, payload):
        """payload = [cmd, b1, b2 ...]，自动补 AA55CC33 头与 Report ID"""
        buf = bytearray(65)
        buf[0] = 0x00
        buf[1:5] = bytes([0xAA, 0x55, 0xCC, 0x33])
        for i, v in enumerate(payload):
            buf[5 + i] = int(v) & 0xFF
        if self.dev is None:
            raise IOError("键盘未连接")
        self.dev.write(bytes(buf))

    def _ensure(self):
        if self.dev is None and not self.open():
            raise IOError(self.last_error or "键盘未连接")

    def set_light(self, mode=None, brightness=None, speed=None, color=None):
        with self.lock:
            s = self.state
            if mode is not None:
                s["mode"] = max(0, min(MODE_COUNT - 1, int(mode)))
            if brightness is not None:
                s["brightness"] = max(0, min(100, int(brightness)))
            if speed is not None:
                s["speed"] = max(0, min(100, int(speed)))
            if color is not None:
                s["color"] = max(0, min(COLOR_COUNT - 1, int(color)))
            try:
                self._ensure()
                br_lv = max(0, min(3, int(round(s["brightness"] / 33.0))))
                sp_lv = max(0, min(2, int(round(s["speed"] / 50.0))))
                # 载荷 6 字节：07 | mode | br | sp | 00 | color
                # 注意：色位在第 6 个字节，第 5 个字节固定 0（少了它或写错位置会被固件忽略）
                self._write_raw([0x07, s["mode"], br_lv, sp_lv, 0x00, s["color"]])
                self.last_ok = time.time()
                self.last_error = ""
                self.save()
                return True
            except Exception as e:
                self.last_error = "写灯效失败：%s" % e
                self.close()
                return False

    def power(self, on):
        """开/关灯。关灯只是把亮度档打到 0，保存的亮度不丢，开灯直接还原。"""
        s = self.state
        s["on"] = bool(on)
        if on:
            if not s["brightness"]:
                s["brightness"] = 100
            return self.set_light(brightness=s["brightness"])
        with self.lock:
            try:
                self._ensure()
                sp_lv = max(0, min(2, int(round(s["speed"] / 50.0))))
                self._write_raw([0x07, s["mode"], 0, sp_lv, 0x00, s["color"]])
                self.last_ok = time.time()
                self.last_error = ""
                self.save()
                return True
            except Exception as e:
                self.last_error = "关灯失败：%s" % e
                self.close()
                return False

    def sync_color(self, rgb):
        """主板 ARGB 主色联动：按校准后的色表映射到最接近的色位（彩色循环不参与）"""
        pal = self.state.get("palette") or COLOR_SWATCH
        best, bd = 0, 1e9
        for i, hx in enumerate(pal):
            if not str(hx).startswith("#"):
                continue
            r, g, b = hex_to_rgb(hx)
            d = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
            if d < bd:
                bd, best = d, i
        return self.set_light(color=best)

    def set_palette(self, palette):
        """校准结果：8 个色位在真机上分别是什么颜色"""
        self.state["palette"] = list(palette)[:COLOR_COUNT]
        self.state["calibrated"] = True
        self.save()

    def mode_name(self, index):
        names = self.state.get("mode_names") or MODE_NAMES_DEFAULT
        if 0 <= index < len(names) and names[index].strip():
            return names[index]
        return "灯效 %02d" % (index + 1)

    def set_mode_names(self, names):
        self.state["mode_names"] = [str(n).strip()[:12] or MODE_NAMES_DEFAULT[i]
                                    for i, n in enumerate(names)][:MODE_COUNT]
        self.save()

    def color_name(self, index):
        pal = self.state.get("palette") or COLOR_SWATCH
        hx = pal[index] if 0 <= index < len(pal) else "#000000"
        if hx == RAINBOW:
            return "彩色"
        if hx in CAL_COLORS:
            return CAL_NAMES[CAL_COLORS.index(hx)]
        return COLOR_NAMES[COLOR_SWATCH.index(hx)] if hx in COLOR_SWATCH \
            else "色位 %d" % (index + 1)

    def keepalive(self):
        if not self.state.get("keep"):
            return
        if self.dev is None:
            self.detect()
            return
        if not self.state.get("on"):
            self.power(False)
        else:
            self.set_light()

    def info(self):
        return {
            "found": self.path is not None,
            "pid": self.pid,
            "path": self.path or "",
            "product": self.product or "—",
            "conn": self.conn or "—",
            "mode": self.state["mode"],
            "brightness": self.state["brightness"],
            "speed": self.state["speed"],
            "color": self.state["color"],
            "on": self.state["on"],
            "linked": self.state["linked"],
            "keep": self.state["keep"],
            "palette": list(self.state.get("palette") or COLOR_SWATCH),
            "calibrated": bool(self.state.get("calibrated")),
            "mode_names": list(self.state.get("mode_names") or MODE_NAMES_DEFAULT),
            "calibrated": bool(self.state.get("calibrated")),
            "error": self.last_error,
            "last_ok": self.last_ok,
            "connected": self.dev is not None,
        }
