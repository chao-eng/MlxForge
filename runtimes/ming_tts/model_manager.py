"""Ming-3.0-tts 模型生命周期、单 worker 串行队列与空闲卸载。

状态名是 `/health`、日志与 Web UI 的唯一来源，只允许 PRD §4.4 登记的六个取值。
"""

from __future__ import annotations

import ctypes
import gc
import json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Deque, Optional

import mlx.core as mx
import psutil
from mlx_audio.tts.utils import load_model

# mlx_audio 的 bailingmm 包会把可选的 onnx 导入异常存进模块全局，该异常的
# traceback 会固定首次导入时所在栈帧的局部变量。若等到 load_model 内部才首次
# 导入，栈帧里已经有权重字典，空闲卸载后 MLX active 内存不会回落。这里在模块
# 导入阶段先触发一次，导入栈帧不含权重，后续加载不再重新导入。
import_module("mlx_audio.tts.models.bailingmm")

logger = logging.getLogger(__name__)


class _RusageInfoV4(ctypes.Structure):
    """libproc 的 rusage_info_v4，字段必须与 sys/resource.h 完全一致。

    proc_pid_rusage 按 flavor 对应的完整结构体写入，少声明字段会越界写内存，
    进程会在后续请求中直接崩溃。
    """

    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
        ("ri_cpu_time_qos_default", ctypes.c_uint64),
        ("ri_cpu_time_qos_maintenance", ctypes.c_uint64),
        ("ri_cpu_time_qos_background", ctypes.c_uint64),
        ("ri_cpu_time_qos_utility", ctypes.c_uint64),
        ("ri_cpu_time_qos_legacy", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_initiated", ctypes.c_uint64),
        ("ri_cpu_time_qos_user_interactive", ctypes.c_uint64),
        ("ri_billed_system_time", ctypes.c_uint64),
        ("ri_serviced_system_time", ctypes.c_uint64),
        ("ri_logical_writes", ctypes.c_uint64),
        ("ri_lifetime_max_phys_footprint", ctypes.c_uint64),
        ("ri_instructions", ctypes.c_uint64),
        ("ri_cycles", ctypes.c_uint64),
        ("ri_billed_energy", ctypes.c_uint64),
        ("ri_serviced_energy", ctypes.c_uint64),
        ("ri_interval_max_phys_footprint", ctypes.c_uint64),
        ("ri_runnable_time", ctypes.c_uint64),
    ]


_LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")
_LIBPROC.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_LIBPROC.proc_pid_rusage.restype = ctypes.c_int


def _phys_footprint_bytes() -> int:
    """进程物理内存足迹，口径与活动监视器的「内存」列一致。

    psutil 的 rss 不含 Metal/GPU 的 IOAccelerator 分配，模型加载后会明显偏小，
    所以直接读 libproc；读取失败时才退回 rss。
    """
    info = _RusageInfoV4()
    if _LIBPROC.proc_pid_rusage(os.getpid(), 4, ctypes.byref(info)) != 0:
        return psutil.Process().memory_info().rss
    return int(info.ri_phys_footprint)


def memory_snapshot() -> dict[str, float]:
    """`/health` 用的内存快照：MLX 占用、进程物理内存与整机占用分开报告。"""
    system = psutil.virtual_memory()
    return {
        "mlx_active_mb": round(mx.get_active_memory() / 1048576, 1),
        "mlx_peak_mb": round(mx.get_peak_memory() / 1048576, 1),
        "mlx_cache_mb": round(mx.get_cache_memory() / 1048576, 1),
        "footprint_mb": round(_phys_footprint_bytes() / 1048576, 1),
        "system_used_mb": round((system.total - system.available) / 1048576, 1),
        "system_total_mb": round(system.total / 1048576, 1),
    }

STATE_UNLOADED = "unloaded"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_GENERATING = "generating"
STATE_UNLOADING = "unloading"
STATE_FAILED = "failed"

# 加载失败后共享同一失败结果的冷却时间（BR-54）
LOAD_COOLDOWN_SECONDS = 5.0
# 输出格式固定 44.1 kHz 16-bit 单声道，health 与响应头共用
SAMPLE_RATE = 44100
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt")


class QueueFullError(RuntimeError):
    """等待队列已满，调用方应返回 429。"""


class QueueTimeoutError(RuntimeError):
    """排队时间超过上限，调用方应返回 429。"""


class ModelUnavailableError(RuntimeError):
    """权重加载失败，或仍处于失败冷却期，调用方应返回 503。"""


class ServiceClosedError(RuntimeError):
    """服务正在停止，不再接受新请求，调用方应返回 503。"""


class RequestCancelledError(RuntimeError):
    """客户端已断开，排队任务被移出队列。"""


@dataclass
class _Job:
    future: Future
    call: Callable[[Any], Any]
    enqueued_at: float
    started: bool = False
    abandoned: bool = False


class ModelManager:
    """启动只加载配置与 tokenizer 校验信息，权重按需加载，合成串行执行。"""

    def __init__(
        self,
        model_path: str,
        idle_timeout: int = 1200,
        max_queue: int = 8,
        queue_timeout: float = 120.0,
        cache_limit_mb: int = 512,
    ) -> None:
        if idle_timeout < 0:
            raise ValueError("空闲阈值不能为负数")
        if max_queue < 0:
            raise ValueError("队列上限不能为负数")
        if queue_timeout <= 0:
            raise ValueError("排队上限必须大于 0")
        if cache_limit_mb < 0:
            raise ValueError("MLX 缓存上限不能为负数")

        self.model_path = model_path
        self.idle_timeout = idle_timeout
        self.max_queue = max_queue
        self.queue_timeout = queue_timeout
        self.cache_limit_mb = cache_limit_mb
        # 缓存上限按进程生效，超限的缓冲在下次分配前归还系统；0 表示禁用缓存
        mx.set_cache_limit(cache_limit_mb * 1048576)

        self._model: Any = None
        self._config: Optional[dict[str, Any]] = None
        self._state = STATE_UNLOADED
        self._last_error: Optional[str] = None
        self._failed_until = 0.0
        self._last_active = time.time()
        self._closed = False
        self._unload_requested = False
        self._assets_error: Optional[str] = None

        self._jobs: Deque[_Job] = deque()
        self._in_flight: Optional[_Job] = None
        self._cond = threading.Condition(threading.Lock())

        # 启动阶段先校验配置与 tokenizer，缺失直接失败；权重路径不存在时允许启动
        self._load_assets()

        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="ming-tts-worker"
        )
        self._worker.start()
        self._monitor = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ming-tts-idle-watch"
        )
        self._monitor.start()

    # ---------- 对外状态 ----------

    @property
    def state(self) -> str:
        with self._cond:
            return self._state

    @property
    def last_error(self) -> Optional[str]:
        with self._cond:
            return self._last_error

    @property
    def model_loaded(self) -> bool:
        with self._cond:
            return self._model is not None

    @property
    def idle_seconds(self) -> float:
        with self._cond:
            return time.time() - self._last_active

    def snapshot(self) -> dict[str, Any]:
        """给 `/health` 用的只读快照，不触发加载。"""
        with self._cond:
            error = self._last_error or self._assets_error
            degraded = self._state == STATE_FAILED or self._assets_error is not None
            data: dict[str, Any] = {
                "status": "degraded" if degraded else "ok",
                "state": self._state,
                "model_loaded": self._model is not None,
                "idle_seconds": round(time.time() - self._last_active, 1),
                "idle_timeout_seconds": self.idle_timeout,
                "sample_rate": SAMPLE_RATE,
                "memory": memory_snapshot(),
            }
            if error:
                data["last_error"] = error
            return data

    # ---------- 任务提交 ----------

    def submit(self, call: Callable[[Any], Any]) -> _Job:
        """把合成任务放入等待队列，返回 job 供 wait/cancel 使用。"""
        with self._cond:
            if self._closed:
                raise ServiceClosedError("服务正在停止")
            if self._state == STATE_FAILED and time.monotonic() < self._failed_until:
                raise ModelUnavailableError(self._last_error or "模型加载失败")
            if len(self._jobs) >= self.max_queue:
                raise QueueFullError("等待队列已满")
            job = _Job(future=Future(), call=call, enqueued_at=time.time())
            self._jobs.append(job)
            self._cond.notify_all()
            return job

    def wait(self, job: _Job, timeout: Optional[float] = None) -> Any:
        """阻塞等待结果；排队超时在锁内完成判定与出队。"""
        limit = self.queue_timeout if timeout is None else timeout
        deadline = job.enqueued_at + limit
        with self._cond:
            while not job.future.done():
                # 已出队的任务不再受排队上限约束（§4.9-4）
                if job.started:
                    self._cond.wait(timeout=0.5)
                    continue
                remaining = deadline - time.time()
                if remaining <= 0:
                    self._expire_locked(job)
                    break
                self._cond.wait(timeout=min(remaining, 0.5))
        return job.future.result()

    def cancel(self, job: _Job) -> bool:
        """客户端断开时调用。返回 True 表示任务仍在队列、由调用方清理临时文件。"""
        with self._cond:
            if job in self._jobs:
                self._jobs.remove(job)
                job.abandoned = True
                if not job.future.done():
                    job.future.set_exception(RequestCancelledError("请求已取消"))
                self._cond.notify_all()
                return True
            if job.started and not job.future.done():
                # 已开始合成不打断，完成后丢弃结果（BR-59）
                job.abandoned = True
            return False

    def _expire_locked(self, job: _Job) -> None:
        """调用方必须持有锁。已出队的任务不在这里处理。"""
        if job not in self._jobs:
            return
        self._jobs.remove(job)
        job.abandoned = True
        if not job.future.done():
            job.future.set_exception(QueueTimeoutError("排队等待超时"))
        self._cond.notify_all()

    # ---------- 关闭 ----------

    def begin_shutdown(self) -> None:
        """停止接新请求，排队任务立即失败（BR-60、BR-89）。"""
        with self._cond:
            self._closed = True
            for job in list(self._jobs):
                if not job.future.done():
                    job.future.set_exception(ServiceClosedError("服务正在停止"))
                job.abandoned = True
            self._jobs.clear()
            self._cond.notify_all()

    def shutdown(self, timeout: float = 120.0) -> None:
        """等待在途合成结束，超时后记录未完成任务并由进程退出兜底。"""
        self.begin_shutdown()
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.warning("在途合成超过 %.0f 秒，强制退出", timeout)

    # ---------- worker ----------

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                while (
                    not self._jobs
                    and not self._unload_requested
                    and not self._closed
                ):
                    self._cond.wait(timeout=0.5)
                if self._closed and not self._jobs:
                    return
                if not self._jobs:
                    # 队列为空才处理卸载，卸载期间到达的请求留在队列里等加载
                    self._unload_requested = False
                    self._state = STATE_UNLOADING
                    self._cond.notify_all()
                    unload = True
                    job = None
                else:
                    job = self._jobs.popleft()
                    job.started = True
                    self._in_flight = job
                    self._state = (
                        STATE_LOADING if self._model is None else STATE_GENERATING
                    )
                    self._cond.notify_all()
                    unload = False

            if unload:
                self._release_locked_after_unload()
                continue

            try:
                if self._model is None:
                    self._load_model()
                    with self._cond:
                        if self._state != STATE_FAILED:
                            self._state = STATE_GENERATING
                        self._cond.notify_all()
                result = job.call(self._model)
            except Exception as exc:
                logger.debug("任务执行失败：%s", type(exc).__name__)
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                if not job.future.done():
                    job.future.set_result(result)
            finally:
                with self._cond:
                    self._in_flight = None
                    self._last_active = time.time()
                    if self._state == STATE_GENERATING:
                        self._state = STATE_READY
                    self._cond.notify_all()
                # 每次合成都会产生尺寸各异的新缓冲，MLX 缓存池会随请求次数持续变大。
                # 这里无条件清空而不是等队列空闲：持续有请求时队列永远不空，
                # 等下去等于不清理；实测每次清空后单次耗时无明显变化。
                mx.clear_cache()

    def _load_model(self) -> None:
        """只在 worker 线程调用，保证同一时刻只有一次加载。"""
        with self._cond:
            if self._closed:
                raise ServiceClosedError("服务正在停止")
            self._state = STATE_LOADING
            self._cond.notify_all()

        started = time.monotonic()
        logger.info("加载权重：%s", self.model_path)
        try:
            if not Path(self.model_path).is_dir():
                raise FileNotFoundError(self.model_path)
            model = load_model(self.model_path)
        except Exception as exc:
            # 加载失败不残留半成品引用，并清理本次分配
            gc.collect()
            message = f"权重加载失败：{type(exc).__name__}"
            if isinstance(exc, FileNotFoundError):
                message = "没有找到语音合成模型，请先运行 ./scripts/setup_ming_tts.sh"
            logger.exception("权重加载失败")
            with self._cond:
                self._model = None
                self._state = STATE_FAILED
                self._last_error = message
                self._failed_until = time.monotonic() + LOAD_COOLDOWN_SECONDS
                self._last_active = time.time()
                self._cond.notify_all()
            raise ModelUnavailableError(message) from exc

        with self._cond:
            self._model = model
            self._state = STATE_READY
            self._last_error = None
            self._cond.notify_all()
        logger.info("权重加载完成，耗时 %.2f 秒", time.monotonic() - started)

    def _release_locked_after_unload(self) -> None:
        """按 BR-52 的顺序释放：解引用、gc、清 Metal 缓存。"""
        idle = self.idle_seconds
        try:
            model = self._model
            self._model = None
            del model
            gc.collect()
            mx.clear_cache()
        except Exception:
            logger.exception("释放权重失败，恢复可用状态")
            with self._cond:
                self._state = STATE_READY if self._model is not None else STATE_UNLOADED
                self._last_active = time.time()
                self._cond.notify_all()
            return

        with self._cond:
            self._state = STATE_UNLOADED
            self._last_active = time.time()
            self._cond.notify_all()
        logger.info("空闲 %.0f 秒，权重已释放", idle)

    def _monitor_loop(self) -> None:
        if self.idle_timeout <= 0:
            # 0 表示常驻，不启动判断
            return
        interval = max(1, min(10, self.idle_timeout // 2))
        while True:
            time.sleep(interval)
            with self._cond:
                if self._closed:
                    return
                if self._state != STATE_READY or self._model is None:
                    continue
                if self._jobs or self._in_flight is not None:
                    continue
                if self._unload_requested:
                    continue
                if time.time() - self._last_active < self.idle_timeout:
                    continue
                self._unload_requested = True
                self._cond.notify_all()

    # ---------- 启动资产 ----------

    def _load_assets(self) -> None:
        """启动时校验配置与 tokenizer 文件，不加载权重（BR-14）。"""
        root = Path(self.model_path)
        if not root.is_dir():
            self._assets_error = (
                "权重目录不存在，请先运行 ./scripts/setup_ming_tts.sh"
            )
            logger.warning("%s", self._assets_error)
            return

        config_path = root / "config.json"
        try:
            self._config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"config.json 缺失或损坏，请重跑 ./scripts/setup_ming_tts.sh：{exc}"
            ) from exc

        missing = [name for name in TOKENIZER_FILES if not (root / name).is_file()]
        if missing:
            raise RuntimeError(
                f"tokenizer 文件缺失（{', '.join(missing)}），请重跑 ./scripts/setup_ming_tts.sh"
            )
        logger.info("配置与 tokenizer 校验通过：%s", root)
