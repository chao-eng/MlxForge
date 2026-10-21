"""能力状态到 API 行为的唯一映射（§1.7、BR-82、BR-83）。

状态只能依据 `docs/benchmarks.md` 的 Spike 结论变更；当前情绪、属性、方言、
IP 均处于「待 Spike」，按实验能力透传，不返回 400，也不承诺效果。
"""

from __future__ import annotations

from typing import Dict

from runtimes.ming_tts.errors import invalid
from runtimes.ming_tts.schema import SpeechRequest

VERIFIED = "verified"
EXPERIMENTAL = "experimental"
UNSUPPORTED = "unsupported"
NOT_OPEN = "not_open"

CAPABILITY_STATUS: Dict[str, str] = {
    "emotion": EXPERIMENTAL,
    "speed": EXPERIMENTAL,
    "pitch": EXPERIMENTAL,
    "volume": EXPERIMENTAL,
    "dialect": EXPERIMENTAL,
    "ip": EXPERIMENTAL,
    "voice_design": VERIFIED,
    "clone": VERIFIED,
    "builtin_voice": VERIFIED,
    "multilingual": VERIFIED,
}

CAPABILITY_LABELS = {
    "emotion": "情绪控制",
    "speed": "语速控制",
    "pitch": "音高控制",
    "volume": "音量控制",
    "dialect": "方言模式",
    "ip": "IP 角色",
    "voice_design": "声音设计",
    "clone": "声音克隆",
    "builtin_voice": "内置音色",
    "multilingual": "多语言",
}


def _ensure(name: str) -> None:
    status = CAPABILITY_STATUS[name]
    if status == UNSUPPORTED:
        raise invalid(f"{CAPABILITY_LABELS[name]}当前不受支持，请移除相关字段")
    if status == NOT_OPEN:
        raise invalid(f"{CAPABILITY_LABELS[name]}尚未开放，请移除相关字段")


def ensure_capabilities(request: SpeechRequest) -> None:
    """实验能力原样透传；仅对判定不支持或未开放的字段返回 400。"""
    if request.emotion:
        _ensure("emotion")
    if request.speed != 1.0:
        _ensure("speed")
    if request.pitch != 0:
        _ensure("pitch")
    if request.volume != 1.0:
        _ensure("volume")
    if request.language_is_dialect:
        _ensure("dialect")
    if request.task == "ip":
        _ensure("ip")
    if request.has_reference:
        _ensure("clone")
    if request.voice_is_builtin:
        _ensure("builtin_voice")
    if request.voice == "design":
        _ensure("voice_design")
    if request.language in ("de", "es", "fr", "ko", "ja"):
        _ensure("multilingual")
