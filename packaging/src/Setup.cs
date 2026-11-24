// X99 控制台 安装程序（C# 5，.NET Framework 自带 csc 编译）
// 功能：解压载荷 → 建桌面/开始菜单/开机自启快捷方式 → 写卸载信息 → 可选立即运行
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

namespace LightDeckSetup
{
    static class Program
    {
        public const string AppName = "X99控制台";
        public const string AppTitle = "X99 控制台 · ARGB 灯效控制台";
        public const string AppExe = "X99控制台.exe";
        public const string UninstExe = "卸载X99控制台.exe";
        public const string AppVersion = "1.6.6";
        public const string Publisher = "自用 · 为本机精粤 X99M GAMING D3/ARGB 主板编写";
        public const string RegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\X99控制台";

        static string _psPath = Path.Combine(Environment.SystemDirectory,
            Path.Combine("WindowsPowerShell", Path.Combine("v1.0", "powershell.exe")));

        [STAThread]
        static void Main(string[] args)
        {
            // 静默安装（自动化测试/批量部署用）：
            //   X99控制台安装包.exe /S /D=D:\X99控制台 /AUTOSTART /NORUN
            if (args != null)
            {
                bool silent = false;
                string dir = DefaultDir();
                bool desktop = true, startMenu = true, autoStart = false, runAfter = true;
                foreach (string a in args)
                {
                    string u = a.ToUpperInvariant();
                    if (u == "/S" || u == "/SILENT") silent = true;
                    else if (a.StartsWith("/D=", StringComparison.OrdinalIgnoreCase)) dir = a.Substring(3).Trim('"');
                    else if (u == "/NODESKTOP") desktop = false;
                    else if (u == "/NOSTARTMENU") startMenu = false;
                    else if (u == "/AUTOSTART") autoStart = true;
                    else if (u == "/NORUN") runAfter = false;
                }
                if (silent)
                {
                    try
                    {
                        Install(dir, desktop, startMenu, autoStart, runAfter);
                        Environment.Exit(0);
                    }
                    catch (Exception ex)
                    {
                        Environment.Exit(2);
                    }
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupForm());
        }

        public static string DefaultDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppName);
        }

        public static void KillRunning()
        {
            foreach (string name in new string[] { "X99控制台", "X99硬件监控" })
            {
                try
                {
                    foreach (Process p in Process.GetProcessesByName(name))
                    {
                        try { p.Kill(); p.WaitForExit(2000); }
                        catch { }
                    }
                }
                catch { }
            }
        }

        static string OldDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "光控台");
        }

        static void CopyDir(string src, string dst)
        {
            Directory.CreateDirectory(dst);
            foreach (string f in Directory.GetFiles(src))
                File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
            foreach (string d in Directory.GetDirectories(src))
                CopyDir(d, Path.Combine(dst, Path.GetFileName(d)));
        }

        // 旧版叫「光控台」，把它的 data（灯效配置 / 预设 / 场景 / 自动化）搬到新名字目录里
        public static void MigrateLegacy(string newDir)
        {
            try
            {
                string oldData = Path.Combine(OldDir(), "data");
                string newData = Path.Combine(newDir, "data");
                if (!Directory.Exists(oldData)) return;
                Directory.CreateDirectory(newData);
                foreach (string item in Directory.GetFileSystemEntries(oldData))
                {
                    string dest = Path.Combine(newData, Path.GetFileName(item));
                    if (Directory.Exists(item))
                    {
                        if (!Directory.Exists(dest)) CopyDir(item, dest);
                    }
                    else if (!File.Exists(dest))
                    {
                        File.Copy(item, dest);
                    }
                }
            }
            catch { }
        }

        // 清掉旧名字留下的快捷方式 / 自启项 / 注册信息 / 旧目录，避免开机同时跑两个版本
        public static void RemoveLegacy()
        {
            try
            {
                foreach (Process p in Process.GetProcessesByName("光控台"))
                {
                    try { p.Kill(); p.WaitForExit(2000); }
                    catch { }
                }
            }
            catch { }
            try
            {
                string desktop = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "光控台.lnk");
                if (File.Exists(desktop)) File.Delete(desktop);
                string startup = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "光控台.lnk");
                if (File.Exists(startup)) File.Delete(startup);
                string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "光控台");
                if (Directory.Exists(startDir)) Directory.Delete(startDir, true);
                Registry.CurrentUser.DeleteSubKeyTree(
                    @"Software\Microsoft\Windows\CurrentVersion\Uninstall\光控台", false);
                string old = OldDir();
                if (Directory.Exists(old)) Directory.Delete(old, true);
            }
            catch { }
        }

        public static void RunPowerShell(string script)        {
            string enc = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
            ProcessStartInfo psi = new ProcessStartInfo(_psPath,
                "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + enc);
            psi.CreateNoWindow = true;
            psi.UseShellExecute = false;
            Process p = Process.Start(psi);
            p.WaitForExit(60000);
        }

        static string Q(string s) { return "'" + s.Replace("'", "''") + "'"; }

        public static void MakeShortcut(string linkPath, string target, string arguments, string workDir, string icon)
        {
            string script =
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + Q(linkPath) + "); " +
                "$s.TargetPath = " + Q(target) + "; " +
                "$s.WorkingDirectory = " + Q(workDir) + "; " +
                "$s.Description = " + Q(AppTitle) + "; ";
            if (arguments != null && arguments.Length > 0)
                script += "$s.Arguments = " + Q(arguments) + "; $s.WindowStyle = 7; ";
            if (icon != null && icon.Length > 0 && File.Exists(icon))
                script += "$s.IconLocation = " + Q(icon + ",0") + "; ";
            script += "$s.Save()";
            RunPowerShell(script);
        }

        public static void ExtractPayload(string dir)
        {
            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream s = asm.GetManifestResourceStream("payload.zip"))
            {
                if (s == null) throw new Exception("安装包损坏：找不到内置载荷");
                Directory.CreateDirectory(dir);
                using (ZipArchive zip = new ZipArchive(s, ZipArchiveMode.Read))
                {
                    foreach (ZipArchiveEntry e in zip.Entries)
                    {
                        string dest = Path.Combine(dir, e.FullName.Replace('/', Path.DirectorySeparatorChar));
                        if (e.FullName.EndsWith("/")) { Directory.CreateDirectory(dest); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(dest));
                        try
                        {
                            using (Stream src = e.Open())
                            using (FileStream fs = new FileStream(dest, FileMode.Create, FileAccess.Write))
                            {
                                src.CopyTo(fs);
                            }
                        }
                        catch
                        {
                            // 个别文件被占用（比如高权限的硬件监控还在跑）不该让整次安装失败
                            // 下次打开程序时温度行会提示重新授权，主功能照常
                        }
                    }
                }
            }
        }

        public static long DirSizeKB(string dir)
        {
            long total = 0;
            try
            {
                foreach (string f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                {
                    try { total += new FileInfo(f).Length; } catch { }
                }
            }
            catch { }
            return total / 1024;
        }

        public static void WriteUninstallInfo(string dir)
        {
            RegistryKey k = Registry.CurrentUser.CreateSubKey(RegKey);
            k.SetValue("DisplayName", AppTitle);
            k.SetValue("DisplayVersion", AppVersion);
            k.SetValue("Publisher", Publisher);
            k.SetValue("InstallLocation", dir);
            k.SetValue("DisplayIcon", Path.Combine(dir, AppExe) + ",0");
            k.SetValue("UninstallString", "\"" + Path.Combine(dir, UninstExe) + "\"");
            k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
            k.SetValue("EstimatedSize", (int)Math.Min(DirSizeKB(dir), int.MaxValue), RegistryValueKind.DWord);
            k.SetValue("NoModify", 1, RegistryValueKind.DWord);
            k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
            k.Close();
        }

        static void InstallHwMon(string dir)
        {
            // CPU 温度/主板温度/风扇转速靠内核驱动采集（hwmon\X99硬件监控.exe 常驻）。
            // 安装器本身是管理员就顺手把常驻任务注册好；否则留给主界面的「启用温度监控」按钮走 UAC。
            string hw = Path.Combine(dir, "hwmon\\X99硬件监控.exe");
            if (!File.Exists(hw)) return;
            bool admin = false;
            try
            {
                admin = new System.Security.Principal.WindowsPrincipal(
                    System.Security.Principal.WindowsIdentity.GetCurrent())
                    .IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator);
            }
            catch { return; }
            if (!admin) return;
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo(hw, "--install");
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WorkingDirectory = Path.Combine(dir, "hwmon");
                using (Process p = Process.Start(psi)) { p.WaitForExit(4000); }
            }
            catch { }
        }

        public static void Install(string dir, bool desktop, bool startMenu, bool autoStart, bool runAfter)
        {
            KillRunning();
            MigrateLegacy(dir);
            RemoveLegacy();
            ExtractPayload(dir);

            string exe = Path.Combine(dir, AppExe);
            string ico = Path.Combine(dir, AppExe);

            string desktopLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), AppName + ".lnk");
            string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), AppName);
            string startLnk = Path.Combine(startDir, AppName + ".lnk");
            string startupLnk = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), AppName + ".lnk");

            if (desktop) MakeShortcut(desktopLnk, exe, "", dir, ico);
            else if (File.Exists(desktopLnk)) File.Delete(desktopLnk);

            if (startMenu)
            {
                Directory.CreateDirectory(startDir);
                MakeShortcut(startLnk, exe, "", dir, ico);
                MakeShortcut(Path.Combine(startDir, "卸载 X99 控制台.lnk"), Path.Combine(dir, UninstExe), "", dir, ico);
            }
            else if (Directory.Exists(startDir)) Directory.Delete(startDir, true);

            if (autoStart) MakeShortcut(startupLnk, exe, "--minimized", dir, ico);
            else if (File.Exists(startupLnk)) File.Delete(startupLnk);

            WriteUninstallInfo(dir);
            InstallHwMon(dir);

            if (runAfter)
            {
                try { Process.Start(new ProcessStartInfo(exe) { WorkingDirectory = dir }); }
                catch { }
            }
        }
    }

    class SetupForm : Form
    {
        TextBox _path;
        CheckBox _desktop, _startMenu, _autoStart, _runAfter;
        Button _install, _browse, _cancel;
        Label _status;
        ProgressBar _bar;

        public SetupForm()
        {
            Text = Program.AppName + " 安装程序";
            ClientSize = new Size(600, 396);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(18, 22, 30);
            ForeColor = Color.FromArgb(232, 239, 250);
            Font = new Font("Microsoft YaHei UI", 9f);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            Label title = new Label();
            title.Text = "X99 控制台";
            title.Font = new Font("Microsoft YaHei UI", 20f, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(34, 211, 238);
            title.SetBounds(28, 22, 300, 44);

            Label sub = new Label();
            sub.Text = "ARGB 灯效控制台 · 桌面客户端 + 托盘常驻";
            sub.ForeColor = Color.FromArgb(125, 139, 160);
            sub.SetBounds(30, 66, 520, 20);

            Label sub2 = new Label();
            sub2.Text = "5 路 ARGB 5V3 排针 · 12 个软件特效 · 18 个硬件灯效 · 不需要浏览器、不需要厂家软件";
            sub2.ForeColor = Color.FromArgb(125, 139, 160);
            sub2.SetBounds(30, 88, 560, 20);

            Label lblDir = new Label();
            lblDir.Text = "安装位置";
            lblDir.SetBounds(30, 132, 80, 22);

            _path = new TextBox();
            _path.Text = Program.DefaultDir();
            _path.SetBounds(30, 156, 448, 24);
            _path.BackColor = Color.FromArgb(28, 34, 46);
            _path.ForeColor = Color.FromArgb(232, 239, 250);
            _path.BorderStyle = BorderStyle.FixedSingle;

            _browse = new Button();
            _browse.Text = "浏览…";
            _browse.SetBounds(486, 155, 84, 26);
            _browse.FlatStyle = FlatStyle.Flat;
            _browse.FlatAppearance.BorderColor = Color.FromArgb(60, 72, 92);
            _browse.BackColor = Color.FromArgb(28, 34, 46);
            _browse.ForeColor = Color.FromArgb(200, 214, 232);
            _browse.Click += delegate
            {
                FolderBrowserDialog d = new FolderBrowserDialog();
                d.Description = "选择安装目录";
                d.SelectedPath = _path.Text;
                if (d.ShowDialog(this) == DialogResult.OK) _path.Text = d.SelectedPath;
            };

            _desktop = MakeCheck("创建桌面快捷方式", true, 30, 196);
            _startMenu = MakeCheck("添加到开始菜单", true, 30, 222);
            _autoStart = MakeCheck("开机自动启动（登录后静默在托盘运行，按上次配置还原灯效）", false, 30, 248);
            _runAfter = MakeCheck("安装完成后立即运行", true, 30, 274);

            _bar = new ProgressBar();
            _bar.SetBounds(30, 312, 540, 6);
            _bar.Style = ProgressBarStyle.Marquee;
            _bar.MarqueeAnimationSpeed = 0;
            _bar.Visible = false;

            _status = new Label();
            _status.Text = "";
            _status.ForeColor = Color.FromArgb(125, 139, 160);
            _status.SetBounds(30, 322, 540, 20);

            _cancel = new Button();
            _cancel.Text = "取消";
            _cancel.SetBounds(400, 350, 84, 32);
            _cancel.FlatStyle = FlatStyle.Flat;
            _cancel.FlatAppearance.BorderColor = Color.FromArgb(60, 72, 92);
            _cancel.BackColor = Color.FromArgb(28, 34, 46);
            _cancel.ForeColor = Color.FromArgb(200, 214, 232);
            _cancel.Click += delegate { Close(); };

            _install = new Button();
            _install.Text = "安 装";
            _install.SetBounds(494, 350, 84, 32);
            _install.FlatStyle = FlatStyle.Flat;
            _install.FlatAppearance.BorderColor = Color.FromArgb(34, 211, 238);
            _install.BackColor = Color.FromArgb(22, 60, 74);
            _install.ForeColor = Color.FromArgb(223, 246, 255);
            _install.Click += delegate { DoInstall(); };

            Controls.AddRange(new Control[] { title, sub, sub2, lblDir, _path, _browse,
                _desktop, _startMenu, _autoStart, _runAfter, _bar, _status, _cancel, _install });
        }

        CheckBox MakeCheck(string text, bool value, int x, int y)
        {
            CheckBox c = new CheckBox();
            c.Text = text;
            c.Checked = value;
            c.SetBounds(x, y, 560, 24);
            c.ForeColor = Color.FromArgb(200, 214, 232);
            return c;
        }

        void DoInstall()
        {
            string dir = _path.Text.Trim();
            if (dir.Length == 0) { MessageBox.Show(this, "请选择安装位置。", "X99 控制台"); return; }
            if (File.Exists(Path.Combine(dir, Program.AppExe)))
            {
                if (MessageBox.Show(this, "这个位置已经装了光控台，要覆盖安装吗？", "光控台",
                        MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            }
            _install.Enabled = false;
            _bar.Visible = true;
            _bar.MarqueeAnimationSpeed = 30;
            _status.Text = "正在安装…";
            Application.DoEvents();
            try
            {
                Program.Install(dir, _desktop.Checked, _startMenu.Checked, _autoStart.Checked, _runAfter.Checked);
                _bar.MarqueeAnimationSpeed = 0;
                _bar.Visible = false;
                _status.ForeColor = Color.FromArgb(52, 211, 153);
                _status.Text = "安装完成：" + dir;
                MessageBox.Show(this, "安装完成。\n\n" +
                    "双击桌面的「X99 控制台」，或从开始菜单启动。\n" +
                    "窗口右上角 × 只是收进托盘；要退出用托盘右键「退出程序」。\n\n" +
                    "装好后在软件界面底部可以直接勾选/取消「开机自启」。",
                    "X99 控制台", MessageBoxButtons.OK, MessageBoxIcon.Information);
                Close();
            }
            catch (Exception ex)
            {
                _bar.MarqueeAnimationSpeed = 0;
                _bar.Visible = false;
                _install.Enabled = true;
                _status.ForeColor = Color.FromArgb(239, 68, 68);
                _status.Text = "安装失败：" + ex.Message;
            }
        }
    }
}
