# -*- coding: utf-8 -*-
"""
系统级真实可控项（不装第三方库，纯 ctypes + 系统自带命令）

- 无线 / 蓝牙开关：Enable-NetAdapter / Disable-NetAdapter（要管理员；普通权限时临时 UAC 提权一次）
- 小键盘（NumLock）：注入 VK_NUMLOCK，并可写 HKCU 让开机默认打开
- 性能模式：powercfg 切换 节能 / 平衡 / 高性能 / 卓越性能
- CPU 上限：powercfg 的 PROCTHROTTLEMAX（50–100%），等于"软超频档 / 限频"滑杆

注意：主板风扇转速与主板温度由 Super I/O 芯片管，Windows 没有官方通道，
本模块不碰它（也不写任何 I/O 端口），避免把风扇写死烧硬件。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import tempfile
import time
import winreg

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

_ROOT = os.environ.get("SystemRoot", r"C:\Windows")
_PC = os.path.join(_ROOT, "System32", "powercfg.exe")
_PS = os.path.join(_ROOT, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
_NO_WIN = 0x08000000


# ----------------------------------------------------------------- 基础
def is_admin():
    try:
        return bool(_shell32.IsUserAnAdmin())
    except Exception:
        return False


def _dec(raw):
    """系统自带程序输出：中文 Windows 上是 GBK，尽量按真实编码解"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def _run(args, timeout=12):
    """跑一个不弹窗的子进程，返回 (rc, stdout, stderr)"""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=_NO_WIN)
        return r.returncode, _dec(r.stdout or b"").strip(), _dec(r.stderr or b"").strip()
    except Exception as e:
        return -1, "", str(e)


def _ps(script, timeout=15):
    return _run([_PS, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                 "-Command", script], timeout=timeout)


def _ps_elevated(script, timeout=40):
    """普通权限下需要管理员动作时，走一次 UAC（用户点「是」即可）"""
    fd, path = tempfile.mkstemp(suffix=".ps1")
    os.close(fd)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("$ErrorActionPreference='Stop'\n" + script + "\n")
    try:
        rc, out, err = _run([_PS, "-NoProfile", "-WindowStyle", "Hidden",
                             "-Command",
                             "Start-Process -FilePath '%s' -ArgumentList "
                             "'-NoProfile','-ExecutionPolicy','Bypass','-File','%s' "
                             "-Verb RunAs -WindowStyle Hidden -Wait" % (_PS, path)],
                            timeout=timeout)
        return rc, out, err
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# ----------------------------------------------------------------- 无线
def wireless_adapters():
    """当前真实存在的无线网卡（跳过 Not Present 的幽灵条目）"""
    script = ("Get-NetAdapter -Physical | Where-Object { $_.Status -ne 'Not Present' -and "
              "($_.InterfaceDescription -match 'Wi-Fi|Wireless|WLAN|802.11') } | "
              "ForEach-Object { \"{0}|{1}|{2}\" -f $_.Name, $_.InterfaceDescription, $_.Status }")
    rc, out, _ = _ps(script)
    res = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 3 and p[0]:
            res.append({"name": p[0], "desc": p[1], "status": p[2]})
    return res


def wifi_state():
    """返回 (是否开启, 适配器名, 说明)"""
    ads = wireless_adapters()
    if not ads:
        return None, "", "没有检测到无线网卡"
    a = ads[0]
    on = a["status"].lower() not in ("disabled", "disabledbypolicymanager", "disabledbyhardware")
    return on, a["name"], ("%s · %s" % (a["name"], a["status"]))


def set_wifi(on):
    ads = wireless_adapters()
    if not ads:
        return False, "没有检测到无线网卡"
    cmd = ("Enable-NetAdapter -Name '%s' -Confirm:$false" if on
           else "Disable-NetAdapter -Name '%s' -Confirm:$false")
    script = "\n".join(cmd % a["name"] for a in ads)
    if is_admin():
        rc, out, err = _ps(script, timeout=25)
    else:
        rc, out, err = _ps_elevated(script)
    time.sleep(1.5)
    now_on, name, msg = wifi_state()
    if now_on == on:
        return True, msg
    detail = (err or out or "").strip().splitlines()
    return False, ("切换失败：%s" % (detail[-1] if detail else "需要管理员权限"))


def net_state():
    """一次调用同时读无线 + 蓝牙（省一次 PowerShell 启动，约 3 秒）
    返回 (wifi_on, wifi_msg, bt_on, bt_msg)；读不到的那项为 None
    """
    script = (
        "$n = Get-NetAdapter -Physical | Where-Object { $_.Status -ne 'Not Present' -and "
        "($_.InterfaceDescription -match 'Wi-Fi|Wireless|WLAN|802.11') } | Select-Object -First 1;"
        "if ($n) { 'W|' + $n.Name + '|' + $n.Status } else { 'W|NONE|x' };"
        "$b = Get-PnpDevice -Class Bluetooth -PresentOnly | "
        "Where-Object { $_.FriendlyName -match 'Bluetooth' } | Select-Object -First 1;"
        "if ($b) { 'B|' + $b.FriendlyName + '|' + $b.Status } else { 'B|NONE|x' }")
    rc, out, err = _ps(script, timeout=25)
    w_on, w_msg, b_on, b_msg = None, "读取失败", None, "读取失败"
    for line in out.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) < 3:
            continue
        if p[0] == "W":
            if p[1] == "NONE":
                w_msg = "没有检测到无线网卡"
                w_on = None
            else:
                w_on = p[2].lower() not in ("disabled", "disabledbypolicymanager",
                                            "disabledbyhardware")
                w_msg = "%s · %s" % (p[1], p[2])
        elif p[0] == "B":
            if p[1] == "NONE":
                b_msg = "没有检测到蓝牙适配器"
                b_on = None
            else:
                b_on = p[2].lower() == "ok"
                b_msg = "%s · %s" % (p[1], p[2])
    if not out:
        w_msg = b_msg = ("读取失败：%s" % (err.splitlines()[-1] if err else "未知错误"))[:60]
    return w_on, w_msg, b_on, b_msg


# ----------------------------------------------------------------- 蓝牙
def bluetooth_devices():
    rc, out, _ = _ps("Get-PnpDevice -Class Bluetooth -PresentOnly | "
                     "Where-Object { $_.FriendlyName -match 'Bluetooth' } | "
                     "ForEach-Object { \"{0}|{1}|{2}\" -f $_.FriendlyName, $_.Status, $_.InstanceId }")
    res = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 3 and p[2]:
            res.append({"name": p[0], "status": p[1], "id": p[2]})
    return res


def bluetooth_state():
    devs = bluetooth_devices()
    if not devs:
        return None, "没有检测到蓝牙适配器"
    ok = all(d["status"].lower() == "ok" for d in devs)
    return ok, "%s · %s" % (devs[0]["name"], devs[0]["status"])


def set_bluetooth(on):
    devs = bluetooth_devices()
    if not devs:
        return False, "没有检测到蓝牙适配器"
    verb = "Enable-PnpDevice" if on else "Disable-PnpDevice"
    script = "\n".join("%s -InstanceId '%s' -Confirm:$false" % (verb, d["id"]) for d in devs)
    if is_admin():
        rc, out, err = _ps(script, timeout=25)
    else:
        rc, out, err = _ps_elevated(script)
    time.sleep(1.5)
    now_on, msg = bluetooth_state()
    if now_on == on:
        return True, msg
    return False, ("切换失败：%s" % ((err or out or "需要管理员权限").strip().splitlines()[-1:][0]
                                    if (err or out) else "需要管理员权限"))


# ----------------------------------------------------------------- 小键盘
VK_NUMLOCK = 0x90
_NUM_KEY = r"Control Panel\Keyboard"
_NUM_VALUE = "InitialKeyboardIndicators"


def numlock_on():
    try:
        return bool(_user32.GetKeyState(VK_NUMLOCK) & 1)
    except Exception:
        return False


def set_numlock(on):
    want = bool(on)
    if numlock_on() == want:
        return True
    for _ in range(3):
        # keybd_event(虚拟键, 扫描码, flags, extra)；0x45 是 NumLock 扫描码
        _user32.keybd_event(VK_NUMLOCK, 0x45, 0x0001 | 0x0002, 0)   # 扩展键 + 按下
        _user32.keybd_event(VK_NUMLOCK, 0x45, 0x0001 | 0x0002 | 0x0004, 0)  # 抬起
        time.sleep(0.06)
        if numlock_on() == want:
            return True
    return numlock_on() == want


def numlock_default():
    """开机（登录）后小键盘是否默认打开"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _NUM_KEY) as k:
            v, _ = winreg.QueryValueEx(k, _NUM_VALUE)
            s = str(v).strip()
            if s in ("2", "3", "80000002", "80000003"):
                return True
            if s in ("0", "1", "80000000", "80000001"):
                return False
            return None
    except Exception:
        return None


def set_numlock_default(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _NUM_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, _NUM_VALUE, 0, winreg.REG_SZ, "2" if on else "0")
        return True
    except Exception:
        return False


# ----------------------------------------------------------------- 性能模式
PLANS = [("节能", "a1841308-3541-4fab-bc81-f71556f20b4a"),
         ("平衡", "381b4222-f694-41f0-9685-ff5bb260df2e"),
         ("高性能", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"),
         ("卓越性能", "8e7360cf-e7e6-4f46-bdcb-2a9793748437")]


def power_scheme():
    """返回 (当前方案名, 当前 GUID, 可用方案列表[(名字, guid)])"""
    rc, out, _ = _run([_PC, "/list"])
    avail = []
    for line in out.splitlines():
        if "GUID" in line:
            low = line.lower()
            for name, guid in PLANS:
                if guid in low:
                    avail.append((name, guid))
    rc2, out2, _ = _run([_PC, "/getactivescheme"])
    cur_guid, cur_name = "", ""
    for line in out2.splitlines():
        if "GUID" in line and ":" in line:
            body = line.split(":", 1)[1].strip()
            cur_guid = body.split(" ")[0].lower()
            m = body[body.find("(") + 1:body.rfind(")")] if "(" in body else ""
            cur_name = m or body
    for name, guid in avail:
        if guid in cur_guid:
            cur_name = name
    return cur_name, cur_guid, (avail or PLANS)


def set_power_scheme(guid):
    rc, out, err = _run([_PC, "/setactive", guid])
    if rc == 0:
        return True, ""
    if not is_admin():
        rc2, out2, err2 = _ps_elevated("& '%s' /setactive %s" % (_PC, guid))
        rc, out, err = rc2, out2, err2
    return rc == 0, (err or out or "").strip()


def cpu_limit():
    """当前 CPU 最大处理器状态（%）；读不到返回 None"""
    rc, out, _ = _run([_PC, "/query", "SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX"])
    for line in out.splitlines():
        if "当前交流" in line and ":" in line:
            hexv = line.split(":", 1)[1].strip()
            try:
                return int(hexv, 16)
            except Exception:
                return None
    return None


def set_cpu_limit(pct):
    pct = max(20, min(100, int(pct)))

    def _apply(prefix):
        a = _run([_PC, "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR",
                  "PROCTHROTTLEMAX", str(pct)])
        b = _run([_PC, "/setactive", "SCHEME_CURRENT"])
        return a[0] == 0 and b[0] == 0, (a[2] or b[2] or a[1] or b[1] or "")

    ok, msg = _apply("")
    if not ok and not is_admin():
        rc, out, err = _ps_elevated(
            "& '%s' /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX %d;"
            "& '%s' /setactive SCHEME_CURRENT" % (_PC, pct, _PC))
        ok = bool(cpu_limit() is not None and cpu_limit() == pct)
        msg = err or out
    return ok, ("已设为 %d%%" % pct if ok else (msg or "需要管理员权限"))


# ----------------------------------------------------------------- 静态硬件信息（一次查询，缓存）
_STATIC = {}


def static_info():
    if _STATIC:
        return dict(_STATIC)
    script = ("$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1;"
              "\"cpu=\" + $cpu.Name;"
              "\"cores=\" + $cpu.NumberOfCores + \"/\" + $cpu.NumberOfLogicalProcessors;"
              "$m = Get-CimInstance Win32_PhysicalMemory;"
              "\"memcount=\" + @($m).Count;"
              "\"memspeed=\" + (@($m) | ForEach-Object { $_.ConfiguredClockSpeed } | Sort-Object -Unique) -join '/';"
              "\"memgb=\" + [math]::Round((@($m) | Measure-Object -Property Capacity -Sum).Sum / 1GB);"
              "$b = Get-CimInstance Win32_BaseBoard;"
              "\"board=\" + $b.Manufacturer + ' ' + $b.Product")
    rc, out, _ = _ps(script, timeout=20)
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    _STATIC.update(d)
    return dict(_STATIC)


# ----------------------------------------------------------------- 风扇调速
# 为什么自己不写：写风扇 PWM 要管理员权限 + Super I/O 驱动，主界面是普通权限，
# 自己做不了。改成把命令丢给常驻的「X99硬件监控」（计划任务最高权限），它 2 秒
# 内执行完把结果写回 hwmon_result.json，这里只负责等结果。
_FAN_FLOOR = 20          # 兜底下限：任何指令都不让风扇低于 20%，避免写停转
_HW_DIR = {"p": None}


def set_hwmon_dir(path):
    """主界面启动时把 data 目录告诉本模块"""
    _HW_DIR["p"] = path


def hwmon_dir():
    if _HW_DIR["p"]:
        return _HW_DIR["p"]
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "X99控制台", "data")


def _send_cmd(payload, timeout=6.0):
    d = hwmon_dir()
    cmd_path = os.path.join(d, "hwmon_cmd.json")
    res_path = os.path.join(d, "hwmon_result.json")
    try:
        if os.path.exists(res_path):
            os.remove(res_path)
    except Exception:
        pass
    try:
        with open(cmd_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        return False, {"err": "写命令文件失败：%s" % e}
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.12)
        if os.path.exists(res_path):
            for _ in range(6):
                try:
                    with open(res_path, "r", encoding="utf-8") as f:
                        return True, json.load(f)
                except Exception:
                    time.sleep(0.05)
            return False, {"err": "结果文件读不出来"}
    return False, {"err": "硬件监控没响应（可能没在跑，或没拿到管理员权限）"}


def set_fan(index, pct):
    """把第 index 路风扇设成 pct%（软件控制），返回 (成功, 信息字典)"""
    pct = max(_FAN_FLOOR, min(100, int(pct)))
    ok, info = _send_cmd({"a": "set", "i": int(index), "v": pct})
    return bool(ok and info.get("ok")), info


def fan_default(index):
    """把第 index 路交回 BIOS 控制"""
    ok, info = _send_cmd({"a": "default", "i": int(index)})
    return bool(ok and info.get("ok")), info


def fan_all(pct):
    """一次写全部通道（比逐路快得多：一条命令搞定 5 路）"""
    pct = max(_FAN_FLOOR, min(100, int(pct)))
    ok, info = _send_cmd({"a": "set", "i": -1, "v": pct})
    return bool(ok and info.get("ok")), info


def fan_all_default():
    """一次把全部通道交回 BIOS"""
    ok, info = _send_cmd({"a": "default", "i": -1})
    return bool(ok and info.get("ok")), info


# ----------------------------------------------------------------- 性能强化（软超频档）
# 说明：E5-2673 v3 倍频锁死、DDR4 ECC REG 内存也锁频，倍频 / BCLK / 电压 / 内存
# 时序只能进 BIOS 改。软件侧能真正影响性能的是 Windows 的功耗与调度策略，
# 这几项加在一起就是"软超频"：不让 CPU 降频、不让核心停放、不让 PCIe 挂起、
# 让 Turbo 更积极。
PROFILES = {
    "silent": {
        "name": "静音",
        "plan": "381b4222-f694-41f0-9685-ff5bb260df2e",   # 平衡
        "vals": [("SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
                 ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 80),
                 ("SUB_PROCESSOR", "PERFBOOSTMODE", 0),     # 关掉 Turbo
                 ("SUB_PROCESSOR", "CPMINCORES", 0),
                 ("SUB_PCIEXPRESS", "PCIEXPRESSPM", 2),     # 最大省电
                 ("SUB_DISK", "DISKIDLE", 1200)],
        "tip": "CPU 最高 80%、Turbo 关闭，机器明显凉快安静",
    },
    "balanced": {
        "name": "均衡",
        "plan": "381b4222-f694-41f0-9685-ff5bb260df2e",
        "vals": [("SUB_PROCESSOR", "PROCTHROTTLEMIN", 5),
                 ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
                 ("SUB_PROCESSOR", "PERFBOOSTMODE", 1),
                 ("SUB_PROCESSOR", "CPMINCORES", 0),
                 ("SUB_PCIEXPRESS", "PCIEXPRESSPM", 1),
                 ("SUB_DISK", "DISKIDLE", 1200)],
        "tip": "Windows 默认策略，按负载自动升降频",
    },
    "boost": {
        "name": "狂暴",
        "plan": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",   # 高性能
        "vals": [("SUB_PROCESSOR", "PROCTHROTTLEMIN", 100),
                 ("SUB_PROCESSOR", "PROCTHROTTLEMAX", 100),
                 ("SUB_PROCESSOR", "PERFBOOSTMODE", 2),     # 激进 Turbo
                 ("SUB_PROCESSOR", "CPMINCORES", 100),      # 核心不停放
                 ("SUB_PCIEXPRESS", "PCIEXPRESSPM", 0),     # PCIe 不许挂起
                 ("SUB_DISK", "DISKIDLE", 0)],
        "tip": "满频锁死 + 激进 Turbo + 核心不停放，性能最高也最热最吵",
    },
}


def _apply_vals(pairs, timeout=30):
    cmds = ["& '%s' /setacvalueindex SCHEME_CURRENT %s %s %s" % (_PC, s, k, v)
            for s, k, v in pairs]
    cmds.append("& '%s' /setactive SCHEME_CURRENT" % _PC)
    script = ";".join(cmds)
    if is_admin():
        rc, out, err = _ps(script, timeout=timeout)
    else:
        rc, out, err = _ps_elevated(script, timeout=timeout + 20)
    if rc == 0:
        return True, ""
    detail = (err or out or "").strip().splitlines()
    return False, (detail[-1] if detail else "需要管理员权限")


def apply_profile(kind):
    """按静音 / 均衡 / 狂暴 一次性套好电源方案 + 处理器策略"""
    p = PROFILES.get(kind)
    if not p:
        return False, "未知档位"
    ok1, msg1 = set_power_scheme(p["plan"])
    ok2, msg2 = _apply_vals(p["vals"])
    if ok1 and ok2:
        return True, "%s档已应用" % p["name"]
    return False, (msg2 or msg1 or "应用失败")


if __name__ == "__main__":
    print("admin:", is_admin())
    print("wifi:", wifi_state())
    print("bt:", bluetooth_state())
    print("numlock:", numlock_on(), "默认:", numlock_default())
    print("power:", power_scheme()[0], "cpu上限:", cpu_limit())
    print("info:", static_info())
