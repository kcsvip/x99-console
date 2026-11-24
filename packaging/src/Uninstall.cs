// X99 控制台 卸载程序（C# 5）
// 用法：直接双击；内部会把自己复制到临时目录再删掉安装目录（否则删不掉正在运行的自己）
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LightDeckUninstall
{
    static class Program
    {
        const string AppName = "X99控制台";
        const string AppExe = "X99控制台.exe";
        const string RegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\X99控制台";

        [STAThread]
        static void Main(string[] args)
        {
            Application.EnableVisualStyles();

            string self = Process.GetCurrentProcess().MainModule.FileName;
            string dir = Path.GetDirectoryName(self);

            // 第二阶段：从临时目录里执行清理
            if (args.Length >= 2 && args[0] == "--clean")
            {
                bool silentClean = false;
                foreach (string a in args)
                {
                    if (a.ToUpperInvariant() == "/S" || a.ToUpperInvariant() == "/SILENT") silentClean = true;
                }
                Clean(args[1], silentClean);
                return;
            }

            bool silent = false;
            foreach (string a in args)
            {
                if (a.ToUpperInvariant() == "/S" || a.ToUpperInvariant() == "/SILENT") silent = true;
            }

            if (!silent)
            {
                string msg = "确定要卸载「X99 控制台」吗？\n\n" +
                             "安装目录：" + dir + "\n" +
                             "会一并删除桌面/开始菜单快捷方式、开机自启项和卸载注册信息。\n" +
                             "data 文件夹里的灯效配置和预设也会被删除。";
                if (MessageBox.Show(msg, "卸载 X99 控制台", MessageBoxButtons.OKCancel,
                        MessageBoxIcon.Warning) != DialogResult.OK) return;
            }

            KillRunning();

            // 复制到临时目录，再从那边删掉整个安装目录
            string temp = Path.Combine(Path.GetTempPath(), "X99控制台卸载_" + DateTime.Now.Ticks + ".exe");
            try
            {
                File.Copy(self, temp, true);
                string argLine = "--clean \"" + dir + "\"" + (silent ? " /S" : "");
                // 工作目录必须设成临时目录：否则子进程会把安装目录当 CWD 锁住，目录删不掉
                Process.Start(new ProcessStartInfo(temp, argLine)
                {
                    UseShellExecute = false,
                    WorkingDirectory = Path.GetDirectoryName(temp)
                });
                return;
            }
            catch
            {
                // 复制失败就就地清（安装目录会残留卸载程序本身）
                Clean(dir, silent);
            }
        }

        static void KillRunning()
        {
            try
            {
                foreach (Process p in Process.GetProcessesByName("X99控制台"))
                {
                    try { p.Kill(); p.WaitForExit(2000); } catch { }
                }
            }
            catch { }
        }

        static void RemoveHwMon()
        {
            // 硬件监控组件是独立常驻进程 + 计划任务，卸载时一并清掉
            try
            {
                foreach (Process p in Process.GetProcessesByName("X99硬件监控"))
                {
                    try { p.Kill(); p.WaitForExit(2000); } catch { }
                }
            }
            catch { }
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo("schtasks",
                    "/delete /tn \"X99控制台-硬件监控\" /f");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                using (Process p = Process.Start(psi)) { p.WaitForExit(4000); }
            }
            catch { }
        }

        static void Clean(string dir, bool silent)
        {
            RemoveHwMon();

            // 进程的当前目录如果是安装目录，目录本身永远删不掉，先换到临时目录
            try { Environment.CurrentDirectory = Path.GetTempPath(); } catch { }

            string desktopLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), AppName + ".lnk");
            string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), AppName);
            string startupLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), AppName + ".lnk");

            try { if (File.Exists(desktopLnk)) File.Delete(desktopLnk); } catch { }
            try { if (File.Exists(startupLnk)) File.Delete(startupLnk); } catch { }
            try { if (Directory.Exists(startDir)) Directory.Delete(startDir, true); } catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(RegKey, false); } catch { }

            // 等一会儿，等应用进程真的退出
            System.Threading.Thread.Sleep(800);

            Exception last = null;
            for (int i = 0; i < 8; i++)
            {
                try
                {
                    if (Directory.Exists(dir)) Directory.Delete(dir, true);
                    last = null;
                    break;
                }
                catch (Exception e)
                {
                    last = e;
                    System.Threading.Thread.Sleep(600);
                }
            }

            if (last != null)
            {
                // 兜底：内容已清空但根目录被占用的典型情况，再单独试一次删空目录
                try
                {
                    if (Directory.Exists(dir) && Directory.GetFileSystemEntries(dir).Length == 0)
                    {
                        System.Threading.Thread.Sleep(500);
                        Directory.Delete(dir, false);
                        last = null;
                    }
                }
                catch { }
            }

            if (last != null)
            {
                if (!silent)
                    MessageBox.Show("部分文件删不掉（可能还在被占用）：\n" + last.Message +
                                "\n\n请关掉 X99 控制台后，手动删除：" + dir, "卸载 X99 控制台",
                                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            else if (!silent)
            {
                MessageBox.Show("「X99 控制台」已卸载。", "卸载 X99 控制台",
                                MessageBoxButtons.OK, MessageBoxIcon.Information);
            }

            // 自删
            try
            {
                string self = Process.GetCurrentProcess().MainModule.FileName;
                ProcessStartInfo psi = new ProcessStartInfo("cmd.exe",
                    "/c timeout /t 2 >nul & del /f /q \"" + self + "\"");
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi);
            }
            catch { }
        }
    }
}
