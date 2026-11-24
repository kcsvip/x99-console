# -*- coding: utf-8 -*-
"""
风扇调速配置持久化。

背景：Super I/O 里写进去的 PWM 占空比寄存器在重启后会被 BIOS 恢复成默认值，
所以光在界面里调完，下次开机又回到「跟随 BIOS」。这里把当前风扇模式和各路
百分比落盘到 data\\fan_profile.json，开机后由两条链路自动还原：

1. 常驻的「X99硬件监控」（最高权限计划任务）一启动就按这份档案直接写回 SIO；
2. 主界面起来后、hwmon 数据就绪，再补写一次并把界面滑块/模式按钮对齐到档案。

档案格式：
    {
      "mode": "manual" | "full" | "quiet" | "curve" | "bios",
      "values": [60, 55, 40, 60, 60],   // 各路软件占空比（curve 下作为兜底值）
      "global": 40,                      // 最近一次统一百分比（full/quiet）
      "ts": 1794843289
    }
"""

import json
import os
import time

FAN_COUNT = 5
PROFILE_NAME = "fan_profile.json"

# 软件控制类模式：开机需要把占空比写回 SIO；bios 表示用户主动交回，还原时什么都不做。
SW_MODES = {"manual", "full", "quiet", "curve"}
DEFAULT_VALUES = [60, 60, 60, 60, 60]


def profile_path(data_dir):
    if not data_dir:
        return None
    return os.path.join(data_dir, PROFILE_NAME)


def _normalize(values):
    out = list(DEFAULT_VALUES)
    if isinstance(values, list):
        for i in range(min(FAN_COUNT, len(values))):
            try:
                v = int(round(float(values[i])))
                out[i] = max(20, min(100, v))
            except (TypeError, ValueError):
                pass
    return out


def load(data_dir):
    """读取档案；缺失/损坏时返回默认的「跟随 BIOS」。"""
    prof = {"mode": "bios", "values": list(DEFAULT_VALUES), "global": None, "ts": 0}
    p = profile_path(data_dir)
    if not p or not os.path.exists(p):
        return prof
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return prof
        mode = d.get("mode")
        if mode in SW_MODES or mode == "bios":
            prof["mode"] = mode
        prof["values"] = _normalize(d.get("values"))
        g = d.get("global")
        prof["global"] = int(g) if g is not None else None
        prof["ts"] = int(d.get("ts") or 0)
    except Exception:
        pass
    return prof


def save(data_dir, mode, values=None, global_pct=None):
    """落盘当前风扇配置。mode=bios 表示交回 BIOS，不再自动还原软件占空比。"""
    p = profile_path(data_dir)
    if not p:
        return False
    try:
        prof = {
            "mode": mode if mode in SW_MODES or mode == "bios" else "bios",
            "values": _normalize(values),
            "global": int(global_pct) if global_pct is not None else None,
            "ts": int(time.time()),
        }
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def mark_bios(data_dir):
    return save(data_dir, "bios")
