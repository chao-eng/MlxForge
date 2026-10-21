"""把解析结果翻译成 mlx-audio 的生成参数并编码输出（BR-41、BR-44）。

只做参数组装与结果编码；任务解析与字段校验在 `tasks.py`、`schema.py`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import mlx.core as mx
import numpy as np
from mlx_audio.tts.models.bailingmm.bailingmm import ming3_instruction

from runtimes.ming_tts import audio
from runtimes.ming_tts.schema import SpeechRequest
from runtimes.ming_tts.tasks import ResolvedTask


class SynthesisError(RuntimeError):
    """合成失败或结果为空，调用方应返回 500。"""


@dataclass(frozen=True)
class SynthesisResult:
    pcm: bytes
    duration: float


def synthesize(
    model: Any,
    request: SpeechRequest,
    task: ResolvedTask,
    reference_path: Optional[Path] = None,
) -> SynthesisResult:
    """在推理 worker 线程内调用，seed 必须在每次生成前设置。"""
    mx.random.seed(request.seed)
    results = list(
        model.generate(**_build_kwargs(request, task, reference_path))
    )
    if not results:
        raise SynthesisError("合成结果为空")

    result = results[-1]
    if int(result.sample_rate) != audio.SAMPLE_RATE:
        raise SynthesisError(f"模型输出采样率异常：{result.sample_rate}")

    samples = np.array(result.audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        raise SynthesisError("合成结果为空")

    pcm = audio.encode_pcm(samples)
    return SynthesisResult(pcm=pcm, duration=audio.duration_seconds(pcm))


def _build_kwargs(
    request: SpeechRequest,
    task: ResolvedTask,
    reference_path: Optional[Path],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "text": request.input,
        "voice": request.voice if task.uses_builtin_voice else None,
        "instruct": _build_instruction(request, task),
        # 中英文不传 language ID，由模型默认处理（A-5）
        "lang_code": task.language_id or "auto",
        "stream": False,
    }
    if reference_path is not None:
        kwargs["ref_audio"] = str(reference_path)
        kwargs["ref_text"] = request.reference_text
    return kwargs


def _build_instruction(
    request: SpeechRequest, task: ResolvedTask
) -> Optional[str]:
    if task.mode in ("freeform", "voice_design"):
        return request.instructions
    if task.mode == "ip":
        return ming3_instruction(ip=request.instructions)
    if task.mode == "emotion":
        return ming3_instruction(
            emotion=request.emotion or None,
            speed=_speed_label(request.speed),
            pitch=_pitch_label(request.pitch),
            volume=_volume_label(request.volume),
        )
    if task.mode == "dialect":
        return ming3_instruction(dialect=task.dialect)
    return None


def _speed_label(value: float) -> Optional[str]:
    if value < 1.0:
        return "慢速"
    if value > 1.0:
        return "快速"
    return None


def _pitch_label(value: int) -> Optional[str]:
    if value < 0:
        return "低"
    if value > 0:
        return "高"
    return None


def _volume_label(value: float) -> Optional[str]:
    if value < 1.0:
        return "低"
    if value > 1.0:
        return "高"
    return None
