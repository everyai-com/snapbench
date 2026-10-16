"""The benchmark run: prepare backends, probe them, run the matrix, write JSON."""

import datetime
import json
import os
import re
import shutil
import sys
import time
import uuid

from . import __version__, bench, device, drivers, fetch, matrix, validate

ENV_KEYS = re.compile(r"^(VK_ICD_FILENAMES|VK_DRIVER_FILES|VK_LOADER_\w+|TU_DEBUG|FD_\w+|MESA_\w+|"
                      r"GGML_\w+|ADSP_LIBRARY_PATH|OPENCL_VENDOR_PATH)$")


def default_home():
    if os.environ.get("SNAPBENCH_HOME"):
        return os.environ["SNAPBENCH_HOME"]
    if sys.platform.startswith("win") and os.environ.get("LOCALAPPDATA"):
        return os.path.join(os.environ["LOCALAPPDATA"], "snapbench")
    return os.path.join(os.path.expanduser("~"), ".snapbench")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    print(msg, flush=True)


def prepare_backend(backend, os_name, args, home):
    """Return (bench_path, source_record) or raise RuntimeError(reason)."""
    custom = dict(args.llama_bench or [])
    if backend in custom:
        path = custom[backend]
        if os.path.isdir(path):
            path = fetch.find_bench(path)
        if not path or not os.path.isfile(path):
            raise RuntimeError("--llama-bench %s=%s: llama-bench not found" % (backend, custom[backend]))
        return path, {"kind": "custom", "path": path}
    sources = matrix.BACKEND_SOURCES.get(os_name, {})
    src = sources.get(backend)
    if src is None:
        raise RuntimeError("%s is not part of the matrix on %s" % (backend, os_name))
    if args.from_source and backend in matrix.CMAKE_FLAGS:
        src = "source"
    if src == "source":
        build = fetch.source_build(backend, home, log=log)
        return fetch.find_bench(build), {"kind": "source", "path": build}
    root = fetch.bundle(src, home, log=log)
    path = fetch.find_bench(root)
    if not path:
        raise RuntimeError("llama-bench missing from bundle %s" % src)
    b = matrix.BUNDLES[src]
    return path, {"kind": "release", "bundle": b["name"], "sha256": b["sha256"]}


def selected(arg, allowed, default):
    if not arg:
        return list(default)
    items = [x.strip() for x in arg.split(",") if x.strip()]
    bad = [x for x in items if x not in allowed]
    if bad:
        raise SystemExit("unknown value(s) %s; choose from %s" % (", ".join(bad), ", ".join(allowed)))
    return items


def wait_cool(baseline, cooldown, limit_factor=4):
    if cooldown <= 0:
        return
    time.sleep(cooldown)
    if baseline is None:
        return
    waited = cooldown
    while waited < cooldown * limit_factor:
        t = device.snapshot().get("max_temp_c")
        if t is None or t <= baseline + 8:
            return
        time.sleep(5)
        waited += 5


def write(doc, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def slug(*parts):
    s = "-".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "device"


def main(args):
    os_name = device.detect_os()
    home = os.path.abspath(args.home or default_home())
    os.makedirs(home, exist_ok=True)

    info = device.collect(os_name)
    dev = info["device"]
    soc = info["soc"]
    log("snapbench %s, matrix %s, llama.cpp %s (%s)" % (__version__, matrix.MATRIX_VERSION,
                                                       matrix.LLAMA_CPP["tag"], matrix.LLAMA_CPP["commit"][:9]))
    log("device: %s %s | SoC: %s %s | GPU: %s | %s %s" % (
        dev.get("manufacturer"), dev.get("model"), soc.get("part"), soc.get("name") or "",
        info["gpu"].get("name"), os_name, info["platform"].get("os_version") or ""))

    if not soc["is_snapdragon"] and not args.dev:
        raise SystemExit("This does not look like a Snapdragon device. snapbench only collects "
                         "Snapdragon results. Use --dev to try the runner anyway (the result is "
                         "marked provenance=dev and cannot be submitted).")
    # Custom llama-bench builds on Snapdragon stay "measured"; llama_cpp.sources says kind=custom.
    provenance = "dev" if args.dev else "measured"

    os_backends = list(matrix.BACKEND_SOURCES.get(os_name, {}).keys()) or ["cpu"]
    custom = dict(args.llama_bench or [])
    backends = selected(args.backends, matrix.BACKENDS,
                        [b for b in matrix.BACKENDS if b in os_backends or b in custom])
    models = selected(args.models, list(matrix.MODELS), list(matrix.MODELS))
    quants = selected(args.quants, matrix.QUANTS, matrix.QUANTS)
    if args.quick:
        models, quants = models[:1], quants[:1]
    full = (set(backends) >= set(os_backends) and models == list(matrix.MODELS)
            and quants == matrix.QUANTS and not args.quick)

    need = sum(matrix.MODELS[m]["files"][q][1] for m in models for q in quants)
    free = shutil.disk_usage(home).free
    log("models: %s | quants: %s | backends: %s | ~%.1f GB of models, %.1f GB free in %s" % (
        ", ".join(models), ", ".join(quants), ", ".join(backends), need / 1e9, free / 1e9, home))
    missing = sum(matrix.MODELS[m]["files"][q][1] for m in models for q in quants
                  if not os.path.exists(os.path.join(home, "models", matrix.MODELS[m]["files"][q][0])))
    if missing + 500e6 > free:
        msg = ("not enough free space: %.1f GB of models still to download, %.1f GB free. "
               "Free some space, set SNAPBENCH_HOME to a bigger drive, or limit --models/--quants."
               % (missing / 1e9, free / 1e9))
        if not args.dry_run:
            raise SystemExit(msg)
        log("warning: " + msg)
    if args.dry_run:
        return 0

    threads = args.threads or device.default_threads(info["cpu"].get("clusters"), info["cpu"].get("cores"))
    env_seen = {k: v for k, v in os.environ.items() if ENV_KEYS.match(k)}

    vk_gpus, vk_err = drivers.run_vulkaninfo()
    doc = {
        "schema_version": 1,
        "id": str(uuid.uuid4()),
        "provenance": provenance,
        "created_at": now_utc(),
        "tool": {"name": "snapbench", "version": __version__, "matrix_version": matrix.MATRIX_VERSION,
                 "args": sys.argv[1:]},
        "llama_cpp": {"tag": matrix.LLAMA_CPP["tag"], "commit": matrix.LLAMA_CPP["commit"], "sources": {}},
        "platform": info["platform"],
        "device": info["device"],
        "soc": info["soc"],
        "cpu": info["cpu"],
        "gpu": info["gpu"],
        "memory_mb": info["memory_mb"],
        "vulkaninfo": {"available": bool(vk_gpus), "error": vk_err, "gpus": vk_gpus},
        "backends": {},
        "config": {"n_prompt": args.n_prompt, "n_gen": args.n_gen, "repetitions": args.repetitions,
                   "threads": threads, "gpu_layers": matrix.GPU_LAYERS, "cooldown_s": args.cooldown,
                   "timeout_s": args.timeout, "full_matrix": full, "env": env_seen},
        "runs": [],
        "submitter": {"github": args.github, "notes": args.notes},
    }
    if vk_gpus:
        for g in vk_gpus:
            log("vulkan: %s | %s %s | int8 dot accelerated: %s | coopmat: %s | subgroup %s" % (
                g["device_name"], g["driver_kind"], g.get("mesa_version") or g.get("driver_version"),
                g["int_dot"]["int8_packed_signed_accelerated"], g["cooperative_matrix"]["extension"],
                g["subgroup"]["size"]))
    else:
        log("vulkaninfo: %s" % vk_err)

    out = args.out or os.path.join(os.getcwd(), "snapbench-%s-%s.json" % (
        slug(soc.get("part"), dev.get("model")), doc["created_at"][:10]))
    write(doc, out)

    # Model files first: the probe needs the smallest one.
    paths = {}
    for m in models:
        for q in quants:
            paths[(m, q)] = fetch.model(m, q, home, log=log)
    probe_model = paths[(models[0], quants[0])]

    ready = {}
    for b in matrix.BACKENDS:
        if b not in backends:
            if b in os_backends:
                doc["backends"][b] = {"status": "skipped", "reason": "not selected"}
            continue
        log("[%s] preparing" % b)
        try:
            path, src = prepare_backend(b, os_name, args, home)
        except Exception as e:  # noqa: BLE001 - every failure is a recorded reason
            doc["backends"][b] = {"status": "unavailable", "reason": str(e)}
            log("[%s] unavailable: %s" % (b, e))
            continue
        env = bench.bench_env(path, b, os_name)
        src["version"] = bench.bench_version(path, env)
        doc["llama_cpp"]["sources"][b] = src
        devs, err = bench.list_devices(path, env)
        dev_name = bench.pick_device(b, devs)
        rec = {"status": "ok", "reason": None, "device": dev_name, "devices": devs}
        if dev_name is None:
            rec.update(status="unavailable", reason=err or "no %s device listed by llama-bench" % b)
            doc["backends"][b] = rec
            log("[%s] unavailable: %s" % (b, rec["reason"]))
            continue
        pr = bench.probe(path, probe_model, b, dev_name, env)
        rec["probe"] = pr
        if not pr["ok"]:
            rec.update(status="failed", reason="probe failed: %s" % pr.get("error"))
            log("[%s] failed: %s" % (b, rec["reason"]))
        else:
            ready[b] = (path, env, dev_name)
            log("[%s] ok, device %s" % (b, dev_name))
        doc["backends"][b] = rec
        write(doc, out)

    baseline = device.snapshot().get("max_temp_c")
    total = len(models) * len(quants) * len(ready)
    n = 0
    for m in models:
        for q in quants:
            for b in matrix.BACKENDS:
                if b not in ready:
                    continue
                n += 1
                path, env, dev_name = ready[b]
                if n > 1:
                    wait_cool(baseline, args.cooldown)
                log("(%d/%d) %s %s %s" % (n, total, b, m, q))
                before = device.snapshot()
                t0 = time.time()
                rows, tail, err = bench.run_bench(
                    bench.bench_args(path, paths[(m, q)], b, dev_name, threads, args.repetitions,
                                     args.n_prompt, args.n_gen), env, args.timeout)
                tests = [bench.summarize_row(r) for r in rows]
                want = {"pp%d" % args.n_prompt, "tg%d" % args.n_gen}
                got = {t["test"] for t in tests}
                status = "ok" if want <= got and not err else ("partial" if tests else "failed")
                run = {"backend": b, "model": m, "quant": q,
                       "model_file": matrix.MODELS[m]["files"][q][0],
                       "model_sha256": matrix.MODELS[m]["files"][q][2],
                       "status": status, "error": err, "duration_s": round(time.time() - t0, 1),
                       "before": before, "after": device.snapshot(), "tests": tests}
                if err:
                    run["stderr_tail"] = tail
                doc["runs"].append(run)
                write(doc, out)
                log("   " + (" | ".join("%s %.2f t/s" % (t["test"], t["avg_ts"]) for t in tests) or "-")
                    + ("  [%s]" % err if err else ""))

    errs = validate.validate(doc)
    if errs:
        log("warning: result does not match the schema (please report this):\n  " + "\n  ".join(errs[:20]))
    log("\nwrote %s" % out)
    if provenance == "measured":
        log("submit it with:  python3 -m snapbench submit %s" % out)
    return 0
