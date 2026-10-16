"""Running llama-bench and parsing what it prints."""

import json
import os
import re
import subprocess

from . import drivers, matrix


def bench_env(bench_path, backend, os_name):
    """Environment for a llama-bench from a bundle or build tree."""
    env = dict(os.environ)
    bindir = os.path.dirname(os.path.abspath(bench_path))
    root = os.path.dirname(bindir) if os.path.basename(bindir) == "bin" else bindir
    libdirs = [d for d in (os.path.join(root, "lib"), bindir) if os.path.isdir(d)]
    if os_name == "windows":
        env["PATH"] = os.pathsep.join(libdirs + [env.get("PATH", "")])
        return env
    extra = []
    if os_name == "android" and backend in ("opencl", "hexagon"):
        # libOpenCL.so and libcdsprpc.so live in the vendor partition.
        extra = [d for d in ("/vendor/lib64", "/system/vendor/lib64") if os.path.isdir(d)]
    var = "DYLD_LIBRARY_PATH" if os_name == "macos" else "LD_LIBRARY_PATH"
    env[var] = os.pathsep.join(libdirs + extra + ([env[var]] if env.get(var) else []))
    if backend == "hexagon":
        env["ADSP_LIBRARY_PATH"] = libdirs[0] if libdirs else bindir
    return env


_DEV = re.compile(r"^\s+(?P<name>[\w:\[\],-]+):\s+(?P<desc>.*?)\s*(\((?P<total>\d+) MiB, (?P<free>\d+) MiB free\))?\s*$")


def parse_list_devices(text):
    """`llama-bench --list-devices` -> [{name, description, memory_mib, free_mib}]"""
    out = []
    started = False
    for line in text.splitlines():
        if line.strip().startswith("Available devices"):
            started = True
            continue
        if not started:
            continue
        m = _DEV.match(line)
        if m:
            out.append({
                "name": m.group("name"),
                "description": m.group("desc"),
                "memory_mib": int(m.group("total")) if m.group("total") else None,
                "free_mib": int(m.group("free")) if m.group("free") else None,
            })
    return out


def list_devices(bench, env, timeout=120):
    try:
        p = subprocess.run([bench, "--list-devices"], capture_output=True, text=True,
                           env=env, timeout=timeout, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], str(e)
    devs = parse_list_devices(p.stdout + "\n" + p.stderr)
    if p.returncode != 0 and not devs:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        return [], "llama-bench --list-devices failed: %s" % " | ".join(tail)
    return devs, None


def pick_device(backend, devices):
    if backend == "cpu":
        return "none"
    pat = re.compile(matrix.DEVICE_PATTERNS[backend])
    for d in devices:
        if pat.search(d["name"]):
            return d["name"]
    return None


def parse_bench_output(text):
    """llama-bench `-o json` (array) or `-o jsonl` (one object per line)."""
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def test_name(row):
    p, g, d = row.get("n_prompt", 0), row.get("n_gen", 0), row.get("n_depth", 0)
    if p and g:
        name = "pp%d+tg%d" % (p, g)
    elif p:
        name = "pp%d" % p
    else:
        name = "tg%d" % g
    return name + ("@d%d" % d if d else "")


# Fields of a llama-bench row worth keeping verbatim next to our summary.
RAW_KEEP = ["build_commit", "build_number", "cpu_info", "gpu_info", "backends", "devices",
            "model_type", "model_size", "model_n_params", "n_batch", "n_ubatch", "n_threads",
            "type_k", "type_v", "n_gpu_layers", "flash_attn", "repack", "load_mode",
            "n_prompt", "n_gen", "n_depth", "test_time"]


def summarize_row(row):
    return {
        "test": test_name(row),
        "avg_ts": round(float(row["avg_ts"]), 3),
        "stddev_ts": round(float(row.get("stddev_ts", 0.0)), 3),
        "samples_ts": [round(float(x), 3) for x in row.get("samples_ts", [])],
        "llama_bench": {k: row[k] for k in RAW_KEEP if k in row},
    }


def bench_args(bench, model_path, backend, device, threads, reps, n_prompt, n_gen):
    args = [bench, "-m", model_path, "-p", str(n_prompt), "-n", str(n_gen),
            "-r", str(reps), "-t", str(threads), "-o", "jsonl"]
    if backend == "cpu":
        args += ["-dev", "none", "-ngl", "0"]
    else:
        args += ["-dev", device, "-ngl", str(matrix.GPU_LAYERS)]
    return args


def run_bench(args, env, timeout):
    """Run llama-bench. Returns (rows, stderr_tail, error)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=env,
                           timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return parse_bench_output(out), [], "timed out after %ds" % timeout
    except OSError as e:
        return [], [], str(e)
    rows = parse_bench_output(p.stdout)
    tail = [l for l in p.stderr.strip().splitlines() if l.strip()][-20:]
    err = None
    if p.returncode != 0:
        err = "llama-bench exited with %d" % p.returncode
        if p.returncode < 0:
            err += " (signal %d)" % -p.returncode
    elif not rows:
        err = "llama-bench printed no results"
    return rows, tail, err


def probe(bench, model_path, backend, device, env, timeout=600):
    """A tiny verbose run to capture the backend's init lines (driver, int dot,
    matrix cores, which device got the weights). Kept separate from the timed
    runs so verbose logging never touches the numbers."""
    args = [bench, "-m", model_path, "-p", "32", "-n", "0", "-r", "1", "--no-warmup",
            "-v", "-o", "json"]
    if backend == "cpu":
        args += ["-dev", "none", "-ngl", "0"]
    else:
        args += ["-dev", device, "-ngl", str(matrix.GPU_LAYERS)]
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=env,
                           timeout=timeout, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e), "log": [], "info": {}}
    lines = p.stderr.splitlines()
    ok = p.returncode == 0 and bool(parse_bench_output(p.stdout))
    result = {"ok": ok, "log": drivers.filter_log(lines), "info": drivers.parse_backend_log(lines)}
    if not ok:
        result["error"] = "exit %d: %s" % (p.returncode, " | ".join(l for l in lines[-5:] if l.strip()))
    return result


def bench_version(bench, env):
    try:
        p = subprocess.run([bench, "--version"], capture_output=True, text=True, env=env,
                           timeout=60, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = p.stdout + p.stderr
    m = re.search(r"version: (\S+) \(build (\d+), commit ([0-9a-f]+)\)", text)
    if not m:
        return None
    built = re.search(r"^built with (.+)$", text, flags=re.M)
    return {"version": m.group(1), "build_number": int(m.group(2)), "commit": m.group(3),
            "built_with": built.group(1).strip() if built else None}
