"""Submit a result to the results repository as a pull request (via the
GitHub CLI), or fall back to the issue form."""

import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

from . import validate

UPSTREAM = "everyai-com/snapbench"


def result_path(doc):
    """results/<SoC part>/<device>/<date>-<id8>.json"""
    soc = doc.get("soc", {}).get("part") or "unknown-soc"
    d = doc.get("device", {})
    devname = " ".join(x for x in (d.get("manufacturer"), d.get("model")) if x) or "unknown-device"
    dev = re.sub(r"[^a-z0-9]+", "-", devname.lower()).strip("-")
    return "results/%s/%s/%s-%s.json" % (soc.lower(), dev, doc["created_at"][:10], doc["id"][:8])


def _gh(args, data=None):
    p = subprocess.run(["gh"] + args, input=json.dumps(data) if data is not None else None,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args[:3]), (p.stderr or p.stdout).strip()[-400:]))
    out = p.stdout.strip()
    return json.loads(out) if out.startswith(("{", "[")) else out


def _api(method, path, data=None):
    args = ["api", "-X", method, path]
    if data is not None:
        args += ["--input", "-"]
    return _gh(args, data)


def pr_body(doc, path):
    soc = doc["soc"]
    lines = [
        "New snapbench result.", "",
        "| | |", "| --- | --- |",
        "| Device | %s %s |" % (doc["device"].get("manufacturer") or "", doc["device"].get("model") or ""),
        "| SoC | %s %s |" % (soc.get("part") or "?", soc.get("name") or ""),
        "| GPU | %s |" % (doc["gpu"].get("name") or "?"),
        "| OS | %s %s |" % (doc["platform"]["os"], doc["platform"].get("os_version") or ""),
        "| llama.cpp | %s (`%s`) |" % (doc["llama_cpp"]["tag"], doc["llama_cpp"]["commit"][:9]),
    ]
    for g in doc["vulkaninfo"]["gpus"]:
        lines.append("| Vulkan | %s, %s %s |" % (g["device_name"], g["driver_kind"],
                                                g.get("mesa_version") or g.get("driver_version") or ""))
    for b, rec in doc["backends"].items():
        lines.append("| %s | %s%s |" % (b, rec["status"], (": " + rec["reason"][:120]) if rec.get("reason") else ""))
    ok = sum(1 for r in doc["runs"] if r["status"] == "ok")
    lines += ["", "%d of %d runs succeeded. File: `%s`" % (ok, len(doc["runs"]), path), "",
              "Submitted with `snapbench submit`. Results are published under CC0."]
    return "\n".join(lines)


def submit_pr(doc, raw, repo=UPSTREAM, log=print):
    if not shutil.which("gh"):
        raise RuntimeError("the GitHub CLI (gh) is not installed")
    login = _gh(["api", "user", "--jq", ".login"])
    up = _api("GET", "repos/%s" % repo)
    base = up["default_branch"]
    base_sha = _api("GET", "repos/%s/git/ref/heads/%s" % (repo, base))["object"]["sha"]
    if up.get("permissions", {}).get("push"):
        target = repo
    else:
        log("forking %s to %s" % (repo, login))
        fork = _api("POST", "repos/%s/forks" % repo, {"default_branch_only": True})
        target = fork["full_name"]
        for _ in range(10):  # a fresh fork takes a few seconds to become usable
            try:
                _api("GET", "repos/%s/git/ref/heads/%s" % (target, base))
                break
            except RuntimeError:
                time.sleep(3)
    path = result_path(doc)
    branch = "result-%s" % doc["id"][:8]
    try:
        _api("POST", "repos/%s/git/refs" % target, {"ref": "refs/heads/" + branch, "sha": base_sha})
    except RuntimeError as e:
        if "already exists" not in str(e):
            # An old fork may not have upstream's newest commit; branch off its own head.
            sha = _api("GET", "repos/%s/git/ref/heads/%s" % (target, base))["object"]["sha"]
            _api("POST", "repos/%s/git/refs" % target, {"ref": "refs/heads/" + branch, "sha": sha})
    _api("PUT", "repos/%s/contents/%s" % (target, path), {
        "message": "Add result: %s %s" % (doc["soc"].get("part") or "", doc["device"].get("model") or ""),
        "content": base64.b64encode(raw).decode(),
        "branch": branch,
    })
    head = branch if target == repo else "%s:%s" % (target.split("/")[0], branch)
    title = "Result: %s (%s, %s)" % (doc["device"].get("model") or "device", doc["soc"].get("part") or "?",
                                     doc["platform"]["os"])
    pr = _api("POST", "repos/%s/pulls" % repo, {"title": title, "head": head, "base": base,
                                               "body": pr_body(doc, path), "maintainer_can_modify": True})
    return pr["html_url"]


def issue_url(doc, repo=UPSTREAM):
    title = "Result: %s (%s, %s)" % (doc["device"].get("model") or "device", doc["soc"].get("part") or "?",
                                     doc["platform"]["os"])
    q = urllib.parse.urlencode({"template": "result.yml", "title": title})
    return "https://github.com/%s/issues/new?%s" % (repo, q)


def main(args):
    with open(args.file, "rb") as f:
        raw = f.read()
    doc = json.loads(raw)
    errs = validate.validate(doc) or validate.acceptance_errors(doc)
    if errs:
        print("cannot submit %s:\n  %s" % (args.file, "\n  ".join(errs[:20])))
        return 1
    if args.github and not doc.get("submitter", {}).get("github"):
        doc.setdefault("submitter", {})["github"] = args.github
        raw = (json.dumps(doc, indent=1) + "\n").encode()
    if not args.issue:
        try:
            url = submit_pr(doc, raw, repo=args.repo)
            print("opened %s" % url)
            return 0
        except RuntimeError as e:
            print("could not open a pull request: %s" % e)
            print("falling back to the issue form.\n")
    print("1. Open: %s" % issue_url(doc, args.repo))
    print("2. Attach %s to the form (drag and drop; if GitHub refuses .json, rename it to .txt),"
          " or paste a gist link to it." % args.file)
    return 0


# --- maintainers: turn an issue-form submission into a results file ---------

def import_issue(args):
    issue = _gh(["issue", "view", str(args.number), "--repo", args.repo, "--json", "body,author,url"])
    urls = re.findall(r"https://(?:github\.com/user-attachments/files/\S+|gist\.github(?:usercontent)?\.com/\S+)",
                      issue["body"])
    if not urls:
        print("no attachment or gist link in %s" % issue["url"])
        return 1
    url = urls[0].rstrip(")>]")
    if "gist.github.com" in url and "/raw" not in url:
        url = url.rstrip("/") + "/raw"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "snapbench"}), timeout=60) as r:
        raw = r.read()
    doc = json.loads(raw)
    errs = validate.validate(doc) or validate.acceptance_errors(doc)
    if errs:
        print("issue %s does not hold a valid result:\n  %s" % (args.number, "\n  ".join(errs[:20])))
        return 1
    doc.setdefault("submitter", {})
    if not doc["submitter"].get("github"):
        doc["submitter"]["github"] = issue["author"]["login"]
    path = result_path(doc)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print("wrote %s (from %s)" % (path, issue["url"]))
    return 0
