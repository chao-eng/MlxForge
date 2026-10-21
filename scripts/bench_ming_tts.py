"""Ming-3.0-tts 性能基准（PRD §6.1.1）。

按同一协议采集，保证不同轮次可比较：

- 模型加载：每次重新拉起子进程，计时从 `load_model` 前到权重可用
- 冷启动首请求：子进程内完成加载 + 20 字合成，计时包含加载、推理与编码
- 热启动首请求 / RTF：同一进程内先预热 1 次，再连续采集，保留每轮原始值
- 内存：1 Hz 采样 MLX active/cache 与进程 RSS，卸载后按 0/5/30/60 秒观测

用法（在仓库根目录执行）：

    envs/ming-tts/bin/python scripts/bench_ming_tts.py --mode load
    envs/ming-tts/bin/python scripts/bench_ming_tts.py --mode cold
    envs/ming-tts/bin/python scripts/bench_ming_tts.py --mode hot
    envs/ming-tts/bin/python scripts/bench_ming_tts.py --mode memory
    envs/ming-tts/bin/python scripts/bench_ming_tts.py --mode all

分位数用 nearest-rank 法，脚本只打印实测值与原始序列，不推断未测结论。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
# 直接以脚本方式运行时，仓库根目录不在 sys.path，需要手动补上
sys.path.insert(0, str(REPO_ROOT))

# 与运行时保持一致：在模块导入阶段触发 bailingmm，避免权重字典被 onnx 异常的
# traceback 钉在内存里，导致卸载后 MLX active 内存不回落
from importlib import import_module  # noqa: E402

import_module("mlx_audio.tts.models.bailingmm")

WEIGHTS = REPO_ROOT / "models" / "ming-tts" / "8bit"
SAMPLE_20 = "今天下午三点我们在楼下咖啡店见面聊聊天。"
SAMPLE_40 = "语音合成模型正在本地设备上运行，我们用它来朗读一段较长的中文文本，并观察实时率。"
SAMPLE_COMMAND = "1 Hz；MLX 用 mx.get_active_memory()/mx.get_cache_memory()，RSS 用 ps -o rss= -p <pid>"


# ---------- 通用 ----------


def _rss_mb() -> float:
    out = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True
    )
    return int(out.strip()) / 1024.0


def _mlx_snapshot() -> Dict[str, float]:
    import mlx.core as mx

    return {
        "active_mb": round(mx.get_active_memory() / 2**20, 1),
        "cache_mb": round(mx.get_cache_memory() / 2**20, 1),
    }


def _percentile(values: List[float], p: float) -> float:
    """nearest-rank：升序后取第 ceil(p*n) 个，至少 1 个。"""
    ordered = sorted(values)
    index = max(1, math.ceil(p * len(ordered)))
    return ordered[index - 1]


def _rounds_summary(values: List[float]) -> Dict[str, Any]:
    return {
        "rounds": len(values),
        "raw": [round(v, 3) for v in values],
        "p50": round(_percentile(values, 0.5), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def _environment() -> Dict[str, Any]:
    from importlib import metadata

    def _cmd(*args: str) -> str:
        try:
            return subprocess.check_output(args, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    revision_file = WEIGHTS / ".revision"
    return {
        "chip": _cmd("sysctl", "-n", "machdep.cpu.brand_string"),
        "memory_gb": round(int(_cmd("sysctl", "-n", "hw.memsize")) / 2**30, 1),
        "macos": platform.mac_ver()[0],
        "python": sys.version.split()[0],
        "mlx": metadata.version("mlx"),
        "mlx_audio": metadata.version("mlx-audio"),
        "weights": str(WEIGHTS.relative_to(REPO_ROOT)),
        "revision": revision_file.read_text(encoding="utf-8").strip()
        if revision_file.is_file()
        else "unknown",
        "sampling": SAMPLE_COMMAND,
    }


def _make_task(text: str):
    from runtimes.ming_tts.schema import parse_speech_request
    from runtimes.ming_tts.tasks import resolve_task

    request = parse_speech_request(
        {
            "model": "Ming-3.0-tts",
            "input": text,
            "voice": "auto",
            "language": "auto",
            "response_format": "wav",
            "seed": 7,
        }
    )
    return request, resolve_task(request)


def _synthesize(model: Any, text: str):
    from runtimes.ming_tts.synth import synthesize

    request, task = _make_task(text)
    started = time.perf_counter()
    result = synthesize(model, request, task)
    elapsed = time.perf_counter() - started
    return elapsed, result.duration


def _spawn_child(mode: str) -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", mode],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"子进程失败：{completed.stderr.strip()[-500:]}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


# ---------- 子进程模式 ----------


def _child_load() -> None:
    from mlx_audio.tts.utils import load_model

    started = time.perf_counter()
    model = load_model(str(WEIGHTS))
    load_seconds = time.perf_counter() - started
    del model
    print(json.dumps({"load_seconds": round(load_seconds, 3)}))


def _child_cold_request() -> None:
    from mlx_audio.tts.utils import load_model

    started = time.perf_counter()
    model = load_model(str(WEIGHTS))
    load_seconds = time.perf_counter() - started
    elapsed, duration = _synthesize(model, SAMPLE_20)
    total = time.perf_counter() - started
    print(
        json.dumps(
            {
                "load_seconds": round(load_seconds, 3),
                "first_request_seconds": round(total, 3),
                "audio_seconds": round(duration, 3),
                "infer_seconds": round(elapsed, 3),
            }
        )
    )


def _child_memory() -> None:
    """基线、峰值与卸载回落放在同一子进程，避免父进程持有 MLX 上下文。"""
    from runtimes.ming_tts.model_manager import ModelManager

    manager = ModelManager(
        model_path=str(WEIGHTS), idle_timeout=2, max_queue=1, queue_timeout=600
    )
    # 基线：进程启动、tokenizer 校验完成、连续空闲 60 秒
    time.sleep(60)
    baseline = {"rss_mb": round(_rss_mb(), 1), **_mlx_snapshot()}

    def run(text: str) -> Dict[str, Any]:
        job = manager.submit(lambda model: _synthesize(model, text))
        elapsed, duration = manager.wait(job, timeout=600)
        return {"elapsed": elapsed, "duration": duration}

    # 预热一次，结果丢弃
    run(SAMPLE_20)

    samples: List[Dict[str, float]] = []
    stop = threading.Event()

    def sample_loop() -> None:
        while not stop.is_set():
            samples.append(
                {
                    "t": round(time.perf_counter(), 3),
                    "rss_mb": round(_rss_mb(), 1),
                    **_mlx_snapshot(),
                }
            )
            stop.wait(1.0)

    sampler = threading.Thread(target=sample_loop, daemon=True)
    sampler.start()
    synthesis = run(SAMPLE_40)
    stop.set()
    sampler.join(timeout=3)

    peak = {
        "rss_mb": max(s["rss_mb"] for s in samples),
        "active_mb": max(s["active_mb"] for s in samples),
        "cache_mb": max(s["cache_mb"] for s in samples),
    }

    # idle_timeout=2，监控线程每 1 秒检查一次
    deadline = time.time() + 30
    while manager.state != "unloaded" and time.time() < deadline:
        time.sleep(0.5)
    if manager.state != "unloaded":
        raise RuntimeError("等待空闲卸载超时")

    unloaded_at = time.perf_counter()
    release: List[Dict[str, Any]] = []
    for offset_seconds in (0, 5, 30, 60):
        wait = unloaded_at + offset_seconds - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        release.append(
            {
                "offset_s": offset_seconds,
                "elapsed_s": round(time.perf_counter() - unloaded_at, 1),
                "rss_mb": round(_rss_mb(), 1),
                **_mlx_snapshot(),
            }
        )

    manager.shutdown(timeout=10)
    print(
        json.dumps(
            {
                "baseline": baseline,
                "peak": peak,
                "samples": [
                    {
                        "t_s": round(s["t"] - samples[0]["t"], 1),
                        "rss_mb": s["rss_mb"],
                        "active_mb": s["active_mb"],
                        "cache_mb": s["cache_mb"],
                    }
                    for s in samples
                ],
                "synthesis": {
                    "elapsed_s": round(synthesis["elapsed"], 3),
                    "audio_s": round(synthesis["duration"], 3),
                },
                "release": release,
            }
        )
    )


# ---------- 父进程编排 ----------


def run_load(rounds: int) -> Dict[str, Any]:
    values = []
    for _ in range(rounds):
        values.append(_spawn_child("load")["load_seconds"])
    return _rounds_summary(values)


def run_cold(rounds: int) -> Dict[str, Any]:
    first_request = []
    load = []
    for _ in range(rounds):
        item = _spawn_child("cold-request")
        load.append(item["load_seconds"])
        first_request.append(item["first_request_seconds"])
    return {
        "load": _rounds_summary(load),
        "first_request": _rounds_summary(first_request),
    }


def run_hot(rounds: int) -> Dict[str, Any]:
    from mlx_audio.tts.utils import load_model

    model = load_model(str(WEIGHTS))
    _synthesize(model, SAMPLE_20)  # 预热，丢弃

    first_request = []
    for _ in range(rounds):
        elapsed, _duration = _synthesize(model, SAMPLE_20)
        first_request.append(elapsed)

    _synthesize(model, SAMPLE_40)  # 预热，丢弃
    rtf = []
    audio = []
    for _ in range(rounds):
        elapsed, duration = _synthesize(model, SAMPLE_40)
        audio.append(duration)
        rtf.append(elapsed / duration)

    return {
        "warm_first_request": _rounds_summary(first_request),
        "rtf_40": _rounds_summary(rtf),
        "rtf_audio_seconds": _rounds_summary(audio),
    }


def run_memory() -> Dict[str, Any]:
    return _spawn_child("memory")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ming-3.0-tts 性能基准")
    parser.add_argument(
        "--mode",
        choices=("load", "cold", "hot", "memory", "all"),
        default="all",
        help="采集项目，默认全部",
    )
    parser.add_argument("--rounds", type=int, default=5, help="每项轮次，默认 5")
    parser.add_argument("--child", choices=("load", "cold-request", "memory"))
    args = parser.parse_args()

    if args.child == "load":
        _child_load()
        return 0
    if args.child == "cold-request":
        _child_cold_request()
        return 0
    if args.child == "memory":
        _child_memory()
        return 0

    if args.rounds < 1:
        parser.error("--rounds 必须大于 0")

    result: Dict[str, Any] = {"environment": _environment(), "rounds": args.rounds}
    if args.mode in ("load", "all"):
        result["load"] = run_load(args.rounds)
    if args.mode in ("cold", "all"):
        result["cold"] = run_cold(args.rounds)
    if args.mode in ("hot", "all"):
        result["hot"] = run_hot(args.rounds)
    if args.mode in ("memory", "all"):
        result["memory"] = run_memory()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
