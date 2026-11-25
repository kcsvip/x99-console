# -*- mode: python ; coding: utf-8 -*-
"""X99 控制台 · Qt 原生版打包脚本（PyInstaller）"""

import os

proj = os.path.dirname(SPECPATH)          # spec 放在 打包\ 下，proj 就是工程根目录

# 内置工具目录（ChangeLogoPro.exe，闭源第三方，不进开源仓库；本地打包时存在才收集）
_datas = [(os.path.join(proj, "assets"), "assets")]
_tools = os.path.join(proj, "tools")
if os.path.isdir(_tools):
    _datas.append((_tools, "tools"))

a = Analysis(
    [os.path.join(proj, "client_qt.py")],
    pathex=[proj],
    binaries=[],
    datas=_datas,
    hiddenimports=["hid", "serial"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "webview", "pythonnet", "clr_loader", "tkinter",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="X99控制台",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(proj, "assets", "tray.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="X99控制台",
)
