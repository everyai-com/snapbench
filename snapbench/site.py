"""Build site/data.json from results/ (and optionally samples/) for the static page."""

import glob
import json
import os

from . import validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slim(doc, path):
    """Keep what the page shows; the full files stay in the repo."""
    runs = []
    for r in doc["runs"]:
        runs.append({
            "backend": r["backend"], "model": r["model"], "quant": r["quant"], "status": r["status"],
            "error": r.get("error"),
            "tests": {t["test"]: [t["avg_ts"], t["stddev_ts"]] for t in r["tests"]},
            "max_temp_c": [r.get("before", {}).get("max_temp_c"), r.get("after", {}).get("max_temp_c")],
        })
    backends = {}
    for b, rec in doc["backends"].items():
        info = (rec.get("probe") or {}).get("info") or {}
        backends[b] = {"status": rec["status"], "reason": rec.get("reason"), "device": rec.get("device"),
                       "info": info}
    return {
        "file": os.path.relpath(path, ROOT).replace(os.sep, "/"),
        "id": doc["id"],
        "provenance": doc["provenance"],
        "created_at": doc["created_at"],
        "matrix_version": doc["tool"]["matrix_version"],
        "llama_cpp": {"tag": doc["llama_cpp"]["tag"], "commit": doc["llama_cpp"]["commit"],
                      "kinds": {b: s["kind"] for b, s in doc["llama_cpp"]["sources"].items()}},
        "platform": {"os": doc["platform"]["os"], "os_version": doc["platform"].get("os_version"),
                     "termux": doc["platform"].get("termux")},
        "device": doc["device"],
        "soc": {"part": doc["soc"].get("part"), "name": doc["soc"].get("name")},
        "gpu": doc["gpu"].get("name"),
        "vulkan": doc["vulkaninfo"]["gpus"],
        "backends": backends,
        "config": {k: doc["config"].get(k) for k in ("threads", "repetitions", "n_prompt", "n_gen",
                                                      "full_matrix", "env")},
        "submitter": (doc.get("submitter") or {}).get("github"),
        "runs": runs,
    }


def build(include_samples=False, out=None):
    out = out or os.path.join(ROOT, "site", "data.json")
    files = sorted(glob.glob(os.path.join(ROOT, "results", "**", "*.json"), recursive=True))
    if include_samples:
        files += sorted(glob.glob(os.path.join(ROOT, "samples", "*.json")))
    docs, problems = [], []
    for path in files:
        sample = os.sep + "samples" + os.sep in path
        errs = validate.validate_file(path, accept=not sample)
        if errs:
            problems.append((path, errs))
            continue
        with open(path) as f:
            docs.append(slim(json.load(f), path))
    docs.sort(key=lambda d: d["created_at"], reverse=True)
    with open(out, "w") as f:
        json.dump({"results": docs}, f, separators=(",", ":"))
        f.write("\n")
    return out, docs, problems
