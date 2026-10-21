"""Hy-MT2 模型生命周期、串行推理队列与空闲卸载。"""

from __future__ import annotations

import gc
import json
import logging
import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional

import mlx.core as mx
from mlx_lm import generate as mlx_generate
from mlx_lm import load
import mlx_lm.sample_utils as su

logger = logging.getLogger(__name__)

STATE_UNLOADED = "unloaded"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_GENERATING = "generating"
STATE_UNLOADING = "unloading"
STATE_FAILED = "failed"

LOAD_COOLDOWN_SECONDS = 5.0
# transformers 用超大整数表示「不限制长度」，这类值不能当上下文上限
IGNORED_MAX_LENGTH = 1_000_000_000


class QueueFullError(RuntimeError):
    """等待队列已满。"""


class ModelLoadError(RuntimeError):
    """权重加载失败，或仍处于失败冷却期。"""


class ServiceClosedError(RuntimeError):
    """服务正在停止，不再接受新请求。"""


@dataclass
class GenerationResult:
    text: str
    finish_reason: str


@dataclass
class _Job:
    future: Future
    call: Callable[[], Any]
    kind: str
    cancelled: bool = False


class ModelManager:
    """启动只加载 tokenizer，权重按需加载，推理任务串行执行。"""

    def __init__(
        self,
        model_path: str,
        idle_timeout: int = 1200,
        max_queue: int = 8,
    ) -> None:
        if idle_timeout < 0:
            raise ValueError("空闲阈值不能为负数")
        if max_queue < 0:
            raise ValueError("队列上限不能为负数")

        self.model_path = model_path
        self.idle_timeout = idle_timeout
        self.max_queue = max_queue

        self._model: Any = None
        self._tokenizer: Any = None
        self._state = STATE_UNLOADED
        self._last_error: Optional[str] = None
        self._failed_until = 0.0
        self._last_active = time.time()
        self._context_limit: Optional[int] = None
        self._context_resolved = False
        self._closed = False

        self._jobs: Deque[_Job] = deque()
        self._in_flight: Optional[_Job] = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._exec_lock = threading.Lock()

        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="hy-mt2-worker",
        )
        self._worker.start()
        self._monitor = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="hy-mt2-idle-watch",
        )
        self._monitor.start()

        self._load_tokenizer()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._last_active

    def tokenizer(self) -> Any:
        """返回启动时加载的分词器，不触发权重加载。"""
        if self._tokenizer is None:
            raise ModelLoadError("tokenizer 不可用")
        return self._tokenizer

    def context_limit(self) -> Optional[int]:
        """上下文上限，无法确定时返回 None。"""
        with self._lock:
            if self._context_resolved:
                return self._context_limit

            limit: Optional[int] = None
            config_path = os.path.join(self.model_path, "config.json")
            try:
                with open(config_path, encoding="utf-8") as handle:
                    value = json.load(handle).get("max_position_embeddings")
                if isinstance(value, int) and 0 < value < IGNORED_MAX_LENGTH:
                    limit = value
            except (OSError, ValueError) as exc:
                logger.warning("读取 config.json 失败：%s", exc)

            if limit is None and self._tokenizer is not None:
                value = getattr(self._tokenizer, "model_max_length", None)
                if isinstance(value, int) and 0 < value < IGNORED_MAX_LENGTH:
                    limit = value

            if limit is None:
                logger.warning("无法确定上下文长度，跳过输入长度校验")

            self._context_limit = limit
            self._context_resolved = True
            return limit

    def count_message_tokens(self, messages: list[dict[str, str]]) -> int:
        """用启动时的 tokenizer 计算消息 token 数。"""
        tokenizer = self.tokenizer()
        encoded = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
        )
        try:
            input_ids = encoded["input_ids"]
        except (TypeError, KeyError):
            input_ids = encoded
        if input_ids and isinstance(input_ids[0], list):
            input_ids = input_ids[0]
        return len(input_ids)

    def submit_generate(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repetition_penalty: float,
    ) -> Future:
        """把生成任务放入队列，返回可等待的 Future。"""
        return self._submit(
            "generate",
            lambda: self.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
            ),
        )

    def cancel(self, future: Future) -> None:
        """排队中的任务直接移出队列，已在生成的标记取消但不打断。"""
        with self._cond:
            for job in list(self._jobs):
                if job.future is future:
                    job.cancelled = True
                    self._jobs.remove(job)
                    future.cancel()
                    self._cond.notify_all()
                    return
            if self._in_flight is not None and self._in_flight.future is future:
                self._in_flight.cancelled = True

    def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.6,
        top_k: int = 20,
        repetition_penalty: float = 1.05,
    ) -> GenerationResult:
        """同步执行一次生成，CLI 和推理 worker 共用。"""
        sampler = su.make_sampler(temp=temperature, top_p=top_p, top_k=top_k)
        logits_processors = su.make_logits_processors(
            repetition_penalty=repetition_penalty
        )
        with self._exec_lock:
            self._ensure_model()
            self._set_state(STATE_GENERATING)
            try:
                text = mlx_generate(
                    self._model,
                    self._tokenizer,
                    prompt,
                    max_tokens=max_tokens,
                    sampler=sampler,
                    logits_processors=logits_processors,
                )
            finally:
                with self._cond:
                    self._last_active = time.time()
                    if self._state == STATE_GENERATING:
                        self._state = (
                            STATE_READY if self._model is not None else STATE_UNLOADED
                        )
                        self._cond.notify_all()

        stripped = text.strip()
        return GenerationResult(
            text=stripped,
            finish_reason="length" if self._reached_limit(stripped, max_tokens) else "stop",
        )

    def begin_shutdown(self) -> None:
        """停止接新请求，并让排队中的请求立即失败。"""
        with self._cond:
            self._closed = True
            for job in list(self._jobs):
                if not job.future.done():
                    job.future.set_exception(ServiceClosedError("服务正在停止"))
                job.cancelled = True
            self._jobs.clear()
            self._cond.notify_all()

    def shutdown(self, timeout: float = 30.0) -> None:
        """等待在途任务结束，超时后由进程退出兜底。"""
        self.begin_shutdown()
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.warning("在途生成超过 %.0f 秒，强制退出", timeout)

    def unload(self, reason: str = "idle") -> None:
        """释放权重，tokenizer 继续常驻。"""
        with self._exec_lock:
            if self._model is None:
                return
            logger.info("卸载权重，原因：%s", reason)
            self._model = None
            gc.collect()
            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                mx.metal.clear_cache()
            self._set_state(STATE_UNLOADED)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            failed = self._state == STATE_FAILED
            data: dict[str, Any] = {
                "status": "degraded" if failed else "ok",
                "state": self._state,
                "model_loaded": self._model is not None,
                "idle_seconds": round(time.time() - self._last_active, 1),
                "idle_timeout_seconds": self.idle_timeout,
            }
            if failed:
                data["last_error"] = self._last_error or "模型加载失败"
            return data

    def _load_tokenizer(self) -> None:
        started = time.time()
        try:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        except Exception as exc:  # 启动阶段失败必须直接暴露
            logger.error("tokenizer 加载失败：%s", exc)
            raise ModelLoadError(
                "tokenizer 加载失败，请先运行 ./scripts/setup_hy_mt2.sh"
            ) from exc
        logger.info("tokenizer 加载完成，耗时 %.2f 秒", time.time() - started)

    def _submit(self, kind: str, call: Callable[[], Any]) -> Future:
        with self._cond:
            if self._closed:
                raise ServiceClosedError("服务正在停止")
            if self._state == STATE_FAILED and time.monotonic() < self._failed_until:
                raise ModelLoadError(self._last_error or "模型加载失败")
            if len(self._jobs) >= self.max_queue and (
                self._jobs or self._in_flight is not None
            ):
                raise QueueFullError("等待队列已满")

            job = _Job(future=Future(), call=call, kind=kind)
            self._jobs.append(job)
            self._cond.notify_all()
            return job.future

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                while not self._jobs and not self._closed:
                    self._cond.wait(timeout=0.5)
                if not self._jobs:
                    if self._closed:
                        return
                    continue
                job = self._jobs.popleft()
                self._in_flight = job
                if not job.cancelled and job.kind == "unload":
                    self._state = STATE_UNLOADING
                self._cond.notify_all()

            if job.cancelled:
                self._finish_job()
                continue

            try:
                result = job.call()
            except Exception as exc:
                logger.debug("任务执行失败：%s", exc)
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                if not job.future.done():
                    job.future.set_result(result)
            finally:
                self._finish_job()

    def _finish_job(self) -> None:
        with self._cond:
            self._in_flight = None
            self._last_active = time.time()
            if self._state in (STATE_GENERATING, STATE_UNLOADING):
                self._state = STATE_READY if self._model is not None else STATE_UNLOADED
            self._cond.notify_all()

    def _weights_missing(self) -> bool:
        """权重目录里没有任何 safetensors 时，直接给出可行动的错误。"""
        if not os.path.isdir(self.model_path):
            return True
        try:
            return not any(
                name.endswith(".safetensors") for name in os.listdir(self.model_path)
            )
        except OSError:
            return True

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        with self._cond:
            if self._state == STATE_FAILED and time.monotonic() < self._failed_until:
                raise ModelLoadError(self._last_error or "模型加载失败")
            self._state = STATE_LOADING
            self._cond.notify_all()

        started = time.time()
        logger.info("加载权重：%s", self.model_path)
        try:
            if self._weights_missing():
                raise FileNotFoundError("未找到 *.safetensors 权重")
            model, tokenizer = load(self.model_path)
        except Exception as exc:
            logger.exception("权重加载失败")
            if isinstance(exc, FileNotFoundError):
                message = "没有找到翻译模型，请先运行安装脚本"
            else:
                message = "权重加载失败"
            with self._cond:
                self._state = STATE_FAILED
                self._last_error = message
                self._failed_until = time.monotonic() + LOAD_COOLDOWN_SECONDS
                self._cond.notify_all()
            raise ModelLoadError(message) from exc

        self._model = model
        self._tokenizer = tokenizer
        with self._cond:
            self._state = STATE_READY
            self._last_error = None
            self._cond.notify_all()
        logger.info("权重加载完成，耗时 %.2f 秒", time.time() - started)

    def _set_state(self, state: str) -> None:
        with self._cond:
            self._state = state
            self._cond.notify_all()

    def _reached_limit(self, text: str, max_tokens: int) -> bool:
        try:
            return len(self._tokenizer.encode(text, add_special_tokens=False)) >= max_tokens
        except Exception:
            return False

    def _monitor_loop(self) -> None:
        interval = max(1, min(10, self.idle_timeout // 2 if self.idle_timeout else 10))
        while True:
            time.sleep(interval)
            if self._closed or self.idle_timeout <= 0:
                continue
            with self._cond:
                if self._closed:
                    return
                if self._state != STATE_READY or self._model is None:
                    continue
                if self._jobs or self._in_flight is not None:
                    continue
                if time.time() - self._last_active < self.idle_timeout:
                    continue
                job = _Job(future=Future(), call=self._unload_job, kind="unload")
                self._jobs.append(job)
                self._cond.notify_all()

    def _unload_job(self) -> None:
        with self._exec_lock:
            with self._cond:
                # 判定后又来了新请求，放弃本轮卸载
                if self._jobs:
                    return
                self._state = STATE_UNLOADING
                idle = time.time() - self._last_active
                self._cond.notify_all()
            logger.info("空闲 %.0f 秒，释放权重", idle)
            self._model = None
            gc.collect()
            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                mx.metal.clear_cache()
