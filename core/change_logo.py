# -*- coding: utf-8 -*-
"""AMI ChangeLogoPro 外部命令行工具封装（随安装包内置，可选调用）

合规说明：
  - ChangeLogoPro.exe 为 AMI 专有闭源工具，本地打包时从 `tools/` 目录收进安装包；
    开源源码仓库与 git **不包含**该二进制（见 NOTICE.md）。
  - 程序在「程序目录 / tools / 数据目录 / 界面指定路径」查找该 exe；找不到时
    相关功能给出明确提示，不报错崩溃。
  - 本模块只拼命令行、起子进程、回显输出；不做任何自动刷写固件。

已知限制（本机实测）：
  - 该工具按 ANSI/GBK 解析命令行路径，中文目录会被解码成乱码导致「文件不存在」，
    因此除只读的列出（/l）外，其余模式统一在纯 ASCII 临时目录里中转输入输出。
  - 在本块精粤 X9MPS007 自定义固件上，提取 / 重建 FFS 可能失败（GenFds C0DE）；
    本板换图请以界面上方的纯 Python 流程为准，外部工具面向标准 AMI 胶囊 BIOS。

命令行参数以官方 ChangeLogoPro 5.11 帮助为准：
  列出 Logo : <exe> /i <rom_in> /l
  提取大图 : <exe> /i <rom_in> /e <img_out>
  提取小图 : <exe> /i <rom_in> /e <img_out> /s
  替换大图 : <exe> /i <rom_in> /o <rom_out> /r <img> /f
  替换小图 : <exe> /i <rom_in> /o <rom_out> /r <img> /s /f
  非 BMP   : 追加 /cap（忽略后缀按 capsule 载入）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

# 社区版里出现过的两个可执行名，按顺序探测
EXE_NAMES = ("ChangeLogoPro.exe", "ChangeLogoWin64.exe")

MODE_SPLASH = "splash"
MODE_SMALL = "small"
MODE_EXTRACT = "extract"
MODE_LIST = "list"


def _candidate_dirs():
    """可能放置外部工具的目录（源码模式在工程根，打包后在 exe 旁 / _internal）。"""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    here = os.path.abspath(os.path.dirname(__file__))
    roots.append(os.path.dirname(here))          # core 的上一级 = 工程根
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
    dirs = list(roots)
    for base in roots:
        dirs.append(os.path.join(base, "data"))
        dirs.append(os.path.join(base, "tools"))
    return dirs


def find_tool(explicit: str | None = None) -> str | None:
    """按 显式路径 → 候选目录 顺序查找可用的 ChangeLogo 工具，返回完整路径或 None。"""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        if os.path.isdir(explicit):
            for name in EXE_NAMES:
                p = os.path.join(explicit, name)
                if os.path.isfile(p):
                    return p
        return None
    for d in _candidate_dirs():
        if not d:
            continue
        for name in EXE_NAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    return None


def _ascii_tmp() -> str:
    """挑一个纯 ASCII 路径的临时目录（工具按 ANSI 解析路径，中文会乱码）。"""
    for base in (r"C:\Windows\Temp", r"C:\Temp", tempfile.gettempdir()):
        try:
            os.makedirs(base, exist_ok=True)
            if all(ord(ch) < 128 for ch in base):
                return tempfile.mkdtemp(prefix="x99cl_", dir=base)
        except OSError:
            continue
    return tempfile.mkdtemp(prefix="x99cl_")


def build_cmd(mode: str, rom_in: str, image: str, rom_out: str | None,
              exe: str) -> list[str]:
    """拼命令行参数列表（不经过 shell，路径空格安全）。"""
    cmd = [exe, "/i", rom_in]
    if mode == MODE_LIST:
        cmd.append("/l")
    elif mode == MODE_EXTRACT:
        cmd += ["/e", image]
    else:
        cmd += ["/o", rom_out, "/r", image]
        if mode == MODE_SMALL:
            cmd.append("/s")
        cmd.append("/f")
        if not image.lower().endswith(".bmp"):
            cmd.append("/cap")
    return cmd


def run(mode: str, rom_in: str, image: str, rom_out: str | None = None,
        exe: str | None = None, timeout: int = 120) -> dict:
    """调用外部工具，返回 {ok, exe, cmd, rc, stdout, stderr, why}。

    mode: MODE_SPLASH / MODE_SMALL / MODE_EXTRACT / MODE_LIST
    rom_in:  输入 BIOS 镜像（.bin/.rom/.cap）
    image:   extract 时为导出图片路径；替换时为输入图片路径
    rom_out: 替换时为输出镜像路径（extract / list 不用）
    """
    tool = exe or find_tool()
    res = {"ok": False, "exe": tool, "cmd": [], "rc": -1,
           "stdout": "", "stderr": "", "why": ""}
    if not tool:
        res["why"] = "未找到 ChangeLogoPro.exe：可在界面里指定它的路径"
        return res
    if not os.path.isfile(rom_in):
        res["why"] = "输入镜像不存在：%s" % rom_in
        return res
    if mode in (MODE_SPLASH, MODE_SMALL):
        if not rom_out:
            res["why"] = "缺少输出镜像路径"
            return res
        if not image:
            res["why"] = "缺少输入图片路径"
            return res
    elif mode == MODE_EXTRACT:
        if not image:
            res["why"] = "缺少导出图片路径"
            return res
    elif mode != MODE_LIST:
        res["why"] = "未知模式：%s" % mode
        return res

    work_dir = None
    try:
        if mode == MODE_LIST:
            # 只读列出，实测中文镜像路径可正常读取，直接调用
            work_rom, work_img, work_out = rom_in, image, rom_out
        else:
            work_dir = _ascii_tmp()
            work_rom = os.path.join(work_dir, "rom.bin")
            shutil.copyfile(rom_in, work_rom)
            if mode in (MODE_SPLASH, MODE_SMALL):
                ext = os.path.splitext(image)[1].lower() or ".bmp"
                work_img = os.path.join(work_dir, "in" + ext)
                shutil.copyfile(image, work_img)
                work_out = os.path.join(work_dir, "out.bin")
            else:  # extract
                work_img = os.path.join(work_dir, "out.bmp")
                work_out = None

        res["cmd"] = build_cmd(mode, work_rom, work_img, work_out, tool)
        proc = subprocess.run(
            res["cmd"], capture_output=True, timeout=timeout, shell=False,
            cwd=work_dir, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        res["rc"] = proc.returncode
        res["stdout"] = (proc.stdout or b"").decode("gbk", errors="replace")
        res["stderr"] = (proc.stderr or b"").decode("gbk", errors="replace")
        res["ok"] = proc.returncode == 0
        if not res["ok"]:
            res["why"] = "工具返回码 %d" % proc.returncode

        # 把 ASCII 临时目录里的产物拷回用户选择的中文路径
        if res["ok"] and work_dir:
            if mode in (MODE_SPLASH, MODE_SMALL) and work_out and os.path.isfile(work_out):
                os.makedirs(os.path.dirname(rom_out), exist_ok=True)
                shutil.copyfile(work_out, rom_out)
            elif mode == MODE_EXTRACT and os.path.isfile(work_img):
                os.makedirs(os.path.dirname(image), exist_ok=True)
                shutil.copyfile(work_img, image)
    except subprocess.TimeoutExpired:
        res["why"] = "工具运行超时（%d 秒）" % timeout
    except OSError as e:
        res["why"] = "无法启动工具：%s" % e
    except Exception as e:                          # noqa: BLE001
        res["why"] = "调用异常：%s" % e
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
    return res
