# Result schema (v1)

[`result-v1.schema.json`](result-v1.schema.json) is the contract. These notes
explain what the fields mean and where they come from.

| Field | Meaning |
| --- | --- |
| `provenance` | `measured`: a real run. `sample`: hand-made demo data, never real. `dev`: a run on a non-Snapdragon machine while developing snapbench. Only `measured` is accepted into `results/`. |
| `tool.matrix_version` | Version of the benchmark matrix in `snapbench/matrix.py`. Compare results only within one matrix version. |
| `llama_cpp.sources.<backend>` | Where that backend's llama-bench came from. `release` is an official bundle (`bundle`, `sha256`), `source` is built here at the pinned commit, and `custom` is a build the contributor supplied. `version` is what `llama-bench --version` printed. |
| `soc.part` | Part number such as `SM8650` or `X1E78100`, from `ro.soc.model`, `/sys/devices/soc0/machine`, the device tree, or the Windows CPU name. `soc.name` and `soc.hexagon_arch` come from `snapbench/socs.py`. |
| `gpu.name` | From kgsl (`/sys/class/kgsl/kgsl-3d0/gpu_model`) on Android, `Win32_VideoController` on Windows, else the SoC table (`name_source` says which). |
| `vulkaninfo.gpus[]` | Parsed from `vulkaninfo`, run with the same environment as the benchmark, so `VK_ICD_FILENAMES` and similar are respected. `driver_kind` is `qualcomm`, `turnip`, `dozen`, `other` or `unknown`, derived from `driverID` and `driverName`. |
| `vulkaninfo.gpus[].int_dot` | `shaderIntegerDotProduct`, plus the `integerDotProduct4x8BitPacked*Accelerated` properties. llama.cpp's Vulkan backend only uses its int8 dot-product shaders when these say accelerated. |
| `vulkaninfo.gpus[].cooperative_matrix` | Whether `VK_KHR_cooperative_matrix` is exposed, and the `cooperativeMatrix` feature. |
| `vulkaninfo.gpus[].subgroup` | `subgroupSize`, and `min`/`max` from subgroup size control. |
| `backends.<backend>.status` | `ok`: the probe ran. `unavailable`: no bundle for this OS, a missing toolchain, or llama-bench lists no such device (`reason` says which). `failed`: the device is listed but a short probe run crashed. `skipped`: not selected. |
| `backends.<backend>.device` | The `-dev` value passed to llama-bench (`none` for CPU, which also uses `-ngl 0`; GPUs and the NPU use `-ngl 99`). |
| `backends.<backend>.probe` | A tiny verbose llama-bench run, separate from the timed runs. `log` holds the backend's init lines; `info` holds the facts parsed from them: OpenCL device and driver strings, the `ggml_vulkan` line (int dot, matrix cores, warp size), the Hexagon HTP library version, and how many layers were offloaded. |
| `config.threads` | CPU threads (`-t`). By default, cores whose max frequency is at least 80% of the fastest core's, so efficiency cores are left out. |
| `config.env` | Environment variables that change driver or backend behaviour (`VK_ICD_FILENAMES`, `TU_DEBUG`, `MESA_*`, `GGML_*`, ...). |
| `runs[]` | One llama-bench invocation per backend × model × quant. `status` is `ok` (both tests), `partial` or `failed`. `before`/`after` are clock and temperature snapshots. |
| `runs[].tests[]` | `test` is `pp512` or `tg128`; `avg_ts`/`stddev_ts`/`samples_ts` are tokens per second as llama-bench reports them. `llama_bench` keeps the raw row's settings (minus the local model path). |

Missing information is `null`. It is never guessed.
