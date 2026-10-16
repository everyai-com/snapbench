"""Command line: python3 -m snapbench <run|validate|submit|info|build-site|import-issue>"""

import argparse
import json
import sys

from . import __version__, matrix


def _kv(text):
    if "=" not in text:
        raise argparse.ArgumentTypeError("expected BACKEND=PATH")
    k, v = text.split("=", 1)
    if k not in matrix.BACKENDS:
        raise argparse.ArgumentTypeError("unknown backend %r" % k)
    return (k, v)


def main(argv=None):
    p = argparse.ArgumentParser(prog="snapbench", description="Local LLM benchmarks on Snapdragon devices.")
    p.add_argument("--version", action="version", version="snapbench " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the benchmark matrix and write one JSON result")
    r.add_argument("--backends", help="comma list from: " + ",".join(matrix.BACKENDS) + " (default: all on this OS)")
    r.add_argument("--models", help="comma list from: " + ",".join(matrix.MODELS) + " (default: all)")
    r.add_argument("--quants", help="comma list from: " + ",".join(matrix.QUANTS) + " (default: all)")
    r.add_argument("--quick", action="store_true", help="first model and quant only (a smoke test, not the full matrix)")
    r.add_argument("--repetitions", type=int, default=matrix.REPETITIONS)
    r.add_argument("--n-prompt", type=int, default=matrix.N_PROMPT, help=argparse.SUPPRESS)
    r.add_argument("--n-gen", type=int, default=matrix.N_GEN, help=argparse.SUPPRESS)
    r.add_argument("--threads", type=int, help="CPU threads (default: performance + prime cores)")
    r.add_argument("--cooldown", type=float, default=20, help="seconds to rest between runs (default 20)")
    r.add_argument("--timeout", type=int, default=1800, help="seconds before one llama-bench run is killed")
    r.add_argument("--home", help="where downloads and builds go (default ~/.snapbench, or $SNAPBENCH_HOME)")
    r.add_argument("--from-source", action="store_true", help="build CPU/OpenCL/Vulkan from the pinned commit instead of release bundles")
    r.add_argument("--llama-bench", action="append", type=_kv, metavar="BACKEND=PATH",
                   help="use your own llama-bench (or build dir) for a backend; recorded as kind=custom")
    r.add_argument("--out", help="result file (default ./snapbench-<soc>-<device>-<date>.json)")
    r.add_argument("--github", help="your GitHub username, for credit")
    r.add_argument("--notes", help="anything unusual: cooling, power mode, custom driver build")
    r.add_argument("--dry-run", action="store_true", help="show the plan and exit")
    r.add_argument("--dev", action="store_true", help="allow non-Snapdragon machines (result marked provenance=dev)")

    v = sub.add_parser("validate", help="check result files against the schema")
    v.add_argument("files", nargs="+")
    v.add_argument("--accept", action="store_true", help="also apply the rules for files in results/")

    s = sub.add_parser("submit", help="open a pull request with a result (or print the issue-form link)")
    s.add_argument("file")
    s.add_argument("--issue", action="store_true", help="skip the pull request, use the issue form")
    s.add_argument("--repo", default="everyai-com/snapbench")
    s.add_argument("--github", help="your GitHub username, for credit")

    sub.add_parser("info", help="print what snapbench detects about this device, then exit")

    b = sub.add_parser("build-site", help="write site/data.json from results/")
    b.add_argument("--samples", action="store_true", help="include the labelled sample results in samples/")

    i = sub.add_parser("import-issue", help="maintainers: turn an issue-form submission into a results file")
    i.add_argument("number", type=int)
    i.add_argument("--repo", default="everyai-com/snapbench")

    args = p.parse_args(argv)
    if args.cmd == "run":
        from . import run
        return run.main(args)
    if args.cmd == "validate":
        from . import validate
        bad = 0
        for f in args.files:
            errs = validate.validate_file(f, accept=args.accept)
            print("%s: %s" % (f, "ok" if not errs else "INVALID"))
            for e in errs[:30]:
                print("  " + e)
            bad += bool(errs)
        return 1 if bad else 0
    if args.cmd == "submit":
        from . import submit
        return submit.main(args)
    if args.cmd == "import-issue":
        from . import submit
        return submit.import_issue(args)
    if args.cmd == "info":
        from . import device, drivers
        info = device.collect()
        gpus, err = drivers.run_vulkaninfo()
        info["vulkaninfo"] = {"gpus": gpus, "error": err}
        info["snapshot"] = device.snapshot()
        print(json.dumps(info, indent=2))
        return 0
    if args.cmd == "build-site":
        from . import site
        out, docs, problems = site.build(include_samples=args.samples)
        for path, errs in problems:
            print("skipped %s: %s" % (path, "; ".join(errs[:3])))
        print("wrote %s with %d result(s)" % (out, len(docs)))
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
