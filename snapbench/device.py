"""Device, SoC, OS, clocks and thermal state. Everything is best effort:
a field that cannot be read is None, never a guess."""

import glob
import os
import platform
import re
import shutil
import subprocess
import sys

from . import socs


def detect_os():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if os.environ.get("TERMUX_VERSION") or os.path.exists("/system/build.prop") \
            or "ANDROID_ROOT" in os.environ:
        return "android"
    return "linux"


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace").strip("\x00").strip()
    except OSError:
        return None


def _int(text):
    try:
        return int(str(text).strip().split()[0])
    except (ValueError, IndexError, TypeError):
        return None


def _run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def getprop(name):
    if not shutil.which("getprop"):
        return None
    v = _run(["getprop", name])
    return v or None


def _powershell(query):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    return _run([exe, "-NoProfile", "-Command", query], timeout=60)


# --- CPU ---------------------------------------------------------------------

def cpu_clusters():
    """Group CPUs by max frequency (Linux/Android). [{cpus: [...], max_khz}]"""
    by_freq = {}
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq")):
        cpu = int(re.search(r"cpu(\d+)/", path).group(1))
        f = _int(_read(path))
        if f:
            by_freq.setdefault(f, []).append(cpu)
    return [{"cpus": sorted(c), "max_khz": f} for f, c in sorted(by_freq.items())]


def default_threads(clusters, cpu_count):
    """Threads for the CPU backend: every core in clusters that reach >= 80% of
    the top frequency (prime + performance cores, not efficiency cores).
    Oversubscribing onto slow cores can cut token generation by 10x."""
    if clusters:
        top = max(c["max_khz"] for c in clusters)
        n = sum(len(c["cpus"]) for c in clusters if c["max_khz"] >= 0.8 * top)
        if n:
            return n
    if sys.platform == "darwin":  # --dev runs only
        n = _int(_run(["sysctl", "-n", "hw.perflevel0.physicalcpu"]))
        if n:
            return n
    return cpu_count or 4


def cpu_freqs_khz():
    out = {}
    for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
        cpu = int(re.search(r"cpu(\d+)/", path).group(1))
        f = _int(_read(path))
        if f is not None:
            out[str(cpu)] = f
    return out or None


def cpu_governor():
    return _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")


# --- GPU clocks ----------------------------------------------------------------

def gpu_clock_mhz():
    """Current GPU clock. Android kgsl first, then upstream msm devfreq."""
    hz = _int(_read("/sys/class/kgsl/kgsl-3d0/gpuclk"))
    if hz:
        return round(hz / 1e6)
    for p in ("/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq",) + tuple(glob.glob("/sys/class/devfreq/*gpu*/cur_freq")):
        hz = _int(_read(p))
        if hz:
            return round(hz / 1e6) if hz > 1e5 else hz
    return None


def gpu_max_clock_mhz():
    hz = _int(_read("/sys/class/kgsl/kgsl-3d0/max_gpuclk"))
    if hz:
        return round(hz / 1e6)
    for p in glob.glob("/sys/class/devfreq/*gpu*/max_freq"):
        hz = _int(_read(p))
        if hz:
            return round(hz / 1e6)
    return None


# --- thermal ------------------------------------------------------------------

def thermal_zones():
    """{zone type: degrees C}. Hottest reading wins when types repeat."""
    temps = {}
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        t = _int(_read(zone + "/temp"))
        name = _read(zone + "/type") or os.path.basename(zone)
        if t is None or t <= -40000 or t == 0:
            continue
        c = t / 1000.0 if abs(t) > 200 else float(t)
        if c > 150:
            continue
        temps[name] = round(max(c, temps.get(name, -1e9)), 1)
    gpu = _int(_read("/sys/class/kgsl/kgsl-3d0/temp"))
    if gpu:
        temps["kgsl-gpu"] = round(gpu / 1000.0, 1) if gpu > 200 else float(gpu)
    return temps


def battery():
    """Battery state on Android/Linux laptops (power_supply class)."""
    for base in glob.glob("/sys/class/power_supply/*"):
        if (_read(base + "/type") or "").lower() != "battery":
            continue
        temp = _int(_read(base + "/temp"))
        return {
            "status": _read(base + "/status"),
            "capacity_pct": _int(_read(base + "/capacity")),
            "temp_c": round(temp / 10.0, 1) if temp is not None else None,
        }
    return None


def snapshot():
    """Clocks and temperatures right now. Taken before and after every run."""
    zones = thermal_zones()
    snap = {
        "max_temp_c": max(zones.values()) if zones else None,
        "zones_c": _hottest(zones, 12),
        "gpu_clock_mhz": gpu_clock_mhz(),
        "cpu_freq_khz": cpu_freqs_khz(),
    }
    b = battery()
    if b:
        snap["battery"] = b
    return snap


def _hottest(zones, n):
    if not zones:
        return None
    return dict(sorted(zones.items(), key=lambda kv: -kv[1])[:n])


# --- device / SoC --------------------------------------------------------------

def collect(os_name=None):
    os_name = os_name or detect_os()
    info = {
        "platform": {
            "os": os_name,
            "os_version": None,
            "kernel": platform.release() if os_name != "windows" else None,
            "arch": platform.machine(),
            "termux": bool(os.environ.get("TERMUX_VERSION")),
            "python": platform.python_version(),
        },
        "device": {"manufacturer": None, "model": None},
        "soc": {"part": None, "name": None, "codename": None, "is_snapdragon": False,
                "hexagon_arch": None},
        "cpu": {"name": None, "cores": os.cpu_count(), "clusters": None, "governor": None},
        "gpu": {"name": None, "max_clock_mhz": None, "driver_version": None},
        "memory_mb": None,
    }
    if os_name == "android":
        _android(info)
    elif os_name == "windows":
        _windows(info)
    else:
        _linux(info)
    if os_name in ("android", "linux"):
        info["cpu"]["clusters"] = cpu_clusters() or None
        info["cpu"]["governor"] = cpu_governor()
        info["gpu"]["max_clock_mhz"] = gpu_max_clock_mhz()
        info["memory_mb"] = _meminfo_mb()
    part = info["soc"]["part"]
    name, gpu, hexagon = socs.lookup(part)
    info["soc"]["name"] = info["soc"]["name"] or name
    info["soc"]["hexagon_arch"] = hexagon
    if not info["gpu"]["name"] and gpu:
        info["gpu"]["name"] = gpu
        info["gpu"]["name_source"] = "soc table"
    hints = " ".join(str(x) for x in (info["soc"]["name"], info["soc"].get("family"),
                                         info["soc"].get("vendor"), info["cpu"]["name"])).lower()
    info["soc"]["is_snapdragon"] = bool(part) or "snapdragon" in hints or "qualcomm" in hints \
        or "qti" in hints
    return info


def _meminfo_mb():
    text = _read("/proc/meminfo") or ""
    m = re.search(r"MemTotal:\s+(\d+)", text)
    return int(m.group(1)) // 1024 if m else None


def _android(info):
    info["platform"]["os_version"] = getprop("ro.build.version.release")
    info["platform"]["android_sdk"] = _int(getprop("ro.build.version.sdk"))
    info["platform"]["build"] = getprop("ro.build.fingerprint")
    info["device"]["manufacturer"] = getprop("ro.product.manufacturer")
    info["device"]["model"] = getprop("ro.product.model")
    info["device"]["codename"] = getprop("ro.product.device")
    soc_model = getprop("ro.soc.model")
    board = getprop("ro.board.platform")
    machine = _read("/sys/devices/soc0/machine")
    part = socs.normalize_part(soc_model) or socs.normalize_part(machine) or socs.normalize_part(board)
    info["soc"]["part"] = part
    info["soc"]["codename"] = board
    info["soc"]["vendor"] = getprop("ro.soc.manufacturer")
    gpu = _read("/sys/class/kgsl/kgsl-3d0/gpu_model")
    if gpu:
        info["gpu"]["name"] = gpu
        info["gpu"]["name_source"] = "kgsl"
    info["cpu"]["name"] = _cpuinfo_hardware()


def _cpuinfo_hardware():
    text = _read("/proc/cpuinfo") or ""
    m = re.search(r"^Hardware\s*:\s*(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else None


def _linux(info):
    osr = _read("/etc/os-release") or ""
    m = re.search(r'^PRETTY_NAME="?([^"\n]+)', osr, flags=re.M)
    info["platform"]["os_version"] = m.group(1) if m else None
    model = _read("/sys/firmware/devicetree/base/model") or _read("/sys/class/dmi/id/product_name")
    info["device"]["model"] = model
    info["device"]["manufacturer"] = _read("/sys/class/dmi/id/sys_vendor")
    compatible = (_read("/sys/firmware/devicetree/base/compatible") or "").replace("\x00", " ")
    machine = _read("/sys/devices/soc0/machine")
    family = _read("/sys/devices/soc0/family")
    part = socs.normalize_part(machine) or socs.normalize_part(compatible.replace("qcom,", " "))
    if not part:
        m = re.search(r"qcom,(x1e\d+|x1p\d+|sm\d{4}|sc\d{4}\w*)", compatible)
        part = socs.normalize_part(m.group(1)) if m else None
    info["soc"]["part"] = part
    info["soc"]["codename"] = machine
    info["soc"]["family"] = family
    info["cpu"]["name"] = _lscpu_model()


def _lscpu_model():
    out = _run(["lscpu"]) or ""
    names = re.findall(r"^Model name:\s*(.+)$", out, flags=re.M)
    return " / ".join(dict.fromkeys(n.strip() for n in names)) or None


def _windows(info):
    info["platform"]["os_version"] = platform.version()
    cs = _powershell("$c=Get-CimInstance Win32_ComputerSystem; \"$($c.Manufacturer)|$($c.Model)|$($c.TotalPhysicalMemory)\"")
    if cs and "|" in cs:
        manu, model, mem = (cs.split("|") + ["", "", ""])[:3]
        info["device"]["manufacturer"] = manu.strip() or None
        info["device"]["model"] = model.strip() or None
        info["memory_mb"] = _int(mem) // (1024 * 1024) if _int(mem) else None
    cpu = _powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name")
    info["cpu"]["name"] = cpu
    info["soc"]["part"] = socs.normalize_part(cpu)
    gpu = _powershell("Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'Adreno|Qualcomm' } | "
                      "Select-Object -First 1 | ForEach-Object { \"$($_.Name)|$($_.DriverVersion)\" }")
    if gpu and "|" in gpu:
        name, ver = gpu.split("|", 1)
        info["gpu"]["name"] = name.strip() or None
        info["gpu"]["name_source"] = "Win32_VideoController"
        info["gpu"]["driver_version"] = ver.strip() or None
