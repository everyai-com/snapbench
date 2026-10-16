"""Tests. Run with:  python3 -m unittest discover -s tests

Fixtures named *-macos-* are real output captured on an Apple M4 Mac with the
llama.cpp b11700 release (CPU and Metal), used only to pin down the output
formats. Fixtures named *-synthetic-* are hand-written in vulkaninfo's layout.
"""

import copy
import glob
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from snapbench import bench, drivers, matrix, site, socs, submit, validate  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


def sample(n=1):
    with open(os.path.join(ROOT, "samples", "sample-%d.json" % n)) as f:
        return json.load(f)


class LlamaBenchOutput(unittest.TestCase):
    def test_json_array(self):
        rows = bench.parse_bench_output(fixture("llama-bench-macos-cpu.json"))
        self.assertEqual([bench.test_name(r) for r in rows], ["pp512", "tg128"])
        self.assertEqual(rows[0]["build_commit"], matrix.LLAMA_CPP["commit"][:9])
        self.assertEqual(rows[0]["devices"], "none")
        self.assertEqual(rows[0]["n_gpu_layers"], 0)

    def test_jsonl(self):
        rows = bench.parse_bench_output(fixture("llama-bench-macos-metal.jsonl"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["n_gen"], 128)
        self.assertEqual(rows[0]["devices"], "MTL0")

    def test_jsonl_with_noise_and_truncation(self):
        text = "some warning\n" + fixture("llama-bench-macos-metal.jsonl") + '{"avg_ts": 1.0, "trunc'
        self.assertEqual(len(bench.parse_bench_output(text)), 2)

    def test_summarize_row(self):
        row = bench.parse_bench_output(fixture("llama-bench-macos-cpu.json"))[1]
        s = bench.summarize_row(row)
        self.assertEqual(s["test"], "tg128")
        self.assertAlmostEqual(s["avg_ts"], 37.758, places=3)
        self.assertEqual(len(s["samples_ts"]), 2)
        self.assertEqual(s["llama_bench"]["model_type"], "llama 1B Q4_0")
        self.assertNotIn("model_filename", s["llama_bench"])  # local paths stay out of results

    def test_test_names(self):
        self.assertEqual(bench.test_name({"n_prompt": 512, "n_gen": 0}), "pp512")
        self.assertEqual(bench.test_name({"n_prompt": 0, "n_gen": 128, "n_depth": 4096}), "tg128@d4096")
        self.assertEqual(bench.test_name({"n_prompt": 512, "n_gen": 128}), "pp512+tg128")

    def test_empty(self):
        self.assertEqual(bench.parse_bench_output(""), [])


class Devices(unittest.TestCase):
    def test_list_devices_macos(self):
        devs = bench.parse_list_devices(fixture("llama-bench-macos-list-devices.txt"))
        self.assertEqual([d["name"] for d in devs], ["MTL0", "BLAS"])
        self.assertEqual(devs[0]["memory_mib"], 12124)

    def test_list_devices_snapdragon_layout(self):
        text = ("Available devices:\n"
                "  GPUOpenCL: QUALCOMM Adreno(TM) 750 (7623 MiB, 7623 MiB free)\n"
                "  HTP0: Hexagon (2048 MiB, 2048 MiB free)\n"
                "  Vulkan0: Turnip Adreno (TM) 750 (11520 MiB, 11520 MiB free)\n")
        devs = bench.parse_list_devices(text)
        self.assertEqual(bench.pick_device("opencl", devs), "GPUOpenCL")
        self.assertEqual(bench.pick_device("hexagon", devs), "HTP0")
        self.assertEqual(bench.pick_device("vulkan", devs), "Vulkan0")
        self.assertEqual(bench.pick_device("cpu", devs), "none")
        self.assertIsNone(bench.pick_device("vulkan", devs[:2]))

    def test_bench_args(self):
        a = bench.bench_args("lb", "m.gguf", "cpu", "none", 6, 5, 512, 128)
        self.assertEqual(a[a.index("-dev") + 1], "none")
        self.assertEqual(a[a.index("-ngl") + 1], "0")
        self.assertEqual(a[a.index("-o") + 1], "jsonl")
        a = bench.bench_args("lb", "m.gguf", "opencl", "GPUOpenCL", 6, 5, 512, 128)
        self.assertEqual(a[a.index("-ngl") + 1], "99")

    def test_hexagon_env(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "bin"))
            os.makedirs(os.path.join(d, "lib"))
            env = bench.bench_env(os.path.join(d, "bin", "llama-bench"), "hexagon", "linux")
            self.assertEqual(env["ADSP_LIBRARY_PATH"], os.path.join(d, "lib"))
            self.assertTrue(env["LD_LIBRARY_PATH"].startswith(os.path.join(d, "lib")))


class Vulkaninfo(unittest.TestCase):
    def test_real_moltenvk(self):
        (g,) = drivers.parse_vulkaninfo(fixture("vulkaninfo-macos-moltenvk.txt"))
        self.assertEqual(g["device_name"], "Apple M4")
        self.assertEqual(g["driver_id"], "DRIVER_ID_MOLTENVK")
        self.assertEqual(g["driver_kind"], "other")
        self.assertEqual(g["api_version"], "1.4.357")
        self.assertEqual(g["subgroup"], {"size": 32, "min": 4, "max": 32, "size_control": True})
        self.assertIs(g["int_dot"]["shader_integer_dot_product"], True)
        self.assertIs(g["int_dot"]["int8_packed_signed_accelerated"], False)
        self.assertFalse(g["cooperative_matrix"]["extension"])
        self.assertIn("VK_KHR_shader_integer_dot_product", g["extensions"])

    def test_turnip(self):
        (g,) = drivers.parse_vulkaninfo(fixture("vulkaninfo-synthetic-turnip.txt"))
        self.assertEqual(g["driver_kind"], "turnip")
        self.assertEqual(g["mesa_version"], "25.3.0-devel")
        self.assertIs(g["int_dot"]["int8_packed_signed_accelerated"], False)
        self.assertIs(g["int_dot"]["int8_packed_unsigned_accelerated"], True)
        self.assertFalse(g["cooperative_matrix"]["extension"])
        self.assertEqual(g["subgroup"]["min"], 64)
        self.assertIs(g["fp16"], True)

    def test_qualcomm_and_cpu_device(self):
        gpus = drivers.parse_vulkaninfo(fixture("vulkaninfo-synthetic-qualcomm.txt"))
        self.assertEqual([g["driver_kind"] for g in gpus], ["qualcomm", "other"])
        self.assertTrue(gpus[0]["cooperative_matrix"]["extension"])
        self.assertIs(gpus[0]["cooperative_matrix"]["feature"], True)
        self.assertEqual(gpus[0]["driver_version"], "512.819.0")
        self.assertIsNone(gpus[0]["mesa_version"])

    def test_classify(self):
        self.assertEqual(drivers.classify_driver("DRIVER_ID_MESA_DOZEN", "Dozen"), "dozen")
        self.assertEqual(drivers.classify_driver(None, None), "unknown")


class BackendLog(unittest.TestCase):
    def test_ggml_vulkan_lines(self):
        lines = [
            "ggml_vulkan: Found 1 Vulkan devices:",
            "ggml_vulkan: 0 = Turnip Adreno (TM) 750 (turnip Mesa driver) | uma: 1 | fp16: 1 | bf16: 0 | fp4: 0 | "
            "warp size: 64 | shared memory: 32768 | int dot: 0 | matrix cores: none",
        ]
        info = drivers.parse_backend_log(lines)
        (vk,) = info["vulkan"]
        self.assertEqual(vk["device_name"], "Turnip Adreno (TM) 750")
        self.assertEqual(vk["driver_name"], "turnip Mesa driver")
        self.assertEqual(vk["driver_kind"], "turnip")
        self.assertEqual(vk["int_dot"], 0)
        self.assertEqual(vk["matrix_cores"], "none")
        self.assertEqual(vk["warp_size"], 64)

    def test_qualcomm_vulkan_line(self):
        d = drivers.parse_ggml_vulkan_line(
            "ggml_vulkan: 0 = Adreno (TM) 830 (Qualcomm Technologies Inc. Adreno Vulkan Driver) | uma: 1 | "
            "fp16: 1 | bf16: 0 | fp4: 0 | warp size: 64 | shared memory: 32768 | int dot: 1 | matrix cores: KHR_coopmat")
        self.assertEqual(d["device_name"], "Adreno (TM) 830")
        self.assertEqual(d["driver_kind"], "qualcomm")
        self.assertEqual(d["matrix_cores"], "KHR_coopmat")

    def test_opencl_and_hexagon(self):
        lines = [
            "ggml_opencl: selected platform: 'QUALCOMM Snapdragon(TM)'",
            "ggml_opencl: OpenCL device: QUALCOMM Adreno(TM) 750",
            "ggml_opencl: OpenCL driver: OpenCL 3.0 QUALCOMM build: commit unknown Compiler E031.45.02.16",
            "ggml_opencl: device FP16 support: true",
            "ggml_opencl: using kernels optimized for Adreno (GGML_OPENCL_USE_ADRENO_KERNELS)",
            "ggml-hex: Hexagon backend (experimental) : allocating new registry : ndev 1",
            "ggml-hex: new session: HTP0 : session-id 0 domain-id 3 uri file:///libggml-htp-v79.so?htp_iface_skel",
            "load_tensors: offloaded 17/17 layers to GPU",
        ]
        info = drivers.parse_backend_log(lines)
        self.assertEqual(info["opencl"]["device"], "QUALCOMM Adreno(TM) 750")
        self.assertTrue(info["opencl"]["driver"].startswith("OpenCL 3.0 QUALCOMM"))
        self.assertTrue(info["opencl"]["adreno_kernels"])
        self.assertEqual(info["hexagon"]["htp_lib"], "libggml-htp-v79")
        self.assertEqual(info["offloaded_layers"], [17, 17])

    def test_filter_real_verbose_log(self):
        lines = fixture("llama-bench-macos-metal-verbose.stderr.txt").splitlines()
        kept = drivers.filter_log(lines)
        self.assertTrue(any("offloaded 17/17 layers" in l for l in kept))
        self.assertTrue(any(l.startswith("ggml_metal_device_init: GPU name") for l in kept))
        self.assertFalse(any(l.startswith("llama_model_loader") for l in kept))
        info = drivers.parse_backend_log(lines)
        self.assertEqual(info["offloaded_layers"], [17, 17])
        self.assertEqual(info["devices_used"], ["MTL0"])


class Socs(unittest.TestCase):
    def test_parts(self):
        self.assertEqual(socs.normalize_part("SM8650"), "SM8650")
        self.assertEqual(socs.normalize_part("pineapple"), "SM8650")
        self.assertEqual(socs.normalize_part(
            "Snapdragon(R) X Elite - X1E78100 - Qualcomm(R) Oryon(TM) CPU"), "X1E78100")
        self.assertEqual(socs.normalize_part("X1E-80-100"), "X1E80100")
        self.assertEqual(socs.lookup("X1E78100")[0], "Snapdragon X Elite")
        self.assertEqual(socs.lookup("SM8750")[1], "Adreno 830")
        self.assertEqual(socs.lookup("SM9999"), (None, None, None))
        self.assertIsNone(socs.normalize_part("Apple M4"))


class Schema(unittest.TestCase):
    def test_samples_valid(self):
        for path in glob.glob(os.path.join(ROOT, "samples", "*.json")):
            with open(path) as f:
                doc = json.load(f)
            self.assertEqual(validate.validate(doc), [], path)
            self.assertEqual(doc["provenance"], "sample")
            self.assertIn("SAMPLE DATA", doc["submitter"]["notes"])

    def test_samples_rejected_from_results(self):
        self.assertTrue(validate.acceptance_errors(sample(1)))

    def test_measured_accepted(self):
        doc = sample(1)
        doc["provenance"] = "measured"
        self.assertEqual(validate.acceptance_errors(doc), [])

    def test_mutations_fail(self):
        cases = [
            lambda d: d.pop("runs"),
            lambda d: d.update(provenance="real"),
            lambda d: d["llama_cpp"].update(commit="abc"),
            lambda d: d["runs"][0]["tests"][0].update(test="pp 512"),
            lambda d: d["runs"][0]["tests"][0].update(avg_ts=-1),
            lambda d: d["runs"][0].update(backend="metal"),
            lambda d: d["backends"].update(metal={"status": "ok"}),
            lambda d: d.update(extra=1),
            lambda d: d["vulkaninfo"]["gpus"][0].update(driver_kind="nvidia"),
            lambda d: d["config"].update(threads="6"),
            lambda d: d["submitter"].update(notes="x" * 2001),
        ]
        for i, mutate in enumerate(cases):
            doc = copy.deepcopy(sample(1))
            mutate(doc)
            self.assertTrue(validate.validate(doc), "mutation %d should fail" % i)

    def test_matches_jsonschema_package(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = validate.load_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        v = jsonschema.Draft202012Validator(schema)
        good = sample(2)
        self.assertEqual(list(v.iter_errors(good)), [])
        bad = copy.deepcopy(good)
        bad["runs"][0]["status"] = "great"
        self.assertTrue(list(v.iter_errors(bad)))
        self.assertTrue(validate.validate(bad))


class Submission(unittest.TestCase):
    def test_result_path(self):
        doc = sample(1)
        self.assertEqual(submit.result_path(doc),
                         "results/sm8650/sample-sample-phone-a-qualcomm-driver/2026-10-11-00000000.json")

    def test_pr_body_mentions_driver(self):
        body = submit.pr_body(sample(2), "results/x.json")
        self.assertIn("turnip", body)
        self.assertIn("b11700", body)

    def test_issue_url(self):
        self.assertIn("template=result.yml", submit.issue_url(sample(3)))


class Site(unittest.TestCase):
    def test_build_with_samples(self):
        with tempfile.TemporaryDirectory() as d:
            out, docs, problems = site.build(include_samples=True, out=os.path.join(d, "data.json"))
            self.assertEqual(problems, [])
            self.assertEqual({r["provenance"] for r in docs}, {"sample"})
            with open(out) as f:
                data = json.load(f)
            r = data["results"][0]
            self.assertIn("pp512", r["runs"][0]["tests"])
            self.assertTrue(r["file"].startswith("samples/"))

    def test_build_without_samples(self):
        with tempfile.TemporaryDirectory() as d:
            _, docs, _ = site.build(include_samples=False, out=os.path.join(d, "data.json"))
            self.assertFalse(any(r["provenance"] == "sample" for r in docs))


class Matrix(unittest.TestCase):
    def test_every_model_has_both_quants(self):
        for m in matrix.MODELS.values():
            self.assertEqual(sorted(m["files"]), sorted(matrix.QUANTS))
            for name, size, sha in m["files"].values():
                self.assertEqual(len(sha), 64)
                self.assertTrue(name.endswith(".gguf"))

    def test_backend_sources_exist(self):
        for os_name, srcs in matrix.BACKEND_SOURCES.items():
            for b, src in srcs.items():
                self.assertIn(b, matrix.BACKENDS)
                self.assertTrue(src == "source" or src in matrix.BUNDLES, (os_name, b))
                self.assertIn(matrix.LLAMA_CPP["tag"], matrix.BUNDLES.get(src, {"name": "b11700"})["name"])


if __name__ == "__main__":
    unittest.main()
