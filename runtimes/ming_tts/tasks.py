"""任务模式解析：七项冲突检查、显式 task 校验与 auto 八步优先级（§4.3、附录 A-6）。

A-6 是唯一权威定义，本模块只实现，不重新定义字段规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from runtimes.ming_tts.capabilities import ensure_capabilities
from runtimes.ming_tts.errors import invalid
from runtimes.ming_tts.schema import DIALECTS, LANGUAGE_IDS, SpeechRequest

MODEL_TASK_NAMES = {
    "tts": "TTS",
    "freeform": "FREEFORM",
    "voice_design": "VOICE_DESIGN",
    "multilingual": "MULTILINGUAL",
    "basic": "BASIC",
    "emotion": "EMOTION",
    "dialect": "DIALECT",
    "ip": "IP",
}


@dataclass(frozen=True)
class ResolvedTask:
    """解析结果：模型侧任务名与需要传给模型的附加控制信息。"""

    mode: str
    model_task: str
    language_id: Optional[str]
    dialect: Optional[str]
    uses_reference: bool
    uses_builtin_voice: bool


def resolve_task(request: SpeechRequest) -> ResolvedTask:
    # 实验能力透传，不支持或未开放的字段在这里统一返回 400（BR-82）
    ensure_capabilities(request)
    _check_conflicts(request)
    mode = request.task
    if mode == "auto":
        mode = _resolve_auto(request)
    _validate_task(mode, request)

    return ResolvedTask(
        mode=mode,
        model_task=MODEL_TASK_NAMES[mode],
        # 方言只走方言指令，不得再传 language ID（BR-36）
        language_id=request.language if request.language in LANGUAGE_IDS else None,
        dialect=request.language if mode == "dialect" else None,
        uses_reference=request.has_reference,
        uses_builtin_voice=request.voice_is_builtin,
    )


def _check_conflicts(request: SpeechRequest) -> None:
    """§4.3 七项冲突检查，顺序固定，命中即 400，不做静默降级。"""
    has_attributes = request.attributes_changed
    if request.has_reference and (
        request.voice_is_builtin or request.voice == "design"
    ):
        raise invalid(
            "reference_audio 不能与内置音色或 voice=design 同时出现；"
            "需要克隆时请把 voice 设为 auto"
        )

    if request.voice_is_builtin and request.instructions:
        raise invalid(
            "内置音色不能与 instructions 同时出现；"
            "请改用 task=voice_design，或使用情绪、属性控制"
        )

    if request.instructions and (request.emotion or has_attributes):
        raise invalid(
            "instructions 不能与 emotion 或 speed/pitch/volume 同时出现；"
            "请显式选择任务模式"
        )

    if request.instructions and request.language_is_dialect:
        raise invalid("instructions 不能与方言语言同时出现")

    if (request.emotion or has_attributes) and request.language_is_dialect:
        raise invalid("emotion 或 speed/pitch/volume 不能与方言语言同时出现")

    if request.has_reference and request.language_is_dialect:
        raise invalid("reference_audio 不能与方言语言同时出现")

    if request.voice == "design" and (request.emotion or has_attributes):
        raise invalid(
            "voice=design 不能与 emotion 或 speed/pitch/volume 同时出现"
        )


def _resolve_auto(request: SpeechRequest) -> str:
    """A-6 的八步优先级，返回第一条命中的任务模式。"""
    if request.has_reference:
        return "tts"
    if request.voice == "design":
        return "voice_design"
    if request.language_is_dialect:
        return "dialect"
    if request.emotion or request.attributes_changed:
        return "emotion"
    if request.instructions:
        return "freeform"
    if request.voice_is_builtin:
        return "tts"
    if request.language in LANGUAGE_IDS:
        return "multilingual"
    return "basic"


def _reject_instructions(request: SpeechRequest, mode: str) -> None:
    if request.instructions:
        raise invalid(f"task={mode} 不允许 instructions")


def _reject_dialect(request: SpeechRequest, mode: str) -> None:
    if request.language_is_dialect:
        raise invalid(f"task={mode} 不允许方言语言")


def _reject_reference(request: SpeechRequest, mode: str) -> None:
    if request.has_reference:
        raise invalid(f"task={mode} 不允许 reference_audio")


def _require_instructions(request: SpeechRequest, label: str) -> None:
    if not request.instructions:
        raise invalid(f"{label}需要提供 instructions")


def _validate_task(mode: str, request: SpeechRequest) -> None:
    """按 A-6 的必填、允许、禁止列逐条校验。"""
    if mode == "tts":
        if request.voice == "design":
            raise invalid("task=tts 不允许 voice=design，请改用 task=voice_design")
        if request.instructions:
            raise invalid("task=tts 不允许 instructions，请改用 task=freeform")
        if request.emotion or request.attributes_changed:
            raise invalid("task=tts 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_dialect(request, mode)
        return

    if mode == "freeform":
        _require_instructions(request, "自由指令模式")
        if request.voice_is_builtin:
            raise invalid("task=freeform 不允许内置音色")
        if request.voice == "design":
            raise invalid("task=freeform 不允许 voice=design，请改用 task=voice_design")
        if request.emotion or request.attributes_changed:
            raise invalid("task=freeform 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_dialect(request, mode)
        return

    if mode == "voice_design":
        _require_instructions(request, "声音设计模式")
        _reject_reference(request, "voice_design")
        if request.voice_is_builtin:
            raise invalid("声音设计不允许内置音色，voice 请设为 design 或 auto")
        if request.emotion or request.attributes_changed:
            raise invalid("声音设计不允许 emotion 或 speed/pitch/volume 控制")
        _reject_dialect(request, "voice_design")
        return

    if mode == "multilingual":
        if request.language not in LANGUAGE_IDS:
            raise invalid(
                "task=multilingual 的 language 必须是 de、es、fr、ko、ja 之一"
            )
        _reject_instructions(request, mode)
        if request.emotion or request.attributes_changed:
            raise invalid("task=multilingual 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_reference(request, mode)
        if request.voice == "design":
            raise invalid("task=multilingual 不允许 voice=design")
        return

    if mode == "basic":
        if request.voice != "auto":
            raise invalid("task=basic 只允许 voice=auto")
        _reject_instructions(request, mode)
        if request.emotion or request.attributes_changed:
            raise invalid("task=basic 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_reference(request, mode)
        if request.language in DIALECTS:
            raise invalid("task=basic 不允许方言语言，请改用 task=dialect")
        if request.language in LANGUAGE_IDS:
            raise invalid(
                "task=basic 不允许 language 为 de/es/fr/ko/ja，请改用 task=multilingual"
            )
        return

    if mode == "emotion":
        if not (request.emotion or request.attributes_changed):
            raise invalid("task=emotion 需要提供 emotion 或至少一项非默认属性")
        _reject_instructions(request, mode)
        _reject_reference(request, mode)
        if request.voice == "design":
            raise invalid("task=emotion 不允许 voice=design")
        _reject_dialect(request, mode)
        return

    if mode == "dialect":
        if request.language not in DIALECTS:
            raise invalid(
                "task=dialect 的 language 必须是 sichuanese 或 cantonese"
            )
        _reject_instructions(request, mode)
        if request.emotion or request.attributes_changed:
            raise invalid("task=dialect 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_reference(request, mode)
        if request.voice == "design":
            raise invalid("task=dialect 不允许 voice=design")
        return

    if mode == "ip":
        _require_instructions(request, "IP 角色模式")
        _reject_reference(request, mode)
        if request.voice_is_builtin:
            raise invalid("task=ip 不允许内置音色")
        if request.emotion or request.attributes_changed:
            raise invalid("task=ip 不允许 emotion 或 speed/pitch/volume 控制")
        _reject_dialect(request, mode)
        return

    raise AssertionError(f"未登记的任务模式：{mode}")
