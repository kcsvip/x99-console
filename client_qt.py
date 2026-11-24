# -*- coding: utf-8 -*-
"""
X99 控制台 · Qt 原生桌面客户端（无 HTML / 无 WebView / 无本地 HTTP 服务）

引擎线程照旧跑在 core.engine.Engine 里，界面是纯 Qt 控件，两者在同一进程内直接调用。

用法：
    python client_qt.py               开窗口
    python client_qt.py --minimized   只出托盘（开机自启用）

单实例说明：用命名互斥量（CreateMutexW）判断，比 socket 探活可靠；
第二次启动不会再开窗口，而是把已经在跑的那个窗口叫到前台。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

FROZEN = bool(getattr(sys, "frozen", False))
RES_DIR = getattr(sys, "_MEIPASS", BASE) if FROZEN else BASE
APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else BASE

MUTEX_NAME = "Local\\X99Console-ARGB-single"
IPC_NAME = "X99Console-ARGB-ipc"      # 命名管道：第二实例用它叫已有实例自己开窗
WIN_TITLE = "X99 控制台"
_MUTEX_HANDLE = None

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (QApplication, QLabel, QMenu, QSystemTrayIcon,
                              QWidgetAction)

from core.engine import Engine
from ui_qt import MainWindow, QSS, THEMES, set_theme_name


def already_running():
    """命名互斥量：已经有一个实例在跑就返回 True（原子操作，杀进程后不会留假锁）"""
    global _MUTEX_HANDLE
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wt.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    h = k32.CreateMutexW(None, False, MUTEX_NAME)
    err = ctypes.get_last_error()
    if not h:
        return False
    if err == 183:                      # ERROR_ALREADY_EXISTS
        try:
            k32.CloseHandle(h)
        except Exception:
            pass
        return True
    _MUTEX_HANDLE = h                   # 必须一直持有，否则锁会消失
    return False


def notify_existing():
    """用本地命名管道让已经在跑的那个实例**自己**开窗。

    这是关键：以前这里直接用 Win32 ShowWindow 从外面把窗口"掀"出来，
    Qt 并不知道窗口已经显示（内部 isVisible 仍是 False），无边框自绘窗口
    的子控件不会被重新绘制，用户看到的就是一个黑框。
    现在改成通知主实例，由它自己 show()/showNormal()，重绘才正常。
    """
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QLocalSocket

        app = QCoreApplication.instance() or QCoreApplication([])   # noqa: F841
        sock = QLocalSocket()
        sock.connectToServer(IPC_NAME)
        if not sock.waitForConnected(2000):
            return False
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(1500)
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.UnconnectedState:
            sock.waitForDisconnected(500)
        return True
    except Exception:
        return False


def activate_existing():
    """兜底：管道连不上（比如旧版本还在跑）时，才用 Win32 硬掀窗口。

    硬掀之后 Qt 不会重绘，所以这里补一次 RedrawWindow 强制重画整窗 + 子控件，
    尽量不留下黑框。
    """
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    found = []

    def cb(hwnd, _lp):
        n = u32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(96)
            u32.GetClassNameW(hwnd, cls, 96)
            if WIN_TITLE in buf.value and cls.value.startswith("Qt"):
                found.append(hwnd)
        return True

    try:
        u32.EnumWindows(enum_proc(cb), 0)
        for hwnd in found:
            u32.ShowWindow(hwnd, 5)     # SW_SHOW：从托盘隐藏态也能叫出来
            u32.ShowWindow(hwnd, 9)     # SW_RESTORE：最小化的还原
            u32.SetForegroundWindow(hwnd)
            # RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW
            u32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)
        return bool(found)
    except Exception:
        return False


def reveal(win):
    """把主窗口叫到前台（托盘隐藏 / 最小化 / 被其他窗口盖住都适用）。

    Qt 自己 show 才会走 showEvent 和重绘，所以托盘、管道通知都走这里。
    """
    if win.isMinimized():
        win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
    win.show()
    win.raise_()
    win.activateWindow()
    win.update()
    QTimer.singleShot(60, win.repaint)


def make_icon(path):
    if path and os.path.exists(path):
        ic = QIcon(path)
        if not ic.isNull():
            return ic
    # 兜底：程序内自己画一个，避免托盘空白
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#ff2d55"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 10, 10)
    p.setPen(QColor("#ffffff"))
    f = QFont("Microsoft YaHei", 17)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "X99")
    p.end()
    return QIcon(pm)


def build_tray_menu(win, engine):
    """托盘右键菜单：窗口里每个标签页、每类主要动作都在这里有对应项"""
    menu = QMenu()

    def show_win():
        reveal(win)

    def add(where, text, slot, checkable=False):
        a = QAction(text, menu)
        if checkable:
            a.setCheckable(True)
        if slot is not None:
            a.triggered.connect(slot)
        where.addAction(a)
        return a

    def section(text):
        """分组标题：Qt 在 Windows 下不画 addSection 的文字，用 QLabel 顶替"""
        lab = QLabel(text)
        lab.setObjectName("menuSection")
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(lab)
        menu.addAction(wa)

    # ------------------------------------------------- 打开主界面 / 七个标签页
    add(menu, "打开主界面", show_win)
    section("界面 · 窗口里的标签页")

    def goto(idx):
        def _f(_checked=False):
            reveal(win)
            if 0 <= idx < win.tabs.count():
                win.tabs.setCurrentIndex(idx)
        return _f

    for i in range(win.tabs.count()):
        add(menu, win.tabs.tabText(i), goto(i))

    # ------------------------------------------------- 灯效
    section("灯效")
    add(menu, "全部熄灭", lambda _c=False: win.tray_lights(True))
    add(menu, "恢复灯效", lambda _c=False: win.tray_lights(False))

    # ------------------------------------------------- 键盘灯效（GK10 98W 直连）
    m_kb = menu.addMenu("键盘灯效")
    add(m_kb, "开灯", lambda _c=False: win._kb_power(True))
    add(m_kb, "关灯", lambda _c=False: win._kb_power(False))
    add(m_kb, "重新检测键盘", lambda _c=False: win._kb_reconnect())
    m_kb_mode = m_kb.addMenu("灯效模式（20 种）")
    for i in range(20):
        add(m_kb_mode, "%02d %s" % (i + 1, win.kbd.mode_name(i)),
            lambda _c=False, k=i: win._kb_mode(k))
    m_kb_color = m_kb.addMenu("色位（8 个）")
    for i in range(8):
        add(m_kb_color, "色位 %d · %s" % (i + 1, win.kbd.color_name(i)),
            lambda _c=False, k=i: win._kb_color(k))
    m_kb_fx = m_kb.addMenu("软件动效")
    for key, label in [("breath", "呼吸"), ("rainbow", "彩虹流转"),
                       ("strobe", "频闪"), ("jump", "跳色"),
                       ("fade", "渐变"), ("pulse", "心跳")]:
        add(m_kb_fx, label, lambda _c=False, k=key: win._kb_fx_start(k))
    add(m_kb_fx, "停止动效", lambda _c=False: win._kb_fx_stop())
    add(m_kb, "色位校准", lambda _c=False: (win.tabs.setCurrentIndex(6), win._kb_cal_start()))
    add(m_kb, "改模式名", lambda _c=False: win._kb_rename_modes())

    # ------------------------------------------------- 鼠标（SMAILWOLF M3 直连）
    def tab_idx(name, default=0):
        for i in range(win.tabs.count()):
            if win.tabs.tabText(i) == name:
                return i
        return default

    m_ms = menu.addMenu("鼠标控制")
    add(m_ms, "读取鼠标配置", lambda _c=False: (reveal(win), win.tabs.setCurrentIndex(tab_idx("鼠标控制")),
                                          win._ms_read_all()))
    add(m_ms, "重新检测鼠标", lambda _c=False: win._ms_reconnect())
    m_ms_light = m_ms.addMenu("灯效模式（7 种）")
    for i, name in enumerate(win.mouse_light_names()):
        add(m_ms_light, "%d %s" % (i, name),
            lambda _c=False, k=i: win.tray_ms_light(k))
    add(m_ms_light, "关闭灯光", lambda _c=False: win.tray_ms_light(6))
    m_ms_rate = m_ms.addMenu("回报率")
    for i, hz in enumerate(win.mouse_rate_list()):
        add(m_ms_rate, "%d Hz" % hz, lambda _c=False, k=i: win.tray_ms_rate(k))
    m_ms_dpi = m_ms.addMenu("DPI 档位")
    for i in range(6):
        add(m_ms_dpi, "第 %d 档" % (i + 1), lambda _c=False, k=i: win.tray_ms_dpi(k))

    m_skin = menu.addMenu("皮肤")
    skin_group = QActionGroup(menu)
    skin_group.setExclusive(True)
    for key, cfg in THEMES.items():
        a = QAction(cfg["name"], m_skin)
        a.setCheckable(True)
        a.triggered.connect(lambda _c=False, k=key: win._on_theme(k))
        skin_group.addAction(a)
        m_skin.addAction(a)

    # ------------------------------------------------- 风扇（写入 Super I/O）
    section("风扇 · 直接写进主板")
    add(menu, "一键全速 100%", lambda _c=False: win._on_fan_all(100))
    add(menu, "静音 40%", lambda _c=False: win._on_fan_all(40))
    add(menu, "交回 BIOS（自动调速）", lambda _c=False: win._on_fan_bios())

    # ------------------------------------------------- 性能档
    section("性能档 · 电源策略")
    add(menu, "狂暴档（高性能 + Turbo 激进）", lambda _c=False: win._on_perf_profile("boost"))
    add(menu, "均衡档（系统默认）", lambda _c=False: win._on_perf_profile("balanced"))
    add(menu, "静音档（上限 80%）", lambda _c=False: win._on_perf_profile("silent"))

    # ------------------------------------------------- 程序
    section("程序")
    act_auto = add(menu, "开机自启", None, checkable=True)

    def toggle_auto(checked):
        from core import autostart
        autostart.set_enabled(bool(checked))
        try:
            win.sw_auto.blockSignals(True)
            win.sw_auto.setChecked(bool(checked))
            win.sw_auto.blockSignals(False)
            win._sync_autostart()
        except Exception:
            pass

    act_auto.toggled.connect(toggle_auto)
    add(menu, "关于 / 支持作者", lambda _c=False: win._show_about())
    add(menu, "退出程序", lambda _c=False: win.really_quit())

    # 每次弹出前同步勾选状态（自启、当前皮肤）
    def sync_menu():
        from core import autostart
        try:
            act_auto.setChecked(autostart.is_enabled())
        except Exception:
            pass
        cur = THEMES.get(getattr(engine, "theme_name", "rog"), {}).get("name")
        for a in skin_group.actions():
            a.setChecked(a.text() == cur)

    menu.aboutToShow.connect(sync_menu)
    return menu


def build_tray_activation(win):
    """托盘图标点击行为。

    - 双击：永远打开窗口（原来只处理了单击，双击的 DoubleClick 事件没人接，等于没反应）
    - 单击：切换显隐，但延迟 250ms 再执行，这样双击不会被"先隐藏"掉；
      判断时用 isMinimized()——最小化时 isVisible() 仍为 True，老代码正是踩在这里。
    """
    pending = {"timer": None}

    def show_win():
        reveal(win)

    def cancel():
        t = pending["timer"]
        if t is not None:
            t.stop()
            pending["timer"] = None

    def toggle():
        pending["timer"] = None
        if win.isVisible() and not win.isMinimized():
            win.hide()
        else:
            show_win()

    def on_tray(reason):
        if reason == QSystemTrayIcon.DoubleClick:
            cancel()
            show_win()
            return
        if reason == QSystemTrayIcon.Trigger:
            cancel()
            t = QTimer()
            t.setSingleShot(True)
            t.timeout.connect(toggle)
            pending["timer"] = t
            t.start(250)

    return on_tray


def main():
    ap = argparse.ArgumentParser(description="X99 控制台（Qt 原生界面）")
    ap.add_argument("--minimized", action="store_true", help="启动时只显示托盘图标")
    ap.add_argument("--tab", type=int, default=-1, help="启动后直接切到第 N 个标签页（调试用）")
    ap.add_argument("--about", action="store_true", help="启动后直接打开「关于」窗口")
    args = ap.parse_args()

    # ------------------------------------------------------------ 只允许一个窗口
    # 两个进程同时开会同时抢设备句柄（HID 独占 + COM5 独占），所以先拦在进程级
    if already_running():
        # 让已经在跑的那个实例自己把窗口开出来（它内部状态才是对的）。
        # 只有管道连不上（比如旧版本还在跑）才退回 Win32 硬掀。
        if not notify_existing():
            activate_existing()
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("X99 控制台")
    app.setQuitOnLastWindowClosed(False)   # 关窗口只收托盘

    data_dir = os.path.join(APP_DIR, "data")
    presets_dir = os.path.join(data_dir, "presets")
    os.makedirs(presets_dir, exist_ok=True)

    icon_path = os.path.join(RES_DIR, "assets", "tray.ico")
    icon = make_icon(icon_path)

    engine = Engine(os.path.join(data_dir, "config.json"))
    if not engine.connect():
        engine.attach_placeholders()
    engine.start()

    # 皮肤要在建窗口之前套上，避免先闪一下默认配色
    app.setStyleSheet(set_theme_name(getattr(engine, "theme_name", "rog")))

    win = MainWindow(engine, presets_dir, icon_path=icon_path,
                     start_minimized=bool(args.minimized))
    win.setWindowIcon(icon)

    # ------------------------------------------------- 单实例唤醒的接收端
    # 第二实例（点桌面快捷方式）会连这个命名管道，这里收到后由主实例自己开窗
    from PySide6.QtNetwork import QLocalServer

    ipc = QLocalServer(win)
    QLocalServer.removeServer(IPC_NAME)          # 清掉上次异常退出留下的残留
    ipc.listen(IPC_NAME)
    if not ipc.isListening():
        QLocalServer.removeServer(IPC_NAME)
        ipc.listen(IPC_NAME)

    def on_activate():
        while ipc.hasPendingConnections():
            conn = ipc.nextPendingConnection()
            try:
                conn.readAll()
                conn.disconnectFromServer()
            except Exception:
                pass
        reveal(win)

    ipc.newConnection.connect(on_activate)

    # ---------------------------------------------------------------- 托盘
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("X99 控制台 · ARGB")

    menu = build_tray_menu(win, engine)
    tray.setContextMenu(menu)

    tray.activated.connect(build_tray_activation(win))
    tray.show()

    def status_tip():
        s = engine.snapshot()
        if not s["connected"]:
            tray.setToolTip("X99 控制台 · 控制器未连接")
        else:
            tray.setToolTip("X99 控制台 · %d 路在线 · %.0f fps"
                            % (len(s["zones"]), s["fps"]))

    t = QTimer()
    t.timeout.connect(status_tip)
    t.start(2000)

    if not args.minimized:
        win.show()

    if args.tab >= 0:
        win.tabs.setCurrentIndex(min(args.tab, win.tabs.count() - 1))

    if args.about:
        QTimer.singleShot(300, win._show_about)

    rc = app.exec()
    try:
        engine.stop()
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
