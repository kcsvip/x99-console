# -*- utf-8 -*-
"""
实时联动（参考 ROG Aura 的 Screen Sync / Music / 温度联动）

三种模式，任何时候只有一种生效，关掉就回到软件特效：
- screen  屏幕取色：把屏幕缩成 16x9 的小图，按 5 路排针切成 5 条横带，取每条的平均色
- music   音乐律动：抓麦克风电平（不需要 FFT，用音量包络驱动亮度和色相）
- temp    温度联动：GPU 温度 → 青→黄→红渐变；CPU 占用控制流动速度

对外只有一个 frame(idx, n) 方法，引擎逐帧调用；内部自己节流（屏幕 12fps、音频 40fps）。
"""

import ctypes
import ctypes.wintypes as wt
import colorsys
import math
import time

_gdi = ctypes.WinDLL("gdi32", use_last_error=True)
_user = ctypes.WinDLL("user32", use_last_error=True)


# ---------------------------------------------------------------------------- 屏幕取色
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class ScreenGrabber:
    COLS, ROWS = 16, 9

    def __init__(self):
        self._hdc_screen = None
        self._hdc_mem = None
        self._bmp = None
        self._buf = None
        self._last = 0.0
        self.colors = [(0, 0, 0)] * self.COLS   # 每一列的平均色

    def _ensure(self):
        if self._hdc_mem:
            return True
        try:
            self._hdc_screen = _user.GetDC(0)
            self._hdc_mem = _gdi.CreateCompatibleDC(self._hdc_screen)
            self._bmp = _gdi.CreateCompatibleBitmap(self._hdc_screen, self.COLS, self.ROWS)
            _gdi.SelectObject(self._hdc_mem, self._bmp)
            self._buf = ctypes.create_string_buffer(self.COLS * self.ROWS * 4)
            return True
        except Exception:
            return False

    def grab(self, force=False):
        now = time.perf_counter()
        if not force and now - self._last < 1 / 12.0:
            return self.colors
        self._last = now
        if not self._ensure():
            return self.colors
        try:
            sw = _user.GetSystemMetrics(0)
            sh = _user.GetSystemMetrics(1)
            _gdi.SetStretchBltMode(self._hdc_mem, 4)          # HALFTONE
            _gdi.SetBrushOrgEx(self._hdc_mem, 0, 0, None)
            ok = _gdi.StretchBlt(self._hdc_mem, 0, 0, self.COLS, self.ROWS,
                                 self._hdc_screen, 0, 0, sw, sh, 0x00CC0020)  # SRCCOPY
            if not ok:
                return self.colors
            bi = _BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth = self.COLS
            bi.biHeight = -self.ROWS          # 负数 = 自上而下
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0
            count = _gdi.GetDIBits(self._hdc_mem, self._bmp, 0, self.ROWS,
                                   self._buf, ctypes.byref(bi), 0)
            if not count:
                return self.colors
            raw = self._buf.raw
            cols = []
            for cx in range(self.COLS):
                r = g = b = 0
                for cy in range(self.ROWS):
                    off = (cy * self.COLS + cx) * 4
                    b += raw[off]
                    g += raw[off + 1]
                    r += raw[off + 2]
                n = self.ROWS
                cols.append((r // n, g // n, b // n))
            self.colors = cols
        except Exception:
            pass
        return self.colors

    def zone_color(self, idx, zones):
        """第 idx 路取屏幕对应那条横带（按列分段）的平均色"""
        cols = self.grab()
        n = max(1, len(zones))
        c0 = int(idx * self.COLS / n)
        c1 = max(c0 + 1, int((idx + 1) * self.COLS / n))
        seg = cols[c0:c1] or cols
        r = sum(c[0] for c in seg) // len(seg)
        g = sum(c[1] for c in seg) // len(seg)
        b = sum(c[2] for c in seg) // len(seg)
        return (r, g, b)

    def avg_color(self):
        cols = self.grab()
        r = sum(c[0] for c in cols) // len(cols)
        g = sum(c[1] for c in cols) // len(cols)
        b = sum(c[2] for c in cols) // len(cols)
        return (r, g, b)


# ---------------------------------------------------------------------------- 麦克风电平
class MicLevel:
    """winmm waveIn 抓 100ms 一帧的 16bit 单声道，算 RMS，平滑成 0..1"""

    RATE = 16000
    FRAME = 1600        # 100ms

    def __init__(self):
        self.level = 0.0
        self.peak = 0.0
        self.error = ""
        self._h = None
        self._running = False

    def start(self):
        if self._h:
            return True
        try:
            mm = ctypes.WinDLL("winmm")

            class WAVEFORMATEX(ctypes.Structure):
                _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD),
                            ("nSamplesPerSec", wt.DWORD), ("nAvgBytesPerSec", wt.DWORD),
                            ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
                            ("cbSize", wt.WORD)]

            class WAVEHDR(ctypes.Structure):
                pass

            self._mm = mm
            self._WAVEFORMATEX = WAVEFORMATEX
            self._WAVEHDR = WAVEHDR
            self._h = True
            self._running = True
            import threading
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
            return True
        except Exception as e:
            self.error = "麦克风不可用：%s" % e
            self._h = None
            return False

    def _loop(self):
        mm = self._mm
        WAVEFORMATEX, WAVEHDR = self._WAVEFORMATEX, self._WAVEHDR
        WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wt.DWORD),
                            ("dwBytesRecorded", wt.DWORD), ("dwUser", ctypes.c_void_p),
                            ("dwFlags", wt.DWORD), ("dwLoops", wt.DWORD),
                            ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]
        fmt = WAVEFORMATEX(1, 1, self.RATE, self.RATE * 2, 2, 16, 0)
        hwi = ctypes.c_void_p()
        rc = mm.waveInOpen(ctypes.byref(hwi), 0xFFFFFFFF, ctypes.byref(fmt),
                           0, None, 0x00030000)   # WAVE_MAPPER, CALLBACK_NULL
        if rc != 0:
            self.error = "打不开录音设备(rc=%d)" % rc
            self._running = False
            return
        buf = ctypes.create_string_buffer(self.FRAME * 2)
        hdr = WAVEHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
        hdr.dwBufferLength = self.FRAME * 2
        mm.waveInPrepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
        mm.waveInAddBuffer(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
        mm.waveInStart(hwi)
        try:
            while self._running:
                time.sleep(0.03)
                if not (hdr.dwFlags & 0x00000010):      # WHDR_DONE
                    continue
                try:
                    raw = buf.raw
                    vals = ctypes.cast(raw, ctypes.POINTER(ctypes.c_short))
                    total = 0
                    for i in range(self.FRAME):
                        v = vals[i]
                        total += v * v
                    rms = math.sqrt(total / self.FRAME) / 32768.0
                    self.level = self.level * 0.65 + min(1.0, rms * 6.0) * 0.35
                except Exception:
                    pass
                hdr.dwFlags = 0
                mm.waveInAddBuffer(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
        finally:
            try:
                mm.waveInStop(hwi)
                mm.waveInUnprepareHeader(hwi, ctypes.byref(hdr), ctypes.sizeof(hdr))
                mm.waveInClose(hwi)
            except Exception:
                pass

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------- 统一入口
def _lerp(a, b, k):
    return a + (b - a) * k


def temp_color(temp):
    """30°C 青色 → 60°C 黄色 → 90°C 红色"""
    if temp is None:
        return (0, 120, 255)
    k = max(0.0, min(1.0, (temp - 30.0) / 60.0))
    if k < 0.5:
        hue = _lerp(0.55, 0.14, k / 0.5)      # 青 → 黄
    else:
        hue = _lerp(0.14, 0.0, (k - 0.5) / 0.5)   # 黄 → 红
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


class LiveHub:
    """引擎逐帧问它要颜色；没开就返回 None，引擎走原来的软件特效"""

    def __init__(self, sysinfo):
        self.sys = sysinfo
        self.mode = ""          # '' | 'screen' | 'music' | 'temp'
        self.split = True       # 屏幕模式：每路取自己那条，否则全屏一个色
        self.smooth = 0.5       # 0..1，越大越跟手
        self._screen = ScreenGrabber()
        self._mic = MicLevel()
        self._col = {}          # 每路平滑后的颜色
        self._t0 = time.perf_counter()
        self.last_error = ""

    # ---------------------------------------------------------------- 开关
    def set_mode(self, mode, **kw):
        if mode == "music" and not self._mic._h:
            if not self._mic.start():
                self.last_error = self._mic.error
                return False
        if mode != "music":
            self._mic.stop()
        if "split" in kw:
            self.split = bool(kw["split"])
        if "smooth" in kw:
            self.smooth = max(0.0, min(1.0, float(kw["smooth"])))
        self.mode = mode if mode in ("screen", "music", "temp") else ""
        self._col = {}
        return True

    @property
    def active(self):
        return self.mode != ""

    # ---------------------------------------------------------------- 颜色
    def _raw_color(self, idx, zones):
        if self.mode == "screen":
            return (self._screen.zone_color(idx, zones) if self.split
                    else self._screen.avg_color())
        if self.mode == "temp":
            d = self.sys.get()
            gpu = d.get("gpu")
            return temp_color(gpu["temp"] if gpu else None)
        if self.mode == "music":
            lv = self._mic.level
            hue = (self._t0 * 0 + lv * 0.7 + idx * 0.06) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.35 + 0.65 * lv)
            return (int(r * 255), int(g * 255), int(b * 255))
        return (255, 255, 255)

    def frame(self, idx, n, zones, brightness=1.0):
        """返回 n 颗灯的 RGB 列表"""
        raw = self._raw_color(idx, zones)
        old = self._col.get(idx)
        if old:
            k = 1.0 - self.smooth * 0.9
            raw = (int(_lerp(old[0], raw[0], k)), int(_lerp(old[1], raw[1], k)),
                   int(_lerp(old[2], raw[2], k)))
        self._col[idx] = raw
        bri = max(0.0, min(1.0, brightness))
        # 温度模式加一点呼吸感，避免死板；音乐模式本来就随音量
        pulse = 1.0
        if self.mode == "temp":
            d = self.sys.get()
            load = (d.get("cpu") or 30) / 100.0
            pulse = 0.75 + 0.25 * abs(math.sin((time.perf_counter() - self._t0) * (1.0 + load * 4)))
        base = (int(raw[0] * bri * pulse), int(raw[1] * bri * pulse), int(raw[2] * bri * pulse))
        return [base] * max(1, n)

    def state(self):
        return {"mode": self.mode, "split": self.split, "smooth": self.smooth,
                "error": self.last_error, "mic": round(self._mic.level, 3)}

    def close(self):
        self._mic.stop()
