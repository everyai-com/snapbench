"""Which GPU driver is active, and what it claims to accelerate.

Two independent sources, both recorded:
  * `vulkaninfo` text output (the Vulkan driver the system loader picks), and
  * the backend's own init lines from a short verbose llama-bench probe
    (`ggml_vulkan: 0 = ...`, `ggml_opencl: OpenCL driver: ...`).
"""

import re
import shutil
import subprocess

# Vulkan properties and extensions that matter for llama.cpp on Adreno.
VK_FIELDS = [
    "apiVersion", "driverVersion", "vendorID", "deviceID", "deviceType", "deviceName",
    "driverID", "driverName", "driverInfo", "conformanceVersion",
    "subgroupSize", "minSubgroupSize", "maxSubgroupSize", "maxComputeSharedMemorySize",
    "shaderFloat16", "shaderInt8", "storageBuffer16BitAccess", "storageBuffer8BitAccess",
    "shaderIntegerDotProduct", "subgroupSizeControl", "computeFullSubgroups",
    "integerDotProduct4x8BitPackedSignedAccelerated",
    "integerDotProduct4x8BitPackedUnsignedAccelerated",
    "integerDotProduct4x8BitPackedMixedSignednessAccelerated",
    "integerDotProduct8BitSignedAccelerated",
    "cooperativeMatrix", "shaderBFloat16Type",
]

VK_EXTENSIONS = [
    "VK_KHR_cooperative_matrix", "VK_NV_cooperative_matrix2",
    "VK_KHR_shader_integer_dot_product", "VK_KHR_shader_float16_int8",
    "VK_EXT_subgroup_size_control", "VK_KHR_16bit_storage", "VK_KHR_8bit_storage",
    "VK_KHR_shader_bfloat16", "VK_EXT_shader_float8",
]


def _value(raw):
    v = raw.strip()
    # "1.4.357 (4211045)" -> keep the readable part
    v = re.sub(r"\s+\(\d+\)$", "", v)
    if v == "true":
        return True
    if v == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def parse_vulkaninfo(text):
    """Parse full `vulkaninfo` text output into one dict per GPU."""
    marker = text.find("Device Properties and Extensions:")
    body = text[marker:] if marker >= 0 else text
    blocks = re.split(r"^GPU(\d+):\s*$", body, flags=re.M)
    gpus = []
    # re.split gives [preamble, idx, block, idx, block, ...]
    for i in range(1, len(blocks) - 1, 2):
        block = blocks[i + 1]
        props = {}
        for m in re.finditer(r"^\s+(\w+)\s+=\s+(.+?)\s*$", block, flags=re.M):
            key = m.group(1)
            if key in VK_FIELDS and key not in props:
                props[key] = _value(m.group(2))
        exts = {}
        for m in re.finditer(r"^\s+(VK_\w+)\s*:\s*extension revision\s+(\d+)", block, flags=re.M):
            exts[m.group(1)] = int(m.group(2))
        gpus.append(summarize_vulkan(int(blocks[i]), props, exts))
    return gpus


def classify_driver(driver_id, driver_name, device_name=""):
    did = (driver_id or "").upper()
    name = (driver_name or "").lower()
    if "TURNIP" in did or "turnip" in name:
        return "turnip"
    if "QUALCOMM" in did or "qualcomm" in name:
        return "qualcomm"
    if "DOZEN" in did or "dozen" in name:
        return "dozen"
    if not did and not name:
        return "unknown"
    return "other"


def mesa_version(driver_info):
    m = re.search(r"Mesa\s+(\d+\.\d+(?:\.\d+)?(?:-\S+)?)", driver_info or "")
    return m.group(1) if m else None


def summarize_vulkan(index, props, exts):
    kind = classify_driver(props.get("driverID"), props.get("driverName"), props.get("deviceName"))
    return {
        "index": index,
        "device_name": props.get("deviceName"),
        "device_type": props.get("deviceType"),
        "vendor_id": props.get("vendorID"),
        "device_id": props.get("deviceID"),
        "driver_id": props.get("driverID"),
        "driver_name": props.get("driverName"),
        "driver_info": props.get("driverInfo"),
        "driver_version": props.get("driverVersion"),
        "api_version": props.get("apiVersion"),
        "driver_kind": kind,
        "mesa_version": mesa_version(props.get("driverInfo")),
        "int_dot": {
            "shader_integer_dot_product": props.get("shaderIntegerDotProduct"),
            "int8_packed_signed_accelerated": props.get("integerDotProduct4x8BitPackedSignedAccelerated"),
            "int8_packed_unsigned_accelerated": props.get("integerDotProduct4x8BitPackedUnsignedAccelerated"),
            "int8_packed_mixed_accelerated": props.get("integerDotProduct4x8BitPackedMixedSignednessAccelerated"),
        },
        "cooperative_matrix": {
            "extension": "VK_KHR_cooperative_matrix" in exts,
            "feature": props.get("cooperativeMatrix"),
        },
        "subgroup": {
            "size": props.get("subgroupSize"),
            "min": props.get("minSubgroupSize"),
            "max": props.get("maxSubgroupSize"),
            "size_control": props.get("subgroupSizeControl"),
        },
        "fp16": props.get("shaderFloat16"),
        "int8": props.get("shaderInt8"),
        "max_compute_shared_memory": props.get("maxComputeSharedMemorySize"),
        "extensions": {k: exts[k] for k in VK_EXTENSIONS if k in exts},
    }


def run_vulkaninfo(env=None, timeout=60):
    """Run vulkaninfo if installed. Returns (gpus, error)."""
    exe = shutil.which("vulkaninfo") or shutil.which("vulkaninfo.exe")
    if not exe:
        return [], "vulkaninfo not installed"
    try:
        p = subprocess.run([exe], capture_output=True, text=True, timeout=timeout,
                           env=env, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], "vulkaninfo failed: %s" % e
    gpus = parse_vulkaninfo(p.stdout)
    if not gpus:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        return [], "vulkaninfo found no GPU: %s" % " | ".join(tail)
    return gpus, None


# --- llama.cpp backend init lines -------------------------------------------

_GGML_VK = re.compile(
    r"ggml_vulkan: (?P<idx>\d+) = (?P<name>.+?) \((?P<driver>[^()]*(?:\([^()]*\)[^()]*)*)\) \| (?P<rest>.*)$")


def parse_ggml_vulkan_line(line):
    """`ggml_vulkan: 0 = NAME (DRIVER) | uma: 1 | fp16: 1 | ... | int dot: 1 | matrix cores: none`"""
    m = _GGML_VK.search(line)
    if not m:
        return None
    out = {"index": int(m.group("idx")), "device_name": m.group("name"),
           "driver_name": m.group("driver")}
    for part in m.group("rest").split("|"):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().replace(" ", "_")
        v = _value(v)
        out[k] = v
    out["driver_kind"] = classify_driver(None, out["driver_name"])
    return out


def parse_backend_log(lines):
    """Pull driver facts out of a verbose llama-bench probe's stderr."""
    info = {}
    vk = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("ggml_vulkan:") and " = " in line and "|" in line:
            d = parse_ggml_vulkan_line(line)
            if d:
                vk.append(d)
        elif line.startswith("ggml_opencl:"):
            body = line[len("ggml_opencl:"):].strip()
            for key, label in (("device", "OpenCL device:"), ("driver", "OpenCL driver:"),
                               ("platform", "selected platform:")):
                if body.startswith(label):
                    info.setdefault("opencl", {})[key] = body[len(label):].strip().strip("'")
            if "using kernels optimized for Adreno" in body:
                info.setdefault("opencl", {})["adreno_kernels"] = True
            if body.startswith("khr dot product support:"):
                info.setdefault("opencl", {})["khr_dot_product"] = body.split(":", 1)[1].strip()
            if body.startswith("device FP16 support:"):
                info.setdefault("opencl", {})["fp16"] = body.split(":", 1)[1].strip()
        elif line.startswith("ggml-hex:") and "new session" in line:
            m = re.search(r"(libggml-htp-v\d+)\.so", line)
            if m:
                info.setdefault("hexagon", {})["htp_lib"] = m.group(1)
        elif line.startswith("load_tensors: offloaded "):
            m = re.search(r"offloaded (\d+)/(\d+) layers", line)
            if m:
                info["offloaded_layers"] = [int(m.group(1)), int(m.group(2))]
        elif ": using device " in line:
            m = re.search(r"using device (\S+)", line)
            if m:
                info.setdefault("devices_used", []).append(m.group(1))
        elif "Hexagon backend" in line:
            info.setdefault("hexagon", {})["banner"] = line.split(":", 1)[-1].strip()
    if vk:
        info["vulkan"] = vk
    return info


# Lines worth keeping from the verbose probe (the rest is model metadata).
KEEP = re.compile(
    r"^(ggml_vulkan:|ggml_opencl:|ggml-hex:|ggml_metal_device_init:|load_tensors:.*(buffer size|offload)|"
    r"llama_(prepare_model_devices|model_load_from_file_impl): using device|.*Hexagon backend)")
DROP = re.compile(r"(execute-op|supports-op|profile-op|trace-evt|compiling |loaded bin kernel)")


def filter_log(lines, limit=120):
    kept = [l.rstrip() for l in lines if KEEP.search(l) and not DROP.search(l)]
    seen = set()
    out = []
    for l in kept:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out[:limit]
