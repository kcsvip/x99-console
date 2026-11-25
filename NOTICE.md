# 第三方组件声明（NOTICE）

本项目主代码以 **GPL-3.0-or-later** 发布。分发的二进制 / 源码中包含下列第三方组件，
其各自许可证保持原样，未被本项目的 GPL 协议覆盖。若与 GPL 条款冲突，以各组件原始许可证为准。

## .NET 组件（位于 `hwmon/`，由硬件监控组件 `HwMon.cs` 编译时引用）

| 文件 | 版本 | 归属 / 项目 | 许可证 | 来源 |
|---|---|---|---|---|
| LibreHardwareMonitorLib.dll | 0.9.6 | LibreHardwareMonitor contributors | Mozilla Public License 2.0 | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| DiskInfoToolkit.dll | 1.1.2 | Blacktempel contributors | Mozilla Public License 2.0 | https://github.com/Blacktempel/DiskInfoToolkit |
| RAMSPDToolkit-NDD.dll | 1.4.2 | Blacktempel contributors | Mozilla Public License 2.0 | https://github.com/Blacktempel/RAMSPDToolkit |
| HidSharp.dll | 2.6.4 | James F. Bellinger / Illusory Studios LLC | Apache License 2.0 | https://github.com/IntergatedCircuits/HidSharp |
| System.Memory.dll | 4.6.3 | Microsoft | .NET Runtime Library License（MIT 类） | .NET Runtime |
| System.Runtime.CompilerServices.Unsafe.dll | 6.1.2 | Microsoft | .NET Runtime Library License（MIT 类） | .NET Runtime |
| System.Threading.AccessControl.dll | 10.0.3 | Microsoft | .NET Runtime Library License（MIT 类） | .NET Runtime |

## 内置闭源工具（仅安装包附带，源码仓库不含该二进制）

| 文件 | 版本 | 归属 | 许可 | 说明 |
|---|---|---|---|---|
| ChangeLogoPro.exe | 5.11.0039 | American Megatrends, Inc. ©2019 | AMI 专有闭源（未附带源码，不并入本项目 GPL） | AMI 固件开机 Logo 的列出 / 提取 / 替换命令行工具。仅在「开机 LOGO」页作为可选后端调用；开源源码仓库与 git 不包含此 exe，由本地打包脚本从 `tools/` 目录收进安装包。文件未做数字签名。 |

- 该工具为 AMI 专有程序，本项目仅以子进程方式调用其命令行，未修改其二进制；其商标、版权与许可条款归 American Megatrends, Inc. 所有。
- 校验 SHA-256（本地打包所用副本）：`663797BECAE16924B77097E71B78097051D80E27D235830E91EC029B92F4E84B`。

## Python 运行时依赖（见 `requirements.txt`）

| 包 | 许可证 | 说明 |
|---|---|---|
| PySide6 | LGPL-3.0-or-later | Qt 官方 Python 绑定；以动态链接方式使用。按 LGPL 要求，最终用户可以替换本机 PySide6 运行库以重新链接修改后的程序。 |
| hidapi | BSD-3-Clause | HID 设备访问绑定（封装 hidapi C 库）。 |
| pyserial | BSD-3-Clause | 串口通信。 |
| Pillow | HPND / MIT-like | 仅图标生成脚本 `scripts/make_icon.py` 使用，不进入运行时。 |

## 合规说明

- MPL-2.0 组件：修改其源文件需在同一文件中公开修改内容；本项目未改动上述第三方 DLL 源码。
- Apache-2.0 组件：保留 `NOTICE` 与版权声明（本文件即履行该项义务）。
- LGPL 组件（PySide6）：本项目仅以动态链接方式调用，未修改 PySide6 本身；源码仓库已提供完整构建脚本，
  便于下游重新链接。
- 完整许可证文本可从各项目仓库 / 官方站点获取：
  - MPL-2.0: https://mozilla.org/MPL/2.0/
  - Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0
  - LGPL-3.0: https://www.gnu.org/licenses/lgpl-3.0.txt
