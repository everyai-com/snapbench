"""Downloads (verified by sha256) and the Android Vulkan source build."""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

from . import matrix

CHUNK = 1 << 20


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url, dest, sha256, size=None, log=print):
    """Resumable download to dest; verifies sha256. Re-uses a verified file."""
    if os.path.exists(dest) and (size is None or os.path.getsize(dest) == size):
        if sha256_file(dest) == sha256:
            return dest
        os.remove(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"User-Agent": "snapbench"})
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    log("  downloading %s" % os.path.basename(dest))
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        total = int(r.headers.get("Content-Length") or 0) + have
        with open(part, "ab" if have else "wb") as f:
            done = have
            last = -1
            while True:
                block = r.read(CHUNK)
                if not block:
                    break
                f.write(block)
                done += len(block)
                pct = int(done * 100 / total) if total else 0
                if sys.stderr.isatty() and pct != last:
                    sys.stderr.write("\r  %3d%% of %d MB" % (pct, total >> 20))
                    last = pct
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    got = sha256_file(part)
    if got != sha256:
        os.remove(part)
        raise RuntimeError("sha256 mismatch for %s: got %s, want %s" % (url, got, sha256))
    os.replace(part, dest)
    return dest


def _extract(archive, dest):
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                target = os.path.realpath(os.path.join(tmp, m.name))
                if not target.startswith(os.path.realpath(tmp) + os.sep):
                    raise RuntimeError("unsafe path in archive: %s" % m.name)
            if hasattr(tarfile, "data_filter"):
                t.extractall(tmp, filter="data")
            else:
                t.extractall(tmp)
    # Release tarballs wrap everything in llama-bXXXX/; zips are flat.
    entries = os.listdir(tmp)
    root = os.path.join(tmp, entries[0]) if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])) else tmp
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(root, dest)
    shutil.rmtree(tmp, ignore_errors=True)


def find_bench(root):
    """Path of llama-bench inside an extracted bundle or build tree."""
    for rel in ("bin/llama-bench", "llama-bench", "build/bin/llama-bench",
                "llama-bench.exe", "bin/llama-bench.exe", "build/bin/Release/llama-bench.exe"):
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f in ("llama-bench", "llama-bench.exe"):
                return os.path.join(dirpath, f)
    return None


def bundle(key, home, log=print):
    """Download and unpack an official release bundle. Returns its directory."""
    b = matrix.BUNDLES[key]
    dest = os.path.join(home, "llama.cpp", matrix.LLAMA_CPP["tag"], key)
    stamp = os.path.join(dest, ".snapbench-sha256")
    if os.path.exists(stamp) and open(stamp).read().strip() == b["sha256"]:
        return dest
    archive = os.path.join(home, "downloads", b["name"])
    download(matrix.bundle_url(key), archive, b["sha256"], log=log)
    _extract(archive, dest)
    for exe in ("bin/llama-bench", "llama-bench"):
        p = os.path.join(dest, exe)
        if os.path.exists(p):
            os.chmod(p, 0o755)
    with open(stamp, "w") as f:
        f.write(b["sha256"])
    return dest


def model(key, quant, home, log=print):
    name, size, sha = matrix.MODELS[key]["files"][quant]
    dest = os.path.join(home, "models", name)
    return download(matrix.model_url(key, quant), dest, sha, size=size, log=log)


VULKAN_TERMUX_PKGS = "git cmake ninja clang vulkan-headers vulkan-loader-android shaderc"


def source_build(backend, home, jobs=None, log=print):
    """Build llama-bench at the pinned commit with one backend enabled.

    Used for Vulkan on Android (no official bundle) and --from-source.
    Returns the build directory, or raises with a hint on what to install.
    """
    missing = [t for t in ("git", "cmake") if not shutil.which(t)]
    if backend == "vulkan" and not (shutil.which("glslc") or shutil.which("glslangValidator")):
        missing.append("glslc")
    if missing:
        hint = ("pkg install " + VULKAN_TERMUX_PKGS) if os.environ.get("TERMUX_VERSION") else \
            "install " + ", ".join(missing)
        raise RuntimeError("cannot build %s from source, missing %s (%s)" % (backend, ", ".join(missing), hint))
    src = os.path.join(home, "src", "llama.cpp")
    commit = matrix.LLAMA_CPP["commit"]
    if not os.path.isdir(os.path.join(src, ".git")):
        os.makedirs(src, exist_ok=True)
        _sh(["git", "init", "-q", src], log)
        _sh(["git", "-C", src, "remote", "add", "origin", matrix.LLAMA_CPP["repo"]], log)
    head = subprocess.run(["git", "-C", src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != commit:
        log("  fetching llama.cpp %s" % commit[:9])
        _sh(["git", "-C", src, "fetch", "-q", "--depth", "1", "origin", commit], log)
        _sh(["git", "-C", src, "checkout", "-q", "--detach", "FETCH_HEAD"], log)
    build = os.path.join(home, "llama.cpp", matrix.LLAMA_CPP["tag"], "source-" + backend)
    stamp = os.path.join(build, ".snapbench-commit")
    if os.path.exists(stamp) and open(stamp).read().strip() == commit and find_bench(build):
        return build
    flags = ["-DCMAKE_BUILD_TYPE=Release", "-DLLAMA_CURL=OFF", "-DLLAMA_BUILD_SERVER=OFF",
             "-DLLAMA_BUILD_TESTS=OFF", "-DGGML_NATIVE=ON"] + matrix.CMAKE_FLAGS[backend]
    if shutil.which("ninja"):
        flags += ["-G", "Ninja"]
    log("  building llama.cpp (%s) at %s, this can take 10-30 minutes on a phone" % (backend, commit[:9]))
    _sh(["cmake", "-S", src, "-B", build] + flags, log)
    _sh(["cmake", "--build", build, "--config", "Release", "--target", "llama-bench",
         "-j", str(jobs or os.cpu_count() or 4)], log)
    with open(stamp, "w") as f:
        f.write(commit)
    return build


def _sh(cmd, log):
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        tail = "\n".join((p.stderr or p.stdout).strip().splitlines()[-15:])
        raise RuntimeError("command failed: %s\n%s" % (" ".join(cmd), tail))
    return p.stdout
