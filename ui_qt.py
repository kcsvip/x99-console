# -*- coding: utf-8 -*-
"""
X99 控制台 · Qt 原生界面（不依赖 HTML / WebView / 本地 HTTP 服务）

界面直接拿 core.engine.Engine 的 snapshot() 数据画控件，所有操作直接调 engine 的方法，
和 web 版共用同一套驱动与灯效引擎。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

from core import (bioslogo, fanprofile, jixue, keyboard as kbmod, mouse as msmod,
                  pcctl, updatecheck)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = (os.path.dirname(os.path.abspath(sys.executable))
           if getattr(sys, "frozen", False) else BASE_DIR)

from PySide6.QtCore import (QAbstractNativeEventFilter, QCoreApplication, QEvent, Qt, QTime,
                            QTimer, QRectF, QSize, Signal, QPoint, QPointF, QThread, QUrl)
from PySide6.QtGui import (QColor, QPainter, QLinearGradient, QRadialGradient, QIcon, QFont,
                           QGradient, QPen, QPixmap, QDesktopServices)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QMenu, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy,
                               QSlider, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

BG = "#08080b"
PANEL = "#0f0f14"
PANEL2 = "#16161c"
LINE = "rgba(255,255,255,0.06)"
LINE_S = "rgba(255,255,255,0.12)"
TEXT = "#eceef2"
MUTED = "#84858f"
ACC = "#ff2d55"          # ROG 红：主强调色
CYAN = "#22d3ee"         # 数据/联动色
GREEN = "#34d399"
RED = "#ef4444"
AMBER = "#f5a623"

# ---------------------------------------------------------------- 皮肤（配色主题）
# 每套皮肤定义：强调色 acc / 次强调 acc2 / 数据色 cyan / 底色 bg / 面板 panel / 高端 panel2
# / 卡片渐变 card1→card2 / 顶栏渐变 top1→top2→top3 / 滑槽 groove / 熄灭态 sw_off,sw_knob
THEMES = {
    "rog": dict(name="ROG 红黑", acc="#ff2d55", acc2="#ff9f43", cyan="#22d3ee",
                bg="#08080b", panel="#0f0f14", panel2="#16161c",
                card1="#14141b", card2="#0c0c11", top1="#12070c", top2="#0c0c11", top3="#0a0a0e",
                groove="#1a1a21", press="#202836", sw_off="#26262e", sw_knob="#6d6f7a",
                logo1="#ff2d55", logo2="#8c0b22", ring="rgba(255,120,150,.55)",
                mono="#b6b8c2", tag_fg="#ffb3c2"),
    "ice": dict(name="冰川蓝", acc="#38bdf8", acc2="#7dd3fc", cyan="#22d3ee",
                bg="#05080d", panel="#0b1017", panel2="#111820",
                card1="#101821", card2="#0a0e13", top1="#07131c", top2="#0a0e13", top3="#080b10",
                groove="#16222d", press="#1b2a36", sw_off="#1e2833", sw_knob="#5f7183",
                logo1="#38bdf8", logo2="#0b3a55", ring="rgba(125,211,252,.5)",
                mono="#a8c4dc", tag_fg="#bae6fd"),
    "violet": dict(name="星云紫", acc="#a855f7", acc2="#6366f1", cyan="#22d3ee",
                   bg="#0a0712", panel="#110d1b", panel2="#171222",
                   card1="#191325", card2="#100c17", top1="#170b24", top2="#110c16", top3="#0c0812",
                   groove="#221a2f", press="#2a2240", sw_off="#2a2137", sw_knob="#7b6a92",
                   logo1="#a855f7", logo2="#3b1170", ring="rgba(200,150,255,.5)",
                   mono="#c4b5fd", tag_fg="#d8b4fe"),
    "emerald": dict(name="翡翠绿", acc="#22c55e", acc2="#a3e635", cyan="#22d3ee",
                    bg="#050a07", panel="#0b120d", panel2="#101a13",
                    card1="#121d16", card2="#0a0f0b", top1="#08160d", top2="#0a0f0b", top3="#070c08",
                    groove="#17271d", press="#1d3324", sw_off="#22332a", sw_knob="#6b8b77",
                    logo1="#22c55e", logo2="#0b4a24", ring="rgba(163,230,53,.45)",
                    mono="#a7f3d0", tag_fg="#bbf7d0"),
    "amber": dict(name="琥珀橙", acc="#ff9f43", acc2="#ffd166", cyan="#22d3ee",
                  bg="#0b0906", panel="#141009", panel2="#1c1610",
                  card1="#221a12", card2="#12100b", top1="#1e1206", top2="#12100b", top3="#0d0a07",
                  groove="#2b2117", press="#3a2b1c", sw_off="#33291e", sw_knob="#8f7a63",
                  logo1="#ff9f43", logo2="#8a3d0b", ring="rgba(255,209,102,.45)",
                  mono="#fcd9a8", tag_fg="#fed7aa"),
    "mono": dict(name="极简钢灰", acc="#cbd5e1", acc2="#94a3b8", cyan="#38bdf8",
                 bg="#0a0b0d", panel="#121418", panel2="#181b20",
                 card1="#1c1f25", card2="#111317", top1="#15181c", top2="#111317", top3="#0c0e11",
                 groove="#242830", press="#2c313a", sw_off="#2a2e35", sw_knob="#8b929c",
                 logo1="#475569", logo2="#1e293b", ring="rgba(203,213,225,.4)",
                 mono="#cbd5e1", tag_fg="#e2e8f0"),
}
THEME_ORDER = ["rog", "ice", "violet", "emerald", "amber", "mono"]


def _trip(h):
    h = h.strip().lstrip("#")
    return "%d,%d,%d" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _mk(t):
    d = dict(t)
    d["acc_rgb"] = _trip(d["acc"])
    d["acc2_rgb"] = _trip(d["acc2"])
    d["cyan_rgb"] = _trip(d["cyan"])
    d["line"] = LINE
    d["line_s"] = LINE_S
    d["text"] = TEXT
    d["muted"] = MUTED
    d["red"] = RED
    d["green"] = GREEN
    return d


CUR = _mk(THEMES["rog"])
CUR["key"] = "rog"


def theme():
    """当前皮肤（绘制类控件从这里取色）"""
    return CUR


def set_theme_name(name):
    """切换全局皮肤：更新 CUR 并返回整套样式表"""
    key = name if name in THEMES else "rog"
    CUR.clear()
    CUR.update(_mk(THEMES[key]))
    CUR["key"] = key
    return build_qss(CUR)


def _colorref(h):
    """#RRGGBB → COLORREF(0x00BBGGRR)"""
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return 0
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


# ---------------------------------------------------------------- 无边框窗口（自绘标题栏）
# 做法：窗口样式保持原样（WS_THICKFRAME 还在，所以系统缩放、Aero 贴边、系统阴影、
# Win+方向键全都是原生的），只用 WM_NCCALCSIZE 把 32px 标题栏从客户区里划掉，
# 再用 WM_NCHITTEST 把顶部那条声明成 HTCAPTION——拖动、双击最大化、右键系统菜单
# 依然由系统处理，我们只是不再显示那条灰色标题栏。
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
HT = dict(client=1, caption=2, left=10, right=11, top=12, topleft=13, topright=14,
          bottom=15, bottomleft=16, bottomright=17)
EDGE_HIT = 6                                   # 边缘缩放热区宽度（px）


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wt.RECT * 3), ("lppos", ctypes.c_void_p)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


_u32 = ctypes.WinDLL("user32", use_last_error=True)
_u32.IsZoomed.argtypes = [wt.HWND]
_u32.IsZoomed.restype = wt.BOOL
_u32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
_u32.MonitorFromWindow.restype = wt.HANDLE
_u32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(_MONITORINFO)]
_u32.GetMonitorInfoW.restype = wt.BOOL


def _cap_icon(kind, color="#b9bcc6"):
    """窗口按钮的小图标（16×16，用 QPainter 画，不依赖字体里的符号）"""
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.5)
    p.setPen(pen)
    if kind == "min":
        p.drawLine(QPointF(3.0, 8.0), QPointF(13.0, 8.0))
    elif kind == "max":
        p.drawRect(QRectF(3.5, 3.5, 9.0, 9.0))
    elif kind == "restore":
        p.drawRect(QRectF(3.5, 6.0, 7.0, 7.0))
        p.drawLine(QPointF(6.0, 3.5), QPointF(12.5, 3.5))
        p.drawLine(QPointF(12.5, 3.5), QPointF(12.5, 10.0))
    elif kind == "close":
        p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
        p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))
    p.end()
    return QIcon(pm)


def apply_dwm_titlebar(widget, caption=None, text="#e8eaf0", border=None):
    """把 Windows 原生标题栏刷成和界面同色，让窗口"长在一起"

    用到的 DWM 属性：
      20 DWMWA_USE_IMMERSIVE_DARK_MODE   深色标题栏（Win10 1809+ 也支持）
      35 DWMWA_CAPTION_COLOR             标题栏底色（Win11 22000+）
      36 DWMWA_TEXT_COLOR                标题文字色（Win11 22000+）
      34 DWMWA_BORDER_COLOR              窗口边框色（Win11 22000+）
    不支持的属性只会返回错误码，这里静默忽略——按钮、拖动、缩放、贴边全都是原生的，
    一个都不动，只是换了颜色。
    """
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        t = theme()
        base = t.get("bg", "#08080b")
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)

        def setv(attr, val):
            v = ctypes.c_int(int(val))
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                      ctypes.byref(v), ctypes.sizeof(v))

        setv(20, 1)
        setv(35, _colorref(caption or base))
        setv(36, _colorref(text))
        setv(34, _colorref(border or base))
        return True
    except Exception:
        return False

# 情景模式：(键, 名称, 特效, 颜色, 速度, 亮度, 是否联排)
SCENES = [
    ("game", "竞技 · 红黑脉冲", "comet", ["#ff2d55"], 95, 100, True),
    ("office", "办公 · 暖白低亮", "solid", ["#f3efe2"], 45, 35, False),
    ("movie", "影音 · 深海呼吸", "breathing", ["#0b3a6b", "#22d3ee"], 35, 45, True),
    ("night", "静夜 · 琥珀微光", "solid", ["#ff6b3d"], 30, 10, False),
    ("mini", "极简 · 纯白恒定", "solid", ["#ffffff"], 45, 55, False),
    ("show", "炫彩 · 彩虹流动", "rainbow", [], 60, 100, True),
]

QSS_TMPL = """
QWidget { background: transparent; color: %(text)s;
          font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; font-size: 12px; }

QFrame#topbar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 %(top1)s, stop:0.45 %(top2)s, stop:1 %(top3)s);
        border: none; border-bottom: 1px solid rgba(%(acc_rgb)s,0.45); }
QFrame#footer { background: %(top3)s; border: none; border-top: 1px solid rgba(%(acc_rgb)s,0.25); }

QLabel { background: transparent; }
QLabel#brandTitle { font-size: 20px; font-weight: 800; letter-spacing: 2px; color: #ffffff; }
QLabel#brandSub { font-size: 9.5px; color: %(muted)s; letter-spacing: 1.5px; }
QLabel#muted { color: %(muted)s; font-size: 11px; }
QLabel#cardTitle { font-size: 13px; font-weight: 600; }
QLabel#sectionTitle { font-size: 12px; font-weight: 700; color: #ffffff; letter-spacing: 1.2px; }
QLabel#metric { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 16px;
        font-weight: 700; color: #ffffff; }
QLabel#mono { font-family: "Cascadia Mono", "Consolas", monospace; color: %(mono)s; }
QLabel#tag { background: rgba(%(acc_rgb)s,0.14); border: 1px solid rgba(%(acc_rgb)s,0.4);
        border-radius: 2px; padding: 1px 6px; color: %(tag_fg)s; font-size: 10px;
        letter-spacing: 1px; }
QLabel#pill { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.10);
        border-radius: 3px; font-family: "Cascadia Mono", "Consolas", monospace; }
QLabel#pillOn { background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.5);
        border-radius: 3px; color: #b9ffe7; font-family: "Cascadia Mono", "Consolas", monospace; }

QPushButton { background: rgba(255,255,255,0.045); color: %(text)s; border: 1px solid %(line_s)s;
        border-radius: 3px; padding: 4px 10px; }
QPushButton:hover { border-color: %(acc)s; background: rgba(%(acc_rgb)s,0.10); color: #ffffff; }
QPushButton:pressed { background: rgba(%(acc_rgb)s,0.18); }
QPushButton:focus { outline: none; border-color: rgba(%(acc_rgb)s,0.6); }
QPushButton:disabled { background: rgba(255,255,255,0.018); color: rgba(255,255,255,0.26);
        border-color: rgba(255,255,255,0.05); }
QPushButton#primary { background: %(acc)s; color: #ffffff; border: none; font-weight: 700; }
QPushButton#primary:hover { background: %(acc2)s; }
QPushButton#primary:pressed { background: %(acc2)s; }
QPushButton#primary:disabled { background: rgba(%(acc_rgb)s,0.16); color: rgba(255,255,255,0.40); }
QPushButton#danger { color: #ffc2c2; border-color: rgba(239,68,68,0.5); }
QPushButton#danger:hover { border-color: %(red)s; color: #ffffff; }
QPushButton#ghost { padding: 2px 8px; font-size: 11px; color: %(muted)s; }
QPushButton#ghost:hover { color: %(acc)s; }
QPushButton#swatch { border-radius: 6px; border: 1px solid %(line_s)s; padding: 0; }
QPushButton#scene { text-align: left; padding: 9px 12px; border-radius: 3px;
        background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.08); }
QPushButton#scene:hover { border-color: %(acc)s; background: rgba(%(acc_rgb)s,0.09); }
QPushButton#scene:checked { border-color: %(acc)s; background: rgba(%(acc_rgb)s,0.16);
        color: #ffffff; }
QPushButton#seg { padding: 5px 14px; border-radius: 3px; }
QPushButton#seg:checked { background: rgba(%(acc_rgb)s,0.18); border-color: %(acc)s;
        color: #ffffff; }
QPushButton#fmod { padding: 4px 10px; border-radius: 3px; font-size: 12px; }
QPushButton#fmod:hover { border-color: %(acc)s; color: #ffffff; }
QPushButton#fmod:checked { background: rgba(%(acc_rgb)s,0.20); border: 1px solid %(acc)s;
        color: #ffffff; font-weight: 700; }
QPushButton#scene:disabled, QPushButton#seg:disabled, QPushButton#fmod:disabled {
        background: rgba(255,255,255,0.015); border-color: rgba(255,255,255,0.05);
        color: rgba(255,255,255,0.24); }
QPushButton#ghost:disabled { color: rgba(255,255,255,0.22); }
QLabel#fanMode { color: %(acc)s; font-family: "Cascadia Mono", "Consolas", monospace; }
QLabel#fanVerdict { color: %(muted)s; font-size: 11px; }
QLabel#fanBad { color: #ff9c9c; font-size: 11px; }

QComboBox, QSpinBox, QLineEdit, QTimeEdit { background: %(card1)s; color: %(text)s;
        border: 1px solid %(line_s)s; border-radius: 3px; padding: 3px 8px; }
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: rgba(%(acc_rgb)s,0.55); }
QComboBox QAbstractItemView { background: %(panel)s; border: 1px solid %(line_s)s;
        selection-background-color: rgba(%(acc_rgb)s,0.22); padding: 2px; }
QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 0; height: 0; }

QSlider::groove:horizontal { height: 3px; background: %(groove)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 %(acc)s, stop:1 %(acc2)s); border-radius: 2px; }
QSlider::handle:horizontal { width: 8px; height: 8px; margin: -4px 0; border-radius: 5px;
        background: #ffffff; border: 2px solid %(acc)s; }

QProgressBar { background: %(groove)s; border: none; border-radius: 2px; height: 10px;
        text-align: center; color: transparent; }
QProgressBar::chunk { border-radius: 2px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 %(acc)s, stop:0.55 %(acc2)s, stop:1 %(cyan)s); }

QPlainTextEdit, QListWidget { background: rgba(9,12,18,0.9); border: 1px solid %(line)s;
        border-radius: 3px; color: %(mono)s; font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 11px; padding: 6px; }
QListWidget::item { padding: 4px 6px; border-radius: 3px; }
QListWidget::item:selected { background: rgba(%(acc_rgb)s,0.18); color: %(text)s; }

QMenu { background: %(panel)s; border: 1px solid %(line_s)s; padding: 4px; }
QMenu::item { padding: 5px 16px; border-radius: 5px; }
QMenu::item:selected { background: rgba(%(acc_rgb)s,0.18); }
QMenu::separator { height: 1px; background: %(line_s)s; margin: 3px 8px; }
QMenu::section { background: transparent; padding: 7px 14px 1px 14px;
        color: %(muted)s; font-size: 10.5px; letter-spacing: 1px; }
QMenu::indicator { width: 12px; height: 12px; }
QLabel#menuSection { background: transparent; color: %(acc)s; font-size: 10px;
        letter-spacing: 1.4px; padding: 9px 16px 1px 16px; }

QFrame#card { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 %(card1)s, stop:1 %(card2)s);
        border: 1px solid rgba(255,255,255,0.07); border-radius: 4px; }
QFrame#card:hover { border-color: rgba(%(acc_rgb)s,0.45); }
QFrame#banner { background: rgba(239,68,68,0.10); border: 1px solid rgba(239,68,68,0.45);
        border-radius: 3px; }

QTabWidget::pane { border: 1px solid %(line)s; border-radius: 4px; background: %(panel)s;
        top: -1px; }
QTabBar::tab { background: rgba(255,255,255,0.02); color: %(muted)s; border: none;
        border-bottom: 2px solid transparent; border-radius: 3px; margin-right: 3px;
        padding: 6px 15px; }
QTabBar::tab:hover { color: #ffffff; background: rgba(255,255,255,0.05); }
QTabBar::tab:selected { color: #ffffff; background: rgba(%(acc_rgb)s,0.12);
        border-bottom: 2px solid %(acc)s; }

QCheckBox { color: %(text)s; }
QTimeEdit { padding: 2px 6px; }
"""


def build_qss(t):
    """按皮肤配色生成整套样式表"""
    return QSS_TMPL % t


QSS = build_qss(CUR)


_user32 = ctypes.WinDLL("user32", use_last_error=True)


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt_x", wt.LONG),
                ("pt_y", wt.LONG), ("private", wt.DWORD)]


class HotkeyFilter(QAbstractNativeEventFilter):
    """接 WM_HOTKEY，把全局快捷键转成 Python 回调"""

    def __init__(self, cb):
        super().__init__()
        self.cb = cb

    def nativeEventFilter(self, evt, msg):
        try:
            if bytes(evt) == b"windows_generic_MSG":
                m = ctypes.cast(int(msg), ctypes.POINTER(_MSG)).contents
                if m.message == 0x0312:      # WM_HOTKEY
                    self.cb(int(m.wParam))
        except Exception:
            pass
        return False, 0


class Switch(QAbstractButton):

    """仿 iOS 的小拨动开关（纯绘制，无 HTML）"""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.update()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme()
        w, h = self.width(), self.height()
        r = h / 2.0
        p.setPen(Qt.NoPen)
        if self.isChecked():
            acc = QColor(t["acc"])
            acc2 = QColor(t["acc2"])
            # 外发光
            p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 55))
            p.drawRoundedRect(QRectF(-2, -2, w + 4, h + 4), r + 2, r + 2)
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, acc)
            g.setColorAt(1, acc2)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QRectF(w - h + 3, 3, h - 6, h - 6))
        else:
            p.setBrush(QColor(t["sw_off"]))
            p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
            p.setBrush(QColor(t["sw_knob"]))
            p.drawEllipse(QRectF(3, 3, h - 6, h - 6))
        # hover 描一圈主题色，按住时再压暗一层 —— 让这个自绘开关也有点击反馈
        if self.underMouse():
            c = QColor(t["acc"])
            c.setAlpha(200 if self.isDown() else 110)
            pen = QPen(c)
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        if self.isDown():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawRoundedRect(QRectF(0, 0, w, h), r, r)


class Preview(QWidget):
    """每路卡片顶部那条流动色带，直接用当前灯效的颜色画渐变"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.colors = ["#00d0ff"]
        self.phase = 0.0
        self.lit = True

    def tick(self, phase):
        self.phase = phase
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        rect = QRectF(0, 0, w, h)
        p.setPen(Qt.NoPen)
        if not self.lit:
            p.setBrush(QColor(theme()["card2"]))
            p.drawRoundedRect(rect, 3, 3)
            p.setPen(QColor(255, 255, 255, 14))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            return
        cols = [QColor(c) for c in (self.colors or ["#00d0ff"])]
        if len(cols) == 1:
            cols = cols * 2
        g = QLinearGradient(-w * self.phase, 0, w - w * self.phase, 0)
        g.setSpread(QGradient.RepeatSpread)
        for i, c in enumerate(cols):
            g.setColorAt(i / max(1, len(cols) - 1), c)
        # 灯条外面一圈同色辉光
        p.setBrush(QColor(cols[0].red(), cols[0].green(), cols[0].blue(), 45))
        p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 4, 4)
        p.setBrush(g)
        p.drawRoundedRect(rect, 3, 3)
        # 顶部高光 + 一道白色扫描线，模拟灯珠质感
        hg = QLinearGradient(0, 0, 0, h)
        hg.setColorAt(0, QColor(255, 255, 255, 70))
        hg.setColorAt(0.45, QColor(255, 255, 255, 0))
        p.setBrush(hg)
        p.drawRoundedRect(rect, 3, 3)
        sx = (w * self.phase * 2.4) % (w + 40) - 40
        sg = QLinearGradient(sx, 0, sx + 40, 0)
        sg.setColorAt(0, QColor(255, 255, 255, 0))
        sg.setColorAt(0.5, QColor(255, 255, 255, 55))
        sg.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(sg)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)


class ZoneCard(QFrame):
    changed = Signal(int, dict)
    identify = Signal(int)

    def __init__(self, idx, effects, hw_modes, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.idx = idx
        self.effects = effects
        self.hw_modes = hw_modes
        self.zone = None
        self._swatches = []
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_title = QLabel("ARGB 排针")
        self.lbl_title.setObjectName("cardTitle")
        self.lbl_area = QLabel("")
        self.lbl_area.setObjectName("muted")
        self.btn_id = QPushButton("定位")
        self.btn_id.setObjectName("ghost")
        self.btn_id.setCursor(Qt.PointingHandCursor)
        self.btn_id.clicked.connect(lambda: self.identify.emit(self.idx))
        head.addWidget(self.lbl_title)
        head.addWidget(self.lbl_area)
        head.addStretch(1)
        head.addWidget(self.btn_id)
        lay.addLayout(head)

        self.preview = Preview()
        lay.addWidget(self.preview)

        self.cmb = QComboBox()
        self.cmb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb.addItem("— 软件特效 —", None)
        self.cmb.model().item(self.cmb.count() - 1).setEnabled(False)
        for e in effects:
            self.cmb.addItem(e["name"], e["id"])
        self.cmb.addItem("— 硬件灯效（主板芯片跑，关软件也不停） —", None)
        self.cmb.model().item(self.cmb.count() - 1).setEnabled(False)
        for m in hw_modes:
            self.cmb.addItem(m["name"], m["value"])
        self.cmb.currentIndexChanged.connect(self._on_effect)
        lay.addWidget(self.cmb)

        row_led = QHBoxLayout()
        row_led.setSpacing(6)
        row_led.addStretch(1)
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setFixedWidth(64)
        self.spin.setSuffix(" 颗")
        self.spin.valueChanged.connect(self._on_leds)
        row_led.addWidget(self.spin)
        lay.addLayout(row_led)

        self.swatch_row = QHBoxLayout()
        self.swatch_row.setSpacing(6)
        self.swatch_row.addStretch(1)
        lay.addLayout(self.swatch_row)

        self.sl_speed, self.val_speed = self._make_slider(lay, "速度")
        self.sl_bri, self.val_bri = self._make_slider(lay, "亮度")
        lay.addStretch(1)

    def _make_slider(self, lay, label):
        row = QHBoxLayout()
        row.setSpacing(8)
        lab = QLabel(label)
        lab.setObjectName("muted")
        lab.setFixedWidth(26)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 100)
        val = QLabel("0")
        val.setFixedWidth(34)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(lab)
        row.addWidget(sl, 1)
        row.addWidget(val)
        lay.addLayout(row)
        return sl, val

    # ------------------------------------------------------------------ 状态
    def apply(self, zone, master):
        self._loading = True
        self.zone = zone
        self.lbl_title.setText(zone.get("name", "ARGB 排针"))
        self.lbl_area.setText("0x%02x" % zone.get("area", 0))
        self.spin.setMaximum(int(zone.get("max_leds", 100)))
        self.spin.setValue(int(zone.get("leds", 30)))
        self.sl_speed.setValue(int(zone.get("speed", 45)))
        self.val_speed.setText(str(int(zone.get("speed", 45))))
        self.sl_bri.setValue(int(zone.get("brightness", 100)))
        self.val_bri.setText("%d%%" % int(zone.get("brightness", 100)))
        self.preview.colors = self._preview_colors(zone)
        self.preview.lit = zone.get("effect") != "hw:10"

        want = zone.get("effect", "rainbow")
        found = -1
        for i in range(self.cmb.count()):
            if self.cmb.itemData(i) == want:
                found = i
                break
        if found >= 0:
            self.cmb.setCurrentIndex(found)

        self._rebuild_swatches(zone)
        self._loading = False

    def _preview_colors(self, zone):
        """预览条颜色：彩虹类直接给全色环，硬件模式给模式自带配色，其余用用户选的颜色"""
        eff = zone.get("effect", "")
        colors = list(zone.get("colors") or [])
        if eff in ("rainbow", "hw:1c", "hw:1a", "hw:14", "hw:15", "hw:22", "hw:1f"):
            return ["#ff3b3b", "#ff9a00", "#ffee00", "#3dff6e", "#00d0ff", "#3b5bff", "#a855f7"]
        if eff.startswith("hw:"):
            n = self._hw_color_count(eff)
            if n == 0:
                return ["#8fa2b8"]
        return colors or ["#00d0ff"]

    def _rebuild_swatches(self, zone):
        while self.swatch_row.count():
            it = self.swatch_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._swatches = []
        eff = zone.get("effect", "")
        if eff.startswith("hw:"):
            try:
                count = self._hw_color_count(eff)
            except Exception:
                count = 1
        else:
            count = self._sw_color_count(eff)
        if count <= 0:
            return
        colors = list(zone.get("colors") or [])
        while len(colors) < count:
            colors.append(["#00d0ff", "#ff3b6b", "#ffd166", "#7bffb2",
                           "#a06bff", "#ff8a3d", "#3dff9e", "#ffffff"][len(colors) % 8])
        for i in range(count):
            btn = QPushButton()
            btn.setObjectName("swatch")
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.PointingHandCursor)
            c = colors[i]
            btn.setStyleSheet("QPushButton{background:%s;border-radius:6px;"
                              "border:1px solid rgba(255,255,255,.18);}"
                              "QPushButton:hover{border:1px solid %s;}" % (c, CYAN))
            btn.setToolTip("点一下改颜色")
            btn.clicked.connect(lambda _=False, i=i: self._pick_color(i))
            self.swatch_row.addWidget(btn)
            self._swatches.append(btn)
        self.swatch_row.addStretch(1)

    def _sw_color_count(self, eff):
        for e in self.effects:
            if e["id"] == eff:
                return int(max(e["colors"]))
        return 1

    def _hw_color_count(self, eff):
        for m in self.hw_modes:
            if m["value"] == eff:
                return int(m["colors"])
        return 1

    # ------------------------------------------------------------------ 交互
    def _emit(self, **kw):
        if self._loading:
            return
        self.changed.emit(self.idx, kw)

    def _on_effect(self, _):
        eff = self.cmb.currentData()
        if eff is None:
            return
        count = self._hw_color_count(eff) if eff.startswith("hw:") else self._sw_color_count(eff)
        colors = list(self.zone.get("colors") or []) if self.zone else []
        while len(colors) < count:
            colors.append(["#00d0ff", "#ff3b6b", "#ffd166", "#7bffb2",
                           "#a06bff", "#ff8a3d", "#3dff9e", "#ffffff"][len(colors) % 8])
        colors = colors[:count] if count else []
        self._emit(effect=eff, colors=colors)

    def _on_leds(self, v):
        self._emit(leds=int(v))

    def _pick_color(self, i):
        if not self.zone:
            return
        colors = list(self.zone.get("colors") or [])
        while len(colors) <= i:
            colors.append("#ffffff")
        cur = QColor(colors[i])
        c = QColorDialog.getColor(cur, self, "选择颜色")
        if c.isValid():
            colors[i] = c.name()
            self._emit(colors=colors)

    def slider_changed(self):
        self.sl_speed.valueChanged.connect(lambda v: (self.val_speed.setText(str(v)),
                                                      self._emit(speed=int(v))))
        self.sl_bri.valueChanged.connect(lambda v: (self.val_bri.setText("%d%%" % v),
                                                    self._emit(brightness=int(v))))

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0.0, QColor(255, 45, 85, 235))
        g.setColorAt(0.45, QColor(255, 45, 85, 70))
        g.setColorAt(1.0, QColor(255, 45, 85, 0))
        p.fillRect(QRectF(1, 1, self.width() - 2, 2), g)


class _UpdateWorker(QThread):
    """后台线程查询 GitHub 最新 Release；不阻塞界面。"""
    done = Signal(object, str)      # 结果 dict（None=失败）, 错误信息

    def __init__(self, current, parent=None):
        super().__init__(parent)
        self._current = current

    def run(self):
        try:
            info = updatecheck.fetch_latest()
            if updatecheck.is_newer(info.get("tag", ""), self._current):
                self.done.emit(info, "")
            else:
                self.done.emit({"up_to_date": True}, "")
        except Exception as e:
            self.done.emit(None, str(e))


class MainWindow(QWidget):
    hw_ready = Signal(object)
    fan_done = Signal(int, str, str)
    fan_arm = Signal(int, int)
    prof_done = Signal(str, bool, str)
    ms_done = Signal(str)

    def __init__(self, engine, presets_dir, icon_path=None, start_minimized=False):
        super().__init__()
        self.eng = engine
        self.presets_dir = presets_dir
        _cfg = getattr(engine, "config_path", None)
        self.kbd = kbmod.Keyboard(os.path.dirname(os.path.abspath(_cfg)) if _cfg else APP_DIR)
        self.mouse = msmod.Mouse(os.path.dirname(os.path.abspath(_cfg)) if _cfg else APP_DIR)
        self._kb_sweep = None
        self.cards = []
        self._phase = 0.0
        self._last_log = None
        self._quitting = False
        self.apps = {}
        self._night_on = False
        self._last_fg = ""
        self._hw_busy = False
        self.hw_ready.connect(self._apply_hw_state)
        self.fan_done.connect(self._on_fan_result)
        self.fan_arm.connect(self._on_fan_arm)
        self.prof_done.connect(self._on_prof_result)
        self.ms_done.connect(self._ms_on_done)
        self._hk_filter = HotkeyFilter(self._on_hotkey)
        self._hk_installed = False
        self._scene_custom = None
        self._scene = ""
        self._rot_idx = -1
        self._rot_next = 0.0
        self._guard_on = False
        # 风扇写后验证：基线 / 待判定 / 已验证有效 / 已验证无效
        self._fan_rpm0 = {}
        self._fan_pend = {}
        self._fan_ok = set()
        self._fan_bad = set()
        # 风扇配置持久化：开机按 data\fan_profile.json 自动还原（见 core/fanprofile.py）
        _cfg_path = getattr(engine, "config_path", None)
        self._fan_data_dir = (os.path.dirname(os.path.abspath(_cfg_path)) if _cfg_path else APP_DIR)
        self._fan_profile = fanprofile.load(self._fan_data_dir)
        self._fan_values = list(self._fan_profile.get("values") or fanprofile.DEFAULT_VALUES)
        self._fan_restored = False

        self.setWindowTitle("X99 控制台 · ARGB")
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1500, 700)
        self.setMinimumSize(1120, 620)

        snap = engine.snapshot()
        effects = snap["effects"]
        hw_modes = snap["hw_modes"]

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ------------------------------------------------------------ 顶栏
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(74)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 8, 0)
        tl.setSpacing(10)

        logo = QLabel()
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignCenter)
        _icon_file = _asset_path("icon.png")
        if os.path.exists(_icon_file):
            logo.setPixmap(QPixmap(_icon_file).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo.setText("X99")
        self.logo_lbl = logo
        bar = QFrame()
        bar.setFixedSize(2, 40)
        self.bar_lbl = bar
        brand = QVBoxLayout()
        brand.setSpacing(2)
        trow = QHBoxLayout()
        trow.setSpacing(7)
        t1 = QLabel("X99 控制台")
        t1.setObjectName("brandTitle")
        tag = QLabel("ARGB")
        tag.setObjectName("tag")
        trow.addWidget(t1)
        trow.addWidget(tag)
        trow.addStretch(1)
        t2 = QLabel("JGINYUE X99M GAMING D3 · 5 路排针 · 逐颗直控")
        t2.setObjectName("brandSub")
        brand.addLayout(trow)
        brand.addWidget(t2)
        tl.addWidget(logo)
        tl.addWidget(bar)
        tl.addLayout(brand)

        self.pill = QLabel("正在连接控制器…")
        self.pill.setObjectName("pill")
        self.pill.setFixedHeight(30)
        self.pill.setAlignment(Qt.AlignCenter)
        tl.addSpacing(6)
        tl.addWidget(self.pill)
        tl.addStretch(1)

        lbl = QLabel("总亮度")
        lbl.setObjectName("muted")
        tl.addWidget(lbl)
        self.sl_master = QSlider(Qt.Horizontal)
        self.sl_master.setRange(0, 100)
        self.sl_master.setFixedWidth(132)
        self.sl_master.setValue(int(snap["master"].get("brightness", 100)))
        self.sl_master.valueChanged.connect(self._on_master_bri)
        tl.addWidget(self.sl_master)
        self.lbl_master = QLabel("%d%%" % int(snap["master"].get("brightness", 100)))
        self.lbl_master.setFixedWidth(38)
        tl.addWidget(self.lbl_master)

        # 总速度：全局倍率，乘到每一路自己的 speed 上（各路仍可单独微调）
        lblsp = QLabel("总速度")
        lblsp.setObjectName("muted")
        tl.addWidget(lblsp)
        self.sl_speed = QSlider(Qt.Horizontal)
        self.sl_speed.setRange(5, 100)
        self.sl_speed.setFixedWidth(104)
        self.sl_speed.setValue(max(5, min(100, int(snap["master"].get("speed", 100))))
                               if snap["master"].get("speed", 100) else 100)
        self.sl_speed.setToolTip("全局速度倍率：100%% 等于各路原始速度，数值越小灯效越慢；"
                                 "拖到这之后各路自己的速度滑杆照旧生效")
        self.sl_speed.valueChanged.connect(self._on_master_speed)
        tl.addWidget(self.sl_speed)
        self.lbl_speed = QLabel("%d%%" % self.sl_speed.value())
        self.lbl_speed.setFixedWidth(38)
        tl.addWidget(self.lbl_speed)

        sw_row = QHBoxLayout()
        sw_row.setSpacing(7)
        lb2 = QLabel("联排")
        lb2.setObjectName("muted")
        self.sw_span = Switch(bool(snap["master"].get("span", True)))
        self.sw_span.clicked.connect(lambda: self.eng.set_master(span=self.sw_span.isChecked()))
        sw_row.addWidget(lb2)
        sw_row.addWidget(self.sw_span)
        tl.addLayout(sw_row)

        lb3 = QLabel("帧率")
        lb3.setObjectName("muted")
        tl.addWidget(lb3)
        self.cmb_fps = QComboBox()
        for v in (20, 30, 40, 60):
            self.cmb_fps.addItem(str(v), v)
        self.cmb_fps.setCurrentIndex([20, 30, 40, 60].index(int(snap["master"].get("fps", 40)))
                                      if int(snap["master"].get("fps", 40)) in (20, 30, 40, 60) else 2)
        self.cmb_fps.currentIndexChanged.connect(
            lambda: self.eng.set_master(fps=int(self.cmb_fps.currentData())))
        tl.addWidget(self.cmb_fps)

        self.btn_off = QPushButton("全部熄灭")
        self.btn_off.setObjectName("danger")
        self.btn_off.setCursor(Qt.PointingHandCursor)
        self.btn_off.clicked.connect(self.eng.set_off)
        tl.addWidget(self.btn_off)

        # 窗口按钮：系统标题栏已经并进这条顶栏，最小化 / 最大化 / 关闭自己画
        capbox = QHBoxLayout()
        capbox.setSpacing(0)
        capbox.setContentsMargins(14, 0, 0, 0)
        self._btn_min = self._caption_button("min", "最小化")
        self._btn_max = self._caption_button("max", "最大化 / 还原")
        self._btn_close = self._caption_button("close", "关闭（收起托盘）", close=True)
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_max.clicked.connect(self._toggle_max)
        self._btn_close.clicked.connect(self.close)
        for _wb in (self._btn_min, self._btn_max, self._btn_close):
            capbox.addWidget(_wb)
        tl.addLayout(capbox)
        root.addWidget(top)

        # ------------------------------------------------------------ 断连提示条
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner.setVisible(False)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(24, 9, 24, 9)
        bl.setSpacing(10)
        dot = QLabel("●")
        dot.setStyleSheet("color:%s; font-size:13px;" % RED)
        self.lbl_banner = QLabel("控制器无应答。")
        self.lbl_banner.setStyleSheet("color:#ffd9d9;")
        self.btn_reconnect = QPushButton("重新连接")
        self.btn_reconnect.setCursor(Qt.PointingHandCursor)
        self.btn_reconnect.clicked.connect(self._on_reconnect)
        bl.addWidget(dot)
        bl.addWidget(self.lbl_banner, 1)
        bl.addWidget(self.btn_reconnect)
        root.addSpacing(4)
        root.addWidget(self.banner)
        root.addSpacing(4)

        # ------------------------------------------------------------ 5 路卡片
        zones = QHBoxLayout()
        zones.setContentsMargins(20, 10, 20, 0)
        zones.setSpacing(12)
        for i in range(5):
            card = ZoneCard(i, effects, hw_modes)
            card.setFixedHeight(236)
            card.changed.connect(self._on_zone_changed)
            card.identify.connect(self._on_identify)
            card.slider_changed()
            sh = QGraphicsDropShadowEffect(card)
            sh.setBlurRadius(20)
            sh.setOffset(0, 4)
            sh.setColor(QColor(0, 0, 0, 150))
            card.setGraphicsEffect(sh)
            zones.addWidget(card, 1)
            self.cards.append(card)
        root.addLayout(zones, 0)

        # ------------------------------------------------------------ 底部：原生标签页
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._tab_presets(), "预设与日志")
        self.tabs.addTab(self._tab_scene(), "情景与守护")
        self.tabs.addTab(self._tab_live(), "实时联动")
        self.tabs.addTab(self._tab_monitor(), "系统监控")
        self.tabs.addTab(self._tab_auto(), "自动化")
        self.tabs.addTab(self._tab_hardware(), "硬件与控制")
        self.tabs.addTab(self._tab_keyboard(), "键盘灯效")
        self.tabs.addTab(self._tab_mouse(), "鼠标控制")
        self.tabs.addTab(self._tab_jixue(), "鸡血 BIOS")
        self.tabs.addTab(self._tab_logo(), "开机 LOGO")
        self.tabs.addTab(self._tab_about(), "关于作者")
        self._hw_ts = time.time()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        threading.Thread(target=pcctl.static_info, daemon=True).start()
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 8, 20, 10)
        wl.addWidget(self.tabs)
        root.addWidget(wrap, 1)

        # ------------------------------------------------------------ 页脚
        foot = QFrame()
        foot.setObjectName("footer")
        foot.setFixedHeight(44)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.setSpacing(10)
        self.lbl_dev = QLabel("设备：JIGUANG ARGB V2 · HID + CDC 双通道")
        self.lbl_dev.setObjectName("muted")
        fl.addWidget(self.lbl_dev)
        fl.addStretch(1)
        lb_skin = QLabel("皮肤")
        lb_skin.setObjectName("muted")
        fl.addWidget(lb_skin)
        self.cmb_theme = QComboBox()
        for k in THEME_ORDER:
            self.cmb_theme.addItem(THEMES[k]["name"], k)
        self.cmb_theme.setFixedWidth(106)
        cur_theme = getattr(self.eng, "theme_name", "rog")
        self.cmb_theme.setCurrentIndex(THEME_ORDER.index(cur_theme)
                                       if cur_theme in THEME_ORDER else 0)
        self.cmb_theme.currentIndexChanged.connect(
            lambda _=0: self._on_theme(self.cmb_theme.currentData()))
        fl.addWidget(self.cmb_theme)
        fl.addSpacing(14)
        lb_auto = QLabel("开机自启")
        lb_auto.setObjectName("muted")
        fl.addWidget(lb_auto)
        self.sw_auto = Switch(False)
        self.sw_auto.clicked.connect(self._on_autostart)
        fl.addWidget(self.sw_auto)
        fl.addStretch(1)
        self.lbl_port = QLabel("")
        self.lbl_port.setObjectName("muted")
        fl.addWidget(self.lbl_port)
        btn_about = QPushButton("关于")
        btn_about.setObjectName("ghost")
        btn_about.clicked.connect(self._show_about)
        fl.addWidget(btn_about)
        btn_quit = QPushButton("退出程序")
        btn_quit.setObjectName("ghost")
        btn_quit.clicked.connect(self.really_quit)
        fl.addWidget(btn_quit)
        root.addWidget(foot)

        # ------------------------------------------------------------ 定时刷新
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(400)
        self.anim = QTimer(self)
        self.anim.timeout.connect(self._on_anim)
        self.anim.start(70)
        # 键盘灯效保持：每 90 秒悄悄重发一次
        self.kb_timer = QTimer(self)
        self.kb_timer.timeout.connect(self._kb_keepalive)
        self.kb_timer.start(90000)

        self._sync_autostart()
        self._load_auto()
        self.load_presets()
        # 应用上次选中的皮肤（config 里存的）
        self._on_theme(self.cmb_theme.currentData(), remember=False, log=False)
        if self.sw_hotkey.isChecked():
            self._register_hotkeys()
        self._sync_live_buttons()
        self.refresh()
        QTimer.singleShot(0, lambda: apply_dwm_titlebar(self))

        # 启动 3 秒后静默检查 GitHub 更新；有新版本才弹窗，失败/已是最新都不打扰
        QTimer.singleShot(3000, lambda: self._start_update_check(manual=False))

        if start_minimized:
            self.hide()

    # ================================================================== 背景
    def paintEvent(self, _):
        """黑色底 + 左上红晕 + 右下青晕 + 45° 细斜纹，营造 ROG 那种"机箱内部"质感"""
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(BG))
        rg = QRadialGradient(QPointF(90, -60), max(r.width() * 0.75, 520))
        rg.setColorAt(0.0, QColor(255, 45, 85, 68))
        rg.setColorAt(0.45, QColor(255, 45, 85, 16))
        rg.setColorAt(1.0, QColor(255, 45, 85, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawRect(r)
        rg2 = QRadialGradient(QPointF(r.width() * 0.92, r.height() * 1.05), max(r.width() * 0.6, 460))
        rg2.setColorAt(0.0, QColor(34, 211, 238, 44))
        rg2.setColorAt(1.0, QColor(34, 211, 238, 0))
        p.setBrush(rg2)
        p.drawRect(r)
        pen = QPen(QColor(255, 255, 255, 9))
        pen.setWidth(1)
        p.setPen(pen)
        step = 26
        for x in range(-r.height(), r.width(), step):
            p.drawLine(x, 0, x + r.height(), r.height())

    # ================================================================== 标签页
    def _panel(self, layout):
        box = QFrame()
        box.setObjectName("card")
        box.setLayout(layout)
        return box

    def _tab_presets(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(14)

        pl = QVBoxLayout()
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(7)
        ph = QHBoxLayout()
        ph.setSpacing(8)
        lbp = QLabel("预设")
        lbp.setObjectName("muted")
        ph.addWidget(lbp)
        self.txt_preset = QLineEdit()
        self.txt_preset.setPlaceholderText("新预设名称")
        self.txt_preset.setMaxLength(20)
        self.txt_preset.setFixedWidth(150)
        ph.addWidget(self.txt_preset)
        btn_save = QPushButton("保存当前")
        btn_save.clicked.connect(self._on_save_preset)
        ph.addWidget(btn_save)
        ph.addStretch(1)
        pl.addLayout(ph)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(7)
        self.lbl_no_preset = QLabel("还没有预设：把 5 路灯效调好，点上面的「保存当前」就能存成一个预设")
        self.lbl_no_preset.setObjectName("muted")
        self.chips.addWidget(self.lbl_no_preset)
        self.chips.addStretch(1)
        pl.addLayout(self.chips)
        pl.addStretch(1)
        h.addWidget(self._panel(pl), 1)

        lg = QVBoxLayout()
        lg.setContentsMargins(14, 12, 14, 12)
        lg.setSpacing(6)
        lbl_log = QLabel("运行日志")
        lbl_log.setObjectName("muted")
        lg.addWidget(lbl_log)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMinimumHeight(96)
        lg.addWidget(self.logbox)
        h.addWidget(self._panel(lg), 1)
        return w

    def _tab_live(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        lb = QLabel("联动源")
        lb.setObjectName("muted")
        row.addWidget(lb)
        self.btn_live = {}
        for key, name in (("screen", "屏幕氛围同步"), ("music", "音乐律动"), ("temp", "温度联动")):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._on_live_click(k))
            row.addWidget(b)
            self.btn_live[key] = b
        row.addStretch(1)
        self.lbl_live = QLabel("当前：软件特效（未开联动）")
        self.lbl_live.setObjectName("muted")
        row.addWidget(self.lbl_live)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        lb2 = QLabel("分区取色")
        lb2.setObjectName("muted")
        row2.addWidget(lb2)
        self.sw_split = Switch(True)
        self.sw_split.clicked.connect(self._on_live_param)
        row2.addWidget(self.sw_split)
        row2.addSpacing(14)
        lb3 = QLabel("平滑")
        lb3.setObjectName("muted")
        row2.addWidget(lb3)
        self.sl_smooth = QSlider(Qt.Horizontal)
        self.sl_smooth.setRange(0, 100)
        self.sl_smooth.setValue(50)
        self.sl_smooth.setFixedWidth(150)
        self.sl_smooth.valueChanged.connect(self._on_live_param)
        row2.addWidget(self.sl_smooth)
        row2.addStretch(1)
        self.lbl_mic = QLabel("")
        self.lbl_mic.setObjectName("muted")
        row2.addWidget(self.lbl_mic)
        v.addLayout(row2)

        hint = QLabel("· 屏幕氛围同步：把屏幕缩成 16×9 取色，5 路各取一条横带，看电影打游戏时灯跟着画面走\n"
                      "· 音乐律动：抓麦克风音量起伏，色相随音量流动（需要有可用的录音设备，且没被静音）\n"
                      "· 温度联动：GPU 温度 30°C 青 → 60°C 黄 → 90°C 红，CPU 负载越高呼吸越快")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return w

    def _tab_monitor(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(9)
        self.bars = {}
        self.vals = {}
        left = [("cpu", "CPU 占用", 100), ("cpu_temp", "CPU 温度", 100),
                ("cpu_mhz", "CPU 频率", 4000),
                ("mobo", "主板温度", 100), ("fan", "CPU 风扇", 3000),
                ("mem", "内存占用", 100),
                ("vram", "显存占用", 100), ("disk", "磁盘已用", 100)]
        right = [("gpu_util", "GPU 占用", 100), ("gpu_temp", "GPU 温度", 100),
                 ("gpu_fan", "GPU 风扇", 100), ("gpu_power", "GPU 功耗", 150),
                 ("gpu_clock", "GPU 核心频率", 2000),
                 ("uptime", "开机时长", 86400), ("fps", "渲染帧率", 60)]
        # 15 项全部带状态条：第三列就是条的量程，占用/温度类 0–100，
        # 频率 0–4000 MHz、风扇 0–3000 RPM、GPU 功耗 0–150 W、核心频率 0–2000 MHz、
        # 开机时长按最近 24 小时算进度，条长和右边的数值一一对应
        hrow = QHBoxLayout()
        hrow.setSpacing(30)
        for group in (left, right):
            gg = QGridLayout()
            gg.setHorizontalSpacing(10)
            gg.setVerticalSpacing(8)
            for r, (key, name, top) in enumerate(group):
                lb = QLabel(name)
                lb.setObjectName("muted")
                lb.setFixedWidth(92)
                bar = None
                if top:
                    bar = QProgressBar()
                    bar.setRange(0, top)
                    bar.setFixedHeight(10)
                    gg.addWidget(bar, r, 1)
                else:
                    ph = QWidget()
                    ph.setFixedHeight(10)
                    gg.addWidget(ph, r, 1)
                val = QLabel("—")
                val.setObjectName("metric")
                val.setFixedWidth(150)
                val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                gg.addWidget(lb, r, 0)
                gg.addWidget(val, r, 2)
                self.bars[key] = bar
                self.vals[key] = val
            gg.setColumnStretch(1, 1)
            hrow.addLayout(gg, 1)
        outer.addLayout(hrow)
        outer.addSpacing(6)
        self.lbl_spec = QLabel("硬件：读取中…")
        self.lbl_spec.setObjectName("muted")
        outer.addWidget(self.lbl_spec)
        # CPU 温度/主板温度/风扇转速靠 hwmon 组件（要管理员权限读内核驱动）
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.lbl_hwmon = QLabel("")
        self.lbl_hwmon.setObjectName("muted")
        row2.addWidget(self.lbl_hwmon, 1)
        self.btn_hwmon = QPushButton("启用温度监控")
        self.btn_hwmon.setObjectName("primary")
        self.btn_hwmon.clicked.connect(self._enable_hwmon)
        row2.addWidget(self.btn_hwmon)
        outer.addLayout(row2)
        note = QLabel("数据每 1.5 秒刷新一次；CPU 温度 / 主板温度 / 风扇转速由内核驱动读取，"
                      "需要「启用温度监控」授权一次（管理员），之后开机自动生效。")
        note.setObjectName("muted")
        self.lbl_note_mon = note
        outer.addWidget(note)
        outer.addStretch(1)
        return w

    # ---------------------------------------------------------------- 硬件监控组件
    def _hwmon_exe(self):
        for cand in (os.path.join(APP_DIR, "hwmon", "X99硬件监控.exe"),
                     os.path.join(BASE_DIR, "hwmon", "X99硬件监控.exe")):
            if os.path.exists(cand):
                return cand
        return None

    def _hwmon_alive(self):
        """温度监控是否已经在跑：能读到 CPU 温度就说明 hwmon 在给数据"""
        try:
            d = self.eng.sysinfo.get() or {}
            return (d.get("cpu") or {}).get("temp") is not None
        except Exception:                                       # noqa: BLE001
            return False

    def _enable_hwmon(self, quiet=False):
        if self._hwmon_alive():
            self.lbl_hwmon.setText("温度监控已在运行：温度/风扇转速每 2 秒刷新，不用重复授权")
            if not quiet:
                QMessageBox.information(
                    self, "温度监控",
                    "温度监控已经在后台跑着了，页面上的温度、风扇转速就是它在给的数据，"
                    "不用再点一次（重复点击只会再弹一次 UAC）。")
            return
        exe = self._hwmon_exe()
        if not exe:
            self.lbl_hwmon.setText("找不到 hwmon\\X99硬件监控.exe（安装目录不完整，重装一次即可）")
            return
        try:
            import ctypes
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, "--install",
                os.path.dirname(exe), 1)
            if rc <= 32:
                self.lbl_hwmon.setText("授权被取消或失败（返回码 %d）" % rc)
                return
        except Exception as e:
            self.lbl_hwmon.setText("启动失败：%s" % e)
            return
        if not quiet:
            QMessageBox.information(
                self, "温度监控",
                "已请求管理员授权。\n\n同意后 X99 硬件监控会常驻（每 2 秒采集一次）并注册开机自启，"
                "几秒后这几行就会有温度了。")

    def _tab_auto(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(9)

        # 夜间模式
        r1 = QHBoxLayout()
        r1.setSpacing(9)
        self.sw_night = Switch(False)
        self.sw_night.clicked.connect(self._on_auto_change)
        r1.addWidget(self.sw_night)
        lbn = QLabel("夜间模式")
        r1.addWidget(lbn)
        self.tm_from = QTimeEdit(QTime(23, 0))
        self.tm_from.setDisplayFormat("HH:mm")
        self.tm_from.timeChanged.connect(self._on_auto_change)
        self.tm_to = QTimeEdit(QTime(7, 0))
        self.tm_to.setDisplayFormat("HH:mm")
        self.tm_to.timeChanged.connect(self._on_auto_change)
        r1.addWidget(self.tm_from)
        r1.addWidget(QLabel("→"))
        r1.addWidget(self.tm_to)
        r1.addWidget(QLabel("期间"))
        self.cmb_night = QComboBox()
        self.cmb_night.addItem("降到指定亮度", "dim")
        self.cmb_night.addItem("全部熄灭", "off")
        self.cmb_night.currentIndexChanged.connect(self._on_auto_change)
        r1.addWidget(self.cmb_night)
        self.sp_night = QSpinBox()
        self.sp_night.setRange(1, 100)
        self.sp_night.setValue(20)
        self.sp_night.setSuffix(" %")
        self.sp_night.setFixedWidth(70)
        self.sp_night.valueChanged.connect(self._on_auto_change)
        r1.addWidget(self.sp_night)
        r1.addStretch(1)
        v.addLayout(r1)

        # 程序联动
        r2 = QHBoxLayout()
        r2.setSpacing(9)
        lbp = QLabel("程序联动")
        lbp.setObjectName("muted")
        r2.addWidget(lbp)
        self.cmb_app_preset = QComboBox()
        self.cmb_app_preset.setMinimumWidth(120)
        r2.addWidget(self.cmb_app_preset)
        btn_add = QPushButton("加入当前前台程序")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.clicked.connect(self._on_add_app)
        r2.addWidget(btn_add)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._on_del_app)
        r2.addWidget(btn_del)
        r2.addStretch(1)
        v.addLayout(r2)
        self.lst_apps = QListWidget()
        self.lst_apps.setMaximumHeight(84)
        v.addWidget(self.lst_apps)

        # 全局热键
        r3 = QHBoxLayout()
        r3.setSpacing(9)
        self.sw_hotkey = Switch(False)
        self.sw_hotkey.clicked.connect(self._on_hotkey_toggle)
        r3.addWidget(self.sw_hotkey)
        r3.addWidget(QLabel("全局快捷键"))
        lbh = QLabel("Ctrl+Alt+O 一键关灯 · Ctrl+Alt+P 恢复刚才的样子（任何程序里都管用）")
        lbh.setObjectName("muted")
        r3.addWidget(lbh)
        r3.addStretch(1)
        v.addLayout(r3)
        v.addStretch(1)
        return w

    # ================================================================== 情景与守护
    def _tab_hardware(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # ---------------------------------------------------------- 性能模式
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 10, 14, 10)
        c1.setSpacing(7)
        t1 = QLabel("性能模式 / 软超频")
        t1.setObjectName("sectionTitle")
        c1.addWidget(t1)
        self.lbl_plan = QLabel("当前：读取中…")
        self.lbl_plan.setObjectName("metric")
        c1.addWidget(self.lbl_plan)
        rowp = QHBoxLayout()
        rowp.setSpacing(7)
        self._plan_btns = {}
        for nm, guid in pcctl.PLANS:
            b = QPushButton(nm)
            b.setObjectName("scene")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, g=guid, n=nm: self._on_set_plan(g, n))
            rowp.addWidget(b)
            self._plan_btns[guid] = b
        c1.addLayout(rowp)
        rowc = QHBoxLayout()
        rowc.setSpacing(8)
        self.sl_cpu = QSlider(Qt.Horizontal)
        self.sl_cpu.setRange(20, 100)
        self.sl_cpu.setValue(100)
        self.sl_cpu.setToolTip("CPU 最大频率上限：越低越省电、越凉、越安静")
        self.lbl_cpu_cap = QLabel("100%")
        self.lbl_cpu_cap.setFixedWidth(46)
        self.lbl_cpu_cap.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sl_cpu.valueChanged.connect(lambda v: self.lbl_cpu_cap.setText("%d%%" % v))
        rowc.addWidget(self.sl_cpu, 1)
        rowc.addWidget(self.lbl_cpu_cap)
        btn_cap = QPushButton("应用上限")
        btn_cap.setObjectName("primary")
        btn_cap.setCursor(Qt.PointingHandCursor)
        btn_cap.clicked.connect(self._on_apply_cpu_cap)
        rowc.addWidget(btn_cap)
        c1.addLayout(rowc)
        lbl_pf = QLabel("软超频档（只调 Windows 功耗与调度，不碰 BIOS）")
        lbl_pf.setObjectName("muted")
        c1.addWidget(lbl_pf)
        rowpf = QHBoxLayout()
        rowpf.setSpacing(7)
        self._prof_btns = {}
        for key in ("silent", "balanced", "boost"):
            prof = pcctl.PROFILES[key]
            b = QPushButton(prof["name"])
            b.setObjectName("fmod")
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.setMinimumWidth(86)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(prof["tip"])
            b.clicked.connect(lambda _=False, k=key: self._on_perf_profile(k))
            rowpf.addWidget(b)
            self._prof_btns[key] = b
        self.lbl_prof = QLabel("上次应用：—")
        self.lbl_prof.setObjectName("fanMode")
        self.lbl_prof.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rowpf.addStretch(1)
        rowpf.addWidget(self.lbl_prof)
        c1.addLayout(rowpf)
        self.lbl_mhz = QLabel("CPU 频率：读取中…")
        self.lbl_mhz.setObjectName("muted")
        c1.addWidget(self.lbl_mhz)
        c1.addStretch(1)
        h.addWidget(self._panel(c1), 1)

        # ---------------------------------------------------------- 无线与输入
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 12, 14, 12)
        c2.setSpacing(8)
        t2 = QLabel("无线与输入")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)
        s2 = QLabel("WiFi / 蓝牙切换要管理员权限，第一次会弹一次 UAC，点「是」即可")
        s2.setObjectName("muted")
        s2.setWordWrap(True)
        c2.addWidget(s2)

        self.lbl_wifi = QLabel("WiFi：读取中…")
        self.lbl_wifi.setObjectName("muted")
        c2.addWidget(self.lbl_wifi)
        self.btn_wifi = QPushButton("读取中…")
        self.btn_wifi.setObjectName("ghost")
        self.btn_wifi.setCursor(Qt.PointingHandCursor)
        self.btn_wifi.setEnabled(False)
        self.btn_wifi.setToolTip("WiFi 状态还没读到，读到才能切换")
        self.btn_wifi.clicked.connect(self._on_wifi_toggle)
        c2.addWidget(self.btn_wifi)

        self.lbl_bt = QLabel("蓝牙：读取中…")
        self.lbl_bt.setObjectName("muted")
        c2.addWidget(self.lbl_bt)
        self.btn_bt = QPushButton("读取中…")
        self.btn_bt.setObjectName("ghost")
        self.btn_bt.setCursor(Qt.PointingHandCursor)
        self.btn_bt.setEnabled(False)
        self.btn_bt.setToolTip("蓝牙状态还没读到，读到才能切换")
        self.btn_bt.clicked.connect(self._on_bt_toggle)
        c2.addWidget(self.btn_bt)

        rnum = QHBoxLayout()
        rnum.setSpacing(9)
        self.sw_num = Switch(False)
        self.sw_num.clicked.connect(self._on_numlock)
        rnum.addWidget(self.sw_num)
        self.lbl_num = QLabel("小键盘（NumLock）：—")
        self.lbl_num.setObjectName("muted")
        rnum.addWidget(self.lbl_num, 1)
        c2.addLayout(rnum)

        rndef = QHBoxLayout()
        rndef.setSpacing(9)
        self.sw_numdef = Switch(False)
        self.sw_numdef.clicked.connect(self._on_numlock_default)
        rndef.addWidget(self.sw_numdef)
        lbl_ndef = QLabel("开机默认打开小键盘")
        lbl_ndef.setObjectName("muted")
        rndef.addWidget(lbl_ndef, 1)
        c2.addLayout(rndef)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 1)

        # ---------------------------------------------------------- 风扇调速
        c3 = QVBoxLayout()
        c3.setContentsMargins(14, 10, 14, 10)
        c3.setSpacing(5)
        rowt = QHBoxLayout()
        rowt.setSpacing(8)
        t3 = QLabel("风扇调速")
        t3.setObjectName("sectionTitle")
        rowt.addWidget(t3)
        self.lbl_fan_chip = QLabel("读取中…")
        self.lbl_fan_chip.setObjectName("muted")
        rowt.addWidget(self.lbl_fan_chip, 1)
        self.btn_fan_note = QPushButton("调速说明")
        self.btn_fan_note.setObjectName("ghost")
        self.btn_fan_note.setCursor(Qt.PointingHandCursor)
        self.btn_fan_note.setFixedHeight(22)
        self.btn_fan_note.setToolTip("软件调不动风扇时看这里：原因判断 + 进 BIOS 怎么调")
        self.btn_fan_note.clicked.connect(self._on_fan_note)
        rowt.addWidget(self.btn_fan_note)
        c3.addLayout(rowt)

        self._fan_rows = []
        for i in range(5):
            row = QHBoxLayout()
            row.setSpacing(6)
            nm = QLabel("Fan #%d" % (i + 1))
            nm.setFixedWidth(48)
            row.addWidget(nm)
            rpm = QLabel("—")
            rpm.setFixedWidth(62)
            rpm.setObjectName("muted")
            row.addWidget(rpm)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(20, 100)
            sl.setValue(60)
            sl.setToolTip("拖动到想要的风扇转速百分比，松手后立即生效")
            sl.valueChanged.connect(lambda v, k=i: self._on_fan_slide_preview(k, v))
            sl.sliderReleased.connect(lambda k=i: self._on_fan_slider(k))
            row.addWidget(sl, 1)
            val = QLabel("60%")
            val.setFixedWidth(34)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(val)
            st = QLabel("BIOS")
            st.setFixedWidth(58)
            st.setObjectName("muted")
            row.addWidget(st)
            c3.addLayout(row)
            self._fan_rows.append({"sl": sl, "val": val, "rpm": rpm, "state": st})

        # 4 个模式按钮：等高同宽（112×30），点了立刻在按钮上加亮 + 下面一行回显当前模式，
        # 不用再去 5 行的状态列里找"到底生效没有"
        rowb = QHBoxLayout()
        rowb.setSpacing(8)
        self._fan_mode_btns = {}
        for _key, _txt, _tip in (
                ("full", "一键全速", "5 路 PWM 一起拉到 100%"),
                ("quiet", "静音 40%", "5 路 PWM 一起降到 40%，风噪明显降下来"),
                ("curve", "智能曲线", "按 CPU 温度自动调速：45℃ 以下 35%、越热越快，80℃ 顶到 100%"),
                ("bios", "交回 BIOS", "撤掉软件占空比，恢复主板自己的自动调速曲线")):
            _b = QPushButton(_txt)
            _b.setObjectName("fmod")
            _b.setCheckable(True)
            _b.setFixedSize(112, 30)
            _b.setCursor(Qt.PointingHandCursor)
            _b.setToolTip(_tip)
            rowb.addWidget(_b)
            self._fan_mode_btns[_key] = _b
        self.btn_curve = self._fan_mode_btns["curve"]
        self._fan_mode_btns["full"].clicked.connect(lambda: self._on_fan_all(100))
        self._fan_mode_btns["quiet"].clicked.connect(lambda: self._on_fan_all(40))
        self.btn_curve.clicked.connect(self._on_fan_curve)
        self._fan_mode_btns["bios"].clicked.connect(self._on_fan_bios)
        rowb.addStretch(1)
        self.lbl_fan_mode = QLabel("当前：跟随 BIOS")
        self.lbl_fan_mode.setObjectName("fanMode")
        self.lbl_fan_mode.setFixedWidth(196)
        self.lbl_fan_mode.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rowb.addWidget(self.lbl_fan_mode)
        c3.addLayout(rowb)
        self._set_fan_mode("bios")     # 进页面就先按"跟随 BIOS"亮着，用户一眼看到当前状态

        tip3 = QLabel("松手立即生效，下限 20% 防停转；「交回 BIOS」恢复主板自动调速")
        tip3.setObjectName("muted")
        tip3.setWordWrap(True)
        c3.addWidget(tip3)

        # 写入后自动验证的结果回显：这一行是"风扇到底动没动"的唯一可信来源
        self.lbl_fan_verdict = QLabel("")
        self.lbl_fan_verdict.setObjectName("fanVerdict")
        self.lbl_fan_verdict.setWordWrap(True)
        self.lbl_fan_verdict.setText("")
        c3.addWidget(self.lbl_fan_verdict)
        c3.addStretch(1)
        h.addWidget(self._panel(c3), 2)
        return w

    # ------------------------------------------------------------------ 风扇调速
    _FAN_MODE_TEXT = {
        "full": "当前：全速 100%",
        "quiet": "当前：静音 40%",
        "curve": "当前：智能曲线",
        "bios": "当前：跟随 BIOS",
        "manual": "当前：手动（各路独立）",
        None: "当前：各路保持当前转速",
    }

    def _set_fan_mode(self, mode):
        """模式按钮的单选回显：只有当前生效的那个是按下态，其余弹起"""
        for k, b in getattr(self, "_fan_mode_btns", {}).items():
            b.blockSignals(True)
            b.setChecked(k == mode)
            b.blockSignals(False)
        self._fan_mode = mode
        lbl = getattr(self, "lbl_fan_mode", None)
        if lbl is not None:
            lbl.setText(self._FAN_MODE_TEXT.get(mode, "当前：跟随 BIOS"))

    # ------------------------------------------------------------ 配置持久化
    def _fan_save_profile(self, mode, values=None, global_pct=None):
        vals = list(values) if values is not None else list(self._fan_values)
        fanprofile.save(self._fan_data_dir, mode, vals, global_pct)

    def _fan_apply_saved_once(self, hw):
        """hwmon 就绪后的首次自动还原：对齐滑块，并把上次保存的软件占空比补发一次。

        常驻监控组件开机已先按档案写过一遍 SIO；这里再补写一次，防止主界面比
        监控组件晚启动、或监控组件尚未就绪期间档案没落上去。
        """
        if self._fan_restored or not hasattr(self, "_fan_rows"):
            return
        if not hw or not (hw.get("controls")):
            return
        prof = self._fan_profile
        mode = prof.get("mode", "bios")
        values = prof.get("values") or list(fanprofile.DEFAULT_VALUES)
        self._fan_values = [max(20, min(100, int(v))) for v in values]
        for i, r in enumerate(self._fan_rows):
            if i < len(self._fan_values):
                v = max(r["sl"].minimum(), min(r["sl"].maximum(), self._fan_values[i]))
                r["sl"].blockSignals(True)
                r["sl"].setValue(v)
                r["sl"].blockSignals(False)
                r["val"].setText("%d%%" % v)
        if mode == "bios":
            self._fan_restored = True
            return
        if mode == "curve":
            self.btn_curve.setChecked(True)
            self._set_fan_mode("curve")
            threading.Thread(target=self._fan_push_all, args=(int(self._fan_values[0]), False),
                             daemon=True).start()
        else:
            global_pct = prof.get("global")
            self._set_fan_mode("full" if global_pct == 100
                               else ("quiet" if mode == "quiet" else mode))
            for i, v in enumerate(self._fan_values):
                threading.Thread(target=self._fan_set_one, args=(i, v, False), daemon=True).start()
        self._fan_restored = True
        self.eng._add_log("已按上次保存的风扇配置还原（%s）" % mode)

    def _on_fan_slide_preview(self, idx, v):
        rows = getattr(self, "_fan_rows", [])
        if idx < len(rows):
            rows[idx]["val"].setText("%d%%" % v)

    # ---------------------------------------------------- 写后验证（转速到底动没动）
    def _fan_rpm_now(self):
        """从引擎快照里取当前各路转速：{0..4: RPM}"""
        hw = (self.eng.sysinfo.get() or {}).get("hw") or {}
        rpms = hw.get("fans") or {}
        out = {}
        for i in range(len(getattr(self, "_fan_rows", [])) or 5):
            try:
                out[i] = float(rpms.get("Fan #%d" % (i + 1)) or 0.0)
            except (TypeError, ValueError):
                out[i] = 0.0
        return out

    def _fan_capture(self):
        """点按钮 / 松手之前先记一份转速基线"""
        self._fan_rpm0 = self._fan_rpm_now()

    def _on_fan_arm(self, idx, pct):
        """写入成功后开始计时，几秒后再比一次转速"""
        rows = getattr(self, "_fan_rows", [])
        base = getattr(self, "_fan_rpm0", {}) or {}
        targets = list(range(len(rows))) if idx < 0 else [idx]
        now = time.time()
        for i in targets:
            if i >= len(rows):
                continue
            self._fan_pend[i] = (now, float(base.get(i, 0.0)))
            rows[i]["state"].setStyleSheet("")

    def _fan_check(self):
        """每轮刷新时检查到点的验证：转速变了才算真的控制住了"""
        pend = getattr(self, "_fan_pend", None)
        if not pend:
            return
        now = time.time()
        cur = self._fan_rpm_now()
        rows = getattr(self, "_fan_rows", [])
        for i in list(pend.keys()):
            t0, rpm0 = pend[i]
            if now - t0 < 4.5:
                continue
            del pend[i]
            if i >= len(rows):
                continue
            rpm1 = cur.get(i, 0.0)
            if rpm0 <= 0 or rpm1 <= 0:
                self._fan_mark_notach(i)
            elif abs(rpm1 - rpm0) / rpm0 >= 0.05:
                self._fan_mark_ok(i)
            else:
                self._fan_mark_bad(i, rpm0, rpm1)
        self._fan_verdict()

    def _fan_mark_ok(self, i):
        rows = self._fan_rows
        rows[i]["state"].setText("软件控制")
        rows[i]["state"].setStyleSheet("")
        rows[i]["sl"].setToolTip("拖动到想要的风扇转速百分比，松手后立即生效")
        self._fan_ok.add(i)
        self._fan_bad.discard(i)

    def _fan_mark_bad(self, i, rpm0, rpm1):
        rows = self._fan_rows
        rows[i]["state"].setText("调速无效")
        rows[i]["state"].setStyleSheet("color: #ff9c9c;")
        rows[i]["sl"].setToolTip(
            "这一路写进去了但转速没变（%.0f → %.0f RPM）。风扇多半由 BIOS/EC 接管，"
            "或是 3-pin 风扇插在 PWM 口上 —— 点右上「调速说明」看怎么处理" % (rpm0, rpm1))
        self._fan_bad.add(i)
        self._fan_ok.discard(i)

    def _fan_mark_notach(self, i):
        rows = self._fan_rows
        rows[i]["state"].setText("无转速")
        rows[i]["state"].setStyleSheet("color: #9095a1;")
        rows[i]["sl"].setToolTip(
            "这一路没有转速反馈（空排针，或风扇没接测速线），"
            "写入是否生效没法判断")
        self._fan_ok.discard(i)
        self._fan_bad.discard(i)

    def _fan_verdict(self):
        lbl = getattr(self, "lbl_fan_verdict", None)
        if lbl is None:
            return
        ok, bad = self._fan_ok, self._fan_bad
        if bad and not ok:
            lbl.setStyleSheet("color: #ff9c9c;")
            lbl.setText("实测：本机风扇不受软件调速 —— 写入成功但转速不变（BIOS/EC 接管，或 3-pin 风扇插在 PWM 口）。"
                        "调速请进 BIOS 的 Smart Fan，或点右上「调速说明」。")
        elif ok and not bad:
            lbl.setStyleSheet("")
            lbl.setText("实测：软件调速生效，转速已跟随（Fan #%d）。" % (min(ok) + 1))
        elif ok and bad:
            lbl.setStyleSheet("")
            lbl.setText("实测：部分通道生效（Fan #%s 有效；Fan #%s 写入无效）。"
                        % ("#".join(str(x + 1) for x in sorted(self._fan_ok)),
                           "#".join(str(x + 1) for x in sorted(self._fan_bad))))
        else:
            lbl.setStyleSheet("")
            lbl.setText("")

    def _on_fan_note(self):
        FanNoteDialog(self.window()).exec()

    def _on_fan_slider(self, idx):
        rows = getattr(self, "_fan_rows", [])
        if idx >= len(rows):
            return
        v = int(rows[idx]["sl"].value())
        self._fan_capture()
        self._fan_rows[idx]["state"].setText("写入…")
        # 手动拖某一格＝退出统一模式，按钮全部弹起，状态栏直接回显这一路的百分比
        self._set_fan_mode("manual")
        self.lbl_fan_mode.setText("当前：Fan #%d 手动 %d%%" % (idx + 1, v))
        self._fan_values[idx] = v
        self._fan_save_profile("manual", self._fan_values)
        threading.Thread(target=self._fan_set_one, args=(idx, v), daemon=True).start()

    def _fan_set_one(self, idx, v, verify=True):
        ok, info = pcctl.set_fan(idx, v)
        err = (info or {}).get("err") or ""
        if ok and verify:
            self.fan_done.emit(idx, "验证中…", "")
            self.fan_arm.emit(idx, v)
        else:
            self.fan_done.emit(idx, ("软件控制" if ok else "失败"), err)

    def _on_fan_result(self, idx, text, err):
        rows = getattr(self, "_fan_rows", [])
        if idx >= len(rows):
            return
        rows[idx]["state"].setText(text)
        if err:
            self.eng._add_log("风扇 %d 操作失败：%s" % (idx + 1, err))
            if hasattr(self, "lbl_fan_mode"):
                self.lbl_fan_mode.setText("当前：写入失败（%s）" % err[:24])

    def _on_fan_all(self, pct):
        self._set_fan_mode("full" if pct >= 100 else "quiet")
        if pct >= 100:
            self._fan_last_push = time.time()
        self._fan_capture()
        for r in getattr(self, "_fan_rows", []):
            r["state"].setText("写入…")
        threading.Thread(target=self._fan_push_all, args=(pct,), daemon=True).start()

    def _fan_push_all(self, pct, verify=True):
        ok, info = pcctl.fan_all(pct)
        err = (info or {}).get("err") or ""
        # 每一行都刷一次状态
        n = len(getattr(self, "_fan_rows", [])) or 5
        if ok and verify:
            # 一键全速 / 静音：写成功后把这份统一占空比落盘，开机自动还原
            self._fan_values = [pct] * n
            self._fan_save_profile("full" if pct >= 100 else "quiet",
                                   self._fan_values, pct)
            for i in range(n):
                self.fan_done.emit(i, "验证中…", "")
            self.fan_arm.emit(-1, pct)
        else:
            for i in range(n):
                self.fan_done.emit(i, ("软件控制" if ok else "失败"), err)
        self.eng._add_log("风扇全部设为 %d%%：%s" % (pct, "成功（正在验证转速）" if ok and verify
                                                    else ("成功" if ok else "失败（%s）" % (err or "未知"))))

    def _on_fan_bios(self):
        self._set_fan_mode("bios")
        for r in getattr(self, "_fan_rows", []):
            r["state"].setText("交回…")
        threading.Thread(target=self._fan_to_bios, daemon=True).start()

    def _fan_to_bios(self):
        ok, info = pcctl.fan_all_default()
        err = (info.get("err") if isinstance(info, dict) else info) or ""
        err = str(err)
        for i in range(len(getattr(self, "_fan_rows", [])) or 5):
            self.fan_done.emit(i, ("BIOS" if ok else "失败"), err)
        # 交回 BIOS 后旧的有效性判定作废，重新开始记
        self._fan_ok.clear()
        self._fan_bad.clear()
        self._fan_pend.clear()
        self._fan_verdict()
        if ok:
            self._fan_save_profile("bios")
        self.eng._add_log("风扇已全部交回 BIOS 控制" if ok
                          else "风扇交回 BIOS 失败：%s" % (err or "未知"))

    def _on_fan_curve(self):
        cur_vals = [int(r["sl"].value()) for r in getattr(self, "_fan_rows", [])]
        if self.btn_curve.isChecked():
            self._set_fan_mode("curve")
            self._fan_last_push = 0
            self._fan_save_profile("curve", cur_vals)
            self._on_fan_curve_tick()
            self.eng._add_log("风扇智能曲线已开启（按 CPU 温度自动调速）")
        else:
            self._set_fan_mode(None)
            # 关掉曲线后保持当前占空比，按手动档落盘，开机沿用而不是回 BIOS
            self._fan_values = cur_vals
            self._fan_save_profile("manual", cur_vals)
            self.eng._add_log("风扇智能曲线已关闭（保持当前转速）")

    def _on_fan_curve_tick(self):
        if not getattr(self, "btn_curve", None) or not self.btn_curve.isChecked():
            return
        now = time.time()
        if now - getattr(self, "_fan_last_push", 0) < 4.5:
            return
        hw = (self.eng.sysinfo.get() or {}).get("hw") or {}
        pkg = hw.get("pkg")
        if pkg is None:
            return
        self._fan_last_push = now
        pct = self._curve_pct(pkg)
        self._fan_values = [pct] * (len(self._fan_rows) or 5)
        for r in getattr(self, "_fan_rows", []):
            r["state"].setText("曲线 %d%%" % pct)
        # 曲线每 4.5 秒就会重推一次，逐次验证会一直闪「验证中」，这里只做写入
        threading.Thread(target=self._fan_push_all, args=(pct, False), daemon=True).start()

    @staticmethod
    def _curve_pct(temp):
        """温度 → PWM 阶梯曲线（保守起步，越热越激进）"""
        if temp < 45:
            return 35
        if temp < 55:
            return 45
        if temp < 62:
            return 58
        if temp < 70:
            return 72
        if temp < 78:
            return 86
        return 100

    def _sync_fan_ui(self, hw):
        """把 hwmon 读到的通道状态回填到界面（不改用户正在拖的滑块）"""
        if not hw or not hasattr(self, "_fan_rows"):
            return
        chip = hw.get("superio") or ""
        if chip:
            self.lbl_fan_chip.setText("%s · %d 路 PWM" % (chip, len(hw.get("controls") or []) or 5))
        elif self.lbl_fan_chip.text() == "读取中…":
            self.lbl_fan_chip.setText("硬件监控未就绪")
        ctrls = hw.get("controls") or []
        rpms = hw.get("fans") or {}
        for i, r in enumerate(self._fan_rows):
            if i >= len(ctrls):
                continue
            c = ctrls[i]
            rpm = rpms.get(c.get("n") or "", 0)
            r["rpm"].setText("%.0f RPM" % rpm if rpm else "—")
            if not r["sl"].isSliderDown():
                v = int(round(float(c.get("v") or 0)))
                v = max(r["sl"].minimum(), min(r["sl"].maximum(), v))
                r["sl"].blockSignals(True)
                r["sl"].setValue(v)
                r["sl"].blockSignals(False)
                r["val"].setText("%d%%" % v)
            mode = c.get("m") or ""
            cur = r["state"].text()
            if cur in ("写入…", "交回…", "失败", "验证中…", "软件控制", "调速无效", "无转速") \
                    or cur.startswith("曲线"):
                continue
            r["state"].setText("软件控制" if mode == "Software" else "BIOS")

    # ------------------------------------------------------------------ 软超频档
    def _on_perf_profile(self, key):
        prof = pcctl.PROFILES.get(key)
        if not prof:
            return
        self._mark_prof(key)
        if getattr(self, "lbl_prof", None) is not None:
            self.lbl_prof.setText("正在应用「%s」…" % prof["name"])
        self.eng._add_log("正在套用「%s」档：%s" % (prof["name"], prof["tip"]))
        threading.Thread(target=self._prof_apply, args=(key,), daemon=True).start()

    def _mark_prof(self, key):
        """软超频档单选高亮"""
        for k, b in getattr(self, "_prof_btns", {}).items():
            b.setChecked(k == key)
        if key:
            self._prof_cur = key

    def _prof_apply(self, key):
        ok, msg = pcctl.apply_profile(key)
        self.prof_done.emit(key, ok, msg or "")

    def _on_prof_result(self, key, ok, msg):
        name = (pcctl.PROFILES.get(key) or {}).get("name", key)
        self.eng._add_log(("「%s」档应用成功" % name) if ok else ("「%s」档应用失败：%s" % (name, msg)))
        lbl = getattr(self, "lbl_prof", None)
        if lbl is not None:
            if ok:
                lbl.setText("上次应用：%s · %s" % (name, time.strftime("%H:%M")))
            else:
                lbl.setText("应用失败：%s" % name)
                self._mark_prof(getattr(self, "_prof_cur_last", None))
        if ok:
            self._prof_cur_last = key
        self._refresh_hw(force=True)
    # ------------------------------------------------------------------ 硬件与控制
    def _on_theme(self, key, remember=True, log=True):
        qss = set_theme_name(key or "rog")
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        if remember:
            try:
                self.eng.theme_name = key
                self.eng.save()
            except Exception:
                pass
        self._apply_theme_visuals()
        apply_dwm_titlebar(self)          # 标题栏跟着皮肤走
        try:
            idx = self.cmb_theme.findData(key or "rog")
            if idx >= 0 and self.cmb_theme.currentIndex() != idx:
                self.cmb_theme.blockSignals(True)
                self.cmb_theme.setCurrentIndex(idx)
                self.cmb_theme.blockSignals(False)
        except Exception:
            pass
        if log:
            self.eng._add_log("皮肤切换：%s" % THEMES.get(key, THEMES["rog"])["name"])

    def _apply_theme_visuals(self):
        """样式表管不到的绘制部分（Logo、竖条、开关、卡片）手动刷一遍"""
        t = theme()
        if self.logo_lbl.pixmap() is not None:
            self.logo_lbl.setStyleSheet("background: transparent; border: none;")
        else:
            self.logo_lbl.setStyleSheet(
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 %s, stop:1 %s);"
                "border-radius: 3px; color:#ffffff; font-size:12px; font-weight:800;"
                "border: 1px solid %s;" % (t["logo1"], t["logo2"], t["ring"]))
        self.bar_lbl.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 %s,"
            " stop:1 rgba(%s,0)); border: none;" % (t["acc"], t["acc_rgb"]))
        for c in self.cards:
            try:
                c.preview.update()
            except Exception:
                pass
            c.update()
        self.update()

    def _on_tab_changed(self, idx):
        try:
            if self.tabs.tabText(idx) == "硬件与控制":
                self._refresh_hw(force=True)
            elif self.tabs.tabText(idx) == "鼠标控制":
                self._ms_timer.start()
                self._ms_refresh(False)
            else:
                if getattr(self, "_ms_timer", None) is not None:
                    self._ms_timer.stop()
        except Exception:
            pass

    def _on_set_plan(self, guid, name):
        # 点下去立刻反映到界面上（不等后台异步刷新，避免两个按钮同时亮）
        for g, b in getattr(self, "_plan_btns", {}).items():
            b.setChecked(g == guid)
        self.lbl_plan.setText("当前：%s" % name)
        ok, msg = pcctl.set_power_scheme(guid)
        self.eng._add_log("性能模式：%s %s" % (name, "已切换" if ok else "切换失败"))
        if not ok:
            self.eng._add_log("（%s）" % (msg or "需要管理员权限"))
        self._refresh_hw(force=True)

    def _on_apply_cpu_cap(self):
        v = int(self.sl_cpu.value())
        ok, msg = pcctl.set_cpu_limit(v)
        self.eng._add_log("CPU 上限：%s" % ("已设为 %d%%" % v if ok else "设置失败（需要管理员权限）"))
        self._refresh_hw(force=True)

    def _sync_net_btns(self):
        """WiFi/蓝牙按钮的文字跟着真实开关状态走（别卡在"切换中…"）"""
        w_on, b_on = getattr(self, "_wifi_on", None), getattr(self, "_bt_on", None)
        self.btn_wifi.setText("关闭 WiFi" if w_on else
                              ("打开 WiFi" if w_on is not None else "读取中…"))
        self.btn_bt.setText("关闭蓝牙" if b_on else
                            ("打开蓝牙" if b_on is not None else "读取中…"))
        self.btn_wifi.setToolTip("点一下关掉 WiFi" if w_on else
                                 ("点一下打开 WiFi" if w_on is not None
                                  else "WiFi 状态还没读到，读到才能切换"))
        self.btn_bt.setToolTip("点一下关掉蓝牙" if b_on else
                               ("点一下打开蓝牙" if b_on is not None
                                else "蓝牙状态还没读到，读到才能切换"))

    def _on_wifi_toggle(self):
        cur = getattr(self, "_wifi_on", None)
        if cur is None:
            self.eng._add_log("WiFi 状态还在读取，等 1 秒再点（读不到多半是没无线网卡）")
            self._refresh_hw(force=True)
            return
        self.btn_wifi.setEnabled(False)
        self.btn_wifi.setText("切换中…（可能要确认 UAC）")
        QApplication.processEvents()
        ok, msg = pcctl.set_wifi(not cur)
        self.btn_wifi.setEnabled(True)
        if ok:
            self._wifi_on = not cur
        self._sync_net_btns()
        self.eng._add_log("WiFi：%s%s" % ("已打开" if not cur else "已关闭",
                                        "" if ok else "，失败（%s）" % msg))
        self._refresh_hw(force=True)

    def _on_bt_toggle(self):
        cur = getattr(self, "_bt_on", None)
        if cur is None:
            self.eng._add_log("蓝牙状态还在读取，等 1 秒再点（读不到多半是没蓝牙模块）")
            self._refresh_hw(force=True)
            return
        self.btn_bt.setEnabled(False)
        self.btn_bt.setText("切换中…（可能要确认 UAC）")
        QApplication.processEvents()
        ok, msg = pcctl.set_bluetooth(not cur)
        self.btn_bt.setEnabled(True)
        if ok:
            self._bt_on = not cur
        self._sync_net_btns()
        self.eng._add_log("蓝牙：%s%s" % ("已打开" if not cur else "已关闭",
                                        "" if ok else "，失败（%s）" % msg))
        self._refresh_hw(force=True)

    def _on_numlock(self):
        ok = pcctl.set_numlock(self.sw_num.isChecked())
        self.eng._add_log("小键盘：%s" % ("已打开" if self.sw_num.isChecked() else "已关闭")
                          if ok else "小键盘切换失败（某些远程桌面会屏蔽）")
        self._refresh_hw(force=True)

    def _on_numlock_default(self):
        ok = pcctl.set_numlock_default(self.sw_numdef.isChecked())
        self.eng._add_log("开机默认小键盘：%s" % ("开" if self.sw_numdef.isChecked() else "关")
                          if ok else "写入注册表失败")
        self._refresh_hw(force=True)

    def _refresh_hw(self, force=False):
        now = time.time()
        if not force and now - getattr(self, "_hw_ts", 0) < 25:
            return
        if getattr(self, "_hw_busy", False):
            return
        self._hw_ts = now
        self._hw_busy = True
        threading.Thread(target=self._collect_hw, daemon=True).start()

    def _collect_hw(self):
        d = {}
        try:
            name, guid, _ = pcctl.power_scheme()
            d["plan"] = (name, guid)
            d["cap"] = pcctl.cpu_limit()
            w_on, w_msg, b_on, b_msg = pcctl.net_state()
            d["wifi"] = (w_on, w_msg)
            d["bt"] = (b_on, b_msg)
            d["num"] = pcctl.numlock_on()
            d["numdef"] = pcctl.numlock_default()
        except Exception as e:
            d["err"] = str(e)
        self._hw_busy = False
        self.hw_ready.emit(d)

    def _apply_hw_state(self, d):
        if d.get("err"):
            self.eng._add_log("硬件状态读取失败：%s" % d["err"])
            return
        name, guid = d.get("plan") or (None, None)
        if name:
            self.lbl_plan.setText("当前：%s" % name)
        for g, b in self._plan_btns.items():
            b.setChecked(bool(guid) and g in guid)
        cap = d.get("cap")
        if cap is not None:
            self.sl_cpu.blockSignals(True)
            self.sl_cpu.setValue(int(cap))
            self.sl_cpu.blockSignals(False)
            self.lbl_cpu_cap.setText("%d%%" % cap)
        w_on, w_msg = d.get("wifi") or (None, "")
        self._wifi_on = w_on
        self.lbl_wifi.setText("WiFi：%s" % w_msg)
        self.btn_wifi.setEnabled(w_on is not None)
        b_on, b_msg = d.get("bt") or (None, "")
        self._bt_on = b_on
        self.lbl_bt.setText("蓝牙：%s" % b_msg)
        self.btn_bt.setEnabled(b_on is not None)
        self._sync_net_btns()
        n_on = d.get("num")
        if n_on is not None:
            self.lbl_num.setText("小键盘（NumLock）：%s" % ("开" if n_on else "关"))
            self.sw_num.blockSignals(True)
            self.sw_num.setChecked(bool(n_on))
            self.sw_num.blockSignals(False)
        dflt = d.get("numdef")
        if dflt is not None:
            self.sw_numdef.setChecked(bool(dflt))

    # ================================================================ 鸡血 BIOS
    # ================================================================== 键盘灯效
    def _tab_keyboard(self):
        w = QWidget()
        self.kbd_page = w
        # 拖动滑杆时先攒着，停手 130ms 再下发，别把 HID 刷爆
        self._kb_dbt = QTimer(self)
        self._kb_dbt.setSingleShot(True)
        self._kb_dbt.setInterval(130)
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # ---------------------------------------------------------- 设备状态
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 12, 14, 12)
        c1.setSpacing(8)
        t1 = QLabel("键盘 · 联想极光 GK10 98W")
        t1.setObjectName("sectionTitle")
        c1.addWidget(t1)
        self.lbl_kb_model = QLabel("检测中…")
        self.lbl_kb_model.setObjectName("metric")
        c1.addWidget(self.lbl_kb_model)
        self.lbl_kb_conn = QLabel("连接方式：—")
        self.lbl_kb_conn.setObjectName("muted")
        c1.addWidget(self.lbl_kb_conn)
        self.lbl_kb_path = QLabel("灯效通道：—")
        self.lbl_kb_path.setObjectName("muted")
        self.lbl_kb_path.setWordWrap(True)
        c1.addWidget(self.lbl_kb_path)
        self.lbl_kb_state = QLabel("状态：未检测")
        self.lbl_kb_state.setObjectName("muted")
        c1.addWidget(self.lbl_kb_state)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.btn_kb_detect = QPushButton("重新检测")
        self.btn_kb_detect.setObjectName("ghost")
        self.btn_kb_detect.setCursor(Qt.PointingHandCursor)
        self.btn_kb_detect.clicked.connect(self._kb_reconnect)
        r1.addWidget(self.btn_kb_detect)
        btn_kb_sweep = QPushButton("按顺序扫 8 色")
        btn_kb_sweep.setObjectName("ghost")
        btn_kb_sweep.setCursor(Qt.PointingHandCursor)
        btn_kb_sweep.setToolTip("每隔 1.2 秒换一个色位，方便你记下键盘上第几格是红/绿/蓝")
        btn_kb_sweep.clicked.connect(self._kb_sweep_colors)
        r1.addWidget(btn_kb_sweep)
        r1.addStretch(1)
        c1.addLayout(r1)
        rk = QHBoxLayout()
        rk.setSpacing(9)
        self.sw_kb_keep = Switch(bool(self.kbd.state.get("keep", True)))
        self.sw_kb_keep.clicked.connect(self._kb_keep)
        rk.addWidget(self.sw_kb_keep)
        lbk = QLabel("保持灯效（定时重发，防止键盘自己回落到内置灯效）")
        lbk.setObjectName("muted")
        lbk.setWordWrap(True)
        rk.addWidget(lbk, 1)
        c1.addLayout(rk)
        rl = QHBoxLayout()
        rl.setSpacing(9)
        self.sw_kb_link = Switch(bool(self.kbd.state.get("linked", False)))
        self.sw_kb_link.clicked.connect(self._kb_link)
        rl.addWidget(self.sw_kb_link)
        lbl = QLabel("跟随主板 ARGB 主色（改主板颜色时键盘一起换色）")
        lbl.setObjectName("muted")
        lbl.setWordWrap(True)
        rl.addWidget(lbl, 1)
        c1.addLayout(rl)
        hint = QLabel("灯效指令直接从官方 Provider 里解出来的私有协议：20 种模式 × 8 个色位 × 4 档亮度 × 3 档速度。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        c1.addWidget(hint)
        c1.addStretch(1)
        h.addWidget(self._panel(c1), 1)

        # ---------------------------------------------------------- 20 种模式
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 12, 14, 12)
        c2.setSpacing(8)
        t2 = QLabel("灯效模式（20 种 · 中文名）")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)
        gp = QGridLayout()
        gp.setSpacing(6)
        self._kb_mode_btns = []
        names = self.kbd.state.get("mode_names") or kbmod.MODE_NAMES_DEFAULT
        for i in range(kbmod.MODE_COUNT):
            b = QPushButton(self._kb_mode_label(i))
            b.setObjectName("fmod")
            b.setCheckable(True)
            b.setFixedHeight(34)
            b.setMinimumWidth(58)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip("%02d · %s（编号与键盘固件对应，点一下就下发）"
                        % (i + 1, names[i] if i < len(names) else "灯效"))
            b.clicked.connect(lambda _c=False, k=i: self._kb_mode(k))
            gp.addWidget(b, i // 5, i % 5)
            self._kb_mode_btns.append(b)
        c2.addLayout(gp)
        rnm = QHBoxLayout()
        rnm.setSpacing(8)
        btn_rename = QPushButton("改模式名")
        btn_rename.setObjectName("ghost")
        btn_rename.setCursor(Qt.PointingHandCursor)
        btn_rename.setToolTip("官方名字已内置；按你实际看到的观感可以自己改")
        btn_rename.clicked.connect(self._kb_rename_modes)
        rnm.addWidget(btn_rename)
        rnm.addStretch(1)
        c2.addLayout(rnm)
        note = QLabel("20 个名字取自官方驱动（Lenovo Aurora）的 GK10 98 定义；编号与固件一致，观感不符可自行改。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        c2.addWidget(note)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 1)

        # ---------------------------------------------------------- 亮度 / 速度 / 色位
        c3 = QVBoxLayout()
        c3.setContentsMargins(14, 12, 14, 12)
        c3.setSpacing(9)
        t3 = QLabel("亮度 / 速度 / 色位")
        t3.setObjectName("sectionTitle")
        c3.addWidget(t3)

        rbr = QHBoxLayout()
        rbr.setSpacing(8)
        lbr = QLabel("亮度")
        lbr.setObjectName("muted")
        rbr.addWidget(lbr)
        self.sl_kb_bri = QSlider(Qt.Horizontal)
        self.sl_kb_bri.setRange(0, 100)
        self.sl_kb_bri.setValue(int(self.kbd.state.get("brightness", 100)))
        self.sl_kb_bri.valueChanged.connect(self._kb_bri_label)
        self.sl_kb_bri.sliderReleased.connect(
            lambda: self._kb_write(brightness=self.sl_kb_bri.value()))
        self.sl_kb_bri.valueChanged.connect(lambda _v: self._kb_dbt.start())
        rbr.addWidget(self.sl_kb_bri, 1)
        self.lbl_kb_bri = QLabel("—")
        self.lbl_kb_bri.setObjectName("fanMode")
        self.lbl_kb_bri.setFixedWidth(64)
        self.lbl_kb_bri.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rbr.addWidget(self.lbl_kb_bri)
        c3.addLayout(rbr)

        rsp = QHBoxLayout()
        rsp.setSpacing(8)
        lsp = QLabel("速度")
        lsp.setObjectName("muted")
        rsp.addWidget(lsp)
        self.sl_kb_speed = QSlider(Qt.Horizontal)
        self.sl_kb_speed.setRange(0, 100)
        self.sl_kb_speed.setValue(int(self.kbd.state.get("speed", 50)))
        self.sl_kb_speed.valueChanged.connect(self._kb_speed_label)
        self.sl_kb_speed.sliderReleased.connect(
            lambda: self._kb_write(speed=self.sl_kb_speed.value()))
        self.sl_kb_speed.valueChanged.connect(lambda _v: self._kb_dbt.start())
        rsp.addWidget(self.sl_kb_speed, 1)
        self.lbl_kb_speed = QLabel("—")
        self.lbl_kb_speed.setObjectName("fanMode")
        self.lbl_kb_speed.setFixedWidth(64)
        self.lbl_kb_speed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rsp.addWidget(self.lbl_kb_speed)
        c3.addLayout(rsp)

        self.lbl_kb_color = QLabel("色位（8 个固定色，点哪个都是即时下发）")
        self.lbl_kb_color.setObjectName("muted")
        c3.addWidget(self.lbl_kb_color)
        rc = QHBoxLayout()
        rc.setSpacing(7)
        self._kb_color_btns = []
        for i, hx in enumerate(kbmod.COLOR_SWATCH):
            b = QPushButton()
            b.setObjectName("swatch")
            b.setCheckable(True)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip("色位 %d" % (i + 1))
            b.clicked.connect(lambda _c=False, k=i: self._kb_color(k))
            rc.addWidget(b)
            self._kb_color_btns.append(b)
        rc.addStretch(1)
        c3.addLayout(rc)

        rpw = QHBoxLayout()
        rpw.setSpacing(8)
        btn_on = QPushButton("开灯")
        btn_on.setObjectName("primary")
        btn_on.setCursor(Qt.PointingHandCursor)
        btn_on.clicked.connect(lambda: self._kb_power(True))
        rpw.addWidget(btn_on)
        btn_off = QPushButton("关灯")
        btn_off.setObjectName("ghost")
        btn_off.setCursor(Qt.PointingHandCursor)
        btn_off.clicked.connect(lambda: self._kb_power(False))
        rpw.addWidget(btn_off)
        btn_cal = QPushButton("色位校准")
        btn_cal.setObjectName("ghost")
        btn_cal.setCursor(Qt.PointingHandCursor)
        btn_cal.setToolTip("依次点亮 8 个色位，你看见什么颜色就点哪个格子，程序把真顺序记下来")
        btn_cal.clicked.connect(self._kb_cal_start)
        rpw.addWidget(btn_cal)
        rpw.addStretch(1)
        c3.addLayout(rpw)

        # 软件动效（自己发帧做的动效，不依赖固件模式）
        rfx = QHBoxLayout()
        rfx.setSpacing(6)
        lfx = QLabel("软件动效")
        lfx.setObjectName("muted")
        rfx.addWidget(lfx)
        self._kb_fx_btns = {}
        for key, label, tip in [("breath", "呼吸", "软件驱动亮度呼吸（不占用固件模式）"),
                                ("rainbow", "彩虹流转", "8 个色位循环切换"),
                                ("strobe", "频闪", "亮/灭快速交替"),
                                ("jump", "跳色", "按固定步长切色位"),
                                ("fade", "渐变", "亮度平滑渐入渐出，同时色位缓慢循环"),
                                ("pulse", "心跳", "双拍脉冲，模仿心跳节奏")]:
            b = QPushButton(label)
            b.setObjectName("ghost")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, k=key: self._kb_fx_start(k))
            rfx.addWidget(b)
            self._kb_fx_btns[key] = b
        bfx_stop = QPushButton("停止")
        bfx_stop.setObjectName("ghost")
        bfx_stop.setCursor(Qt.PointingHandCursor)
        bfx_stop.clicked.connect(self._kb_fx_stop)
        rfx.addWidget(bfx_stop)
        rfx.addStretch(1)
        c3.addLayout(rfx)

        self._fx_timer = QTimer(self)
        self._fx_timer.setInterval(220)
        self._fx_timer.timeout.connect(self._kb_fx_tick)
        self._fx = None

        # 校准答案条（平时隐藏，进入校准才出现）
        self._kb_ans_box = QWidget()
        va = QVBoxLayout(self._kb_ans_box)
        va.setContentsMargins(0, 0, 0, 0)
        va.setSpacing(4)
        la = QLabel("这一格在键盘上是哪种颜色？")
        la.setObjectName("muted")
        va.addWidget(la)
        ra = QHBoxLayout()
        ra.setSpacing(6)
        self._kb_ans_btns = []
        for i, hx in enumerate(kbmod.CAL_COLORS):
            b = QPushButton()
            b.setObjectName("swatch")
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip(kbmod.CAL_NAMES[i])
            b.setStyleSheet(self._swatch_css(hx, 30))
            b.clicked.connect(lambda _c=False, k=i: self._kb_cal_answer(k))
            ra.addWidget(b)
            self._kb_ans_btns.append(b)
        ra.addStretch(1)
        va.addLayout(ra)
        self._kb_ans_box.setVisible(False)
        c3.addWidget(self._kb_ans_box)

        self.lbl_kb_msg = QLabel("—")
        self.lbl_kb_msg.setObjectName("muted")
        self.lbl_kb_msg.setWordWrap(True)
        c3.addWidget(self.lbl_kb_msg)
        c3.addStretch(1)
        h.addWidget(self._panel(c3), 1)

        # 初始化显示
        self._kb_bri_label(self.sl_kb_bri.value())
        self._kb_speed_label(self.sl_kb_speed.value())
        self._kb_sync_ui()
        QTimer.singleShot(400, self._kb_autodetect)
        return w

    # ================================================== 鼠标（SMAILWOLF M3）页
    def _tab_mouse(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)
        self._ms_busy = False
        self._ms_action_btns = []

        # ------------------------------------------------------ 一、设备状态
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 12, 14, 12)
        c1.setSpacing(8)
        t1 = QLabel("鼠标 · SMAILWOLF M3")
        t1.setObjectName("sectionTitle")
        c1.addWidget(t1)
        self.lbl_ms_model = QLabel("检测中…")
        self.lbl_ms_model.setObjectName("metric")
        c1.addWidget(self.lbl_ms_model)
        self.lbl_ms_conn = QLabel("通道：VID_A8A5 / PID_2255 / Page 0xFF01")
        self.lbl_ms_conn.setObjectName("muted")
        self.lbl_ms_conn.setWordWrap(True)
        c1.addWidget(self.lbl_ms_conn)
        self.lbl_ms_ver = QLabel("固件：—")
        self.lbl_ms_ver.setObjectName("muted")
        c1.addWidget(self.lbl_ms_ver)
        self.lbl_ms_batt = QLabel("电量：—")
        self.lbl_ms_batt.setObjectName("fanMode")
        c1.addWidget(self.lbl_ms_batt)
        self.lbl_ms_state = QLabel("状态：未检测")
        self.lbl_ms_state.setObjectName("muted")
        self.lbl_ms_state.setWordWrap(True)
        c1.addWidget(self.lbl_ms_state)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        b_det = QPushButton("重新检测")
        b_det.setObjectName("ghost")
        b_det.setCursor(Qt.PointingHandCursor)
        b_det.clicked.connect(self._ms_reconnect)
        r1.addWidget(b_det)
        b_read = QPushButton("读取鼠标配置")
        b_read.setObjectName("primary")
        b_read.setCursor(Qt.PointingHandCursor)
        b_read.setToolTip("从鼠标里读出固件版本、电量、DPI、回报率、灯效等当前值")
        b_read.clicked.connect(self._ms_read_all)
        r1.addWidget(b_read)
        self._ms_action_btns.append(b_read)
        r1.addStretch(1)
        c1.addLayout(r1)

        b_free = QPushButton("释放鼠标通道（给官方驱动让路）")
        b_free.setObjectName("ghost")
        b_free.setCursor(Qt.PointingHandCursor)
        b_free.setToolTip("本程序独占鼠标厂商通道时，官方 SMAILWOLF 软件会打不开设备；"
                         "点这里临时释放，用完再点「重新检测」接回来")
        b_free.clicked.connect(self._ms_release)
        c1.addWidget(b_free)

        note = QLabel("协议是从官方网页驱动（f0a91.yjx2012.com）的 WebHID 报文里解出来的私有协议："
                      "64 字节帧、report id 0xF0，命令 0x0E/0x0F 读写配置、0x21 设灯效、0x30 读电量。"
                      "不装官方软件也能调。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        c1.addWidget(note)
        c1.addStretch(1)
        h.addWidget(self._panel(c1), 1)

        # ------------------------------------------------------ 二、DPI 与回报率
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 12, 14, 12)
        c2.setSpacing(8)
        t2 = QLabel("DPI 档位（6 档 · 写进鼠标本体）")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)
        gd = QGridLayout()
        gd.setSpacing(6)
        self._ms_dpi_spins = []
        self._ms_dpi_btns = []
        for i in range(6):
            cell = QHBoxLayout()
            cell.setSpacing(5)
            lb = QLabel("%d" % (i + 1))
            lb.setObjectName("muted")
            lb.setFixedWidth(12)
            sp = QSpinBox()
            sp.setRange(50, 50000)
            sp.setSingleStep(50)
            sp.setFixedSize(78, 26)
            sp.setToolTip("第 %d 档 DPI 数值（50–50000，写进去才生效）" % (i + 1))
            b = QPushButton("切")
            b.setObjectName("fmod")
            b.setCheckable(True)
            b.setFixedSize(38, 26)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setToolTip("把当前 DPI 切到第 %d 档" % (i + 1))
            b.clicked.connect(lambda _c=False, k=i: self._ms_set_dpi_index(k))
            cell.addWidget(lb)
            cell.addWidget(sp)
            cell.addWidget(b)
            gd.addLayout(cell, i % 3, i // 3)
            self._ms_dpi_btns.append(b)
            self._ms_dpi_spins.append(sp)
            self._ms_action_btns.append(b)
        c2.addLayout(gd)
        rw = QHBoxLayout()
        rw.setSpacing(8)
        b_write = QPushButton("写入 6 档 DPI 数值")
        b_write.setObjectName("ghost")
        b_write.setFixedHeight(28)
        b_write.setCursor(Qt.PointingHandCursor)
        b_write.setToolTip("把左边 6 个输入框里的数值整组写进鼠标（6 档一起写）")
        b_write.clicked.connect(self._ms_write_dpi)
        rw.addWidget(b_write)
        rw.addStretch(1)
        c2.addLayout(rw)
        self._ms_action_btns.append(b_write)

        t3 = QLabel("回报率")
        t3.setObjectName("sectionTitle")
        c2.addWidget(t3)
        rr = QHBoxLayout()
        rr.setSpacing(7)
        self._ms_rate_btns = []
        for i, hz in enumerate(msmod.RATE_LIST):
            b = QPushButton("%d Hz" % hz)
            b.setObjectName("fmod")
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=i: self._ms_set_rate(k))
            rr.addWidget(b)
            self._ms_rate_btns.append(b)
            self._ms_action_btns.append(b)
        rr.addStretch(1)
        c2.addLayout(rr)
        tip_rate = QLabel("官方只开放 125 / 250 / 500 / 1000 四档；2.4G 接收器下高回报率更耗电。")
        tip_rate.setObjectName("muted")
        tip_rate.setWordWrap(True)
        c2.addWidget(tip_rate)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 1)

        # ------------------------------------------------------ 三、灯效与手感
        c3 = QVBoxLayout()
        c3.setContentsMargins(14, 12, 14, 12)
        c3.setSpacing(9)
        t4 = QLabel("灯效模式（7 种 · 官方定义）")
        t4.setObjectName("sectionTitle")
        c3.addWidget(t4)
        gl = QGridLayout()
        gl.setSpacing(6)
        self._ms_light_btns = []
        for i, name in enumerate(msmod.LIGHT_NAMES):
            b = QPushButton("%d %s" % (i, name))
            b.setObjectName("fmod")
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, k=i: self._ms_set_light(k))
            gl.addWidget(b, i // 4, i % 4)
            self._ms_light_btns.append(b)
            self._ms_action_btns.append(b)
        c3.addLayout(gl)

        def spin_row(label, lo, hi, tip):
            row = QHBoxLayout()
            row.setSpacing(6)
            lb = QLabel(label)
            lb.setObjectName("muted")
            lb.setFixedWidth(56)
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setFixedSize(56, 28)
            sp.setToolTip(tip)
            bt = QPushButton("应用")
            bt.setObjectName("ghost")
            bt.setFixedSize(44, 28)
            bt.setCursor(Qt.PointingHandCursor)
            row.addWidget(lb)
            row.addWidget(sp)
            row.addWidget(bt)
            row.addStretch(1)
            c3.addLayout(row)
            self._ms_action_btns.append(bt)
            return sp, bt

        rs = QHBoxLayout()
        rs.setSpacing(6)
        lb_sleep = QLabel("睡眠灯效")
        lb_sleep.setObjectName("muted")
        lb_sleep.setFixedWidth(56)
        self.sp_ms_sleep = QSpinBox()
        self.sp_ms_sleep.setRange(0, 10)
        self.sp_ms_sleep.setFixedSize(56, 28)
        self.sp_ms_sleep.setToolTip("鼠标休眠时的灯效强度（0 = 休眠关灯）")
        bt_sleep = QPushButton("应用")
        bt_sleep.setObjectName("ghost")
        bt_sleep.setFixedSize(44, 28)
        bt_sleep.setCursor(Qt.PointingHandCursor)
        bt_sleep.clicked.connect(lambda: self._ms_apply_sleep(self.sp_ms_sleep.value()))
        rs.addWidget(lb_sleep)
        rs.addWidget(self.sp_ms_sleep)
        rs.addWidget(bt_sleep)
        rs.addSpacing(10)
        self.sw_ms_move = Switch(bool(self.mouse.state.get("move_light", 0)))
        self.sw_ms_move.setToolTip("鼠标一动才亮，静止熄灯")
        self.sw_ms_move.clicked.connect(self._ms_toggle_movelight)
        rs.addWidget(self.sw_ms_move)
        lbm = QLabel("移动点灯")
        lbm.setObjectName("muted")
        rs.addWidget(lbm)
        rs.addStretch(1)
        c3.addLayout(rs)
        self._ms_action_btns.append(bt_sleep)

        ro = QHBoxLayout()
        ro.setSpacing(8)
        b_off = QPushButton("一键关灯")
        b_off.setObjectName("primary")
        b_off.setFixedHeight(28)
        b_off.setCursor(Qt.PointingHandCursor)
        b_off.clicked.connect(lambda: self._ms_set_light(6))
        ro.addWidget(b_off)
        b_on = QPushButton("恢复上次灯效")
        b_on.setObjectName("ghost")
        b_on.setFixedHeight(28)
        b_on.setCursor(Qt.PointingHandCursor)
        b_on.setToolTip("回到上次你选的灯效模式")
        b_on.clicked.connect(self._ms_light_restore)
        ro.addWidget(b_on)
        ro.addStretch(1)
        c3.addLayout(ro)
        self._ms_action_btns.extend([b_off, b_on])

        self.lbl_ms_msg = QLabel("—")
        self.lbl_ms_msg.setObjectName("muted")
        self.lbl_ms_msg.setWordWrap(True)
        c3.addWidget(self.lbl_ms_msg)
        tip_lod = QLabel("固件实测：LOD / 按键响应 / 高速模式写入不生效，故不放这些空开关。")
        tip_lod.setObjectName("muted")
        tip_lod.setWordWrap(True)
        c3.addWidget(tip_lod)
        c3.addStretch(1)
        h.addWidget(self._panel(c3), 1)

        self._ms_timer = QTimer(self)
        self._ms_timer.setInterval(4000)
        self._ms_timer.timeout.connect(lambda: self._ms_refresh(False))
        self._ms_sync_ui()
        QTimer.singleShot(500, self._ms_read_all)
        return w

    # ---------------------------------------------------------------- 鼠标动作
    def _ms_run(self, fn, ok_msg):
        """鼠标读写都走 HID，会阻塞几百毫秒，丢到后台线程里做"""
        if self._ms_busy:
            self.lbl_ms_msg.setText("上一个操作还在进行，稍等…")
            return
        self._ms_busy = True
        for b in self._ms_action_btns:
            b.setEnabled(False)
        self.lbl_ms_msg.setText("下发中…")

        def work():
            try:
                ok = fn()
                msg = ok_msg if ok else ("失败：%s" % (self.mouse.last_error or "鼠标无应答"))
            except Exception as e:
                msg = "异常：%s" % e
            self.ms_done.emit(msg)

        threading.Thread(target=work, daemon=True).start()

    def _ms_on_done(self, msg):
        self._ms_busy = False
        for b in self._ms_action_btns:
            b.setEnabled(True)
        self.lbl_ms_msg.setText("%s · %s" % (msg, time.strftime("%H:%M:%S")))
        self._ms_sync_ui()

    def _ms_reconnect(self):
        self.mouse.close()
        self.lbl_ms_msg.setText("重新连接中…")
        QTimer.singleShot(120, self._ms_read_all)

    def _ms_read_all(self):
        def fn():
            if not self.mouse.open():
                return False
            self.mouse.read_version()
            self.mouse.read_info()
            self.mouse.read_battery()
            self.mouse.read_config()
            return True
        self._ms_run(fn, "已读取鼠标配置")

    def _ms_refresh(self, read=False):
        if self._ms_busy:
            return
        if read:
            self._ms_read_all()
            return
        self._ms_sync_ui()

    def _ms_release(self):
        self.mouse.close()
        self.lbl_ms_state.setText("状态：已释放通道（官方驱动可以打开了）")
        self.lbl_ms_model.setText("通道已释放")
        self.lbl_ms_msg.setText("已释放 · 点「重新检测」可再次接管")

    def _ms_sync_ui(self):
        info = self.mouse.info()
        st = self.mouse.state
        self.lbl_ms_model.setText("%s · %s" % (info["model"], info["serial"]
                                               if info["serial"] != "—" else "未读取"))
        self.lbl_ms_ver.setText("固件：%s" % info["version"])
        if info["battery"] is None:
            self.lbl_ms_batt.setText("电量：—")
        else:
            self.lbl_ms_batt.setText("电量：%d%%%s" % (info["battery"],
                                                     "（充电中）" if info["charge"] else ""))
        if info["connected"]:
            self.lbl_ms_state.setText("状态：已接管厂商通道，可读写")
        elif info["found"]:
            self.lbl_ms_state.setText("状态：已发现接收器，尚未写入（点「读取鼠标配置」）")
        else:
            self.lbl_ms_state.setText("状态：%s" % (info["error"] or "未发现鼠标接收器"))
        dpi = list(info["dpi"] or [])
        for i, sp in enumerate(self._ms_dpi_spins):
            v = dpi[i] if i < len(dpi) else 1000
            if not sp.hasFocus():
                sp.setValue(int(v))
            sp.setEnabled(not self._ms_busy)
        for i, b in enumerate(self._ms_dpi_btns):
            b.setChecked(i == info["dpi_index"])
        for i, b in enumerate(self._ms_rate_btns):
            b.setChecked(i == int(st.get("rate_index", 3)))
        for i, b in enumerate(self._ms_light_btns):
            b.setChecked(i == int(st.get("light_mode", 0)))
        if not self.sp_ms_sleep.hasFocus():
            self.sp_ms_sleep.setValue(int(st.get("sleep_light", 10) or 0))
        sw = getattr(self, "sw_ms_move", None)
        if sw is not None:
            sw.setChecked(bool(int(st.get("move_light", 0) or 0)))

    # 各动作 -------------------------------------------------------------
    def _ms_set_dpi_index(self, idx):
        # 先亮起来给反馈，写失败再刷新回真实状态
        for i, b in enumerate(self._ms_dpi_btns):
            b.setChecked(i == idx)
        self._ms_run(lambda: self.mouse.set_dpi_index(idx), "已切到第 %d 档" % (idx + 1))

    def _ms_write_dpi(self):
        vals = [sp.value() for sp in self._ms_dpi_spins]

        def fn():
            if not self.mouse.open():
                return False
            ok = True
            for i, v in enumerate(vals):
                ok = self.mouse.set_dpi_value(i, v) and ok
            return ok
        self._ms_run(fn, "6 档 DPI 已写入")

    def _ms_set_rate(self, idx):
        self._ms_run(lambda: self.mouse.set_rate(idx), "回报率已设为 %d Hz" % msmod.RATE_LIST[idx])

    def _ms_set_light(self, mode):
        cur = int(self.mouse.state.get("light_mode", 0) or 0)
        if cur != 6:
            self._ms_light_last = cur        # 记住关灯前用的灯效
        for i, b in enumerate(self._ms_light_btns):
            b.setChecked(i == mode)
        self._ms_run(lambda: self.mouse.set_light_mode(mode), "灯效已切到「%s」" % msmod.LIGHT_NAMES[mode])

    def _ms_light_restore(self):
        mode = int(getattr(self, "_ms_light_last", 0) or 0)
        if mode >= len(msmod.LIGHT_NAMES) or mode == 6:
            mode = 0
        self._ms_set_light(mode)

    def _ms_apply_sleep(self, v):
        self._ms_run(lambda: self.mouse.set_sleep_light(v), "睡眠灯效已设为 %d" % v)

    def _ms_apply_key(self, v):
        self._ms_run(lambda: self.mouse.set_key_respond(v), "按键响应已设为 %d" % v)

    def _ms_apply_lod(self, v):
        self._ms_run(lambda: self.mouse.set_lod(v), "静默高度已设为 %d" % v)

    def _ms_toggle_highspeed(self, checked):
        self._ms_run(lambda: self.mouse.set_highspeed(checked),
                     "高速模式已%s" % ("开启" if checked else "关闭"))

    def _ms_toggle_movelight(self, checked):
        self._ms_run(lambda: self.mouse.set_move_light(checked),
                     "移动点灯已%s" % ("开启" if checked else "关闭"))

    # 托盘用 -------------------------------------------------------------
    def mouse_light_names(self):
        return list(msmod.LIGHT_NAMES)

    def mouse_rate_list(self):
        return list(msmod.RATE_LIST)

    def tray_ms_light(self, mode):
        self.mouse.set_light_mode(mode)
        self._ms_sync_ui()

    def tray_ms_rate(self, idx):
        self.mouse.set_rate(idx)
        self._ms_sync_ui()

    def tray_ms_dpi(self, idx):
        self.mouse.set_dpi_index(idx)
        self._ms_sync_ui()

    def _kb_autodetect(self):
        """进界面时悄悄连一次，连不上不打扰"""
        if self.kbd.dev is None:
            self.kbd.open()
        self._kb_sync_ui()

    def _kb_sync_ui(self):
        info = self.kbd.info()
        if info["found"]:
            self.lbl_kb_model.setText("GK10 98W")
            self.lbl_kb_model.setToolTip("系统上报名：%s" % info["product"])
            self.lbl_kb_path.setText("HID 通道：VID_1A2C / PID_%04X / Page 0xFF02"
                                    % int(info.get("pid") or 0))
            self.lbl_kb_path.setToolTip(info["path"] or "")
        else:
            self.lbl_kb_model.setText("未检测到键盘")
            self.lbl_kb_path.setText("HID 通道：—")
        self.lbl_kb_conn.setText("连接方式：%s" % info["conn"])
        if info["connected"]:
            st = "状态：已连接，可下发灯效"
            if info["last_ok"]:
                st += " · 上次下发 %s" % time.strftime("%H:%M:%S", time.localtime(info["last_ok"]))
            self.lbl_kb_state.setText(st)
        elif info["found"]:
            self.lbl_kb_state.setText("状态：已发现设备，等待首次写入")
        else:
            self.lbl_kb_state.setText("状态：%s" % (info["error"] or "未发现键盘"))
        for i, b in enumerate(self._kb_mode_btns):
            b.setChecked(i == info["mode"])
        for i, b in enumerate(self._kb_color_btns):
            b.setChecked(i == info["color"])
        self._kb_paint_chips(info.get("palette"))
        if getattr(self, "_cal", None) is None:
            self.lbl_kb_color.setText(
                "色位（已按真机实测颜色排好，点哪个都是即时下发）" if info.get("calibrated")
                else "色位（色块顺序还没校准，点下面「色位校准」对一次就准了）")
        self.sw_kb_keep.setChecked(bool(info["keep"]))
        self.sw_kb_link.setChecked(bool(info["linked"]))
        # 滑杆跟着真实状态走（正在拖的时候别抢）
        if not self.sl_kb_bri.isSliderDown() and self.sl_kb_bri.value() != int(info["brightness"]):
            v = int(info["brightness"])
            self.sl_kb_bri.blockSignals(True)
            self.sl_kb_bri.setValue(v)
            self.sl_kb_bri.blockSignals(False)
            self._kb_bri_label(v)
        if not self.sl_kb_speed.isSliderDown() and self.sl_kb_speed.value() != int(info["speed"]):
            v2 = int(info["speed"])
            self.sl_kb_speed.blockSignals(True)
            self.sl_kb_speed.setValue(v2)
            self.sl_kb_speed.blockSignals(False)
            self._kb_speed_label(v2)
        if info["error"]:
            self.lbl_kb_msg.setText("上次错误：%s" % info["error"])

    def _kb_bri_label(self, v):
        lv = max(0, min(3, int(round(v / 33.0))))
        self.lbl_kb_bri.setText("%d%% · %d/4" % (v, lv + 1))

    def _kb_speed_label(self, v):
        lv = max(0, min(2, int(round(v / 50.0))))
        self.lbl_kb_speed.setText("%d%% · %d/3" % (v, lv + 1))

    def _kb_write(self, **kw):
        self._kb_fx_stop(silent=True)
        ok = self.kbd.set_light(**kw)
        if ok:
            self.lbl_kb_msg.setText("已下发 · %s" % time.strftime("%H:%M:%S"))
        else:
            self.lbl_kb_msg.setText("下发失败：%s" % (self.kbd.last_error or "键盘无应答"))
        self._kb_sync_ui()
        return ok

    def _kb_mode(self, idx):
        self._kb_write(mode=idx)

    def _kb_color(self, idx):
        if getattr(self, "_cal", None):
            # 校准模式下，点色块 = 「刚才那个是这种颜色」
            self._cal["res"].append(kbmod.COLOR_SWATCH[idx])
            self._cal["i"] += 1
            self._kb_cal_step()
            return
        self._kb_write(color=idx)

    def _kb_power(self, on):
        self._kb_fx_stop(silent=True)
        ok = self.kbd.power(on)
        if ok and on:
            # 开灯后把滑杆同步回实际亮度（避免界面上和灯不一致）
            v = int(self.kbd.state.get("brightness", 100))
            self.sl_kb_bri.blockSignals(True)
            self.sl_kb_bri.setValue(v)
            self.sl_kb_bri.blockSignals(False)
            self._kb_bri_label(v)
        self.lbl_kb_msg.setText(("已开灯 · " if on else "已关灯 · ") + time.strftime("%H:%M:%S")
                                if ok else "操作失败：%s" % (self.kbd.last_error or "键盘无应答"))
        self._kb_sync_ui()

    def _kb_keep(self):
        self.kbd.state["keep"] = bool(self.sw_kb_keep.isChecked())
        self.kbd.save()
        self.lbl_kb_msg.setText("保持灯效：%s" % ("开" if self.kbd.state["keep"] else "关"))

    def _kb_link(self):
        self.kbd.state["linked"] = bool(self.sw_kb_link.isChecked())
        self.kbd.save()
        self.lbl_kb_msg.setText("跟随主板主色：%s" % ("开" if self.kbd.state["linked"] else "关"))

    def _swatch_css(self, hx, size=34):
        """色块样式；彩色循环那格用彩虹渐变"""
        if hx == kbmod.RAINBOW:
            bg = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff3b3b,"
                  " stop:0.17 #ffd93b, stop:0.34 #5ce65c, stop:0.51 #3bc9ff,"
                  " stop:0.68 #3b6bff, stop:0.85 #b03bff, stop:1 #ff3b8f)")
        else:
            bg = hx
        return ("QPushButton#swatch { background: %s; border: 1px solid rgba(255,255,255,0.18);"
                " border-radius: 4px; }"
                "QPushButton#swatch:hover { border: 1px solid rgba(255,255,255,0.55); }"
                "QPushButton#swatch:checked { border: 2px solid #ffffff; }" % bg)

    def _kb_paint_chips(self, palette=None):
        """按（校准后的）色表重画 8 个色块"""
        pal = palette or (self.kbd.state.get("palette") or kbmod.COLOR_SWATCH)
        for i, b in enumerate(getattr(self, "_kb_color_btns", [])):
            hx = pal[i] if i < len(pal) else "#888888"
            if hx == kbmod.RAINBOW:
                name = "彩色（循环）"
            elif hx in kbmod.CAL_COLORS:
                name = kbmod.CAL_NAMES[kbmod.CAL_COLORS.index(hx)]
            else:
                name = "未知"
            b.setStyleSheet(self._swatch_css(hx))
            b.setToolTip("色位 %d · %s" % (i + 1, name))

    def _kb_mode_label(self, i):
        return "%02d %s" % (i + 1, self.kbd.mode_name(i)[:5])

    def _kb_fx_start(self, kind):
        """软件动效：自己按定时器发帧，做出固件里没有的节奏"""
        self._fx = {"kind": kind, "i": 0}
        intervals = {"breath": 300, "rainbow": 260, "strobe": 160, "jump": 380,
                     "fade": 200, "pulse": 220}
        self._fx_timer.setInterval(intervals.get(kind, 260))
        self._fx_timer.start()
        for k, b in getattr(self, "_kb_fx_btns", {}).items():
            b.setChecked(k == kind)
        btn = getattr(self, "_kb_fx_btns", {}).get(kind)
        self.lbl_kb_msg.setText("软件动效运行中：%s（点「停止」或任意手动操作会结束）"
                                % (btn.text() if btn else kind))
        self._kb_fx_tick()

    def _kb_fx_stop(self, silent=False):
        if getattr(self, "_fx_timer", None) is not None:
            self._fx_timer.stop()
        self._fx = None
        for b in getattr(self, "_kb_fx_btns", {}).values():
            b.setChecked(False)
        if not silent:
            self.lbl_kb_msg.setText("软件动效已停止")

    def _kb_fx_tick(self):
        f = getattr(self, "_fx", None)
        if not f:
            return
        kind = f["kind"]
        i = f["i"]
        f["i"] = i + 1
        if kind == "breath":
            steps = [100, 80, 60, 40, 20, 40, 60, 80]
            self.kbd.set_light(brightness=steps[i % len(steps)])
        elif kind == "rainbow":
            self.kbd.set_light(color=i % kbmod.COLOR_COUNT, brightness=100)
        elif kind == "strobe":
            self.kbd.set_light(brightness=100 if i % 2 == 0 else 0)
        elif kind == "jump":
            self.kbd.set_light(color=(i * 3 + 1) % kbmod.COLOR_COUNT, brightness=100)
        elif kind == "fade":
            bri = 100 - (i % 10) * 10
            kelvin = (i // 4) % kbmod.COLOR_COUNT
            self.kbd.set_light(color=kelvin, brightness=max(20, bri))
        elif kind == "pulse":
            steps = [100, 40, 90, 20, 60, 20]
            self.kbd.set_light(brightness=steps[i % len(steps)])

    def _kb_rename_modes(self):
        """改 20 个模式的中文名"""
        dlg = QDialog(self)
        dlg.setWindowTitle("改模式名")
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        tip = QLabel("名字只是显示用；官方名字已填好，按你在键盘上看到的实际效果改，留空自动回填。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        grid = QGridLayout()
        grid.setSpacing(6)
        eds = []
        for i in range(kbmod.MODE_COUNT):
            e = QLineEdit(self.kbd.mode_name(i))
            e.setMaxLength(12)
            e.setFixedHeight(30)
            eds.append(e)
            grid.addWidget(QLabel("%02d" % (i + 1)), i % 10, (i // 10) * 2)
            grid.addWidget(e, i % 10, (i // 10) * 2 + 1)
        lay.addLayout(grid)
        r = QHBoxLayout()
        r.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(dlg.reject)
        r.addWidget(cancel)
        ok = QPushButton("保存")
        ok.setObjectName("primary")
        r.addWidget(ok)
        lay.addLayout(r)

        def save():
            self.kbd.set_mode_names([e.text() for e in eds])
            for i, b in enumerate(self._kb_mode_btns):
                b.setText(self._kb_mode_label(i))
                b.setToolTip("%02d · %s" % (i + 1, self.kbd.mode_name(i)))
            self.lbl_kb_msg.setText("模式名已保存")
            dlg.accept()

        ok.clicked.connect(save)
        dlg.exec()

    def _kb_cal_answer(self, idx):
        c = getattr(self, "_cal", None)
        if not c:
            return
        c["res"].append(kbmod.CAL_COLORS[idx])
        c["i"] += 1
        self._kb_cal_step()

    def _kb_cal_start(self):
        """色位校准：依次点亮 8 个色位，用户点下方答案条来给出真顺序"""
        self._cal = {"i": 0, "res": []}
        if hasattr(self, "_kb_ans_box"):
            self._kb_ans_box.setVisible(True)
        self._kb_cal_step()

    def _kb_cal_step(self):
        c = getattr(self, "_cal", None)
        if not c:
            return
        if c["i"] >= kbmod.COLOR_COUNT:
            self.kbd.set_palette(c["res"])
            self._cal = None
            if hasattr(self, "_kb_ans_box"):
                self._kb_ans_box.setVisible(False)
            self._kb_paint_chips()
            self.lbl_kb_color.setText("色位（已按真机实测颜色排好，点哪个都是即时下发）")
            self.lbl_kb_msg.setText("校准完成：8 个色位已对齐，保存在 keyboard.json")
            self._kb_sync_ui()
            return
        i = c["i"]
        self.lbl_kb_color.setText("校准 %d/8：看键盘现在是什么颜色，点下面同色格子"
                                  % (i + 1))
        self.lbl_kb_msg.setText("正在点亮色位 %d…（键盘亮什么色就点下面答案条里对应的一格；流动彩色点「彩色」）"
                                % (i + 1))
        if not self.kbd.set_light(color=i, brightness=100):
            self._cal = None
            self.lbl_kb_msg.setText("校准中断：%s" % (self.kbd.last_error or "键盘无应答"))
            self._kb_sync_ui()

    def _kb_reconnect(self):
        self.kbd.close()
        ok = self.kbd.open()
        self.lbl_kb_msg.setText("已重新检测：%s" % ("成功" if ok else (self.kbd.last_error or "失败")))
        self._kb_sync_ui()

    def _kb_sweep_colors(self):
        """每隔 1.2 秒切一个色位，方便肉眼确认色序"""
        if getattr(self, "_kb_sweep", None):
            return
        self._kb_sweep = {"i": 0}

        def step():
            s = self._kb_sweep
            if s is None or s["i"] >= kbmod.COLOR_COUNT:
                self._kb_sweep = None
                t.stop()
                self.lbl_kb_msg.setText("扫色结束：请记下键盘上第几个是红/绿/蓝")
                return
            self._kb_write(color=s["i"])
            s["i"] += 1

        t = QTimer(self)
        t.timeout.connect(step)
        t.start(1200)
        self._kb_sweep["timer"] = t
        step()

    def _kb_keepalive(self):
        try:
            self.kbd.keepalive()
        except Exception:
            pass

    def _kb_follow_master(self):
        """主板主亮度/主色变化时，把键盘也跟着调一下"""
        if not self.kbd.state.get("linked"):
            return
        try:
            bri = int(self.eng.master.get("brightness", 100))
            self.kbd.set_light(brightness=bri)
        except Exception:
            pass

    def _tab_jixue(self):
        """E5 v3 全核睿频解锁：官方包校验 + 一键铺 U 盘刷写盘 + 跑分对比

        本页不刷固件，刷写由用户从 U 盘启动 EFI Shell 完成（见右侧四步）。
        """
        self._jx = {"pkg": {}, "bench": None, "busy": False}

        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # ------------------------------------------------------- 左：平台与操作
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 10, 14, 10)
        c1.setSpacing(6)

        rowt = QHBoxLayout()
        t1 = QLabel("鸡血 BIOS · 全核睿频解锁")
        t1.setObjectName("sectionTitle")
        rowt.addWidget(t1)
        rowt.addStretch(1)
        self.lbl_jx_state = QLabel("待跑分确认")
        self.lbl_jx_state.setObjectName("pill")
        rowt.addWidget(self.lbl_jx_state)
        c1.addLayout(rowt)

        self.lbl_jx_plat = QLabel("平台：读取中…")
        self.lbl_jx_plat.setObjectName("mono")
        self.lbl_jx_plat.setWordWrap(True)
        c1.addWidget(self.lbl_jx_plat)

        self.lbl_jx_pkg = QLabel("官方包：校验中…")
        self.lbl_jx_pkg.setObjectName("muted")
        self.lbl_jx_pkg.setWordWrap(True)
        c1.addWidget(self.lbl_jx_pkg)

        rowg = QHBoxLayout()
        rowg.setSpacing(10)
        self.lbl_jx_gain = QLabel("全核 2400 MHz  →  3100 MHz")
        self.lbl_jx_gain.setObjectName("metric")
        rowg.addWidget(self.lbl_jx_gain)
        lab_gain = QLabel("理论 +29%，实际看散热与功耗墙")
        lab_gain.setObjectName("muted")
        rowg.addWidget(lab_gain)
        rowg.addStretch(1)
        c1.addLayout(rowg)

        rowu = QHBoxLayout()
        rowu.setSpacing(7)
        self.cmb_jx_usb = QComboBox()
        self.cmb_jx_usb.setMinimumWidth(210)
        self.cmb_jx_usb.setToolTip("插上 FAT32 的 U 盘后点「刷新」")
        rowu.addWidget(self.cmb_jx_usb)
        btn_rf = QPushButton("刷新")
        btn_rf.setObjectName("ghost")
        btn_rf.setCursor(Qt.PointingHandCursor)
        btn_rf.setToolTip("重新扫描可移动磁盘")
        btn_rf.clicked.connect(self._jx_scan_usb)
        rowu.addWidget(btn_rf)
        self.btn_jx_jixue = QPushButton("写入鸡血包")
        self.btn_jx_jixue.setObjectName("primary")
        self.btn_jx_jixue.setCursor(Qt.PointingHandCursor)
        self.btn_jx_jixue.setToolTip("把官方鸡血 BIOS 的 U 盘刷写包铺到 U 盘")
        self.btn_jx_jixue.clicked.connect(lambda: self._jx_write("jixue"))
        rowu.addWidget(self.btn_jx_jixue)
        self.btn_jx_stock = QPushButton("写入原版包")
        self.btn_jx_stock.setObjectName("seg")
        self.btn_jx_stock.setCursor(Qt.PointingHandCursor)
        self.btn_jx_stock.setToolTip("铺原厂 BIOS，用于回滚")
        self.btn_jx_stock.clicked.connect(lambda: self._jx_write("stock"))
        rowu.addWidget(self.btn_jx_stock)
        rowu.addStretch(1)
        c1.addLayout(rowu)

        rowb = QHBoxLayout()
        rowb.setSpacing(10)
        self.btn_jx_bench = QPushButton("跑分 8 秒")
        self.btn_jx_bench.setObjectName("seg")
        self.btn_jx_bench.setCursor(Qt.PointingHandCursor)
        self.btn_jx_bench.setToolTip("24 线程负载，读全核实时频率")
        self.btn_jx_bench.clicked.connect(self._on_jx_bench)
        rowb.addWidget(self.btn_jx_bench)
        self.lbl_jx_bench = QLabel("还没跑过：刷前跑一次，刷完再跑一次就有对比")
        self.lbl_jx_bench.setObjectName("muted")
        rowb.addWidget(self.lbl_jx_bench)
        rowb.addStretch(1)
        c1.addLayout(rowb)

        self.lbl_jx_log = QLabel("")
        self.lbl_jx_log.setObjectName("muted")
        self.lbl_jx_log.setWordWrap(True)
        self.lbl_jx_log.setMinimumHeight(28)
        c1.addWidget(self.lbl_jx_log)
        c1.addStretch(1)
        h.addWidget(self._panel(c1), 3)

        # ------------------------------------------------------- 右：四步与风险
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 10, 14, 10)
        c2.setSpacing(5)
        t2 = QLabel("四步刷写")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)

        steps = [
            ("1", "插 U 盘点「写入鸡血包」", "程序铺好 EFI\\BOOT 与刷写脚本，并回读校验 16 MB 镜像"),
            ("2", "关机，插到主板后置 USB", "BIOS 里把 U 盘设为首选启动（或开机连按 F11 选它）"),
            ("3", "EFI Shell 自动刷写", "全程别断电、别按电源键，刷完自己重启"),
            ("4", "回来跑分验证", "全核 2.4 GHz → 3.1 GHz，徽章变「已解锁」"),
        ]
        for n, title, sub in steps:
            row = QHBoxLayout()
            row.setSpacing(9)
            dot = QLabel(n)
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedSize(19, 19)
            dot.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 4px;"
                              " color: %s; font-size: 11px; font-weight: 700;" % ACC)
            row.addWidget(dot)
            col = QVBoxLayout()
            col.setSpacing(0)
            lt = QLabel(title)
            lt.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #eceef2;")
            ls = QLabel(sub)
            ls.setObjectName("muted")
            ls.setWordWrap(True)
            col.addWidget(lt)
            col.addWidget(ls)
            row.addLayout(col, 1)
            c2.addLayout(row)

        c2.addSpacing(2)
        warn = QLabel("这块板是单 BIOS 芯片，刷坏只能拆芯片用编程器救。\n"
                      "所以：先用「写入原版包」做一张回滚盘，并确认供电稳定再刷。")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size: 10.5px; color: #ffb4b4; line-height: 150%%;")
        c2.addWidget(warn)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 2)

        QTimer.singleShot(150, self._jx_boot)
        return w

    def _jx_set_log(self, text):
        self.lbl_jx_log.setText(text)

    def _jx_boot(self):
        p = jixue.platform_info()
        self._jx["plat"] = p
        mark = "包型号与本板匹配" if p["match"] else "⚠ 包型号与主板不一致"
        self.lbl_jx_plat.setText(
            "CPU　%s · %d 线程 · 基准 %d MHz\n主板　%s · BIOS %s（%s）· %s"
            % (p["cpu"], p["cores"], p["base_mhz"], p["board"],
               p["bios_version"], p["bios_date"], mark))
        self.lbl_jx_gain.setText("全核 %d MHz  →  %d MHz" % (p["base_mhz"], jixue.TURBO_MHZ))
        self._jx_scan_usb()
        self._jx_verify()

    def _jx_scan_usb(self):
        usbs = jixue.list_usb()
        self.cmb_jx_usb.clear()
        ok_any = False
        for u in usbs:
            fs = (u.get("fs") or "").upper()
            good = fs in ("FAT32", "FAT")
            self.cmb_jx_usb.addItem(
                "%s  %s · %s · 空闲 %.0f MB%s"
                % (u.get("drive", "?"), u.get("label") or "-", fs or "未知",
                   float(u.get("free_gb") or 0) * 1024,
                   "" if good else "（需 FAT32）"), u.get("drive"))
            ok_any = ok_any or good
        if not usbs:
            self.cmb_jx_usb.addItem("（没检测到 U 盘，插上后点「刷新」）", None)
        self.btn_jx_jixue.setEnabled(ok_any)
        self.btn_jx_stock.setEnabled(ok_any)
        # 按钮是灰的时候，鼠标悬停也要说清楚为什么点不动
        tip_off = "还没有可用的 U 盘：插一个 FAT32 的盘，再点「刷新」"
        tip_on_j = "把官方鸡血 BIOS 的 U 盘刷写包铺到 U 盘"
        tip_on_s = "铺原厂 BIOS，用于回滚"
        self.btn_jx_jixue.setToolTip(tip_on_j if ok_any else tip_off)
        self.btn_jx_stock.setToolTip(tip_on_s if ok_any else tip_off)
        if usbs:
            self._jx_set_log("检测到 %d 个可移动磁盘%s。"
                             % (len(usbs), "" if ok_any else "，但没有 FAT32 的，不能用来刷 BIOS"))
        else:
            self._jx_set_log("没检测到可移动磁盘：插一个 FAT32 的 U 盘，再点「刷新」。")

    def _jx_verify(self):
        def done(v):
            if isinstance(v, Exception):
                self.lbl_jx_pkg.setText("官方包校验失败：%s" % v)
                return
            self._jx["pkg"] = v
            parts = []
            for k in ("jixue", "stock"):
                r = v.get(k) or {}
                nm = "鸡血" if k == "jixue" else "原版"
                if r.get("ok"):
                    parts.append("%s ✓ 16 MB / %s" % (nm, r.get("sha256", "")[:8]))
                else:
                    parts.append("%s ✗ %s" % (nm, r.get("why") or "缺失"))
            self.lbl_jx_pkg.setText("官方包（精粤 X9MPS007）：" + "　·　".join(parts))

        self._jx_async(jixue.verify_all, done)

    def _jx_async(self, fn, on_done):
        box = {"done": False, "val": None}

        def work():
            try:
                box["val"] = fn()
            except Exception as e:                       # noqa: BLE001
                box["val"] = e
            finally:
                box["done"] = True

        threading.Thread(target=work, daemon=True).start()

        def poll():
            if not box["done"]:
                QTimer.singleShot(200, poll)
                return
            on_done(box["val"])

        QTimer.singleShot(200, poll)

    def _jx_write(self, kind):
        drive = self.cmb_jx_usb.currentData()
        if not drive:
            self._jx_set_log("先插一个 FAT32 的 U 盘，再点「刷新」。")
            return
        ok, why = jixue.usb_ok(drive)
        if not ok:
            self._jx_set_log("这个盘不能用来刷 BIOS：%s" % why)
            return
        title = jixue.KINDS[kind]["title"]
        custom = None
        try:
            cp = self._lg_custom_path(kind)
            if os.path.isfile(cp):
                custom = cp
        except Exception:                                        # noqa: BLE001
            custom = None
        extra = ("\n\n这次会写入**自定义镜像**（含换过的开机 LOGO），不是官方原包。"
                 if custom else "")
        ans = QMessageBox.question(
            self, "写入刷写盘",
            "会把「%s」的 U 盘刷写包写到 %s 根目录。%s\n\n"
            "会覆盖该盘上已有的 EFI\\BOOT 目录，其它文件不动。\n继续吗？"
            % (title, drive, extra),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.btn_jx_jixue.setEnabled(False)
        self.btn_jx_stock.setEnabled(False)
        self._jx_set_log("正在写入 %s 到 %s …%s"
                         % (title, drive, "（自定义 LOGO 镜像）" if custom else ""))

        def done(v):
            self.btn_jx_jixue.setEnabled(True)
            self.btn_jx_stock.setEnabled(True)
            if isinstance(v, Exception):
                self._jx_set_log("写入失败：%s" % v)
                return
            ok2, log = v
            self._jx_set_log(("✓ " if ok2 else "✗ ") + " | ".join(log))

        self._jx_async(lambda: jixue.write_usb(drive, kind, custom), done)

    def _on_jx_bench(self):
        if self._jx.get("busy"):
            return
        self._jx["busy"] = True
        self.btn_jx_bench.setEnabled(False)
        self.btn_jx_bench.setText("跑分中…")
        n = os.cpu_count() or 8
        self._jx_set_log("正在用 %d 个线程跑 8 秒负载，风扇会明显加速，属正常。" % n)
        self.lbl_jx_bench.setText("跑分中…")

        def done(v):
            self._jx["busy"] = False
            self.btn_jx_bench.setEnabled(True)
            self.btn_jx_bench.setText("跑分 8 秒")
            if isinstance(v, Exception):
                self._jx_set_log("跑分失败：%s" % v)
                self.lbl_jx_bench.setText("跑分失败")
                return
            self._jx["bench"] = v
            hist = jixue.save_history(os.path.dirname(self.presets_dir), v)
            self._jx_show_bench(v, hist)
            if v.get("unlocked"):
                self.lbl_jx_state.setText("已解锁 · 全核 %d MHz" % v["mhz_avg"])
                self.lbl_jx_state.setObjectName("pillOn")
                self._jx_set_log("满载全核稳定在 %d MHz，鸡血已生效。" % v["mhz_avg"])
            else:
                self.lbl_jx_state.setText("未解锁 · 全核 %d MHz" % v["mhz_avg"])
                self.lbl_jx_state.setObjectName("pill")
                self._jx_set_log("满载全核 %d MHz（原厂上限），说明还没刷鸡血 BIOS。"
                                 % v["mhz_avg"])
            self._restyle(self.lbl_jx_state)

        self._jx_async(lambda: jixue.bench(seconds=8), done)

    def _jx_show_bench(self, v, hist):
        txt = "全核 %d MHz（峰值 %d） · %d 线程 · %.0f MB/s" % (
            v["mhz_avg"], v["mhz_peak"], v["threads"], v["mbps"])
        prev = [h for h in (hist or []) if h.get("ts") != v.get("ts")]
        if prev:
            last = prev[-1]
            d = v["mbps"] - last.get("mbps", 0)
            txt += "　｜ 对比上次 %+.0f MB/s（%d MHz）" % (d, last.get("mhz_avg", 0))
        self.lbl_jx_bench.setText(txt)

    # ===================================================== 开机 LOGO 页
    def _tab_logo(self):
        """AMI 开机 LOGO：把 800×600 图写进 BIOS 镜像，随刷写盘一起刷

        本页只改镜像里的图片，不刷固件；刷写仍走「鸡血 BIOS」页的 U 盘流程。
        """
        self._lg = {"bmp": None, "src": "", "built": None, "orig": {}}

        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # ------------------------------------------------------- 左：预览与操作
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 8, 14, 8)
        c1.setSpacing(5)

        rowt = QHBoxLayout()
        t1 = QLabel("开机 LOGO · POST 开机画面")
        t1.setObjectName("sectionTitle")
        rowt.addWidget(t1)
        rowt.addStretch(1)
        self.lbl_lg_state = QLabel("官方原图")
        self.lbl_lg_state.setObjectName("pill")
        rowt.addWidget(self.lbl_lg_state)
        c1.addLayout(rowt)

        self.lbl_lg_view = QLabel("载入中…")
        self.lbl_lg_view.setFixedSize(288, 216)
        self.lbl_lg_view.setAlignment(Qt.AlignCenter)
        self.lbl_lg_view.setStyleSheet(
            "background:#050608; border:1px solid rgba(255,255,255,0.09); border-radius:6px;"
            " color:#6b7280; font-size:11px;")

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self.lbl_lg_view)

        right = QVBoxLayout()
        right.setSpacing(7)

        self.cmb_lg_base = QComboBox()
        self.cmb_lg_base.addItem("基底 · 鸡血 BIOS（3.1 GHz）", "jixue")
        self.cmb_lg_base.addItem("基底 · 原版 BIOS", "stock")
        self.cmb_lg_base.setToolTip("换了 LOGO 的镜像基于哪个包；刷过鸡血就选鸡血包，别把 3.1 GHz 刷没了")
        self.cmb_lg_base.currentIndexChanged.connect(self._lg_switch_base)
        right.addWidget(self.cmb_lg_base)

        row1 = QHBoxLayout()
        row1.setSpacing(7)
        btn_pick = QPushButton("选择图片")
        btn_pick.setCursor(Qt.PointingHandCursor)
        btn_pick.setToolTip("PNG / JPG / BMP / WebP，自动缩放到 800×600 居中")
        btn_pick.clicked.connect(self._lg_pick)
        row1.addWidget(btn_pick)
        btn_rst = QPushButton("恢复原图")
        btn_rst.setObjectName("seg")
        btn_rst.setCursor(Qt.PointingHandCursor)
        btn_rst.setToolTip("删掉生成的自定义镜像，回到官方图")
        btn_rst.clicked.connect(self._lg_reset)
        row1.addWidget(btn_rst)
        row1.addStretch(1)
        right.addLayout(row1)

        self.btn_lg_build = QPushButton("生成 ROM")
        self.btn_lg_build.setObjectName("primary")
        self.btn_lg_build.setCursor(Qt.PointingHandCursor)
        self.btn_lg_build.setToolTip("把这张图写进 16 MB 镜像，存到 data\\bios_custom\\")
        self.btn_lg_build.clicked.connect(self._lg_build)
        right.addWidget(self.btn_lg_build)

        self.lbl_lg_log = QLabel("选图 → 生成 ROM → 去「鸡血 BIOS」页插 U 盘点写入")
        self.lbl_lg_log.setObjectName("muted")
        self.lbl_lg_log.setWordWrap(True)
        self.lbl_lg_log.setAlignment(Qt.AlignTop)
        right.addWidget(self.lbl_lg_log, 1)

        body.addLayout(right, 1)
        c1.addLayout(body)
        h.addWidget(self._panel(c1), 3)

        # ------------------------------------------------------- 右：步骤与风险
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 8, 14, 8)
        c2.setSpacing(4)
        t2 = QLabel("换的是固件里的那张图")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)

        steps = [
            ("1", "选图 · 必须 800×600 8 位色", "BIOS 只吃这个规格，程序自动缩放居中、黑边补齐"),
            ("2", "选基底 · 别把鸡血刷没了", "已刷 3.1 GHz 就选鸡血包：新镜像同时保住睿频和新 LOGO"),
            ("3", "生成 ROM · 铺 U 盘", "回「鸡血 BIOS」页选盘 → 写入，会自动带上这张图"),
            ("4", "刷完开机看效果", "全程别断电；出问题用原版回滚盘刷回来"),
        ]
        for n, title, sub in steps:
            row = QHBoxLayout()
            row.setSpacing(9)
            dot = QLabel(n)
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedSize(19, 19)
            dot.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 4px;"
                              " color: %s; font-size: 11px; font-weight: 700;" % ACC)
            row.addWidget(dot)
            col = QVBoxLayout()
            col.setSpacing(0)
            lt = QLabel(title)
            lt.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #eceef2;")
            ls = QLabel(sub)
            ls.setObjectName("muted")
            ls.setWordWrap(True)
            col.addWidget(lt)
            col.addWidget(ls)
            row.addLayout(col, 1)
            c2.addLayout(row)

        c2.addSpacing(2)
        warn = QLabel("改的是 SPI 镜像，和刷鸡血是同一条风险线：单 BIOS 芯片、没编程器。\n"
                      "官方的「按 Del 进 BIOS」那行提示也在图里，替换后就没有了。")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size: 10.5px; color: #ffb4b4; line-height: 150%%;")
        c2.addWidget(warn)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 2)

        QTimer.singleShot(150, self._lg_boot)
        return w

    def _lg_custom_path(self, kind):
        return os.path.join(os.path.dirname(self.presets_dir), "bios_custom",
                            "logo_%s.bin" % kind)

    def _lg_base(self):
        return self.cmb_lg_base.currentData() or "jixue"

    def _lg_show(self, bmp, note=""):
        if not bmp:
            self.lbl_lg_view.setText("没有图可预览")
            return
        pm = bioslogo.bmp_pixmap(bmp, 280, 210)
        if pm.isNull():
            self.lbl_lg_view.setText("预览失败")
            return
        self.lbl_lg_view.setPixmap(pm)
        if note:
            self.lbl_lg_view.setToolTip(note)

    def _lg_orig_bmp(self, kind):
        if kind in self._lg["orig"]:
            return self._lg["orig"][kind]
        rom = open(jixue.bin_path(kind), "rb").read()
        loc = bioslogo.locate(rom)
        self._lg["orig"][kind] = loc["bmp"]
        return loc["bmp"]

    def _lg_boot(self):
        kind = self._lg_base()
        try:
            bmp = self._lg_orig_bmp(kind)
        except Exception as e:                                  # noqa: BLE001
            self.lbl_lg_view.setText("读不到镜像里的 LOGO：%s" % e)
            return
        if self._lg["bmp"] is None:
            self._lg_show(bmp, "当前是官方原图（JGINYUE）")
        cp = self._lg_custom_path(kind)
        if os.path.isfile(cp):
            self.lbl_lg_log.setText("已有自定义镜像：%s（去鸡血页点写入就会用它）"
                                    % os.path.basename(cp))
            self.lbl_lg_state.setText("已生成自定义")
        else:
            self.lbl_lg_state.setText("官方原图")

    def _lg_switch_base(self):
        self._lg["built"] = None
        kind = self._lg_base()
        try:
            bmp = self._lg_orig_bmp(kind)
        except Exception as e:                                  # noqa: BLE001
            self.lbl_lg_log.setText("基底包读取失败：%s" % e)
            return
        if self._lg["bmp"] is None:
            self._lg_show(bmp, "当前是官方原图")
        else:
            self._lg_show(self._lg["bmp"], "你选的图")
        self.lbl_lg_log.setText("基底切成 %s；重新点「生成 ROM」才会生效。"
                                % ("鸡血 BIOS" if kind == "jixue" else "原版 BIOS"))

    def _lg_pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择开机 LOGO 图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        kind = self._lg_base()
        try:
            loc = bioslogo.locate(open(jixue.bin_path(kind), "rb").read())
            bmp = bioslogo.convert_image(path, loc["w"], loc["h"])
        except Exception as e:                                  # noqa: BLE001
            self.lbl_lg_log.setText("这张图转不了：%s" % e)
            return
        self._lg["bmp"] = bmp
        self._lg["src"] = path
        self._lg["built"] = None
        self._lg_show(bmp, os.path.basename(path))
        self.lbl_lg_state.setText("待生成")
        self._lg_widget_sync()
        self.lbl_lg_log.setText("已载入 %dx%d 转换结果，点「生成 ROM」写进镜像。"
                                % (loc["w"], loc["h"]))

    def _lg_widget_sync(self):
        self._restyle(self.lbl_lg_state)

    def _lg_reset(self):
        kind = self._lg_base()
        cp = self._lg_custom_path(kind)
        try:
            if os.path.isfile(cp):
                os.remove(cp)
        except Exception as e:                                  # noqa: BLE001
            self.lbl_lg_log.setText("删不掉自定义镜像：%s" % e)
            return
        self._lg["bmp"] = None
        self._lg["built"] = None
        try:
            self._lg_show(self._lg_orig_bmp(kind), "当前是官方原图")
        except Exception:                                       # noqa: BLE001
            pass
        self.lbl_lg_state.setText("官方原图")
        self._lg_widget_sync()
        self.lbl_lg_log.setText("已恢复官方图，下次写入用官方镜像。")

    def _lg_build(self):
        if not self._lg["bmp"]:
            self.lbl_lg_log.setText("先点「选择图片」挑一张图。")
            return
        kind = self._lg_base()
        self.btn_lg_build.setEnabled(False)
        self.lbl_lg_log.setText("正在重压 LZMA 并写回镜像…")
        bmp = self._lg["bmp"]

        def work():
            rom = open(jixue.bin_path(kind), "rb").read()
            new_rom, info = bioslogo.make_rom(rom, bmp)
            cp = self._lg_custom_path(kind)
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            tmp = cp + ".part"
            with open(tmp, "wb") as f:
                f.write(new_rom)
            os.replace(tmp, cp)
            return info

        def done(v):
            self.btn_lg_build.setEnabled(True)
            if isinstance(v, Exception):                        # noqa: BLE001
                self.lbl_lg_log.setText("生成失败：%s" % v)
                return
            self._lg["built"] = v
            self.lbl_lg_state.setText("已生成自定义")
            self._lg_widget_sync()
            self.lbl_lg_log.setText(
                "✓ 已生成 %s（压缩 %d 字节，模块 %d→%d，sha %s）→ 去「鸡血 BIOS」页插 U 盘点写入"
                % ("logo_%s.bin" % kind, v["comp"], v["old_size"], v["new_size"], v["new_sha"]))

        self._jx_async(work, done)

    def _restyle(self, widget):
        """换 objectName 后要让 QSS 重新生效"""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _tab_scene(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)

        # ---------------------------------------------------------- 情景模式
        c1 = QVBoxLayout()
        c1.setContentsMargins(14, 12, 14, 12)
        c1.setSpacing(8)
        t1 = QLabel("情景模式")
        t1.setObjectName("sectionTitle")
        c1.addWidget(t1)
        s1 = QLabel("点一下整机换风格（5 路一起变），也可以把自己的调法存成自定义")
        s1.setObjectName("muted")
        s1.setWordWrap(True)
        c1.addWidget(s1)
        grid = QGridLayout()
        grid.setSpacing(8)
        self._scene_btns = {}
        for i, item in enumerate(SCENES):
            key, label = item[0], item[1]
            b = QPushButton(label)
            b.setObjectName("scene")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._apply_scene(k))
            grid.addWidget(b, i // 2, i % 2)
            self._scene_btns[key] = b
        c1.addLayout(grid)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.btn_custom = QPushButton("自定义 · 当前状态")
        self.btn_custom.setObjectName("scene")
        self.btn_custom.setCheckable(True)
        self.btn_custom.setCursor(Qt.PointingHandCursor)
        self.btn_custom.clicked.connect(lambda: self._apply_scene("custom"))
        self._scene_btns["custom"] = self.btn_custom
        btn_save_scene = QPushButton("把当前存为自定义")
        btn_save_scene.setObjectName("primary")
        btn_save_scene.setCursor(Qt.PointingHandCursor)
        btn_save_scene.clicked.connect(self._save_scene_custom)
        row1.addWidget(self.btn_custom, 2)
        row1.addWidget(btn_save_scene, 1)
        c1.addLayout(row1)
        c1.addStretch(1)
        h.addWidget(self._panel(c1), 1)

        # ---------------------------------------------------------- 轮播 + 备份
        c2 = QVBoxLayout()
        c2.setContentsMargins(14, 12, 14, 12)
        c2.setSpacing(7)
        t2 = QLabel("灯效轮播")
        t2.setObjectName("sectionTitle")
        c2.addWidget(t2)
        s2 = QLabel("按设定间隔在已保存的预设之间自动切换，挂机/展示用")
        s2.setObjectName("muted")
        s2.setWordWrap(True)
        c2.addWidget(s2)
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.sw_rot = Switch(False)
        self.sw_rot.clicked.connect(self._on_rot_toggle)
        r2.addWidget(self.sw_rot)
        r2.addWidget(QLabel("开启"))
        self.cmb_rot = QComboBox()
        for label, sec in (("30 秒", 30), ("1 分钟", 60), ("2 分钟", 120), ("5 分钟", 300)):
            self.cmb_rot.addItem(label, sec)
        self.cmb_rot.setCurrentIndex(1)
        self.cmb_rot.currentIndexChanged.connect(lambda _=0: self._on_rot_toggle())
        r2.addWidget(self.cmb_rot)
        r2.addStretch(1)
        c2.addLayout(r2)
        self.lbl_rot = QLabel("未开启")
        self.lbl_rot.setObjectName("mono")
        c2.addWidget(self.lbl_rot)
        c2.addSpacing(10)

        t4 = QLabel("预设备份")
        t4.setObjectName("sectionTitle")
        c2.addWidget(t4)
        s4 = QLabel("把 data\\presets 打成 zip 带走，或者从备份里恢复")
        s4.setObjectName("muted")
        s4.setWordWrap(True)
        c2.addWidget(s4)
        r4 = QHBoxLayout()
        r4.setSpacing(8)
        btn_exp = QPushButton("导出全部预设")
        btn_exp.setCursor(Qt.PointingHandCursor)
        btn_exp.clicked.connect(self._on_export_presets)
        btn_imp = QPushButton("从备份导入")
        btn_imp.setCursor(Qt.PointingHandCursor)
        btn_imp.clicked.connect(self._on_import_presets)
        r4.addWidget(btn_exp)
        r4.addWidget(btn_imp)
        r4.addStretch(1)
        c2.addLayout(r4)
        c2.addStretch(1)
        h.addWidget(self._panel(c2), 1)

        # ---------------------------------------------------------- 过热守护
        c3 = QVBoxLayout()
        c3.setContentsMargins(14, 12, 14, 12)
        c3.setSpacing(7)
        t3 = QLabel("过热守护")
        t3.setObjectName("sectionTitle")
        c3.addWidget(t3)
        s3 = QLabel("GPU 超过设定温度时，5 路自动转红色呼吸警示；降回来会还原原来的灯效。"
                    "（要读得到 GPU 温度，需有 NVIDIA 显卡）")
        s3.setObjectName("muted")
        s3.setWordWrap(True)
        c3.addWidget(s3)
        r3 = QHBoxLayout()
        r3.setSpacing(8)
        self.sw_guard = Switch(False)
        self.sw_guard.clicked.connect(self._on_guard_toggle)
        r3.addWidget(self.sw_guard)
        r3.addWidget(QLabel("开启 · 阈值"))
        self.sp_guard = QSpinBox()
        self.sp_guard.setRange(60, 95)
        self.sp_guard.setValue(82)
        self.sp_guard.setSuffix(" °C")
        self.sp_guard.setFixedWidth(82)
        self.sp_guard.valueChanged.connect(lambda _=0: self._on_guard_toggle())
        r3.addWidget(self.sp_guard)
        r3.addStretch(1)
        c3.addLayout(r3)
        self.lbl_guard = QLabel("待命")
        self.lbl_guard.setObjectName("mono")
        c3.addWidget(self.lbl_guard)
        c3.addSpacing(12)

        t5 = QLabel("状态提示")
        t5.setObjectName("sectionTitle")
        c3.addWidget(t5)
        s5 = QLabel("· 情景与轮播都会立即生效，不用重启\n"
                    "· 联排打开时，跑动类效果会从第 1 路一直跑到第 5 路\n"
                    "· 夜间模式、程序联动、全局快捷键在「自动化」页")
        s5.setObjectName("muted")
        s5.setWordWrap(True)
        c3.addWidget(s5)
        c3.addStretch(1)
        h.addWidget(self._panel(c3), 1)
        return w

    # ------------------------------------------------------------------ 情景
    def _apply_scene(self, key):
        label = ""
        if key == "custom":
            st = getattr(self, "_scene_custom", None)
            if not st:
                self.lbl_dev.setText("还没有自定义情景，先点「把当前存为自定义」")
                return
            self._apply_state(st, "自定义")
            label = "自定义"
        else:
            for item in SCENES:
                if item[0] != key:
                    continue
                _, label, eff, cols, spd, bri, span = item
                zones = [{"effect": eff, "colors": list(cols), "speed": spd, "brightness": bri}
                         for _ in range(len(self.eng.zones))]
                self._apply_state({"zones": zones, "master": 100, "span": span}, label)
                break
        self._mark_scene(key)

    def _apply_state(self, st, label):
        for i, z in enumerate(st.get("zones", [])[:len(self.eng.zones)]):
            self.eng.set_zone(i, effect=z.get("effect", "solid"),
                              colors=list(z.get("colors", [])),
                              speed=int(z.get("speed", 45)),
                              brightness=int(z.get("brightness", 100)),
                              leds=int(self.eng.zones[i].get("leds", 30)))
        self.eng.set_master(brightness=int(st.get("master", 100)),
                            span=bool(st.get("span", True)))
        self.sl_master.setValue(int(st.get("master", 100)))
        self.sw_span.setChecked(bool(st.get("span", True)))
        self.eng._add_log("情景：切换到「%s」" % label)
        self._scene = label
        self.refresh()

    def _mark_scene(self, key):
        for k, b in self._scene_btns.items():
            b.setChecked(k == key)

    def _scene_path(self):
        return os.path.join(os.path.dirname(self.presets_dir), "scenes.json")

    def _save_scene_custom(self):
        st = {"zones": [dict(z) for z in self.eng.zones],
              "master": int(self.eng.master.get("brightness", 100)),
              "span": bool(self.eng.master.get("span", True))}
        self._scene_custom = st
        try:
            with open(self._scene_path(), "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            self.lbl_dev.setText("已把当前状态存为自定义情景")
        except Exception as e:
            self.lbl_dev.setText("保存自定义情景失败：%s" % e)
        self._mark_scene("custom")

    # ------------------------------------------------------------------ 轮播
    def _preset_names(self):
        try:
            if self.presets_dir and os.path.isdir(self.presets_dir):
                return sorted(f[:-5] for f in os.listdir(self.presets_dir) if f.endswith(".json"))
        except Exception:
            pass
        return []

    def _rot_sec(self):
        return int(self.cmb_rot.currentData() or 60)

    def _on_rot_toggle(self):
        self._save_auto()
        if self.sw_rot.isChecked():
            self._rot_next = time.time() + self._rot_sec()
            self.lbl_rot.setText("已开启，%d 秒后切下一个" % self._rot_sec())
        else:
            self.lbl_rot.setText("未开启")

    def _rot_tick(self):
        if not self.sw_rot.isChecked():
            return
        names = self._preset_names()
        if len(names) < 2:
            self.lbl_rot.setText("至少要有 2 个预设才能轮播（当前 %d 个）" % len(names))
            return
        left = int(getattr(self, "_rot_next", 0) - time.time())
        if left > 0:
            self.lbl_rot.setText("下一个：%s · %d 秒后" % (names[(self._rot_idx + 1) % len(names)], left))
            return
        self._rot_idx = (self._rot_idx + 1) % len(names)
        self._rot_next = time.time() + self._rot_sec()
        self._on_load_preset(names[self._rot_idx])
        self.eng._add_log("轮播：切换到预设「%s」" % names[self._rot_idx])

    # ------------------------------------------------------------------ 过热守护
    def _on_guard_toggle(self):
        self._save_auto()
        if not self.sw_guard.isChecked() and getattr(self, "_guard_on", False):
            self._guard_restore()
        if not getattr(self, "_guard_on", False):
            self.lbl_guard.setText("待命中（阈值 %d°C）" % int(self.sp_guard.value()))

    def _check_guard(self, snap=None):
        if not self.sw_guard.isChecked():
            if getattr(self, "_guard_on", False):
                self._guard_restore()
            return
        if snap is None:
            snap = self.eng.snapshot()
        gpu = (snap.get("sys") or {}).get("gpu")
        t = gpu.get("temp") if gpu else None
        if t is None:
            self.lbl_guard.setText("读不到 GPU 温度（无 NVIDIA 显卡或驱动未装）")
            return
        lim = int(self.sp_guard.value())
        if not getattr(self, "_guard_on", False) and t >= lim:
            self._guard_saved = {"master": int(self.eng.master.get("brightness", 100)),
                                 "zones": [dict(z) for z in self.eng.zones]}
            for i in range(len(self.eng.zones)):
                self.eng.set_zone(i, effect="breathing", colors=["#ff2d22"], speed=100,
                                  brightness=100)
            self.eng.set_master(brightness=100)
            self.sl_master.setValue(100)
            self.eng._add_log("过热守护：GPU %d°C 已超过 %d°C，全部转红色呼吸警示" % (t, lim))
            self.lbl_guard.setText("⚠ 已触发（GPU %d°C）" % t)
            self._guard_on = True
        elif getattr(self, "_guard_on", False):
            if t <= lim - 5:
                self._guard_restore()
            else:
                self.lbl_guard.setText("⚠ 警示中（GPU %d°C，降到 %d°C 以下自动还原）" % (t, lim - 5))

    def _guard_restore(self):
        sv = getattr(self, "_guard_saved", None)
        if sv:
            for i, z in enumerate(sv["zones"][:len(self.eng.zones)]):
                self.eng.set_zone(i, effect=z.get("effect", "rainbow"),
                                  colors=list(z.get("colors", [])),
                                  speed=int(z.get("speed", 45)),
                                  brightness=int(z.get("brightness", 100)),
                                  leds=int(z.get("leds", 30)),
                                  direction=int(z.get("direction", 0)))
            self.eng.set_master(brightness=int(sv.get("master", 100)))
            self.sl_master.setValue(int(sv.get("master", 100)))
            self.eng._add_log("过热守护：温度已回落，还原原来的灯效")
            self._guard_saved = None
            self.refresh()
        self._guard_on = False
        self.lbl_guard.setText("待命中（阈值 %d°C）" % int(self.sp_guard.value()))

    # ------------------------------------------------------------------ 预设备份
    def _on_export_presets(self):
        import zipfile
        names = self._preset_names()
        if not names:
            self.lbl_dev.setText("还没有预设可导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出预设备份", "X99控制台预设备份.zip",
                                              "ZIP 压缩包 (*.zip)")
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for n in names:
                    z.write(os.path.join(self.presets_dir, n + ".json"), n + ".json")
            self.lbl_dev.setText("已导出 %d 个预设 → %s" % (len(names), os.path.basename(path)))
            self.eng._add_log("已导出 %d 个预设备份" % len(names))
        except Exception as e:
            self.lbl_dev.setText("导出失败：%s" % e)

    def _on_import_presets(self):
        import zipfile
        path, _ = QFileDialog.getOpenFileName(self, "选择预设备份", "", "ZIP 压缩包 (*.zip)")
        if not path:
            return
        ok = 0
        try:
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if not n.lower().endswith(".json"):
                        continue
                    base = os.path.basename(n)[:-5]
                    safe = "".join(c for c in base if c not in '\\/:*?"<>|')[:40]
                    if not safe:
                        continue
                    raw = z.read(n).decode("utf-8")
                    json.loads(raw)
                    os.makedirs(self.presets_dir, exist_ok=True)
                    fp = os.path.join(self.presets_dir, safe + ".json")
                    with open(fp, "w", encoding="utf-8") as f:
                        f.write(raw)
                    ok += 1
        except Exception as e:
            self.lbl_dev.setText("导入失败：%s" % e)
            return
        self.load_presets()
        self.lbl_dev.setText("已导入 %d 个预设" % ok)
        self.eng._add_log("已从备份导入 %d 个预设" % ok)

    # ================================================================== 实时联动
    def _sync_live_buttons(self):
        mode = self.eng.live.mode
        for k, b in self.btn_live.items():
            b.setChecked(k == mode)
        txt = {"": "当前：软件特效（未开联动）",
               "screen": "当前：屏幕氛围同步",
               "music": "当前：音乐律动",
               "temp": "当前：温度联动"}[mode]
        if self.eng.live.last_error:
            txt += " · " + self.eng.live.last_error
        self.lbl_live.setText(txt)

    def _on_live_click(self, key):
        mode = self.eng.live.mode
        new = "" if mode == key else key
        ok = self.eng.set_live(new, split=self.sw_split.isChecked(),
                               smooth=self.sl_smooth.value() / 100.0)
        if not ok:
            self.lbl_dev.setText(self.eng.live.last_error or "开启失败")
        self._sync_live_buttons()

    def _on_live_param(self):
        if self.eng.live.active:
            self.eng.set_live(self.eng.live.mode, split=self.sw_split.isChecked(),
                              smooth=self.sl_smooth.value() / 100.0)
        self._sync_live_buttons()

    # ================================================================== 自动化
    def _auto_path(self):
        return os.path.join(os.path.dirname(self.presets_dir), "automation.json")

    def _load_auto(self):
        try:
            p = self._auto_path()
            if not os.path.exists(p):
                return
            d = json.load(open(p, "r", encoding="utf-8"))
            n = d.get("night", {})
            self.sw_night.setChecked(bool(n.get("on")))
            self.tm_from.setTime(QTime.fromString(n.get("from", "23:00"), "HH:mm"))
            self.tm_to.setTime(QTime.fromString(n.get("to", "07:00"), "HH:mm"))
            idx = self.cmb_night.findData(n.get("action", "dim"))
            self.cmb_night.setCurrentIndex(max(0, idx))
            self.sp_night.setValue(int(n.get("bri", 20)))
            self.apps = dict(d.get("apps", {}))
            self.sw_hotkey.setChecked(bool(d.get("hotkey", False)))
            r = d.get("rotation", {})
            self.sw_rot.setChecked(bool(r.get("on", False)))
            i = self.cmb_rot.findData(int(r.get("sec", 60)))
            if i >= 0:
                self.cmb_rot.setCurrentIndex(i)
            if self.sw_rot.isChecked():
                self._rot_next = time.time() + self._rot_sec()
            g = d.get("guard", {})
            self.sw_guard.setChecked(bool(g.get("on", False)))
            self.sp_guard.setValue(int(g.get("temp", 82)))
        except Exception:
            self.apps = {}
        try:
            sp = self._scene_path()
            if os.path.exists(sp):
                self._scene_custom = json.load(open(sp, "r", encoding="utf-8"))
        except Exception:
            self._scene_custom = None
        self._fill_apps()

    def _save_auto(self):
        try:
            d = {"night": {"on": self.sw_night.isChecked(),
                           "from": self.tm_from.time().toString("HH:mm"),
                           "to": self.tm_to.time().toString("HH:mm"),
                           "action": self.cmb_night.currentData(),
                           "bri": int(self.sp_night.value())},
                 "apps": getattr(self, "apps", {}),
                 "hotkey": self.sw_hotkey.isChecked(),
                 "rotation": {"on": self.sw_rot.isChecked(), "sec": self._rot_sec()},
                 "guard": {"on": self.sw_guard.isChecked(),
                           "temp": int(self.sp_guard.value())}}
            with open(self._auto_path(), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_auto_change(self):
        self._save_auto()
        if not self.sw_night.isChecked() and getattr(self, "_night_on", False):
            self._apply_night(False)

    def _fill_apps(self):
        self.lst_apps.clear()
        for exe, preset in sorted(getattr(self, "apps", {}).items()):
            self.lst_apps.addItem("%s  →  %s" % (exe, preset))

    def _on_add_app(self):
        exe = (self.eng.sysinfo.get().get("fg") or "").strip()
        if not exe:
            self.lbl_dev.setText("拿不到当前前台程序名，先点一下别的窗口再试")
            return
        preset = self.cmb_app_preset.currentText().strip()
        if not preset:
            self.lbl_dev.setText("先建一个预设，再用它绑程序")
            return
        if not hasattr(self, "apps"):
            self.apps = {}
        self.apps[exe] = preset
        self._fill_apps()
        self._save_auto()

    def _on_del_app(self):
        it = self.lst_apps.currentItem()
        if not it:
            self.lbl_dev.setText("先在上面的列表里选中一条，再点「删除选中」")
            return
        exe = it.text().split("→")[0].strip()
        if hasattr(self, "apps"):
            self.apps.pop(exe, None)
        self._fill_apps()
        self._save_auto()
        self.lbl_dev.setText("已解除「%s」的绑定" % exe)

    def _night_window(self):
        f = self.tm_from.time()
        t = self.tm_to.time()
        now = QTime.currentTime()
        if f <= t:
            return f <= now < t
        return now >= f or now < t

    def _apply_night(self, enter):
        if enter:
            # 已经在夜间态就别再覆盖基线，否则基线会被记成"夜间亮度"
            if not getattr(self, "_night_on", False):
                self._night_saved = {"master": int(self.eng.master.get("brightness", 100)),
                                     "zones": [dict(z) for z in self.eng.zones]}
            if self.cmb_night.currentData() == "off":
                self.eng.set_off()
                self.eng._add_log("夜间模式：已熄灭")
            else:
                self.eng.set_master(brightness=int(self.sp_night.value()))
                self.sl_master.setValue(int(self.sp_night.value()))
                self.eng._add_log("夜间模式：亮度降到 %d%%" % int(self.sp_night.value()))
            self._night_on = True
        else:
            sv = getattr(self, "_night_saved", None)
            cur = int(self.eng.master.get("brightness", 100))
            target = int(self.sp_night.value())
            # 只有亮度还停在夜间设定值时才还原；中途手动改过就保留用户的
            if sv and (cur == target or self.cmb_night.currentData() == "off"):
                if self.cmb_night.currentData() == "off":
                    for i, z in enumerate(sv["zones"][:len(self.eng.zones)]):
                        self.eng.set_zone(i, effect=z.get("effect", "rainbow"),
                                          colors=z.get("colors", []), leds=z.get("leds", 30))
                self.eng.set_master(brightness=sv["master"])
                self.sl_master.setValue(sv["master"])
                self.eng._add_log("夜间模式结束，亮度已还原到 %d%%" % sv["master"])
            elif sv:
                self.eng._add_log("夜间模式结束（亮度已被手动改过，保留 %d%%）" % cur)
            else:
                self.eng._add_log("夜间模式结束")
            self._night_saved = None
            self._night_on = False

    def _check_night(self):
        if not self.sw_night.isChecked():
            if getattr(self, "_night_on", False):
                self._apply_night(False)
            return
        want = self._night_window()
        if want != getattr(self, "_night_on", False):
            self._apply_night(want)

    def _check_apps(self):
        apps = getattr(self, "apps", {})
        if not apps:
            return
        fg = (self.eng.sysinfo.get().get("fg") or "").lower()
        if not fg or fg == getattr(self, "_last_fg", ""):
            return
        self._last_fg = fg
        preset = apps.get(fg)
        if preset:
            self._on_load_preset(preset)

    # ================================================================== 全局热键
    def _on_hotkey_toggle(self):
        self._save_auto()
        if self.sw_hotkey.isChecked():
            ok = self._register_hotkeys()
            self.lbl_dev.setText("全局快捷键已启用" if ok else "快捷键注册被系统拒绝（可能被别的软件占用）")
        else:
            self._unregister_hotkeys()
            self.lbl_dev.setText("全局快捷键已关闭")

    def _register_hotkeys(self):
        try:
            if not self._hk_installed:
                QCoreApplication.instance().installNativeEventFilter(self._hk_filter)
                self._hk_installed = True
            hwnd = int(self.winId())
            MOD = 0x0002 | 0x0001        # CTRL | ALT
            ok1 = _user32.RegisterHotKey(hwnd, 1, MOD, 0x4F)     # Ctrl+Alt+O 关灯
            ok2 = _user32.RegisterHotKey(hwnd, 2, MOD, 0x50)     # Ctrl+Alt+P 还原
            return bool(ok1) and bool(ok2)
        except Exception:
            return False

    def tray_lights(self, on):
        """托盘菜单用：一键熄灭（on=True）/ 恢复灯效（on=False）。
        复用全局热键那套"改之前先备份"的逻辑，但要绕过它的 0.3 秒防抖。"""
        self._hk_last_id = None
        self._hk_last_t = 0
        self._on_hotkey(1 if on else 2)

    def _unregister_hotkeys(self):
        try:
            hwnd = int(self.winId()) if self.winId() else 0
            _user32.UnregisterHotKey(hwnd, 1)
            _user32.UnregisterHotKey(hwnd, 2)
        except Exception:
            pass

    def _on_hotkey(self, hid):
        # 同一条按键消息 Qt 可能回调两次，短时间同 id 直接忽略
        import time
        now = time.perf_counter()
        if getattr(self, "_hk_last_id", None) == hid and now - getattr(self, "_hk_last_t", 0) < 0.3:
            return
        self._hk_last_id, self._hk_last_t = hid, now

        if hid == 1:
            # 已经关过一次、还没还原时，不要用"关灯状态"覆盖基线
            if not getattr(self, "_night_saved", None):
                self._night_saved = {"master": int(self.eng.master.get("brightness", 100)),
                                     "zones": [dict(z) for z in self.eng.zones]}
            self.eng.set_off()
            self.eng._add_log("快捷键：全部熄灭")
        elif hid == 2:
            sv = getattr(self, "_night_saved", None)
            if sv:
                for i, z in enumerate(sv["zones"][:len(self.eng.zones)]):
                    self.eng.set_zone(i, effect=z.get("effect", "rainbow"),
                                      colors=list(z.get("colors", [])),
                                      leds=z.get("leds", 30),
                                      speed=z.get("speed", 45),
                                      brightness=z.get("brightness", 100),
                                      direction=z.get("direction", 0))
                self.eng.set_master(brightness=sv["master"])
                self.sl_master.setValue(sv["master"])
                self.eng._add_log("快捷键：已恢复")
                self._night_saved = None
                self.refresh()

    # ------------------------------------------------------------------ 交互
    def _on_zone_changed(self, idx, kw):
        self.eng.set_zone(idx, **kw)

    def _on_identify(self, idx):
        zones = getattr(self.eng, "zones", [])
        z = zones[idx] if 0 <= idx < len(zones) else {}
        name = z.get("area") or ("灯带 %d" % (idx + 1))
        if not self.eng.connected:
            self.eng._add_log("定位「%s」：设备没连上，闪不了（点顶栏「重新连接」）" % name)
            return
        ok = self.eng.identify(idx)
        if ok:
            self.eng._add_log("定位「%s」：已闪一下，约 1.2 秒后自动还原" % name)
        else:
            self.eng._add_log("定位「%s」失败：设备拒绝写入" % name)

    def _on_master_bri(self, v):
        self.lbl_master.setText("%d%%" % v)
        self.eng.set_master(brightness=int(v))
        self._kb_follow_master()

    def _on_master_speed(self, v):
        self.lbl_speed.setText("%d%%" % v)
        self.eng.set_master(speed=int(v))

    def _on_reconnect(self):
        self.btn_reconnect.setEnabled(False)
        self.btn_reconnect.setText("正在重连…")
        QApplication.processEvents()
        ok = self.eng.reconnect()
        self.btn_reconnect.setEnabled(True)
        self.btn_reconnect.setText("重新连接")
        self.refresh()
        if not ok:
            self.lbl_banner.setText("还是没反应：把控制器 USB 拔下重插一次；"
                                    "不好拔就关机再开机（「重启」不行，软重启不给 USB 断电）。")

    def _on_autostart(self):
        try:
            from core import autostart
            autostart.set_enabled(self.sw_auto.isChecked())
        except Exception as e:
            print("autostart:", e)
        self._sync_autostart()

    def _sync_autostart(self):
        try:
            from core import autostart
            self.sw_auto.setChecked(bool(autostart.is_enabled()))
        except Exception:
            pass

    # ------------------------------------------------------------------ 预设
    def load_presets(self):
        self.chips.removeWidget(self.lbl_no_preset)
        while self.chips.count() > 1:
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        names = []
        try:
            if self.presets_dir and os.path.isdir(self.presets_dir):
                names = sorted(f[:-5] for f in os.listdir(self.presets_dir) if f.endswith(".json"))
        except Exception:
            names = []
        for n in names:
            chip = QPushButton(n)
            chip.setObjectName("ghost")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setContextMenuPolicy(Qt.CustomContextMenu)
            chip.clicked.connect(lambda _=False, n=n: self._on_load_preset(n))
            chip.customContextMenuRequested.connect(
                lambda pos, n=n, w=chip: self._preset_menu(n, w, pos))
            self.chips.insertWidget(self.chips.count() - 1, chip)

        self.chips.insertWidget(0, self.lbl_no_preset)
        self.lbl_no_preset.setVisible(not names)

        # 程序联动用的预设下拉框也跟着刷新（尽量保留当前选择）
        if hasattr(self, "cmb_app_preset"):
            cur = self.cmb_app_preset.currentText()
            self.cmb_app_preset.clear()
            for n in names:
                self.cmb_app_preset.addItem(n)
            if cur:
                i = self.cmb_app_preset.findText(cur)
                if i >= 0:
                    self.cmb_app_preset.setCurrentIndex(i)

    def _preset_menu(self, name, widget, pos):
        m = QMenu(widget)
        act = m.addAction("删除这个预设")
        act.triggered.connect(lambda: self._on_delete_preset(name))
        m.exec(widget.mapToGlobal(pos))

    def _on_save_preset(self):
        name = self.txt_preset.text().strip()
        if not name:
            self.lbl_dev.setText("预设名不能为空")
            return
        safe = "".join(c for c in name if c not in '\\/:*?"<>|')[:40]
        import json
        data = {"zones": self.eng.zones, "master": self.eng.master}
        try:
            os.makedirs(self.presets_dir, exist_ok=True)
            with open(os.path.join(self.presets_dir, safe + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.txt_preset.clear()
            self.load_presets()
            self.eng._add_log("预设已保存：%s" % safe)
        except Exception as e:
            self.lbl_dev.setText("保存失败：%s" % e)

    def _on_load_preset(self, name):
        import json
        fp = os.path.join(self.presets_dir, name + ".json")
        if not os.path.exists(fp):
            self.lbl_dev.setText("预设「%s」的文件已经不在了，列表会自动刷新" % name)
            self.load_presets()
            return
        try:
            data = json.load(open(fp, "r", encoding="utf-8"))
            zs = data.get("zones", [])
            saved = {z["area"]: z for z in zs if "area" in z}
            for i, z in enumerate(self.eng.zones):
                s = saved.get(z["area"])
                if s is None and i < len(zs):
                    s = zs[i]          # 没有 area 字段的旧备份/外部备份：按顺序对应
                if s:
                    self.eng.set_zone(i, **{k: s[k] for k in
                                            ("effect", "colors", "speed", "brightness", "leds",
                                             "direction") if k in s})
            for k in ("brightness", "speed", "span", "fps"):
                if k in data.get("master", {}):
                    self.eng.master[k] = data["master"][k]
            self.sl_master.setValue(int(self.eng.master.get("brightness", 100)))
            self.sl_speed.setValue(max(5, min(100, int(self.eng.master.get("speed", 100)))))
            self.sw_span.setChecked(bool(self.eng.master.get("span", True)))
            self.eng._add_log("已载入预设：%s" % name)
            self.refresh()
        except Exception as e:
            self.eng._add_log("载入预设失败：%s" % e)

    def _on_delete_preset(self, name):
        try:
            fp = os.path.join(self.presets_dir, name + ".json")
            if os.path.exists(fp):
                os.remove(fp)
            self.load_presets()
        except Exception:
            pass

    # ------------------------------------------------------------------ 刷新
    def _on_anim(self):
        self._phase = (self._phase + 0.004) % 1.0
        for c in self.cards:
            c.preview.tick(self._phase)

    def refresh(self):
        snap = self.eng.snapshot()
        connected = snap["connected"]
        self.pill.setText(("%s · %d 路排针 · %.0f fps" % (snap["product"] or "已连接",
                                                         len(snap["zones"]), snap["fps"]))
                          if connected else "未连接 · 控制器无应答")
        self.pill.setObjectName("pillOn" if connected else "pill")
        self.pill.setStyleSheet("")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        if connected:
            self.banner.setVisible(False)
        else:
            self.banner.setVisible(True)
            if self.btn_reconnect.isEnabled():
                self.lbl_banner.setText((snap["error"] or "未检测到控制器。") + "  → 拔插一次，或关机再开机。")
        zones = snap["zones"]
        for i, card in enumerate(self.cards):
            if i < len(zones) and (card.zone is None or card.zone != zones[i]):
                if card.zone is None or self._differs(card.zone, zones[i]):
                    card.apply(zones[i], snap["master"])
        log = "\n".join(snap["log"])
        if log != self._last_log:
            self._last_log = log
            self.logbox.setPlainText(log)
            sb = self.logbox.verticalScrollBar()
            sb.setValue(sb.maximum())
        if not self.txt_preset.hasFocus():
            pass
        self.lbl_port.setText(("CDC 直通串口：%s" % snap["port"]) if snap["port"]
                              else "CDC 串口不可用（仅硬件模式可用）")

        # ---------------------------------------------------------- 系统监控
        sy = snap.get("sys") or {}
        cpu = sy.get("cpu")
        memv = sy.get("mem")
        gpu = sy.get("gpu")
        self._set_bar("cpu", cpu, "—" if cpu is None else "%.0f%%" % cpu)
        self._set_bar("mem", memv, "—" if memv is None else "%.0f%%" % memv)
        self._set_bar("gpu_util", gpu["util"] if gpu else 0,
                      "%.0f%%" % gpu["util"] if gpu else "不可用")
        self._set_bar("gpu_temp", gpu["temp"] if gpu else 0,
                      "%.0f°C" % gpu["temp"] if gpu else "不可用")
        vr = (gpu["vram_used"] / max(1.0, gpu["vram_total"]) * 100) if gpu else 0
        self._set_bar("vram", vr, ("%.0f / %.0f MB" % (gpu["vram_used"], gpu["vram_total"]))
                      if gpu else "不可用")
        self._set_bar("fps", snap["fps"], "%.1f" % snap["fps"])

        mhz = sy.get("mhz")
        self._set_bar("cpu_mhz", mhz or 0, ("%.0f MHz" % mhz) if mhz else "—")

        # CPU 温度 / 主板温度 / 风扇转速（来自 hwmon 组件）
        hw = sy.get("hw")
        if hw:
            pkg = hw.get("pkg")
            self._set_bar("cpu_temp", pkg or 0, ("%.0f°C" % pkg) if pkg else "—")
            mb = hw.get("mobo")
            self._set_bar("mobo", mb or 0, ("%.1f°C" % mb) if mb else "—")
            fan = hw.get("fan")
            self._set_bar("fan", fan or 0, ("%.0f RPM" % fan) if fan else "—")
            if hasattr(self, "btn_hwmon"):
                self.btn_hwmon.setVisible(False)
                self.lbl_hwmon.setText("温度监控已启用（内核驱动采集，每 2 秒刷新）")
                if hasattr(self, "lbl_note_mon"):
                    self.lbl_note_mon.setText("温度来自内核驱动采集（LibreHardwareMonitor）；"
                                              "风扇 PWM 也可以调（见「风扇调速」栏），点「交回 BIOS」即恢复主板曲线。")
        else:
            self._set_bar("cpu_temp", 0, "未启用")
            self._set_bar("mobo", 0, "未启用")
            self._set_bar("fan", 0, "未启用")
            if hasattr(self, "btn_hwmon"):
                self.btn_hwmon.setVisible(True)
                if not getattr(self, "_hwmon_hinted", False):
                    self._hwmon_hinted = True
                    self.lbl_hwmon.setText("CPU 温度 / 主板温度 / 风扇转速需要先授权一次（管理员）")
                if hasattr(self, "lbl_note_mon"):
                    self.lbl_note_mon.setText(
                        "数据每 1.5 秒刷新一次；CPU 温度 / 主板温度 / 风扇转速由内核驱动读取，"
                        "需要「启用温度监控」授权一次（管理员），之后开机自动生效。")
        self._set_bar("gpu_fan", gpu.get("fan") if gpu and gpu.get("fan") is not None else 0,
                      "%.0f%%" % gpu["fan"] if gpu and gpu.get("fan") is not None else "不可用")
        self._set_bar("gpu_power", (gpu.get("power") if gpu and gpu.get("power") is not None else 0),
                      ("%.0f W" % gpu["power"]) if gpu and gpu.get("power") is not None
                      else "不可用")
        self._set_bar("gpu_clock", (gpu.get("clock") if gpu and gpu.get("clock") is not None else 0),
                      ("%.0f MHz" % gpu["clock"]) if gpu and gpu.get("clock") is not None
                      else "不可用")
        dk = sy.get("disk")
        self._set_bar("disk", dk["used_pct"] if dk else 0,
                      ("%.0f%% · 剩 %.0f GB" % (dk["used_pct"], dk["free_gb"])) if dk else "—")
        up = sy.get("uptime")
        if up:
            h = int(up // 3600)
            m = int((up % 3600) // 60)
            self._set_bar("uptime", up, ("%d 小时 %d 分" % (h, m)) if h else ("%d 分钟" % m))
        else:
            self._set_bar("uptime", 0, "—")
        if hasattr(self, "lbl_spec"):
            info = pcctl.static_info()
            if info.get("cpu"):
                self.lbl_spec.setText("CPU %s（%s 线程）· 内存 %s×%sGB @%sMHz · %s"
                                      % (info.get("cpu", "?"), info.get("cores", "?"),
                                         info.get("memcount", "?"), info.get("memgb", "?"),
                                         info.get("memspeed", "?"), info.get("board", "?")))
        self._sync_fan_ui(hw)
        self._fan_apply_saved_once(hw)
        self._on_fan_curve_tick()
        self._fan_check()
        if hasattr(self, "lbl_mhz"):
            mz = sy.get("mhz")
            pk = (hw or {}).get("hwmon_mhz_max")
            if mz and pk:
                self.lbl_mhz.setText("CPU 频率：%.0f MHz（峰值 %.0f MHz）" % (mz, pk))
            elif mz:
                self.lbl_mhz.setText("CPU 频率：%.0f MHz" % mz)
        self._refresh_hw()

        # ---------------------------------------------------------- 联动状态
        lv = snap.get("live") or {}
        if lv.get("mode") == "music":
            self.lbl_mic.setText("麦克风电平 %.0f%%" % (lv.get("mic", 0) * 100))
        elif lv.get("mode") == "screen":
            self.lbl_mic.setText("分区取色 %s" % ("开" if lv.get("split") else "关"))
        elif lv.get("mode") == "temp":
            t = (gpu["temp"] if gpu else None)
            self.lbl_mic.setText("GPU %s" % ("%.0f°C" % t if t else "温度不可用"))
        else:
            self.lbl_mic.setText("")

        # ---------------------------------------------------------- 自动化
        self._check_night()
        self._check_apps()
        self._rot_tick()
        self._check_guard(snap)

        # ---------------------------------------------------------- 键盘灯效页
        try:
            if getattr(self, "kbd_page", None) is not None \
                    and self.tabs.currentWidget() is self.kbd_page:
                self._kb_sync_ui()
        except Exception:
            pass

    def _set_bar(self, key, value, text):
        bar = self.bars.get(key)
        lbl = self.vals.get(key)
        if bar is not None:
            v = int(max(0, min(bar.maximum(), value or 0)))
            bar.setValue(v)
        if lbl:
            lbl.setText(text)

    @staticmethod
    def _differs(a, b):
        keys = ("effect", "colors", "speed", "brightness", "leds")
        return any(a.get(k) != b.get(k) for k in keys)

    # ------------------------------------------------------------------ 托盘/退出
    def closeEvent(self, e):
        if self._quitting:
            e.accept()
            return
        e.ignore()
        self.hide()

    # ------------------------------------------------------------------ 无边框 / 自绘标题栏
    _TITLE_H = 74                      # 顶部条（就是新的标题栏）高度

    def _caption_button(self, kind, tip, close=False):
        b = QPushButton()
        b.setFixedSize(46, 30)
        b.setCursor(Qt.PointingHandCursor)
        b.setIcon(_cap_icon(kind))
        b.setIconSize(QSize(16, 16))
        b.setToolTip(tip)
        if close:
            b.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 4px; }"
                "QPushButton:hover { background: #c42b1c; }"
                "QPushButton:pressed { background: #8f1d12; }")
        else:
            b.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 4px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.12); }"
                "QPushButton:pressed { background: rgba(255,255,255,0.22); }")
        return b

    def _toggle_max(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _caption_is_drag(self, gpt):
        """这个屏幕点落在顶部条上时，能不能当拖动区（压到按钮/滑杆就不算）"""
        w = QApplication.widgetAt(gpt)
        while w is not None and w is not self:
            if isinstance(w, (QAbstractButton, QSlider, QComboBox, QLineEdit, QPlainTextEdit)):
                return False
            w = w.parentWidget()
        return True

    def nativeEvent(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG":
                msg = wt.MSG.from_address(int(message))
                if msg.message == WM_NCCALCSIZE and msg.wParam:
                    return self._on_nccalc(msg)
                if msg.message == WM_NCHITTEST:
                    return self._on_nchit(msg)
        except Exception:
            if os.environ.get("X99_DEBUG_NATIVE"):
                import traceback
                traceback.print_exc()
        return False, 0

    def _on_nccalc(self, msg):
        """客户区不再给标题栏留位置；最大化时严格贴显示器工作区"""
        hwnd = wt.HWND(msg.hWnd)
        params = ctypes.cast(msg.lParam, ctypes.POINTER(_NCCALCSIZE_PARAMS)).contents
        if _u32.IsZoomed(hwnd):
            mon = _u32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if mon and _u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcWork
                params.rgrc[0].left = r.left
                params.rgrc[0].top = r.top
                params.rgrc[0].right = r.right
                params.rgrc[0].bottom = r.bottom
        return True, 0

    def _on_nchit(self, msg):
        """边缘 6px 交给系统缩放；顶部条交给系统当标题栏（拖动/双击/右键菜单原生）"""
        hwnd = wt.HWND(msg.hWnd)
        lp = int(msg.lParam)
        sx = lp & 0xFFFF
        sy = (lp >> 16) & 0xFFFF
        sx = sx - 65536 if sx >= 32768 else sx
        sy = sy - 65536 if sy >= 32768 else sy
        gpt = QPoint(int(sx), int(sy))
        local = self.mapFromGlobal(gpt)
        x, y = local.x(), local.y()
        w, h = self.width(), self.height()
        if not _u32.IsZoomed(hwnd):
            e = EDGE_HIT
            left, right = x < e, x >= w - e
            top, bottom = y < e, y >= h - e
            if left and top:
                return True, HT["topleft"]
            if right and top:
                return True, HT["topright"]
            if left and bottom:
                return True, HT["bottomleft"]
            if right and bottom:
                return True, HT["bottomright"]
            if left:
                return True, HT["left"]
            if right:
                return True, HT["right"]
            if top:
                return True, HT["top"]
            if bottom:
                return True, HT["bottom"]
        if 0 <= y < self._TITLE_H and 0 <= x < w and self._caption_is_drag(gpt):
            return True, HT["caption"]
        return False, 0

    def changeEvent(self, e):
        super().changeEvent(e)
        try:
            if e.type() == QEvent.WindowStateChange and getattr(self, "_btn_max", None):
                self._btn_max.setIcon(_cap_icon("restore" if self.isMaximized() else "max"))
        except Exception:
            pass

    # ------------------------------------------------------------------ 更新检测
    def _start_update_check(self, manual=False):
        if getattr(self, "_update_worker", None) is not None and self._update_worker.isRunning():
            return
        self._update_worker = _UpdateWorker(ABOUT_VERSION, self)
        self._update_worker.done.connect(
            lambda info, err: self._on_update_result(info, err, manual))
        self._update_worker.start()

    def _on_update_result(self, info, err, manual):
        if info is None:
            if manual:
                QMessageBox.warning(self, "检查更新",
                                    "检查更新失败：网络不通或 GitHub 暂时不可用。\n%s" % err)
            return
        if info.get("up_to_date"):
            if manual:
                QMessageBox.information(self, "检查更新", "当前已是最新版本 v%s。" % ABOUT_VERSION)
            return

        tag = info.get("tag") or ""
        url = info.get("url") or updatecheck.RELEASES_URL
        body = (info.get("body") or "").strip()
        if len(body) > 500:
            body = body[:500] + "…"
        text = "发现新版本 %s（当前 v%s）。\n\n%s\n\n是否打开浏览器前往下载页面？" % (
            tag, ABOUT_VERSION, body)
        box = QMessageBox(self)
        box.setWindowTitle("发现新版本")
        box.setText(text)
        box.setIcon(QMessageBox.Information)
        btn_web = box.addButton("前往下载", QMessageBox.AcceptRole)
        box.addButton("稍后再说", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_web:
            QDesktopServices.openUrl(QUrl(url))

    def _show_about(self):
        dlg = AboutDialog(self, on_check=lambda: self._start_update_check(manual=True))
        dlg.exec()

    # ------------------------------------------------------------------ 关于作者（标签页）
    def _tab_about(self):
        th = theme()
        w = QWidget()
        w.setStyleSheet(
            'QLabel { font-size: 12px; }'
            'QLabel#abName { color: #ffffff; font-size: 21px; font-weight: 800; }'
            'QLabel#abVer { color: #8b8d97; font-size: 11px; }'
            'QLabel#abSec { color: %s; font-size: 12px; font-weight: 700; }'
            'QLabel#abMuted { color: #80838d; font-size: 11px; }' % th["acc"])
        root = QHBoxLayout(w)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(26)

        left = QVBoxLayout()
        left.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(10)
        logo = QLabel("X99")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(42, 42)
        logo.setStyleSheet("background: %s; color: #ffffff; border-radius: 7px;"
                           " font-size: 15px; font-weight: 800;" % th["acc"])
        head.addWidget(logo)
        nm = QLabel("X99 控制台")
        nm.setObjectName("abName")
        head.addWidget(nm)
        head.addStretch(1)
        ver = QLabel("v%s · 纯 Qt 原生 · 无 WebView" % ABOUT_VERSION)
        ver.setObjectName("abVer")
        head.addWidget(ver)
        left.addLayout(head)
        left.addSpacing(10)
        s1 = QLabel("这个程序是什么")
        s1.setObjectName("abSec")
        left.addWidget(s1)
        intro = QLabel('厂家那套 ARGB 软件卡、糊、还爱掉线，所以照 OpenRGB 把控制器重新逆向了一遍：\n'
                       'HID 64 字节报文握手 + CDC 串口直通下发，5 路排针各 100 颗灯珠逐颗可控，实测稳定 39–40 fps。\n'
                       '界面全是 PySide6 原生控件，没有 HTML、没有 WebView；完整改动清单与第三方许可见页脚「关于」。')
        intro.setWordWrap(False)
        intro.setFixedHeight(66)
        left.addWidget(intro)
        left.addSpacing(8)
        s_follow = QLabel("关注作者")
        s_follow.setObjectName("abSec")
        left.addWidget(s_follow)
        follow = follow_label(CYAN)
        left.addWidget(follow)
        fol_tip = QLabel("更新日志、装机视频、BIOS 折腾记录都发在这两个号上")
        fol_tip.setObjectName("abMuted")
        fol_tip.setWordWrap(True)
        left.addWidget(fol_tip)
        left.addStretch(1)
        root.addLayout(left, 3)

        right = _donate_block(320, 168, "支付宝扫码请作者喝杯咖啡（点图可放大再扫），不打赏也照常免费使用。")
        right.addStretch(1)
        root.addLayout(right, 4)
        return w

    def really_quit(self):
        self._quitting = True
        try:
            self._unregister_hotkeys()
        except Exception:
            pass
        try:
            self.eng.stop()
        except Exception:
            pass
        QApplication.quit()


# ---------------------------------------------------------------------- 关于 / 支持作者
def _asset_path(name):
    """assets 下的资源：源码模式读项目目录，打包后读 _internal"""
    for base in (getattr(sys, "_MEIPASS", None), BASE_DIR, APP_DIR):
        if not base:
            continue
        p = os.path.join(base, "assets", name)
        if os.path.exists(p):
            return p
    return os.path.join(BASE_DIR, "assets", name)


ABOUT_VERSION = "1.6.3"
ABOUT_FEATS = [
    "6 套皮肤，页脚下拉即换：ROG 红黑 / 冰川蓝 / 星云紫 / 翡翠绿 / 琥珀橙 / 极简钢灰",
    "5 路独立特效 + 总亮度 / 总速度 / 联排 / 帧率；6 个情景模式一键换整套风格；灯效轮播、过热守护",
    "实时联动：屏幕氛围同步、音乐律动、温度联动",
    "系统监控 15 项全部带动态状态条，含 CPU 温度 / 主板温度 / 风扇转速（内核驱动，授权一次）",
    "硬件与控制：性能模式、CPU 上限、WiFi / 蓝牙开关、小键盘默认状态",
    "风扇调速：5 路 PWM 手动 / 一键全速 / 静音 40% / 按温度智能曲线 / 交回 BIOS（四个模式按钮等高同宽、点哪个亮哪个）",
    "软超频三档（静音 / 均衡 / 狂暴）+ CPU 频率实时显示",
    "自动化：夜间模式、程序联动、全局快捷键；预设 zip 导入导出",
    "开机 LOGO：换 BIOS 那张开机图，800×600 自动缩放，生成镜像后随刷写盘一起刷",
    "鸡血 BIOS：校验精粤官方原版/鸡血包、一键铺 U 盘刷写盘、跑分对比全核频率（固件仍由你自己刷）",
    "托盘常驻、**右键菜单直达每一页**（7 个标签页 + 灯效 / 皮肤 / 风扇 / 性能档），单实例单窗口、开机自启、安装包一键装",
]


def _about_info_block(text_min_width=None, plain=False):
    """「这个程序是什么」+「都已经做了」两段（关于窗口与「关于作者」页共用）

    plain=True 时用纯文本（QLabel 自带行距，tab 页里高度可算得准），
    默认用富文本带 150% 行距（弹窗里更舒展）。
    """
    lv = QVBoxLayout()
    lv.setSpacing(5)
    s1 = QLabel("这个程序是什么")
    s1.setObjectName("abSec")
    lv.addWidget(s1)
    intro = ('厂家那套 ARGB 软件卡、糊、还爱掉线，'
             '所以照 OpenRGB 把控制器重新逆向了一遍：HID 64 字节报文握手 + CDC 串口直通下发，'
             '5 路排针各 100 颗灯珠逐颗可控，实测稳定 39–40 fps。界面全是 PySide6 原生控件，'
             '没有 HTML、没有 WebView、也没有本地 HTTP 服务。')
    if plain:
        # tab 页里空间窄且布局会抢高度，干脆手工分好行，行数固定就不会被压成一坨
        t1 = QLabel('厂家那套 ARGB 软件卡、糊、还爱掉线，所以照 OpenRGB 把控制器重新逆向了一遍：\n'
                    'HID 64 字节报文握手 + CDC 串口直通下发，5 路排针各 100 颗灯珠逐颗可控，实测稳定 39–40 fps。\n'
                    '界面全是 PySide6 原生控件，没有 HTML、没有 WebView、也没有本地 HTTP 服务。')
        t1.setWordWrap(False)
        t1.setFixedHeight(64)
    else:
        t1 = QLabel('<p style="line-height:150%%; margin:0;">%s</p>' % intro)
        t1.setTextFormat(Qt.RichText)
        t1.setWordWrap(True)
    if text_min_width:
        # wordWrap 的 QLabel 在布局里按给定宽度算行高，避免被压成一行
        t1.setMinimumWidth(text_min_width)
    lv.addWidget(t1)
    lv.addSpacing(10)
    s2 = QLabel("都已经做了")
    s2.setObjectName("abSec")
    lv.addWidget(s2)
    for f in ABOUT_FEATS:
        if plain:
            lb = QLabel("· " + f)
        else:
            lb = QLabel('<p style="line-height:150%%; margin:0;">· %s</p>' % f)
            lb.setTextFormat(Qt.RichText)
        lb.setObjectName("abMuted")
        if plain:
            lb.setWordWrap(False)
            lb.setFixedHeight(19)
        else:
            lb.setWordWrap(True)
        lv.addWidget(lb)
    return lv


FOLLOW_BILI = "https://search.bilibili.com/all?keyword=Kcs1993"
FOLLOW_DY = "https://www.douyin.com/search/CK2768"


def follow_label(color=None):
    """「B 站 Kcs1993 / 抖音 CK2768」一行（关于作者页与「关于」弹窗共用）"""
    c = color or theme()["acc"]
    lb = QLabel('B 站&nbsp;&nbsp;<a href="%s" style="color:%s; text-decoration:none;">Kcs1993</a>'
                '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;抖音&nbsp;&nbsp;'
                '<a href="%s" style="color:%s; text-decoration:none;">CK2768</a>'
                % (FOLLOW_BILI, c, FOLLOW_DY, c))
    lb.setTextFormat(Qt.RichText)
    lb.setOpenExternalLinks(True)
    lb.setToolTip("B 站 Kcs1993　抖音 CK2768（点一下直接在浏览器里打开搜索页）")
    lb.setCursor(Qt.PointingHandCursor)
    return lb


def _donate_block(img_w=470, img_h=352, tip_text=None):
    """「支持作者」+ 捐赠二维码（点一下放大）"""
    rv = QVBoxLayout()
    rv.setSpacing(6)
    s3 = QLabel("支持作者")
    s3.setObjectName("abSec")
    s3.setAlignment(Qt.AlignHCenter)      # 跟下面的二维码居中对齐，别一个左一个中
    rv.addWidget(s3)
    pix = QPixmap(_asset_path("donate.jpg"))
    if pix.isNull():
        shot = QLabel("（找不到 assets\\donate.jpg）")
        shot.setStyleSheet("color: #ff9f43;")
    else:
        shot = _ZoomLabel(pix)
        shot.setPixmap(pix.scaled(img_w, img_h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    shot.setAlignment(Qt.AlignCenter)
    shot.setFixedHeight(img_h)     # 钉死高度，别让 tab 页的布局把它压扁裁掉
    rv.addWidget(shot)
    tip = QLabel(tip_text if tip_text else
                 "支付宝扫码请作者喝杯咖啡（点图片可放大再扫）；\n"
                 "不打赏也照常免费使用，功能一个都不少。")
    tip.setObjectName("abMuted")
    tip.setWordWrap(True)
    tip.setAlignment(Qt.AlignHCenter)
    rv.addWidget(tip)
    return rv


class _ZoomLabel(QLabel):
    """可点击放大的图片（捐赠二维码用）"""

    def __init__(self, pix, parent=None):
        super().__init__(parent)
        self._pix = pix
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if self._pix is not None and not self._pix.isNull():
            ZoomDialog(self._pix, self.window()).exec()
        super().mouseReleaseEvent(e)


class FanNoteDialog(QDialog):
    """风扇调速说明：为什么软件调不动，以及这块板要怎么调。

    纯 Qt 控件，没有 HTML —— 和主界面一样是原生窗口。
    """

    _SECTIONS = (
        ("软件这边是怎么工作的",
         "主界面是普通权限，不直接写芯片。点按钮后它把命令交给常驻的「X99硬件监控」（管理员），"
         "由它用 LibreHardwareMonitor 去写 Nuvoton Super I/O 的 PWM 占空比寄存器。\n"
         "写完之后会回读一次，但回读拿到的是硬件监控库自己记住的值 —— 只证明「命令收下了」，"
         "不证明风扇真的转了。所以 v1.4.6 起多了一步：写完等 4.5 秒再比一次转速，动了才算有效。"),
        ("这台机器的实测结果",
         "芯片 Nuvoton NCT6779D，5 路 PWM 通道都在；但只有 Fan #2 读得到转速，"
         "其余 4 路恒为 0（排针空着，或风扇没接测速线）。\n"
         "把占空比从 0% → 20% → 40% → 100% 走了一遍，Fan #2 始终 1931–1956 RPM，"
         "连 0% 都不停转。结论：寄存器写进去了，风扇不跟。"),
        ("为什么会这样（三种可能）",
         "1. 3-pin 风扇插在 4-pin PWM 口上 —— 最常见。3-pin 没有 PWM 信号线，只吃电压，"
         "插在 PWM 口会恒速全转，软件写占空比完全没用。\n"
         "2. 风扇实际由主板 EC 或 BIOS 的 Smart Fan 掌管，Super I/O 的 PWM 引脚没接到风扇排针。\n"
         "3. BIOS 里把「风扇软件调速」的使能位关了，外部写入被忽略。"),
        ("先确认是哪种",
         "拔下风扇看插头：4 根针（或 4 条线）是 PWM 风扇，3 根针就是 3-pin。\n"
         "本机只有一个风扇有转速，大概率就是 CPU 风扇。"),
        ("进 BIOS 怎么调",
         "1. 重启，开机按 Del 或 F2 进 BIOS。\n"
         "2. 找 Hardware Monitor / Smart Fan / Q-Fan / Fan Control 这一类页面。\n"
         "3. 每个风扇通道（CPU_FAN、SYS_FAN1…）通常可选 Auto / PWM / DC / Manual。\n"
         "4. 3-pin 风扇选 DC；4-pin 风扇选 PWM；想自己定曲线就选 Manual。\n"
         "5. 按 F10 保存退出。"),
        ("软件这边还能做什么",
         "温度、转速、电压这些监控项是真实有效的，照常看。\n"
         "调速按钮不会再假装成功了 —— 判定无效的那一路会标红字「调速无效」，"
         "并在这里给出去 BIOS 调的建议。"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        th = theme()
        acc, acc2 = th["acc"], th["acc2"]
        self.setWindowTitle("风扇调速说明")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(720, 640)
        self.setStyleSheet(
            'QDialog { background: #0a0a0d; }'
            'QLabel { color: #c9ccd4; font-size: 12px; }'
            'QLabel#fnTitle { color: #ffffff; font-size: 17px; font-weight: 800; }'
            'QLabel#fnSub { color: #80838d; font-size: 11px; }'
            'QLabel#fnSec { color: %s; font-size: 12px; font-weight: 700; }'
            'QFrame#fnLine { background: rgba(255,255,255,0.10); border: none; }'
            'QPushButton#fnClose { background: %s; color: #ffffff; border: none; border-radius: 3px;'
            ' padding: 8px 28px; font-weight: 700; }'
            'QPushButton#fnClose:hover { background: %s; }'
            % (acc, acc, acc2))

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 16)
        root.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(10)
        ico = QLabel("风扇")
        ico.setAlignment(Qt.AlignCenter)
        ico.setFixedSize(50, 50)
        ico.setStyleSheet("background: %s; color: #ffffff; border-radius: 8px;"
                          " font-size: 15px; font-weight: 800;" % acc)
        head.addWidget(ico)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        t = QLabel("风扇调速说明")
        t.setObjectName("fnTitle")
        tv.addWidget(t)
        sub = QLabel("为什么按了没反应 · 本机实测结论 · 进 BIOS 怎么调")
        sub.setObjectName("fnSub")
        tv.addWidget(sub)
        head.addLayout(tv)
        head.addStretch(1)
        root.addLayout(head)

        line = QFrame()
        line.setObjectName("fnLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        for title, body in self._SECTIONS:
            root.addSpacing(3)
            sec = QLabel(title)
            sec.setObjectName("fnSec")
            root.addWidget(sec)
            lb = QLabel(body)
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(lb)

        root.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("关闭")
        btn.setObjectName("fnClose")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        root.addLayout(row)
        # 标题栏跟着窗口一起深色，不留一条浅灰系统标题栏
        QTimer.singleShot(0, lambda: apply_dwm_titlebar(self, caption="#0a0a0d"))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(e)


class ZoomDialog(QDialog):
    """把二维码放大到屏幕 60% 宽，方便手机扫。

    关闭方式给足三条：右下角「关闭」按钮、点图/点窗口任意处、按 Esc。
    """

    def __init__(self, pix, parent=None):
        super().__init__(parent)
        self.setWindowTitle("支持作者 · 扫码")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        scr = QApplication.primaryScreen().availableGeometry()
        max_w = int(scr.width() * 0.6)
        max_h = int(scr.height() * 0.8) - 84      # 留出底部提示 + 关闭按钮
        w = min(max_w, pix.width())
        h = max(1, pix.height() * w // pix.width())
        if h > max_h:
            h = max_h
            w = max(1, pix.width() * h // pix.height())
        self.setFixedSize(w + 24, h + 92)
        self.setStyleSheet(
            'QDialog { background: #0a0a0d; }'
            'QLabel { color: #80838d; font-size: 11px; }'
            'QPushButton#zoomClose { background: %s; color: #ffffff; border: none;'
            ' border-radius: 3px; padding: 6px 26px; font-weight: 700; font-size: 12px; }'
            'QPushButton#zoomClose:hover { background: #ffffff; color: #0a0a0d; }'
            % theme()["acc"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        lb = QLabel()
        lb.setAlignment(Qt.AlignCenter)
        lb.setPixmap(pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(lb, 1)
        hint = QLabel("点图片、点窗口任意处，或按 Esc 都能关掉这个放大窗口")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)
        btn = QPushButton("关闭")
        btn.setObjectName("zoomClose")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        # 标题栏跟着窗口一起深色（v1.4.4）：不放这一句，系统会给它一条浅灰原生标题栏
        QTimer.singleShot(0, lambda: apply_dwm_titlebar(self, caption="#0a0a0d"))

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()
        self.raise_()
        self.setFocus()

    def mousePressEvent(self, e):
        # 点窗口任意处直接关，避免"只有图没有按钮、关不掉"的尴尬
        self.accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(e)


class AboutDialog(QDialog):
    """关于 / 支持作者：功能介绍 + 捐赠二维码"""

    def __init__(self, parent=None, on_check=None):
        super().__init__(parent)
        self._on_check = on_check
        th = theme()
        acc, acc2 = th["acc"], th["acc2"]
        self.setWindowTitle("关于 X99 控制台")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setFixedSize(980, 738)      # 11 条功能 + 二维码 + 关注作者，596 会被内容顶开
        self.setStyleSheet(
            'QDialog { background: #0a0a0d; }'
            'QLabel { color: #d5d7de; font-size: 12px; }'
            'QLabel#abName { color: #ffffff; font-size: 25px; font-weight: 800; }'
            'QLabel#abTag { color: %s; font-size: 10px; font-weight: 700; }'
            'QLabel#abVer { color: #8b8d97; font-size: 11px; }'
            'QLabel#abSec { color: %s; font-size: 12px; font-weight: 700; }'
            'QLabel#abMuted { color: #80838d; font-size: 11px; }'
            'QFrame#abLine { background: rgba(255,255,255,0.10); border: none; }'
            'QPushButton#abClose { background: %s; color: #ffffff; border: none; border-radius: 3px;'
            ' padding: 8px 28px; font-weight: 700; }'
            'QPushButton#abClose:hover { background: %s; }'
            % (acc, acc, acc, acc2))

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(12)

        # ---------------------------------------------------------------- 标题行
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel("X99")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(54, 54)
        logo.setStyleSheet("background: %s; color: #ffffff; border-radius: 8px;"
                           " font-size: 19px; font-weight: 800;" % acc)
        head.addWidget(logo)
        tv = QVBoxLayout()
        tv.setSpacing(1)
        name = QLabel("X99 控制台")
        name.setObjectName("abName")
        tv.addWidget(name)
        sub = QLabel("JGINYUE X99M GAMING D3 · JIGUANG ARGB V2 · 5 路排针 · 逐颗直控")
        sub.setObjectName("abMuted")
        tv.addWidget(sub)
        head.addLayout(tv)
        head.addStretch(1)
        ver = QLabel("v%s\n纯 Qt 原生 · 无 WebView" % ABOUT_VERSION)
        ver.setObjectName("abVer")
        ver.setAlignment(Qt.AlignRight | Qt.AlignTop)
        head.addWidget(ver)
        root.addLayout(head)

        line = QFrame()
        line.setObjectName("abLine")
        line.setFixedHeight(1)
        root.addWidget(line)

        body = QHBoxLayout()
        body.setSpacing(24)

        # ---------------------------------------------------------------- 左：说明 + 功能
        lv = _about_info_block()
        lv.addStretch(1)
        body.addLayout(lv, 3)

        # ---------------------------------------------------------------- 右：支持作者
        rv = _donate_block(470, 352)
        rv.addSpacing(4)
        rv.addWidget(follow_label(acc))
        rv.addStretch(1)
        body.addLayout(rv, 4)
        root.addLayout(body, 1)

        # ---------------------------------------------------------------- 底部
        foot = QHBoxLayout()
        left = QLabel("协议参考 OpenRGB · 硬件监控基于 LibreHardwareMonitor（MPL-2.0）")
        left.setObjectName("abMuted")
        foot.addWidget(left)
        foot.addStretch(1)
        if self._on_check is not None:
            btn_check = QPushButton("检查更新")
            btn_check.setObjectName("ghost")
            btn_check.clicked.connect(self._on_check)
            foot.addWidget(btn_check)
            foot.addSpacing(10)
        btn = QPushButton("关闭")
        btn.setObjectName("abClose")
        btn.clicked.connect(self.accept)
        foot.addWidget(btn)
        root.addLayout(foot)
        QTimer.singleShot(0, lambda: apply_dwm_titlebar(self, caption="#0a0a0d"))
