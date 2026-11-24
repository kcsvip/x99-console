// X99 控制台 · 硬件监控 + 风扇控制组件（X99硬件监控.exe）
//
// 为什么要有这个独立小程序：
//   CPU 温度、主板温度、风扇转速在 Windows 里没有官方接口（ACPI 热区不支持、
//   Win32_TemperatureProbe 无读数），必须走内核驱动读 MSR / Super I/O。
//   驱动加载需要管理员权限，所以放在这个无窗口的小程序里跑，由主界面读它写的 JSON。
//   风扇 PWM 同理：写 Super I/O 也要驱动权限，所以只能由这里代劳。
//
// 用法：
//   (无参数)              常驻采集，每 2 秒写一次 hwmon.json，并轮询 hwmon_cmd.json 执行风扇命令
//   --install             注册计划任务（最高权限、登录自动启动），并立刻启动一个实例，然后退出
//   --remove              删除计划任务并退出
//   --once                只采一次，打印到标准输出（调试用）
//   --out <路径>          指定 JSON 输出路径（默认：exe 所在目录的上一级 data\hwmon.json）
//   --fan <序号> <0-100>  一次性把某路风扇设为软件控制值（调试用，需管理员）
//   --fan-default <序号>  一次性把某路风扇交回 BIOS 控制（调试用）
//
// 命令文件 hwmon_cmd.json（主界面写、这里读完即删）：
//   {"a":"set","i":0,"v":60}      -> 第 0 路设 60%
//   {"a":"default","i":0}         -> 第 0 路交回 BIOS
// 结果写 hwmon_result.json：{"ok":true,"i":0,"v":60,"mode":"Software","err":""}

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using LibreHardwareMonitor.Hardware;

static class HwMon
{
    const string TASK_NAME = "X99控制台-硬件监控";
    const string MUTEX_NAME = "Local\\X99Console-hwmon";

    static Mutex _mutex;
    static string _outPath;
    static bool _verbose;

    class Ctl
    {
        public string Name;
        public float Value;
        public float Min;
        public float Max;
        public string Mode;
        public ISensor Sensor;
    }

    static int Main(string[] args)
    {
        _verbose = Environment.UserInteractive;
        _outPath = DefaultOutPath();
        string mode = "run";
        string fanIdx = null, fanVal = null;
        for (int i = 0; i < args.Length; i++)
        {
            string a = args[i].ToLowerInvariant();
            if (a == "--install") mode = "install";
            else if (a == "--remove") mode = "remove";
            else if (a == "--once") mode = "once";
            else if (a == "--out" && i + 1 < args.Length) { _outPath = args[++i]; }
            else if (a == "--fan" && i + 2 < args.Length) { mode = "fan"; fanIdx = args[++i]; fanVal = args[++i]; }
            else if (a == "--fan-default" && i + 1 < args.Length) { mode = "fan-default"; fanIdx = args[++i]; }
        }

        if (mode == "install") return Install();
        if (mode == "remove") return Remove();
        if (mode == "once") return Once();
        if (mode == "fan") return FanOnce(fanIdx, fanVal, false);
        if (mode == "fan-default") return FanOnce(fanIdx, fanVal, true);
        return RunForever();
    }

    static string DefaultOutPath()
    {
        string exeDir = Path.GetDirectoryName(Application_ExecutablePath());
        string parent = Path.GetDirectoryName(exeDir);
        string data = parent == null ? exeDir : Path.Combine(parent, "data");
        try { Directory.CreateDirectory(data); } catch { data = exeDir; }
        return Path.Combine(data, "hwmon.json");
    }

    static string Application_ExecutablePath()
    {
        return Process.GetCurrentProcess().MainModule.FileName;
    }

    static Computer NewComputer()
    {
        return new Computer
        {
            IsCpuEnabled = true,
            IsMotherboardEnabled = true,
            IsControllerEnabled = true,
            IsGpuEnabled = false,
            IsMemoryEnabled = false,
            IsStorageEnabled = false,
            IsNetworkEnabled = false
        };
    }

    // ---------------------------------------------------------------- 采集
    static string Sample(Computer c)
    {
        float? pkg = null, coreMax = null, coreAvg = null;
        float? mobo = null, mhz = null, mhzMax = null;
        var fans = new List<KeyValuePair<string, float>>();
        var controls = new List<Ctl>();
        string superio = "";

        foreach (IHardware h in c.Hardware)
        {
            h.Update();
            string type = h.HardwareType.ToString();
            if (type == "Cpu")
            {
                foreach (ISensor s in h.Sensors)
                {
                    if (!s.Value.HasValue) continue;
                    if (s.SensorType == SensorType.Temperature)
                    {
                        string n = s.Name;
                        if (n == "CPU Package") pkg = s.Value;
                        else if (n == "Core Max") coreMax = s.Value;
                        else if (n == "Core Average") coreAvg = s.Value;
                    }
                }
                ScanClock(h, ref mhz, ref mhzMax);
            }
            foreach (IHardware sub in h.SubHardware)
            {
                sub.Update();
                if (superio == "")
                {
                    string st = sub.HardwareType.ToString();
                    if (st == "SuperIO" || st == "EmbeddedController") superio = sub.Name;
                }
                // CPU 频率传感器有可能挂在子硬件下，这里一并找
                if (type == "Cpu") ScanClock(sub, ref mhz, ref mhzMax);
                Collect(sub, ref mobo, fans, controls);
            }
            Collect(h, ref mobo, fans, controls);
        }

        if (!pkg.HasValue) pkg = coreMax;
        if (!coreMax.HasValue) coreMax = pkg;

        var sb = new StringBuilder();
        sb.Append("{");
        sb.Append("\"ts\":").Append(Now()).Append(",");
        sb.Append("\"ok\":").Append((pkg.HasValue || fans.Count > 0) ? "true" : "false").Append(",");
        sb.Append("\"cpu_package\":").Append(Num(pkg)).Append(",");
        sb.Append("\"cpu_max\":").Append(Num(coreMax)).Append(",");
        sb.Append("\"cpu_avg\":").Append(Num(coreAvg)).Append(",");
        sb.Append("\"cpu_mhz\":").Append(Num(mhz)).Append(",");
        sb.Append("\"cpu_mhz_max\":").Append(Num(mhzMax)).Append(",");
        sb.Append("\"mobo\":").Append(Num(mobo)).Append(",");
        sb.Append("\"superio\":\"").Append(Esc(superio)).Append("\",");
        sb.Append("\"fans\":[");
        for (int i = 0; i < fans.Count; i++)
        {
            if (i > 0) sb.Append(",");
            sb.Append("{\"n\":\"").Append(Esc(fans[i].Key)).Append("\",\"v\":")
              .Append(fans[i].Value.ToString("0.#", CultureInfo.InvariantCulture)).Append("}");
        }
        sb.Append("],\"controls\":[");
        for (int i = 0; i < controls.Count; i++)
        {
            Ctl k = controls[i];
            if (i > 0) sb.Append(",");
            sb.Append("{\"n\":\"").Append(Esc(k.Name)).Append("\",\"v\":")
              .Append(k.Value.ToString("0.#", CultureInfo.InvariantCulture))
              .Append(",\"m\":\"").Append(Esc(k.Mode)).Append("\",\"min\":")
              .Append(k.Min.ToString("0.#", CultureInfo.InvariantCulture))
              .Append(",\"max\":").Append(k.Max.ToString("0.#", CultureInfo.InvariantCulture))
              .Append("}");
        }
        sb.Append("]}");
        return sb.ToString();
    }

    static void Collect(IHardware h, ref float? mobo, List<KeyValuePair<string, float>> fans,
                        List<Ctl> controls)
    {
        foreach (ISensor s in h.Sensors)
        {
            if (s.SensorType == SensorType.Control)
            {                var k = new Ctl();
                k.Name = s.Name;
                k.Value = s.Value.HasValue ? s.Value.Value : -1f;
                k.Sensor = s;
                k.Mode = "?";
                k.Min = 0f;
                k.Max = 100f;
                try
                {
                    if (s.Control != null)
                    {
                        k.Mode = s.Control.ControlMode.ToString();
                        k.Min = s.Control.MinSoftwareValue;
                        k.Max = s.Control.MaxSoftwareValue;
                        float? sw = s.Control.SoftwareValue;
                        if (sw.HasValue && s.Control.ControlMode == ControlMode.Software) k.Value = sw.Value;
                    }
                }
                catch { }
                controls.Add(k);
            }
            if (!s.Value.HasValue) continue;
            if (s.SensorType == SensorType.Temperature)
            {
                // 主板上的 "CPU Core" 传感器是贴近 CPU 的板载测温点，比 CPU 内部低几度
                if (mobo == null && s.Name == "CPU Core") mobo = s.Value;
                if (mobo == null && s.Name.StartsWith("System") && s.Value < 90) mobo = s.Value;
            }
            else if (s.SensorType == SensorType.Fan)
            {
                if (s.Value.Value > 0) fans.Add(new KeyValuePair<string, float>(s.Name, s.Value.Value));
            }
        }
    }

    // 从硬件（含子硬件）里取 CPU 实际频率（LHM 的时钟传感器名形如 "CPU Core #1"）
    static void ScanClock(IHardware h, ref float? avg, ref float? max)
    {
        float sum = 0f;
        int cnt = 0;
        float mx = float.MinValue;
        AccClock(h, ref sum, ref cnt, ref mx);
        if (cnt > 0)
        {
            avg = sum / cnt;
            max = mx;
        }
    }

    static void AccClock(IHardware h, ref float sum, ref int cnt, ref float mx)
    {
        foreach (ISensor s in h.Sensors)
        {
            if (s.SensorType != SensorType.Clock || !s.Value.HasValue) continue;
            if (!s.Name.Contains("Core #")) continue;
            float v = s.Value.Value;
            sum += v;
            cnt++;
            if (v > mx) mx = v;
        }
        foreach (IHardware sub in h.SubHardware) AccClock(sub, ref sum, ref cnt, ref mx);
    }

    static string Num(float? v)
    {
        if (!v.HasValue || float.IsNaN(v.Value)) return "null";
        return v.Value.ToString("0.#", CultureInfo.InvariantCulture);
    }

    static long Now()
    {
        return (long)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
    }

    static string Esc(string s)
    {
        return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    static void WriteAtomic(string path, string text)
    {
        string tmp = path + ".tmp";
        File.WriteAllText(tmp, text, new UTF8Encoding(false));
        if (File.Exists(path))
        {
            try { File.Replace(tmp, path, null); return; }
            catch { File.Delete(path); }
        }
        File.Move(tmp, path);
    }

    // ---------------------------------------------------------------- 风扇控制
    static List<Ctl> ControlList(Computer c)
    {
        var list = new List<Ctl>();
        float? dummy = null;
        foreach (IHardware h in c.Hardware)
        {
            h.Update();
            foreach (IHardware sub in h.SubHardware)
            {
                sub.Update();
                Collect(sub, ref dummy, new List<KeyValuePair<string, float>>(), list);
            }
            Collect(h, ref dummy, new List<KeyValuePair<string, float>>(), list);
        }
        return list;
    }

    static bool ApplyFan(Computer c, int index, bool toDefault, float value,
                         out string err, out string modeText, out float readBack)
    {
        err = "";
        modeText = "?";
        readBack = -1f;
        var list = ControlList(c);
        if (list.Count == 0)
        {
            err = "没有可调节的风扇通道";
            return false;
        }
        var targets = new List<int>();
        if (index < 0) for (int i = 0; i < list.Count; i++) targets.Add(i);   // -1 = 全部
        else if (index < list.Count) targets.Add(index);
        else
        {
            err = "没有第 " + index + " 路风扇（共 " + list.Count + " 路）";
            return false;
        }

        int okCount = 0;
        var errs = new List<string>();
        foreach (int t in targets)
        {
            Ctl k = list[t];
            if (k.Sensor == null || k.Sensor.Control == null)
            {
                errs.Add(k.Name + " 不支持调节");
                continue;
            }
            try
            {
                if (toDefault)
                {
                    k.Sensor.Control.SetDefault();
                }
                else
                {
                    float v = value;
                    if (v < k.Min) v = k.Min;
                    if (v > k.Max) v = k.Max;
                    k.Sensor.Control.SetSoftware(v);
                }
                okCount++;
            }
            catch (Exception e)
            {
                errs.Add(k.Name + ":" + e.Message);
            }
        }
        if (okCount == 0)
        {
            err = errs.Count > 0 ? string.Join("; ", errs.ToArray()) : "写入失败";
            return false;
        }
        if (errs.Count > 0) err = string.Join("; ", errs.ToArray());

        // 写完后重新读一遍，回报真实状态
        var again = ControlList(c);
        if (index < 0)
        {
            modeText = toDefault ? "Default" : "Software";
            readBack = toDefault ? value : value;
        }
        else if (index < again.Count)
        {
            modeText = again[index].Mode;
            readBack = again[index].Value;
        }
        return true;
    }

    static void DumpTree(IHardware h, int depth, StringBuilder sb)
    {
        h.Update();
        sb.AppendLine(new string(' ', depth * 2) + "[" + h.HardwareType + "] " + h.Name);
        foreach (ISensor s in h.Sensors)
        {
            string v = s.Value.HasValue ? s.Value.Value.ToString("0.#", CultureInfo.InvariantCulture) : "null";
            sb.AppendLine(new string(' ', depth * 2 + 2) + "<" + s.SensorType + "> " + s.Name + " = " + v);
        }
        foreach (IHardware sub in h.SubHardware) DumpTree(sub, depth + 1, sb);
    }

    static void WriteTree(Computer c, string path)
    {
        var sb = new StringBuilder();
        foreach (IHardware h in c.Hardware) DumpTree(h, 0, sb);
        File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
    }

    static void WriteResult(string dir, bool ok, int index, float value, string mode, string err)
    {
        var sb = new StringBuilder();
        sb.Append("{\"ts\":").Append(Now()).Append(",");
        sb.Append("\"ok\":").Append(ok ? "true" : "false").Append(",");
        sb.Append("\"i\":").Append(index).Append(",");
        sb.Append("\"v\":").Append(value.ToString("0.#", CultureInfo.InvariantCulture)).Append(",");
        sb.Append("\"mode\":\"").Append(Esc(mode)).Append("\",");
        sb.Append("\"err\":\"").Append(Esc(err)).Append("\"}");
        try { WriteAtomic(Path.Combine(dir, "hwmon_result.json"), sb.ToString()); } catch { }
    }

    static double Field(string json, string key, double dflt)
    {
        Match m = Regex.Match(json ?? "", "\"" + key + "\"\\s*:\\s*(-?[0-9.]+)");
        if (m.Success)
        {
            double d;
            if (double.TryParse(m.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) return d;
        }
        return dflt;
    }

    static string StrField(string json, string key)
    {
        Match m = Regex.Match(json ?? "", "\"" + key + "\"\\s*:\\s*\"([^\"]*)\"");
        return m.Success ? m.Groups[1].Value : "";
    }

    // ------------------------------------------------ 开机还原风扇档案
    // 主界面把当前风扇模式 / 各路占空比写进 data\fan_profile.json；本程序是最高权限
    // 常驻组件，开机随计划任务起来后直接按档案把 SIO 占空比写回去，不必等主界面。
    static List<float> FanProfileValues(string json)
    {
        Match m = Regex.Match(json ?? "", "\"values\"\\s*:\\s*\\[([^\\]]*)\\]");
        if (!m.Success) return null;
        var list = new List<float>();
        foreach (string tok in m.Groups[1].Value.Split(','))
        {
            float v;
            if (float.TryParse(tok.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out v))
                list.Add(v);
        }
        return list.Count > 0 ? list : null;
    }

    static void RestoreFanProfile(Computer c)
    {
        try
        {
            string dir = Path.GetDirectoryName(_outPath);
            if (dir == null) return;
            string path = Path.Combine(dir, "fan_profile.json");
            if (!File.Exists(path)) return;
            string json = File.ReadAllText(path);
            string mode = StrField(json, "mode");
            if (mode == "bios" || mode == "") return;      // 用户主动交回 BIOS，保持默认
            List<float> values = FanProfileValues(json);
            if (values == null) return;
            var list = ControlList(c);
            if (list.Count == 0) { Log("开机还原风扇：没有可调通道"); return; }
            int ok = 0;
            for (int i = 0; i < list.Count && i < values.Count; i++)
            {
                string err, modeText;
                float back;
                if (ApplyFan(c, i, false, values[i], out err, out modeText, out back)) ok++;
                else Log("开机还原风扇 i=" + i + " 失败: " + err);
            }
            Log("开机还原风扇配置 mode=" + mode + " 成功 " + ok + "/" + list.Count);
        }
        catch (Exception e)
        {
            Log("开机还原风扇档案失败: " + e.Message);
        }
    }

    static void HandleCommandFile(Computer c)
    {        string dir = Path.GetDirectoryName(_outPath);
        if (dir == null) return;
        string cmdPath = Path.Combine(dir, "hwmon_cmd.json");
        if (!File.Exists(cmdPath)) return;

        string json = "";
        try { json = File.ReadAllText(cmdPath); }
        catch { return; }
        try { File.Delete(cmdPath); } catch { }

        string act = StrField(json, "a");
        int idx = (int)Field(json, "i", -1);
        float val = (float)Field(json, "v", -1);
        bool toDefault = act == "default" || act == "auto";

        if (act == "tree")
        {
            try { WriteTree(c, Path.Combine(dir, "hwmon_tree.txt")); }
            catch (Exception e) { Log("导出硬件树失败: " + e.Message); }
            WriteResult(dir, true, -1, 0, "tree", "");
            return;
        }

        string err, modeText;
        float back;
        bool ok = ApplyFan(c, idx, toDefault, val, out err, out modeText, out back);
        WriteResult(dir, ok, idx, ok ? back : val, modeText, err);
        Log("风扇命令 " + act + " i=" + idx + " v=" + val + " -> " + (ok ? "ok" : err));
    }

    static int FanOnce(string idxText, string valText, bool toDefault)
    {
        int idx;
        if (!int.TryParse(idxText, out idx)) { Console.WriteLine("[ERR] 序号不是数字"); return 2; }
        float val = 0f;
        if (!toDefault && valText != null) float.TryParse(valText, NumberStyles.Float, CultureInfo.InvariantCulture, out val);

        Computer c = null;
        try
        {
            c = NewComputer();
            c.Open();
            string err, modeText;
            float back;
            bool ok = ApplyFan(c, idx, toDefault, val, out err, out modeText, out back);
            Console.WriteLine((ok ? "[OK] " : "[ERR] ") + "i=" + idx
                              + " mode=" + modeText + " value=" + back.ToString("0.#", CultureInfo.InvariantCulture)
                              + (ok ? "" : " " + err));
            return ok ? 0 : 3;
        }
        catch (Exception e)
        {
            Console.WriteLine("[ERR] " + e.GetType().Name + ": " + e.Message);
            return 2;
        }
        finally
        {
            try { if (c != null) c.Close(); } catch { }
        }
    }

    // ---------------------------------------------------------------- 常驻
    static int RunForever()
    {
        bool created;
        _mutex = new Mutex(false, MUTEX_NAME, out created);
        if (!created)
        {
            Log("已有实例在跑，本进程退出");
            return 0;
        }

        Computer c = null;
        try
        {
            Log("准备 Open 驱动");
            c = NewComputer();
            c.Open();
            Log("采集已启动 -> " + _outPath);
            RestoreFanProfile(c);
        }
        catch (Exception e)
        {
            Log("打开驱动失败（需要管理员权限）: " + e.GetType().Name + ": " + e.Message);
            try { if (c != null) c.Close(); } catch { }
            return 2;
        }

        DateTime lastErrLog = DateTime.MinValue;
        bool first = true;
        while (true)
        {
            try
            {
                if (first) { Log("首轮采集开始"); }
                WriteAtomic(_outPath, Sample(c));
                if (first) { Log("首轮采集完成"); first = false; }
            }
            catch (Exception e)
            {
                if ((DateTime.Now - lastErrLog).TotalSeconds > 60)
                {
                    Log("写 JSON 失败: " + e.Message);
                    lastErrLog = DateTime.Now;
                }
            }
            try
            {
                HandleCommandFile(c);
            }
            catch (Exception e)
            {
                Log("处理风扇命令失败: " + e.Message);
            }
            // 采一次 2 秒，但这 2 秒里每 0.33 秒看一眼有没有风扇命令，
            // 否则拖完滑块要等两秒才生效，手感很差
            for (int k = 0; k < 6; k++)
            {
                Thread.Sleep(330);
                try { HandleCommandFile(c); }
                catch { }
            }
        }
    }

    static int Once()
    {
        try
        {
            var c = NewComputer();
            c.Open();
            string json = Sample(c);
            Console.WriteLine(json);
            c.Close();
            return 0;
        }
        catch (Exception e)
        {
            Console.WriteLine("[ERR] " + e.GetType().Name + ": " + e.Message);
            return 2;
        }
    }

    // ---------------------------------------------------------------- 计划任务
    static int Install()
    {
        string exe = Application_ExecutablePath();
        string args = "/create /tn \"" + TASK_NAME + "\" /tr \"\\\"" + exe + "\\\"\" "
                    + "/sc onlogon /rl highest /delay 0000:20 /f";
        int rc = RunTool("schtasks.exe", args);
        Log("注册计划任务 rc=" + rc);
        if (rc == 0)
        {
            try { Process.Start(new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true }); }
            catch (Exception e) { Log("启动采集实例失败: " + e.Message); }
        }
        return rc;
    }

    static int Remove()
    {
        int rc = RunTool("schtasks.exe", "/delete /tn \"" + TASK_NAME + "\" /f");
        Log("删除计划任务 rc=" + rc);
        return 0;
    }

    static int RunTool(string exe, string args)
    {
        try
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            var p = Process.Start(psi);
            string output = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            p.WaitForExit(15000);
            if (output.Trim().Length > 0) Log(output.Trim());
            return p.HasExited ? p.ExitCode : -1;
        }
        catch (Exception e)
        {
            Log("调用 " + exe + " 失败: " + e.Message);
            return -1;
        }
    }

    static void Log(string msg)
    {
        // 始终写日志：计划任务身份下 UserInteractive 为 false，之前靠它开关会把关键
        // 排障信息全部丢掉（风扇调试期非常需要）。
        try
        {
            string logPath = Path.Combine(Path.GetDirectoryName(_outPath) ?? ".", "hwmon.log");
            File.AppendAllText(logPath, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg + "\r\n",
                               new UTF8Encoding(false));
        }
        catch { }
    }
}
