# -*- coding: utf-8 -*-
"""
引擎层：状态管理 + 逐帧渲染 + 硬件推送 + 断线自恢复 + 预览数据
"""

import json
import os
import threading
import time

from . import effects
from . import pcctl as _pcctl
from .device import (ArgbDevice, HW_MODES, hw_color_count, AREA_NAMES, MODE_OFF,
                     MODE_DIRECT, MODE_STATIC)
from . import sysinfo as _sysinfo
from .live import LiveHub

DEFAULT_ZONE = {
    "effect": "rainbow",
    "colors": ["#00d0ff", "#ff3b6b", "#ffd166", "#7bffb2"],
    "speed": 45,
    "brightness": 100,
    "leds": 30,
    "direction": 0,
}

IMPORTANT_NOTE = ("Direct 逐颗模式需要 CDC 串口；若日志提示串口不可用，"
                  "请确认主板 ARGB 的 USB 接口没有被禁用")


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


class Engine:
    def __init__(self, config_path=None):
        self.dev = ArgbDevice()
        self.lock = threading.RLock()
        self.zones = []
        self.master = {
            "brightness": 100,
            "speed": 100,        # 总速度（%），乘到每一路自己的 speed 上
            "span": True,        # 联排：效果跨 5 路排针连续
            "fps": 40,
            "running": True,
        }
        self.config_path = config_path
        self.theme_name = "rog"        # 界面皮肤（config 里持久化）
        self._t0 = time.perf_counter()
        self._stop = False
        self._thread = None
        self._preview = {"zones": [], "fps": 0}
        self._zeroed = set()
        self._frames = 0
        self._fps_t = time.perf_counter()
        self._fps = 0
        self._override = {}      # {index: (color, expire_ts)}
        self._reconnect_at = 0
        self._err_log_t = 0
        self.log = []
        self._dirty = False
        self.sysinfo = _sysinfo.SysInfo(os.path.dirname(os.path.abspath(config_path)))
        # 风扇调速要经「X99硬件监控」转手，它读写的是同一个 data 目录
        try:
            _pcctl.set_hwmon_dir(os.path.dirname(os.path.abspath(config_path)))
        except Exception:
            pass
        self.live = LiveHub(self.sysinfo)

    # ------------------------------------------------------------ 生命周期
    def _add_log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log.append("[%s] %s" % (ts, msg))
        if len(self.log) > 120:
            self.log = self.log[-120:]

    def connect(self):
        ok = self.dev.open()
        if ok:
            self._add_log("已连接 %s%s" % (self.dev.product,
                                       "，直通串口 " + self.dev.port if self.dev.port else "（无 CDC 串口）"))
            self._build_zones()
            self._load_config()
            # 上电先按保存的配置还原
            for i in range(len(self.zones)):
                self._apply_zone(i, initial=True)
        else:
            self._add_log(self.dev.last_error or "连接失败")
            self._err_log_t = time.perf_counter()   # 避免主循环立刻重复记一条
        return ok

    def reconnect(self):
        """界面「重新连接」按钮：丢掉旧句柄重新打开一次。"""
        self._add_log("手动重新连接…")
        try:
            self.dev.close()
        except Exception:
            pass
        self._reconnect_at = 0
        return self.connect()

    def attach_placeholders(self):
        """设备没连上时也先铺出 5 路空卡片，界面不至于空白"""
        if self.zones:
            return
        for area in (0x04, 0x08, 0x10, 0x20, 0x40):
            z = dict(DEFAULT_ZONE)
            z.update({"area": area, "name": AREA_NAMES.get(area, "ARGB 排针"),
                      "max_leds": 100})
            self.zones.append(z)
        self._load_config()

    def _build_zones(self):
        old = {z["area"]: z for z in self.zones}
        self.zones = []
        for d in self.dev.zones:
            z = dict(DEFAULT_ZONE)
            z["area"] = d["area"]
            z["name"] = d["name"]
            z["max_leds"] = d["max_leds"]
            if d["area"] in old:
                z.update(old[d["area"]])
            self.zones.append(z)

    # ------------------------------------------------------------ 配置持久化
    def _load_config(self):
        if not self.config_path or not os.path.exists(self.config_path):
            return
        try:
            data = json.load(open(self.config_path, "r", encoding="utf-8"))
            saved = {z["area"]: z for z in data.get("zones", [])}
            for z in self.zones:
                if z["area"] in saved:
                    s = saved[z["area"]]
                    for k in ("effect", "colors", "speed", "brightness", "leds", "direction"):
                        if k in s:
                            z[k] = s[k]
            for k in ("brightness", "speed", "span", "fps"):
                if k in data.get("master", {}):
                    self.master[k] = data["master"][k]
            th = data.get("ui", {}).get("theme")
            if th:
                self.theme_name = th
        except Exception as e:
            self._add_log("读取配置失败：%s" % e)

    def save(self):
        if not self.config_path:
            return
        try:
            data = {"zones": [{k: z[k] for k in ("area", "name", "effect", "colors",
                                                "speed", "brightness", "leds", "direction")}
                              for z in self.zones],
                    "master": self.master,
                    "ui": {"theme": getattr(self, "theme_name", "rog")}}
            tmp = self.config_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_path)
        except Exception as e:
            self._add_log("保存配置失败：%s" % e)

    # ------------------------------------------------------------ 启动/停止
    def start(self):
        self.sysinfo.start()
        self._thread = threading.Thread(target=self._loop, name="argb-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        try:
            self.live.close()
            self.sysinfo.stop()
        except Exception:
            pass

    # ------------------------------------------------------------ 实时联动
    def set_live(self, mode, **kw):
        """mode: '' 关闭 / 'screen' 屏幕取色 / 'music' 音乐律动 / 'temp' 温度联动"""
        ok = self.live.set_mode(mode, **kw)
        if ok:
            self._add_log({(""): "实时联动已关闭",
                           "screen": "已开启屏幕氛围同步",
                           "music": "已开启音乐律动",
                           "temp": "已开启温度联动"}[self.live.mode])
        else:
            self._add_log(self.live.last_error or "开启失败")
        return ok

    # ------------------------------------------------------------ 对外控制
    def set_zone(self, idx, **kw):
        """更新单路配置并立即生效"""
        with self.lock:
            if idx < 0 or idx >= len(self.zones):
                return False
            z = self.zones[idx]
            for k, v in kw.items():
                if k in ("effect", "colors", "speed", "brightness", "leds", "direction"):
                    z[k] = v
            z["leds"] = max(0, min(int(z.get("leds", 30)), z.get("max_leds", 100)))
            z["speed"] = max(0, min(100, int(z.get("speed", 50))))
            z["brightness"] = max(0, min(100, int(z.get("brightness", 100))))
        self._apply_zone(idx)
        self._dirty = True
        return True

    def set_all(self, **kw):
        for i in range(len(self.zones)):
            self.set_zone(i, **kw)
        return True

    def set_master(self, **kw):
        with self.lock:
            for k, v in kw.items():
                if k in ("brightness", "span", "fps", "speed"):
                    self.master[k] = v
            self.master["brightness"] = max(0, min(100, int(self.master["brightness"])))
            self.master["speed"] = max(5, min(200, int(self.master.get("speed", 100))))
        self.save()
        return True

    def set_off(self):
        """5 路一起关灯（走硬件关断模式，灯珠彻底熄灭）"""
        self.set_all(effect="hw:%02x" % MODE_OFF)

    def identify(self, idx, duration=1.2):
        """闪一下某一路，用来认线。硬件模式的排针会临时切到直通再还原。"""
        z = self.zones[idx]
        if not self.dev.connected:
            return True
        was_hw = z.get("effect", "").startswith("hw:")
        if was_hw:
            try:
                self.dev.enter_direct(z["area"], max(1, z["leds"]), 255)
            except Exception as e:
                self._add_log("定位失败：%s" % e)
                return False
        with self.lock:
            self._override[idx] = ((255, 255, 255), time.perf_counter() + duration)
        if was_hw:
            def _restore():
                time.sleep(duration + 0.4)
                self._apply_zone(idx)
            threading.Thread(target=_restore, daemon=True).start()
        return True

    def _apply_zone(self, idx, initial=False):
        """把该路当前配置下发到硬件（硬件模式一次生效；软件模式交给渲染线程）"""
        z = self.zones[idx]
        eff = z.get("effect", "solid")
        if not self.dev.connected:
            return
        try:
            if eff.startswith("hw:"):
                try:
                    mode = int(eff.split(":")[1], 16)
                except ValueError:
                    self._add_log("%s → 无效的灯效参数 %s" % (z["name"], eff))
                    return
                colors = [hex_to_rgb(c) for c in z.get("colors", [])]
                colors = colors[:hw_color_count(mode)]
                self.dev.set_hw_mode(z["area"], mode, z["leds"], colors,
                                     int(z["speed"] * 2.55),
                                     int(z["brightness"] * 2.55),
                                     int(z.get("direction", 0)))
                self._add_log("%s → 硬件模式 %s" % (z["name"], HW_MODES.get(mode, mode)))
            else:
                # 软件灯效必须保证这一路处于 Direct 模式，否则逐颗数据会被控制器忽略：
                # 冷启动 / 控制器断电重置后，它可能还停在硬件灯效或静态色上。
                self.dev.enter_direct(z["area"], max(1, z["leds"]),
                                      int(z["brightness"] * 2.55))
        except Exception as e:
            self._add_log("下发失败：%s" % e)

    # ------------------------------------------------------------ 渲染主循环
    def _loop(self):
        while not self._stop:
            try:
                if not self.dev.connected:
                    if time.perf_counter() >= self._reconnect_at:
                        self._reconnect_at = time.perf_counter() + 3.0
                        if self.dev.open():
                            self._add_log("重新连接成功")
                            self._build_zones()
                            for i in range(len(self.zones)):
                                self._apply_zone(i, initial=True)
                            self._err_log_t = 0
                        else:
                            # 一直连不上时别刷屏，每 30 秒提示一次原因
                            now = time.perf_counter()
                            if now - self._err_log_t >= 30.0:
                                self._err_log_t = now
                                self._add_log("仍在等待设备：%s" % (self.dev.last_error or "无应答"))
                    time.sleep(0.2)
                    continue

                fps = max(10, min(60, int(self.master.get("fps", 40))))
                frame_start = time.perf_counter()
                self._render_frame()

                # 配置变更落盘（最多每 2 秒一次）
                if self._dirty:
                    self._dirty = False
                    self.save()

                # fps 统计
                self._frames += 1
                now = time.perf_counter()
                if now - self._fps_t >= 1.0:
                    self._fps = self._frames / (now - self._fps_t)
                    self._frames = 0
                    self._fps_t = now

                rest = 1.0 / fps - (time.perf_counter() - frame_start)
                if rest > 0:
                    time.sleep(rest)
            except Exception as e:
                self._add_log("渲染异常：%s" % e)
                time.sleep(0.2)

    def _layout(self):
        """计算联排偏移。返回 [(zone_idx, off, total, leds_eff)]"""
        zs = self.zones
        if self.master.get("span", True):
            total = sum(max(1, z["leds"]) for z in zs) or 1
            out, off = [], 0
            for i, z in enumerate(zs):
                n = max(1, z["leds"])
                out.append((i, off, total, z["leds"]))
                off += n
            return out
        return [(i, 0, max(1, z["leds"]), z["leds"]) for i, z in enumerate(zs)]

    def _render_frame(self):
        t = time.perf_counter() - self._t0
        master = self.master.get("brightness", 100) / 100.0
        # 总速度：百分比乘到每路自己的 speed 上，效果类按 0–100 换算
        mspd = int(self.master.get("speed", 100)) / 100.0
        prev = []
        for idx, off, total, leds in self._layout():
            z = self.zones[idx]
            eff = z.get("effect", "solid")
            if eff.startswith("hw:"):
                prev.append([])
                continue
            n = int(leds)
            if n <= 0:
                # 颗数填 0 = 这一路关掉，先补一帧全黑再停发，否则会停在上一帧的颜色
                if idx not in self._zeroed:
                    try:
                        self.dev.direct(z["area"], [(0, 0, 0)] * max(1, min(100, int(z.get("max_leds", 100))) ))
                    except Exception:
                        pass
                    self._zeroed.add(idx)
                prev.append([])
                continue
            self._zeroed.discard(idx)
            bri = z.get("brightness", 100) * master
            pal = [hex_to_rgb(c) for c in z.get("colors", [])] or [(255, 255, 255)]
            if self.live.active:
                # 实时联动优先：屏幕取色 / 音频 / 温度 直接接管这一路的颜色
                frame = self.live.frame(idx, n, self.zones, bri / 100.0)
            else:
                spd = max(0.0, min(100.0, z.get("speed", 50) * mspd))
                frame = effects.render(eff, n, off, total, t, pal, spd, bri, z)
            # 临时覆盖（识别模式）
            ov = self._override.get(idx)
            if ov:
                if time.perf_counter() < ov[1]:
                    frame = [ov[0]] * n
                else:
                    self._override.pop(idx, None)
            if int(z.get("direction", 0)) == 1:
                frame = frame[::-1]
            try:
                self.dev.direct(z["area"], frame)
            except Exception as e:
                self._add_log("直通写入失败：%s" % e)
                self.dev.connected = False
                return
            # 预览采样：每路最多 36 个采样点
            step = max(1, n // 36)
            prev.append([frame[i] for i in range(0, n, step)][:36])
        self._preview = {"zones": prev, "fps": round(self._fps, 1)}

    # ------------------------------------------------------------ 对外快照
    def snapshot(self):
        with self.lock:
            return {
                "connected": self.dev.connected,
                "product": self.dev.product,
                "port": self.dev.port,
                "error": self.dev.last_error,
                "zones": [dict(z) for z in self.zones],
                "master": dict(self.master),
                "fps": round(self._fps, 1),
                "log": self.log[-40:],
                "hw_modes": [{"value": "hw:%02x" % k, "name": v, "colors": hw_color_count(k)}
                             for k, v in sorted(HW_MODES.items())],
                "effects": [{"id": k, "name": v["name"], "desc": v["desc"],
                             "colors": list(v["colors"])} for k, v in effects.EFFECTS.items()],
                "live": self.live.state(),
                "sys": self.sysinfo.get(),
            }

    def preview(self):
        return self._preview

    @property
    def fps(self):
        return round(self._fps, 1)

    @property
    def connected(self):
        return bool(self.dev.connected)

    def read_hw_state(self):
        """从设备读回每路真实状态（用于自检/排查）"""
        out = []
        if not self.dev.connected:
            return out
        for z in self.zones:
            try:
                st = self.dev.read_zone(z["area"])
            except Exception as e:
                st = {"error": str(e)}
            if st:
                st["name"] = z["name"]
                st["area_hex"] = "0x%02X" % z["area"]
                out.append(st)
        return out
