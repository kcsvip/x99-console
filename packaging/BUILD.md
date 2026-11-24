# 构建说明

本项目分两部分：

- **主程序**：Python + PySide6，用 PyInstaller 打包成单个目录发行版；
- **硬件监控组件**：C# / .NET Framework 4.x 无窗口小程序，编译成 `hwmon/X99硬件监控.exe`，
  负责读 Super I/O / MSR、采集温度与风扇转速、代写风扇 PWM（需要管理员权限）。

安装器 / 卸载器是两个独立的 C# 小程序（`packaging/src/`），把整目录载荷压成 `payload.zip`
作为内嵌资源打进安装包。

## 环境要求

- Windows 10/11 x64
- Python 3.13（3.11+ 可尝试），`pip install pyinstaller pillow -r requirements.txt`
- .NET Framework 4.x 自带 csc：`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`

## 1. 编译硬件监控组件（hwmon）

在 `hwmon/` 目录下，引用同目录全部第三方 DLL，输出无窗口 x64 exe：

```powershell
cd hwmon
& "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" `
  /target:winexe /platform:x64 /optimize+ `
  /reference:LibreHardwareMonitorLib.dll `
  /reference:DiskInfoToolkit.dll `
  /reference:RAMSPDToolkit-NDD.dll `
  /reference:HidSharp.dll `
  /reference:System.Memory.dll `
  /reference:System.Runtime.CompilerServices.Unsafe.dll `
  /reference:System.Threading.AccessControl.dll `
  /out:X99硬件监控.exe HwMon.cs
```

> 第三方 DLL 的归属与许可证见仓库根目录 `NOTICE.md`，分发时须随 exe 一起保留。

## 2. 打包主程序（PyInstaller）

在仓库根目录执行：

```powershell
pyinstaller packaging/X99控制台Qt.spec
```

产物在 `dist/X99控制台/`（单目录模式，主程序 `X99控制台.exe`）。

## 3. 合并 hwmon 组件

把第 1 步编译出的监控组件和 DLL 放进发行目录的 `hwmon/` 子目录：

```powershell
New-Item -ItemType Directory -Force "dist/X99控制台/hwmon"
Copy-Item hwmon\*.dll "dist/X99控制台/hwmon\"
Copy-Item hwmon\X99硬件监控.exe "dist/X99控制台/hwmon\"
```

主程序会依次在 `程序目录\hwmon\` 与源码根 `hwmon\` 下查找该 exe。

> **合规提醒**：主板 BIOS 固件（`*.bin`）、AMI 刷写工具（`AFUDOS.exe` / `AfuEfix64.efi` / `boot*.efi`）
> 及教程 PDF 属于第三方版权，**不得**打进发行包。打包载荷前务必剔除 `assets/bios/` 目录与所有
> `*.bin` / `*.efi` 文件；缺少这些文件时，相关 BIOS / 开机 LOGO 功能会自动降级，不影响灯控主流程。

## 4.（可选）生成安装包

1. 把第 3 步的 `dist/X99控制台/` 整目录压成 `payload.zip`（目录内为程序文件，解压即安装目录内容；
   打包时按上面的合规提醒排除 `bios/` 目录与固件 / 刷写工具）；
2. 在 `packaging/src/` 下编译安装器，内嵌载荷：

```powershell
& "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" `
  /target:winexe /optimize+ /win32icon:..\..\assets\tray.ico `
  /resource:payload.zip `
  /out:..\X99控制台安装包.exe Setup.cs
```

3. 卸载器同理编译 `Uninstall.cs`（无内嵌资源）：

```powershell
& "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" `
  /target:winexe /optimize+ /out:卸载X99控制台.exe Uninstall.cs
```

`Setup.cs` 中的版本号（`AppVersion`）、显示名称等常量在文件头部，发布前按需修改。

## 5. 重新生成图标（可选）

`scripts/make_icon.py` 需要 Pillow；输入为图标母版 PNG，输出 `assets/icon.png` 与
多尺寸 `assets/tray.ico`。母版未随仓库公开，缺省时直接使用仓库内现有图标即可。
