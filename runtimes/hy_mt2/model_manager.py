"""Hy-MT2 模型生命周期管理。"""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Any

import mlx.core as mx
from mlx_lm import generate as mlx_generate
from mlx_lm import load
import mlx_lm.sample_utils as su

logger = logging.getLogger(__name__)


class ModelManager:
    """按需加载模型，空闲超时后释放统一内存。"""

    def __init__(self, model_path: str, idle_timeout: int = 1200) -> None:
        self.model_path = model_path
        self.idle_timeout = idle_timeout
        self.check_interval = max(1, min(10, idle_timeout // 2))
        self._model: Any = None
        self._tokenizer: Any = None
        self._last_active = time.time()
        self._lock = threading.Lock()
        threading.Thread(
            target=self._watch_idle,
            daemon=True,
            name="hy-mt2-idle-watch",
        ).start()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_active

    def tokenizer(self) -> Any:
        with self._lock:
            self._load_locked()
            self._last_active = time.time()
            return self._tokenizer

    def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float = 0.6,
        top_k: int = 20,
        repetition_penalty: float = 1.05,
    ) -> str:
        sampler = su.make_sampler(temp=temperature, top_p=top_p, top_k=top_k)
        logits_processors = su.make_logits_processors(repetition_penalty=repetition_penalty)
        # 生成过程独占锁，避免并发请求同时进 Metal，也防止空闲线程中途卸载
        with self._lock:
            self._load_locked()
            self._last_active = time.time()
            text = mlx_generate(
                self._model,
                self._tokenizer,
                prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                logits_processors=logits_processors,
            )
            self._last_active = time.time()
        return text.strip()

    def unload(self, reason: str = "idle") -> None:
        with self._lock:
            if self._model is None:
                return
            logger.info("卸载模型，原因：%s", reason)
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            gc.collect()
            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                mx.metal.clear_cache()

    def _load_locked(self) -> None:
        if self._model is not None:
            return
        started = time.time()
        logger.info("加载模型：%s", self.model_path)
        self._model, self._tokenizer = load(self.model_path)
        logger.info("模型加载完成，耗时 %.2f 秒", time.time() - started)

    def _watch_idle(self) -> None:
        while True:
            time.sleep(self.check_interval)
            if self.is_loaded and self.idle_seconds >= self.idle_timeout:
                self.unload(reason=f"空闲 {int(self.idle_seconds)} 秒")
