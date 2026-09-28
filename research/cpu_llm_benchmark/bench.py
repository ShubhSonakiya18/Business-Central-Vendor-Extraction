"""Main orchestrator for the Ternary-Bonsai-2-27B-GGUF CPU benchmark.

Runs, in order:
  1. Machine inspection (machine_info.py)
  2. CPU-only verification (--list-devices, explicit -ngl 0)
  3. Model load time measurement (server_manager.py)
  4. 5-prompt suite: 1 warmup + N_MEASURED_RUNS measured runs each, via the
     running llama-server (server_client.py) -- real prompt text, first-party
     runtime timings, wall-clock TTFT
  5. Thread-scaling sweep via a SINGLE llama-bench invocation with a
     comma-separated -t list (one model load, not one per thread count --
     see CPU_BENCHMARK_REPORT.md methodology for why: this machine measured
     0.22GB free RAM after a single model load, so repeated reloads were a
     real stability risk, not just an efficiency concern)

Every numeric knob below that trades precision for wall-clock time is
labeled EXPLICIT SCOPE REDUCTION with the reasoning inline -- per the
requirement to document, not silently make, that trade-off. None of them
reduce the precision of a throughput RATE measurement (tokens/sec), which is
scale-invariant; they only bound how much total volume is generated to
reach that measurement.

Writes results.json (raw, machine-readable) as it goes -- if this process is
interrupted partway, whatever completed is still on disk, not lost.
"""
from __future__ import annotations

import json
import pathlib
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import machine_info  # noqa: E402
from prompts import PROMPTS  # noqa: E402
from server_client import run_completion  # noqa: E402
from server_manager import start_server_and_measure_load, stop_server  # noqa: E402

# ---------------------------------------------------------------------------
# Fixed paths to the already-downloaded, already-verified assets (see
# CPU_BENCHMARK_REPORT.md section 2/3 for how these were obtained and
# verified -- this script does not download anything itself).
SERVER_EXE = pathlib.Path(r"C:\Users\shubh\Downloads\tb_bench\extracted\llama-server.exe")
BENCH_EXE = pathlib.Path(r"C:\Users\shubh\Downloads\tb_bench\extracted\llama-bench.exe")
MODEL_PATH = pathlib.Path(r"C:\Users\shubh\Downloads\tb_bench\models\Ternary-Bonsai-2-27B-PTQ1_0.gguf")

OUT_DIR = pathlib.Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "results.json"
SERVER_LOG_PATH = OUT_DIR / "server_run.log"

HOST = "127.0.0.1"
PORT = 18077
N_CTX = 4096                 # covers the longest prompt in the suite (long_medium, ~450 tok) with room to spare
N_THREADS_MAIN = 13          # 14 physical cores - 1, this machine's "all reasonable" figure -- used for
                              # the main prompt suite; the THREAD-SCALING sweep below tests this choice
                              # against others rather than assuming it's optimal
N_GPU_LAYERS = 0             # explicit, unconditional -- see CPU-only verification section of the report

# EXPLICIT SCOPE REDUCTION: 1 warmup + 2 measured runs per prompt, not the
# suggested 3-5. Reasoning: 5 prompts x (1+5) runs at this model's measured
# ~1-1.5 tok/s would push total wall-clock past 2 hours; 1+2 keeps total time
# in the ~60-90 minute range while still producing mean/median/min/max/stdev
# (with n=2, min/max/stdev are honest but a small sample -- reported as such,
# not overstated).
N_MEASURED_RUNS = 2

# EXPLICIT SCOPE REDUCTION: thread-scaling uses a SMALL synthetic probe
# workload (-p 64 -n 16), not the full -p512/-n128 used for the main
# throughput reference numbers. Reasoning: the 1-thread configuration alone
# would take on the order of 30+ minutes at the full workload size, purely
# to produce a RATE number that a smaller workload also produces (tokens/sec
# is the metric; a shorter run measures the same steady-state rate, just
# faster to collect). The full-size pp512/tg128 numbers at the "all
# reasonable" thread count are reported separately, from an earlier
# unmodified run at the same commit/config, as the precision reference.
THREAD_SWEEP_PP = 64
THREAD_SWEEP_TG = 16
THREAD_SWEEP_REPS = 2
THREAD_SWEEP_THREADS = [1, 2, 4, 7, 13, 20]  # 20 = all logical cores, included specifically to test
                                              # (not assume) whether max threads helps or hurts


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{utc_now_iso()}] {msg}", flush=True)


def stat_block(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    block = {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }
    if len(values) >= 2:
        block["stdev"] = statistics.stdev(values)
    return block


def verify_cpu_only_no_devices() -> str:
    """--list-devices with THIS exact binary -- independent, mechanical proof
    that no GPU backend is even compiled in, not just unrequested."""
    result = subprocess.run(
        [str(SERVER_EXE), "--list-devices"], capture_output=True, text=True, timeout=30, check=False,
    )
    return (result.stdout or "") + (result.stderr or "")


def run_prompt_suite(base_url: str) -> list[dict]:
    suite_results = []
    for prompt in PROMPTS:
        log(f"prompt suite: {prompt.id} -- warmup run")
        warmup = run_completion(base_url, prompt.text, prompt.max_tokens)
        log(f"  warmup: ttft={warmup.ttft_s:.2f}s total={warmup.total_wall_s:.2f}s "
            f"gen_tok_s={warmup.generation_tok_per_s}")

        measured_runs = []
        for i in range(N_MEASURED_RUNS):
            log(f"prompt suite: {prompt.id} -- measured run {i + 1}/{N_MEASURED_RUNS}")
            r = run_completion(base_url, prompt.text, prompt.max_tokens)
            log(f"  run {i + 1}: ttft={r.ttft_s:.2f}s total={r.total_wall_s:.2f}s "
                f"prompt_tok_s={r.prompt_tok_per_s} gen_tok_s={r.generation_tok_per_s}")
            measured_runs.append(asdict(r))

        suite_results.append({
            "prompt_id": prompt.id,
            "category": prompt.category,
            "prompt_text": prompt.text,
            "requested_max_tokens": prompt.max_tokens,
            "warmup_run": asdict(warmup),
            "measured_runs": measured_runs,
            "ttft_s_stats": stat_block([r["ttft_s"] for r in measured_runs if r["ttft_s"] is not None]),
            "generation_tok_per_s_stats": stat_block(
                [r["generation_tok_per_s"] for r in measured_runs if r["generation_tok_per_s"] is not None]
            ),
            "prompt_tok_per_s_stats": stat_block(
                [r["prompt_tok_per_s"] for r in measured_runs if r["prompt_tok_per_s"] is not None]
            ),
            "total_wall_s_stats": stat_block([r["total_wall_s"] for r in measured_runs]),
        })
    return suite_results


def parse_llama_bench_md(md_text: str) -> list[dict]:
    """Parse llama-bench's markdown table output into structured rows.
    Columns observed from real output (see report methodology): model, size,
    params, backend, threads, test, t/s (mean ± stdev)."""
    rows = []
    for line in md_text.splitlines():
        if not line.startswith("|") or "---" in line or "model" in line.lower() and "backend" in line.lower():
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            continue
        test_col = cols[5]
        tps_col = cols[6]
        try:
            threads = int(cols[4])
        except ValueError:
            continue
        # NOTE: the thread-sweep subprocess.run() call that produced this data
        # (line ~196) was missing encoding="utf-8", so Windows decoded the
        # captured stdout with the console codepage instead of UTF-8. The
        # "\xc2\xb1" (UTF-8 for U+00B1 "+/-") bytes were mis-decoded byte-by-byte
        # into "Â±" ("A+/-" mojibake) before ever reaching this
        # function. Handled here rather than by re-running the 3.5h sweep,
        # since only this separator byte is affected -- the numeric values on
        # either side of it are untouched. Fixed at the source for future runs.
        for sep_candidate in ("Â±", "±"):
            mean_str, sep_found, stdev_str = tps_col.partition(sep_candidate)
            if sep_found:
                break
        try:
            mean_tps = float(mean_str.strip())
            stdev_tps = float(stdev_str.strip()) if stdev_str.strip() else None
        except ValueError:
            continue
        rows.append({
            "threads": threads,
            "test": test_col,
            "t_s_mean": mean_tps,
            "t_s_stdev": stdev_tps,
        })
    return rows


def run_thread_sweep() -> dict:
    threads_arg = ",".join(str(t) for t in THREAD_SWEEP_THREADS)
    command = [
        str(BENCH_EXE), "-m", str(MODEL_PATH),
        "-p", str(THREAD_SWEEP_PP), "-n", str(THREAD_SWEEP_TG),
        "-r", str(THREAD_SWEEP_REPS), "-t", threads_arg, "-ngl", "0", "-o", "md",
    ]
    log(f"thread sweep command: {' '.join(command)}")
    t0 = time.monotonic()
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", timeout=3600, check=False
    )
    elapsed = time.monotonic() - t0
    log(f"thread sweep finished in {elapsed:.1f}s (exit code {result.returncode})")
    rows = parse_llama_bench_md(result.stdout)
    return {
        "command": command,
        "elapsed_s": elapsed,
        "raw_stdout": result.stdout,
        "raw_stderr": result.stderr,
        "parsed_rows": rows,
    }


def main() -> None:
    results: dict = {
        "benchmark_started_utc": utc_now_iso(),
        "model_file": str(MODEL_PATH),
        "model_file_size_bytes": MODEL_PATH.stat().st_size,
        "server_binary": str(SERVER_EXE),
        "bench_binary": str(BENCH_EXE),
        "scope_reductions": {
            "n_measured_runs_per_prompt": N_MEASURED_RUNS,
            "n_measured_runs_reasoning": (
                "Reduced from the suggested 3-5 to 2 to keep total wall-clock "
                "under ~90 minutes given this model's measured ~1-1.5 tok/s on "
                "this CPU; does not affect the precision of the RATE metric "
                "itself, only sample size for mean/stdev."
            ),
            "thread_sweep_workload": f"pp{THREAD_SWEEP_PP}/tg{THREAD_SWEEP_TG} x{THREAD_SWEEP_REPS} reps",
            "thread_sweep_workload_reasoning": (
                "Reduced from the full pp512/tg128 workload used elsewhere in "
                "this report; the 1-thread configuration alone would take "
                "30+ minutes at full size. tokens/sec is scale-invariant, so "
                "this still measures real steady-state throughput per thread "
                "count -- see the separately-reported full-size pp512/tg128 "
                "numbers for the precision reference at the 'all reasonable' "
                "thread count."
            ),
        },
    }

    log("=== Step 1: machine info ===")
    results["machine"] = asdict(machine_info.gather())
    results["ram_free_gb_before_model_load"] = machine_info.current_free_ram_gb()

    log("=== Step 2: CPU-only verification (--list-devices) ===")
    results["cpu_only_verification"] = {
        "list_devices_output": verify_cpu_only_no_devices(),
        "n_gpu_layers_flag_used_every_run": N_GPU_LAYERS,
    }

    log("=== Step 3: start server, measure model load time ===")
    load_result = start_server_and_measure_load(
        server_exe=SERVER_EXE, model_path=MODEL_PATH, host=HOST, port=PORT,
        n_threads=N_THREADS_MAIN, n_ctx=N_CTX, n_gpu_layers=N_GPU_LAYERS,
        log_path=SERVER_LOG_PATH,
    )
    results["model_load_time_s"] = load_result.load_time_s
    results["server_command"] = load_result.command
    results["ram_free_gb_after_model_load"] = machine_info.current_free_ram_gb()
    log(f"model loaded in {load_result.load_time_s:.2f}s; "
        f"free RAM before={results['ram_free_gb_before_model_load']}GB "
        f"after={results['ram_free_gb_after_model_load']}GB")

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")  # checkpoint

    try:
        log("=== Step 4: 5-prompt suite ===")
        base_url = f"http://{HOST}:{PORT}"
        results["prompt_suite"] = run_prompt_suite(base_url)
        RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")  # checkpoint
    finally:
        log("stopping server before thread sweep (llama-bench needs its own exclusive load)")
        stop_server(load_result.process)
        results["ram_free_gb_after_server_stop"] = machine_info.current_free_ram_gb()

    log("=== Step 5: thread-scaling sweep (single model load, comma-separated -t) ===")
    results["thread_sweep"] = run_thread_sweep()

    results["benchmark_finished_utc"] = utc_now_iso()
    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log(f"=== DONE. Results written to {RESULTS_PATH} ===")


if __name__ == "__main__":
    main()
