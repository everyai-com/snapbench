"""Write the hand-made sample results in samples/.

They exist so the results page and the schema tests have something to chew on
before real submissions arrive. Every number in them is invented. They carry
provenance="sample", the device manufacturer "SAMPLE", and a note saying so;
the page labels them, and validate --accept rejects them from results/.

    python3 tools/make_samples.py
"""

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from snapbench import matrix  # noqa: E402

NOTE = "SAMPLE DATA. Hand-made to demo the results page. These numbers were not measured on any device."


def vk(kind, int_dot, coopmat):
    turnip = kind == "turnip"
    return {
        "index": 0,
        "device_name": "Turnip Adreno (TM) 750" if turnip else "Adreno (TM) 750",
        "device_type": "PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU",
        "driver_id": "DRIVER_ID_MESA_TURNIP" if turnip else "DRIVER_ID_QUALCOMM_PROPRIETARY",
        "driver_name": "turnip Mesa driver" if turnip else "Qualcomm Technologies Inc. Adreno Vulkan Driver",
        "driver_info": "Mesa 25.3.0 (sample)" if turnip else "Driver Build: sample",
        "driver_version": "25.3.0" if turnip else "512.819.0",
        "api_version": "1.4.318",
        "driver_kind": kind,
        "mesa_version": "25.3.0" if turnip else None,
        "int_dot": {"shader_integer_dot_product": True, "int8_packed_signed_accelerated": int_dot,
                    "int8_packed_unsigned_accelerated": int_dot, "int8_packed_mixed_accelerated": int_dot},
        "cooperative_matrix": {"extension": coopmat, "feature": coopmat or None},
        "subgroup": {"size": 64, "min": 64, "max": 128, "size_control": True},
        "extensions": {"VK_KHR_shader_integer_dot_product": 1},
    }


def make(idx, model_name, os_name, part, soc_name, gpu, vk_kind, backends, speeds, seed):
    rnd = random.Random(seed)
    runs = []
    for m in matrix.MODELS:
        size = {"llama-3.2-1b": 1.0, "llama-3.2-3b": 2.6, "qwen3-4b": 3.4}[m]
        for q in matrix.QUANTS:
            qf = 1.0 if q == "Q4_0" else 0.62
            for b in backends:
                pp, tg = speeds[b]
                if b == "hexagon" and q == "Q8_0":
                    runs.append({"backend": b, "model": m, "quant": q,
                                 "model_file": matrix.MODELS[m]["files"][q][0],
                                 "model_sha256": matrix.MODELS[m]["files"][q][2],
                                 "status": "failed", "error": "llama-bench exited with 1 (sample)",
                                 "duration_s": 3.0, "tests": []})
                    continue
                tests = []
                for name, base in (("pp512", pp), ("tg128", tg)):
                    v = base / size * (qf if name == "tg128" else 1.0) * rnd.uniform(0.93, 1.07)
                    tests.append({"test": name, "avg_ts": round(v, 2), "stddev_ts": round(v * 0.02, 2),
                                  "samples_ts": [round(v * rnd.uniform(0.98, 1.02), 2) for _ in range(5)]})
                runs.append({"backend": b, "model": m, "quant": q,
                             "model_file": matrix.MODELS[m]["files"][q][0],
                             "model_sha256": matrix.MODELS[m]["files"][q][2],
                             "status": "ok", "error": None, "duration_s": round(rnd.uniform(20, 90), 1),
                             "before": {"max_temp_c": round(rnd.uniform(34, 40), 1)},
                             "after": {"max_temp_c": round(rnd.uniform(44, 58), 1)},
                             "tests": tests})
    gpus = [vk(vk_kind, vk_kind == "qualcomm", vk_kind == "qualcomm")] if vk_kind else []
    backend_recs = {}
    for b in matrix.BACKENDS:
        if b in backends:
            backend_recs[b] = {"status": "ok", "reason": None,
                               "device": {"cpu": "none", "opencl": "GPUOpenCL", "vulkan": "Vulkan0",
                                          "hexagon": "HTP0"}[b]}
        elif b in matrix.BACKEND_SOURCES[os_name]:
            backend_recs[b] = {"status": "unavailable", "reason": "sample: backend not available"}
    return {
        "schema_version": 1,
        "id": "00000000-0000-4000-8000-%012d" % idx,
        "provenance": "sample",
        "created_at": "2026-10-1%dT12:00:00Z" % idx,
        "tool": {"name": "snapbench", "version": "0.1.0", "matrix_version": matrix.MATRIX_VERSION},
        "llama_cpp": {"tag": matrix.LLAMA_CPP["tag"], "commit": matrix.LLAMA_CPP["commit"],
                      "sources": {b: {"kind": "release", "bundle": "sample"} for b in backends}},
        "platform": {"os": os_name, "os_version": "sample", "arch": "aarch64", "termux": os_name == "android"},
        "device": {"manufacturer": "SAMPLE", "model": model_name},
        "soc": {"part": part, "name": soc_name, "is_snapdragon": True},
        "cpu": {"name": None, "cores": 8},
        "gpu": {"name": gpu},
        "memory_mb": 12000,
        "vulkaninfo": {"available": bool(gpus), "error": None if gpus else "vulkaninfo not installed",
                       "gpus": gpus},
        "backends": backend_recs,
        "config": {"n_prompt": 512, "n_gen": 128, "repetitions": 5, "threads": 6, "gpu_layers": 99,
                   "cooldown_s": 20, "full_matrix": True, "env": {}},
        "runs": runs,
        "submitter": {"github": None, "notes": NOTE},
    }


def main():
    out = os.path.join(ROOT, "samples")
    os.makedirs(out, exist_ok=True)
    docs = [
        make(1, "Sample phone A (Qualcomm driver)", "android", "SM8650", "Snapdragon 8 Gen 3", "Adreno 750",
             "qualcomm", ["cpu", "opencl", "vulkan", "hexagon"],
             {"cpu": (120, 28), "opencl": (95, 16), "vulkan": (60, 12), "hexagon": (150, 22)}, 1),
        make(2, "Sample phone A (Turnip)", "android", "SM8650", "Snapdragon 8 Gen 3", "Adreno 750",
             "turnip", ["cpu", "opencl", "vulkan"],
             {"cpu": (118, 27), "opencl": (93, 16), "vulkan": (45, 10)}, 2),
        make(3, "Sample laptop B", "windows", "X1E78100", "Snapdragon X Elite", "Adreno X1-85",
             None, ["cpu", "opencl"],
             {"cpu": (240, 40), "opencl": (130, 22)}, 3),
    ]
    for d in docs:
        path = os.path.join(out, "sample-%s.json" % d["id"][-1])
        with open(path, "w") as f:
            json.dump(d, f, indent=1)
            f.write("\n")
        print("wrote", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
