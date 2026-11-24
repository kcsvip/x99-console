# X99 控制台 · ARGB 灯效控制台

面向 **精粤 JGINYUE X99M GAMING D3/ARGB**（Nuvoton NCT6779D Super I/O、Xeon E5 v3 平台）的
Windows 桌面 ARGB 灯控与硬件监控软件。原生 Qt（PySide6）界面，直接与主板 ARGB 控制器
（USB HID + CDC 双通道）通信，自绘动画并逐颗下发颜色；不走 OpenRGB、不用 WebView、不依赖浏览器。

> 本项目为个人自用整理开源。**硬件针对性很强**，在其他主板 / 其他控制器上大概率无法直接点灯，
> 仅作同类逆向与控制思路参考。

**下载成品**：[Releases · v1.6.2](https://github.com/kcsvip/x99-console/releases/tag/v1.6.2)
（`X99-Console-Setup-v1.6.2.exe`，安装包未签名，SmartScreen 选「更多信息 → 仍要运行」）

## 功能一览

- **5 路 ARGB 5V3 排针**，每路最多 100 颗灯珠；实时预览、联排跨路、总亮度、总速度（全局倍率）、预设保存 / 导入导出
- **12 个自绘软件特效** + **18 个主板内置硬件灯效**；灯效轮播、过热守护（GPU 超温自动红色呼吸、降温还原）
- **情景模式**：竞技红黑脉冲 / 办公暖白 / 影音深海呼吸 / 静夜琥珀 / 极简纯白 / 炫彩彩虹，可存自定义
- **ROG 式四件套**：屏幕氛围同步 · 音乐律动 · 温度 / 负载联动 · 场景自动化（夜间模式 / 程序联动 / 全局快捷键）
- **系统监控面板**：CPU / 主板 / 内存 / 硬盘 / 显卡等多项指标，带动态状态条
- **风扇调速**：各路手动百分比 / 交回 BIOS，**配置持久化到本地档案，重启后自动还原**；写后验证转速是否真的变化
- **系统级控制**：性能模式（节能 / 平衡 / 高性能 / 卓越性能）· CPU 限频 · WiFi / 蓝牙开关 · 小键盘开关
- **托盘常驻**：单实例互斥量，重复双击只把已有窗口拉到前台；关窗收进托盘，灯效继续
- **6 套皮肤**：ROG 红黑 / 冰川蓝 / 星云紫 / 翡翠绿 / 琥珀橙 / 极简钢灰，重启保持
- 命令行参数：`--minimized`（只出托盘）、`--tab 0..8`（启动直达标签页）

## 目录结构

```
x99-console/
├─ client_qt.py            # 程序入口
├─ ui_qt.py               # Qt 界面
├─ core/                  # 设备驱动、特效、引擎、风扇档案、系统控制等核心模块
├─ hwmon/                 # 硬件监控 + 风扇控制组件（C# 源码 HwMon.cs 及第三方 DLL）
├─ assets/                # 图标、托盘 ICO、捐赠二维码（可自行删除 donate.jpg）
├─ scripts/make_icon.py   # 从母版重生成托盘图标的脚本（需 Pillow）
├─ packaging/
│  ├─ X99控制台Qt.spec    # PyInstaller 打包脚本
│  └─ src/                # 安装器 / 卸载器 C# 源码
├─ requirements.txt
├─ NOTICE.md               # 第三方组件归属与许可证
└─ LICENSE                 # GPL-3.0
```

## 快速开始

### 方式一：直接用成品

在本仓库的 **Releases** 页面下载对应版本的 `X99控制台安装包.exe`，双击按界面提示安装
（默认装到 `%LOCALAPPDATA%\X99控制台`，主程序无需管理员权限）。安装包未做数字签名，
首次运行 SmartScreen 可能提示「已保护你的电脑」，点「更多信息 → 仍要运行」即可。

### 方式二：从源码运行

要求 Windows 10/11 x64，Python 3.13（3.11+ 均可尝试）。

```powershell
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动主界面
python client_qt.py
```

硬件监控 / 风扇控制由 `hwmon/X99硬件监控.exe` 负责（需管理员权限读取 Super I/O / MSR）；
从源码首次运行时，按 `packaging/BUILD.md` 编译该组件。

## 自行构建

见 [`packaging/BUILD.md`](packaging/BUILD.md)：编译 hwmon 组件 → PyInstaller 打包 → （可选）生成安装包。

## 合规与第三方组件

主代码以 **GPL-3.0-or-later** 发布。仓库内附带的第三方 DLL、Python 依赖及其许可证见
[`NOTICE.md`](NOTICE.md)，其中包含 MPL-2.0、Apache-2.0、LGPL-3.0、BSD 等组件，
各组件许可证保持原样。

## 免责声明

- 本软件读写主板 Super I/O、风扇 PWM、电源计划与系统注册表，**仅在指定主板上实测通过**；
  在其他硬件上运行前请自行确认，误操作可能导致风扇停转、温度异常等问题，风险由使用者承担。
- 仓库**不附带任何主板 BIOS 固件、AMI AFU 刷写工具或 EFI 启动文件**。
  源码中涉及固件包整理 / 开机 LOGO 的模块在缺少对应目录时会自动降级；
  如需使用相关功能，请自行取得合法的主板固件与官方工具。
- `assets/donate.jpg` 为个人收款二维码，公开分发前可自行删除，不影响任何功能。

## 致谢

- [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)
- [DiskInfoToolkit](https://github.com/Blacktempel/DiskInfoToolkit)
- [RAMSPDToolkit](https://github.com/Blacktempel/RAMSPDToolkit)
- [HidSharp](https://github.com/IntergatedCircuits/HidSharp)
- [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython/)
