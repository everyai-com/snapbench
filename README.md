# snapbench

How fast do local LLMs run on **Snapdragon** phones and laptops, and which
llama.cpp backend is fastest: CPU, OpenCL on the Adreno GPU, Vulkan, or the
Hexagon NPU?

Nobody can answer that reproducibly today. The numbers people quote are
stitched together from different dates, models and builds: Qualcomm's IWOCL
2025 slides, llama.cpp discussion #8336, scattered issues. What they suggest is
that the Adreno GPU paths are often *slower* than the CPU. On a Snapdragon X
Elite, for example, Llama 7B Q4_0 has been reported at 177/25 tok/s
(prompt/generation) on the CPU and 101/18 on OpenCL.

snapbench runs one fixed matrix on any Snapdragon device and publishes every
result as open data:

| | |
| --- | --- |
| llama.cpp | release [`b11700`](https://github.com/ggml-org/llama.cpp/releases/tag/b11700), commit `23f7aabc16c7`. Official release bundles, verified by sha256. |
| Backends | CPU, OpenCL (Adreno kernels), Vulkan, Hexagon NPU, whichever the device supports |
| Models | Llama 3.2 1B, Llama 3.2 3B, Qwen3 4B (bartowski GGUFs, pinned revision, sha256-checked) |
| Quants | Q4_0, Q8_0 |
| Tests | `pp512` (prompt processing, 512 tokens) and `tg128` (generation, 128 tokens), 5 repetitions |

Each result also records what usually explains the numbers: the device, SoC
and GPU, **which Vulkan driver was active** (Qualcomm's or Mesa's Turnip, with
version), whether the driver reports int8 dot products as accelerated, whether it exposes
`VK_KHR_cooperative_matrix`, the subgroup sizes, what the OpenCL and
Hexagon backends printed at startup, and CPU/GPU clocks and temperatures
before and after every run.

**Results page:** https://everyai-com.github.io/snapbench/

## Contribute a run

You need a Snapdragon device, about 15 GB of free space for all six models,
and an hour or so. Plug it in and keep it somewhere cool. Results are more
comparable when the device is not hot from earlier use.

### Android (Termux)

Install [Termux](https://termux.dev) from F-Droid or GitHub (the Play Store
build is outdated), then:

```bash
pkg install python git vulkan-tools
git clone https://github.com/everyai-com/snapbench
cd snapbench
python3 -m snapbench run --github YOUR_GITHUB_NAME
```

CPU, OpenCL and Hexagon come from llama.cpp's official Android Snapdragon
bundle. There is no official Android Vulkan build, so snapbench builds
llama-bench from source for Vulkan if you have the toolchain:

```bash
pkg install cmake ninja clang vulkan-headers vulkan-loader-android shaderc
```

Without it, Vulkan is recorded as unavailable and the rest of the matrix still
runs. To benchmark Turnip instead of Qualcomm's driver, install it (for
example `pkg install mesa-vulkan-icd-freedreno`) and point the loader at it
with `VK_ICD_FILENAMES` before running. snapbench records the driver it
finds, and the environment variables that select it, so both runs can sit
side by side.

### Linux on Snapdragon X (or other Snapdragon boards)

```bash
sudo apt install python3 git vulkan-tools     # or your distro's equivalents
git clone https://github.com/everyai-com/snapbench
cd snapbench
python3 -m snapbench run --github YOUR_GITHUB_NAME
```

This uses the official `linux-arm64-snapdragon` bundle (CPU, OpenCL, Hexagon)
and the `ubuntu-vulkan-arm64` bundle (Vulkan). OpenCL needs an Adreno OpenCL
ICD, and Hexagon needs FastRPC access to the NPU. If either is missing, it
is recorded as unavailable with the reason.

### Windows on Snapdragon X

Install Python 3 from python.org (ARM64) and Git, then in PowerShell:

```powershell
git clone https://github.com/everyai-com/snapbench
cd snapbench
py -m snapbench run --github YOUR_GITHUB_NAME
```

This uses the official `win-cpu-arm64`, `win-opencl-adreno-arm64` and
`win-vulkan-arm64` bundles. Hexagon on Windows needs signed NPU libraries the
release does not ship, so it is not part of the Windows matrix.

### Submit it

The run writes one JSON file, for example
`snapbench-sm8650-pixel-9-2026-10-17.json`. Then:

```bash
python3 -m snapbench submit snapbench-sm8650-....json
```

If the [GitHub CLI](https://cli.github.com) is installed and logged in
(`gh auth login`), this forks this repository, adds your file under
`results/`, and opens a pull request. Without `gh`, it prints a link to the
**Submit a result** issue form, where you attach the file instead.

Useful options:

| | |
| --- | --- |
| `--quick` | Only Llama 3.2 1B Q4_0. A smoke test, marked as a partial matrix. |
| `--backends cpu,opencl` | Limit backends. Also `--models`, `--quants`. |
| `--cooldown 60` | Seconds to rest between runs (default 20; snapbench also waits for temperatures to settle). |
| `--llama-bench vulkan=PATH` | Use your own llama-bench build for one backend, e.g. to test a driver or kernel patch. Recorded as `kind: custom`. |
| `--from-source` | Build CPU/OpenCL/Vulkan from the pinned commit instead of using release bundles. |
| `--notes "..."` | Anything unusual: a cooling fan, a performance mode, a custom Mesa build. |
| `python3 -m snapbench info` | Print what snapbench detects (device, SoC, GPU, Vulkan driver, temperatures) and exit. |

Downloads and builds go to `~/.snapbench` (or `%LOCALAPPDATA%\snapbench`);
set `SNAPBENCH_HOME` to move them.

## What's in a result

One JSON file per run, described by
[`schema/result-v1.schema.json`](schema/result-v1.schema.json) with field
notes in [`schema/README.md`](schema/README.md). It contains no personal data
beyond the GitHub name you choose to give. Local file paths and hostnames are
not recorded, except the path of a `--llama-bench` build you supply yourself.

`provenance` says where a file came from: `measured` (a real run),
`sample` (hand-made demo data in [`samples/`](samples), every number
invented) or `dev` (someone developing snapbench on a non-Snapdragon machine).
Only `measured` results are accepted into [`results/`](results).

## Layout

| Path | What |
| --- | --- |
| `snapbench/` | The runner. Python 3.9+ standard library only, so it runs on a bare Termux or Windows Python. |
| `snapbench/matrix.py` | The pinned matrix: llama.cpp release and bundle hashes, models, quants, tests. |
| `schema/` | The result JSON Schema. |
| `results/` | Contributed results (CC0). |
| `samples/` | Labelled sample results for the page and tests. Not measurements. |
| `site/` | The static results page. `python3 -m snapbench build-site` writes `site/data.json`. |
| `tests/` | `python3 -m unittest discover -s tests`. Fixtures include real llama-bench and vulkaninfo output. |

To preview the page locally:

```bash
python3 -m snapbench build-site --samples
python3 -m http.server --directory site 8000
```

## Related projects

A small set of open tools for Qualcomm Adreno GPUs, built to work together:

| Project | What it does |
| --- | --- |
| [drivermatch](https://github.com/everyai-com/drivermatch) | Picks the right community Turnip driver and settings for your GPU and game, and turns GPU crashes into plain-language fixes. [Live hub](https://drivermatch.everyai-com.workers.dev) |
| [snapbench](https://github.com/everyai-com/snapbench) | Reproducible llama.cpp benchmarks on Snapdragon: CPU vs OpenCL vs Vulkan (Qualcomm and Turnip) vs Hexagon. [Results](https://everyai-com.github.io/snapbench/) |
| [turnip-signed-dot4](https://github.com/everyai-com/turnip-signed-dot4) | Mesa patch and test kit that makes Turnip report signed int8 dot product as accelerated, turning on llama.cpp's int8 path on Adreno. Not yet submitted upstream. |
| [everyai-com/mesa](https://github.com/everyai-com/mesa) | Mesa fork carrying that patch (`turnip-signed-dot4` branch, plus a 26.2.5 backport). |

How they fit: the Turnip patch makes the driver faster for AI, snapbench
measures the difference on real devices, and drivermatch tells players which
driver build to install for each game.

## Licenses

- Code: MIT, see [LICENSE](LICENSE).
- Results in `results/` (and the sample files): CC0 1.0, see
  [LICENSE-DATA](LICENSE-DATA). Copy them, mirror them, build on them.
- Models and llama.cpp binaries are not hosted here. snapbench downloads them
  from Hugging Face and llama.cpp's GitHub releases.

Not affiliated with Qualcomm, Meta, Alibaba or the llama.cpp and Mesa
projects. Snapdragon, Adreno and Hexagon are trademarks of Qualcomm.
