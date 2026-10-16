"""The fixed benchmark matrix: pinned llama.cpp, models, quants, tests, backends.

Changing anything here changes what results mean. Bump MATRIX_VERSION when you
do, so results from different matrices are never compared side by side.
"""

MATRIX_VERSION = "2026.10"

# llama.cpp release b11700, published 2026-10-16.
LLAMA_CPP = {
    "tag": "b11700",
    "commit": "23f7aabc16c72f6f707dba227251c35d7bd1ed96",
    "repo": "https://github.com/ggml-org/llama.cpp",
}

RELEASE_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"

# Official release bundles, with the sha256 GitHub reports for each asset.
BUNDLES = {
    # CPU + OpenCL (Adreno kernels) + Hexagon, built with the Android NDK.
    "android-snapdragon": {
        "name": "llama-b11700-bin-android-arm64-snapdragon.tar.gz",
        "sha256": "3b9d31c876e9ad873bf5fe42d6e004653929157cdc5a56b3257a111e8c07ca59",
    },
    # CPU + OpenCL + Hexagon for Linux on Snapdragon (glibc, aarch64).
    "linux-snapdragon": {
        "name": "llama-b11700-bin-linux-arm64-snapdragon.tar.gz",
        "sha256": "480885eae8dea0e7d51e61ae642bbd728e6f113618fb384c848dca6fd68ccbf5",
    },
    "linux-vulkan": {
        "name": "llama-b11700-bin-ubuntu-vulkan-arm64.tar.gz",
        "sha256": "a270ba756019220b2153943b3a11d340ba163282e9f252d1a4cc720271474891",
    },
    "windows-cpu": {
        "name": "llama-b11700-bin-win-cpu-arm64.zip",
        "sha256": "97d76ec70354f070e122954ffdb0912dca37efe9e3d85b1b164c39c9c55a9a7d",
    },
    "windows-opencl": {
        "name": "llama-b11700-bin-win-opencl-adreno-arm64.zip",
        "sha256": "8e36d90e6669622adeeef09d7c35609fff8dc4ca6f28341fbd685a3d3b6bc681",
    },
    "windows-vulkan": {
        "name": "llama-b11700-bin-win-vulkan-arm64.zip",
        "sha256": "a0e35ae761c847edb7c6da0e02f8cc02c3ba463836d5f503919caa5f7c11f933",
    },
}

BACKENDS = ["cpu", "opencl", "vulkan", "hexagon"]

# Where each backend comes from on each OS. "source" means snapbench builds
# llama.cpp at the pinned commit (only Vulkan on Android: there is no official
# Android Vulkan bundle). Hexagon on Windows needs signed NPU libraries that the
# release does not ship, so it is not part of the Windows matrix.
BACKEND_SOURCES = {
    "android": {"cpu": "android-snapdragon", "opencl": "android-snapdragon",
                "hexagon": "android-snapdragon", "vulkan": "source"},
    "linux": {"cpu": "linux-snapdragon", "opencl": "linux-snapdragon",
              "hexagon": "linux-snapdragon", "vulkan": "linux-vulkan"},
    "windows": {"cpu": "windows-cpu", "opencl": "windows-opencl",
                "vulkan": "windows-vulkan"},
}

# llama-bench device names (from `llama-bench --list-devices`) per backend.
# CPU runs use `-dev none -ngl 0`, so no device is needed.
DEVICE_PATTERNS = {
    "opencl": r"^GPUOpenCL",
    "vulkan": r"^Vulkan\d+",
    "hexagon": r"^HTP\d+",
}

# Source build flags, used for Vulkan on Android and for --from-source.
CMAKE_FLAGS = {
    "cpu": [],
    "opencl": ["-DGGML_OPENCL=ON", "-DGGML_OPENCL_USE_ADRENO_KERNELS=ON"],
    "vulkan": ["-DGGML_VULKAN=ON"],
}

# GGUF files, all from one quantizer (bartowski) and pinned to a repo revision.
MODELS = {
    "llama-3.2-1b": {
        "name": "Llama-3.2-1B-Instruct",
        "repo": "bartowski/Llama-3.2-1B-Instruct-GGUF",
        "revision": "067b946cf014b7c697f3654f621d577a3e3afd1c",
        "files": {
            "Q4_0": ("Llama-3.2-1B-Instruct-Q4_0.gguf", 773025920,
                     "fa0390e7c043f89ae1847bd6682d748041a99d4ef3de0e0b27d33b6af97a8be8"),
            "Q8_0": ("Llama-3.2-1B-Instruct-Q8_0.gguf", 1321083008,
                     "432f310a77f4650a88d0fd59ecdd7cebed8d684bafea53cbff0473542964f0c3"),
        },
    },
    "llama-3.2-3b": {
        "name": "Llama-3.2-3B-Instruct",
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "revision": "5ab33fa94d1d04e903623ae72c95d1696f09f9e8",
        "files": {
            "Q4_0": ("Llama-3.2-3B-Instruct-Q4_0.gguf", 1921909280,
                     "4d491003bf6b470e4d04233824c5c939b76d6c81974ba17a3ff207343e1d8e85"),
            "Q8_0": ("Llama-3.2-3B-Instruct-Q8_0.gguf", 3421899296,
                     "b5607b5090a8280063fff2d706bb3408ca6542341b06aab39c3eca0a28575921"),
        },
    },
    "qwen3-4b": {
        "name": "Qwen3-4B",
        "repo": "bartowski/Qwen_Qwen3-4B-GGUF",
        "revision": "cb76885dc66d50759b207c5a48c4e78dfa00c638",
        "files": {
            "Q4_0": ("Qwen_Qwen3-4B-Q4_0.gguf", 2375773120,
                     "003e104a544c3cdb008db07acb07b8f6feeb62e50c4eca3cfff14fc59e62e5b7"),
            "Q8_0": ("Qwen_Qwen3-4B-Q8_0.gguf", 4280405440,
                     "4050871d20fa939e88e83b1a86060061bdeff01e0d9e5d000d374766f0caf7d7"),
        },
    },
}

QUANTS = ["Q4_0", "Q8_0"]

HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"

# llama-bench test parameters. pp512 = prompt processing of 512 tokens,
# tg128 = generating 128 tokens.
N_PROMPT = 512
N_GEN = 128
REPETITIONS = 5
GPU_LAYERS = 99


def model_url(model_key, quant):
    m = MODELS[model_key]
    return HF_URL.format(repo=m["repo"], revision=m["revision"], file=m["files"][quant][0])


def bundle_url(bundle_key):
    return RELEASE_URL.format(tag=LLAMA_CPP["tag"], name=BUNDLES[bundle_key]["name"])
