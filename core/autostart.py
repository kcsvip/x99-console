# -*- coding: utf-8 -*-
"""
开机自启：在用户的「启动」文件夹里放 / 删一个 X99控制台.lnk

- 源码运行：目标是无控制台的 pythonw + client_qt.py --minimized（只出托盘，不弹窗）
- 安装包运行（PyInstaller 打包后）：目标就是程序自己，带 --minimized 参数
"""

import os
import subprocess
import sys

LNK_NAME = "X99控制台.lnk"

PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                  "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def startup_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def lnk_path():
    return os.path.join(startup_dir(), LNK_NAME)


def is_enabled():
    return os.path.isfile(lnk_path())


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _target():
    """返回 (可执行文件, 参数, 工作目录, 图标)"""
    exe = sys.executable
    root = _project_root()
    res = getattr(sys, "_MEIPASS", root) if getattr(sys, "frozen", False) else root
    ico = os.path.join(res, "assets", "tray.ico")

    if getattr(sys, "frozen", False):
        return exe, "--minimized", os.path.dirname(exe), ico

    pyw = exe
    if pyw.lower().endswith("python.exe"):
        cand = pyw[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(cand):
            pyw = cand
    return pyw, '"%s" --minimized' % os.path.join(root, "client_qt.py"), root, ico


def _ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def enable():
    exe, args, workdir, ico = _target()
    d = startup_dir()
    os.makedirs(d, exist_ok=True)
    link = lnk_path()

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); "
        "$s.TargetPath = %s; $s.Arguments = %s; $s.WorkingDirectory = %s; "
        "$s.WindowStyle = 7; $s.Description = 'X99 控制台 · ARGB'; "
    ) % (_ps_quote(link), _ps_quote(exe), _ps_quote(args), _ps_quote(workdir))
    if os.path.isfile(ico):
        script += "$s.IconLocation = %s; " % _ps_quote(ico + ",0")
    script += "$s.Save()"

    flags = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-Command", script],
                          capture_output=True, creationflags=flags)
    ok = os.path.isfile(link)
    msg = "已开启开机自启" if ok else ("开启失败：" + (proc.stderr or b"").decode("utf-8", "ignore")[:200])
    return {"ok": ok, "enabled": is_enabled(), "message": msg}


def disable():
    link = lnk_path()
    try:
        if os.path.isfile(link):
            os.remove(link)
        ok = not os.path.isfile(link)
        return {"ok": ok, "enabled": is_enabled(), "message": "已关闭开机自启" if ok else "关闭失败"}
    except Exception as e:
        return {"ok": False, "enabled": is_enabled(), "message": "关闭失败：%s" % e}


def set_enabled(on):
    return enable() if on else disable()


def state():
    return {"enabled": is_enabled(), "path": lnk_path()}
