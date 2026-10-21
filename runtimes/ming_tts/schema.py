"""语音合成请求的字段校验与默认值归一化（BR-17~BR-30、BR-75）。

只做与框架无关的标量校验，供 API 与 CLI 共用；参考音频的格式、时长、
采样率校验属于解码环节（`audio.py`），base64 解码也必须在线程池执行（BR-98）。
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict

from runtimes.ming_tts.errors import invalid

MAX_BODY_BYTES = 20 * 1024 * 1024
MAX_INPUT_CODEPOINTS = 1000
MAX_INSTRUCTIONS_CODEPOINTS = 500
MAX_EMOTION_CODEPOINTS = 32
MAX_REFERENCE_TEXT_CODEPOINTS = 500
MAX_REFERENCE_AUDIO_BYTES = 10 * 1024 * 1024
# base64 每 3 字节编码为 4 字符，按上限换算成编码后的字符数，避免在事件循环里解码
MAX_REFERENCE_AUDIO_BASE64_CHARS = ((MAX_REFERENCE_AUDIO_BYTES + 2) // 3) * 4
MAX_SEED = 2147483647

MIN_REFERENCE_SECONDS = 5.0
MAX_REFERENCE_SECONDS = 30.0
MIN_REFERENCE_SAMPLE_RATE = 16000
MAX_REFERENCE_SAMPLE_RATE = 48000
MAX_REFERENCE_CHANNELS = 2

SUPPORTED_FORMATS = ("wav", "pcm")
LANGUAGES = (
    "auto",
    "zh",
    "en",
    "de",
    "es",
    "fr",
    "ko",
    "ja",
    "sichuanese",
    "cantonese",
)
TASKS = (
    "auto",
    "tts",
    "freeform",
    "voice_design",
    "multilingual",
    "basic",
    "emotion",
    "dialect",
    "ip",
)
LANGUAGE_IDS = ("de", "es", "fr", "ko", "ja")
DIALECTS = ("sichuanese", "cantonese")

VOICE_AUTO = "auto"
VOICE_DESIGN = "design"
# 与 mlx-audio 的 bailingmm 保持同一命名形式：US_/UK_ 前缀或纯中文名
MING_VOICE_PATTERN = re.compile(
    r"^(?:(?:US|UK)_[A-Z][a-z]+|[\u4e00-\u9fff][\u4e00-\u9fff_]*)$"
)
# OpenAI 自带音色名必须显式拒绝，不能静默回退（§6.2）
OPENAI_VOICE_NAMES = frozenset(
    {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
    }
)
KNOWN_VOICE_EXAMPLES = ("UK_Charlotte", "US_James", "灵小柔")


@dataclass(frozen=True)
class SpeechRequest:
    """已完成类型校验与默认值归一化的合成请求。"""

    model: str
    input: str
    voice: str
    language: str
    response_format: str
    speed: float
    pitch: int
    volume: float
    emotion: str
    instructions: str
    reference_audio: str
    reference_text: str
    task: str
    seed: int
    stream: bool

    @property
    def attributes_changed(self) -> bool:
        return self.speed != 1.0 or self.pitch != 0 or self.volume != 1.0

    @property
    def voice_is_builtin(self) -> bool:
        return self.voice not in (VOICE_AUTO, VOICE_DESIGN)

    @property
    def language_is_dialect(self) -> bool:
        return self.language in DIALECTS

    @property
    def has_reference(self) -> bool:
        return bool(self.reference_audio)


def _field(data: Dict[str, Any], key: str) -> Any:
    return data.get(key)


def _string(data: Dict[str, Any], key: str, default: str = "") -> str:
    value = _field(data, key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise invalid(f"字段 {key} 必须是字符串")
    return value


def _number(data: Dict[str, Any], key: str, default: float) -> float:
    value = _field(data, key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid(f"字段 {key} 必须是数字")
    return float(value)


def _integer(data: Dict[str, Any], key: str, default: int) -> int:
    value = _field(data, key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise invalid(f"字段 {key} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise invalid(f"字段 {key} 必须是整数")


def _bounded_text(
    raw: str, field: str, minimum: int, maximum: int
) -> str:
    text = raw.strip()
    count = len(text)
    if count < minimum or count > maximum:
        raise invalid(
            f"{field} 去除首尾空白后必须是 {minimum}~{maximum} 个 Unicode 码点，当前 {count} 个"
        )
    return text


def _normalize_reference_audio(raw: str) -> str:
    payload = raw.strip()
    if not payload:
        return ""
    if payload.startswith("data:"):
        header, separator, body = payload.partition(",")
        if not separator or ";base64" not in header.lower():
            raise invalid(
                "reference_audio 只支持 base64 字符串或 data:<类型>;base64,<数据> 形式"
            )
        payload = body.strip()
    if not payload:
        raise invalid("reference_audio 不能为空")
    if len(payload) > MAX_REFERENCE_AUDIO_BASE64_CHARS:
        raise invalid("reference_audio 解码后不能超过 10MB")
    return payload


def _normalize_voice(raw: str) -> str:
    voice = raw.strip() or VOICE_AUTO
    if voice in (VOICE_AUTO, VOICE_DESIGN):
        return voice
    if voice.lower() in OPENAI_VOICE_NAMES:
        raise invalid(
            f"音色 “{voice[:64]}” 是 OpenAI 默认音色名，本服务不支持；"
            f"可用 auto、design 或 Ming 内置音色名（如 {'、'.join(KNOWN_VOICE_EXAMPLES)}）"
        )
    if not MING_VOICE_PATTERN.match(voice):
        raise invalid(
            f"未知音色 “{voice[:64]}”：可用 auto、design，"
            f"或形如 {'、'.join(KNOWN_VOICE_EXAMPLES)} 的内置音色名"
        )
    return voice


def parse_speech_request(data: Any) -> SpeechRequest:
    """校验原始 JSON 对象；任何不合格字段都抛 `ApiError`（400）。"""
    if not isinstance(data, dict):
        raise invalid("请求体必须是 JSON 对象")

    input_text = _string(data, "input")
    if not input_text.strip():
        raise invalid("input 必填，去除首尾空白后不能为空")
    input_text = _bounded_text(input_text, "input", 1, MAX_INPUT_CODEPOINTS)

    voice = _normalize_voice(_string(data, "voice", VOICE_AUTO))

    language = _string(data, "language", "auto").strip() or "auto"
    if language not in LANGUAGES:
        raise invalid(
            "language 只接受 auto、zh、en、de、es、fr、ko、ja、sichuanese、cantonese"
        )

    response_format = (
        _string(data, "response_format", "wav").strip().lower() or "wav"
    )
    if response_format not in SUPPORTED_FORMATS:
        raise invalid("response_format 只支持 wav 和 pcm")

    speed = _number(data, "speed", 1.0)
    if not 0.5 <= speed <= 2.0:
        raise invalid("speed 范围是 0.5~2.0")

    pitch = _integer(data, "pitch", 0)
    if not -12 <= pitch <= 12:
        raise invalid("pitch 范围是 -12~12")

    volume = _number(data, "volume", 1.0)
    if not 0.5 <= volume <= 2.0:
        raise invalid("volume 范围是 0.5~2.0")

    emotion = _string(data, "emotion")
    if emotion.strip():
        emotion = _bounded_text(emotion, "emotion", 1, MAX_EMOTION_CODEPOINTS)
    else:
        emotion = ""

    instructions = _string(data, "instructions")
    if instructions.strip():
        instructions = _bounded_text(
            instructions, "instructions", 1, MAX_INSTRUCTIONS_CODEPOINTS
        )
    else:
        instructions = ""

    reference_audio = _normalize_reference_audio(
        _string(data, "reference_audio")
    )
    reference_text = _string(data, "reference_text")
    if reference_text.strip():
        reference_text = _bounded_text(
            reference_text, "reference_text", 1, MAX_REFERENCE_TEXT_CODEPOINTS
        )
    else:
        reference_text = ""
    if bool(reference_audio) != bool(reference_text):
        raise invalid("reference_audio 和 reference_text 必须成对出现")

    task = _string(data, "task", "auto").strip().lower() or "auto"
    if task not in TASKS:
        raise invalid(
            "task 只接受 auto、tts、freeform、voice_design、multilingual、"
            "basic、emotion、dialect、ip"
        )

    seed_value = _field(data, "seed")
    if seed_value is None:
        seed = secrets.randbelow(MAX_SEED + 1)
    else:
        seed = _integer(data, "seed", 0)
        if not 0 <= seed <= MAX_SEED:
            raise invalid("seed 范围是 0~2147483647")

    stream_value = _field(data, "stream")
    if stream_value is None:
        stream = False
    elif isinstance(stream_value, bool):
        stream = stream_value
    else:
        raise invalid("字段 stream 必须是布尔值")
    if stream:
        raise invalid("v1 暂不支持流式音频，请移除 stream 或设为 false")

    model_value = _field(data, "model")
    if model_value is None:
        model = "Ming-3.0-tts"
    elif isinstance(model_value, str):
        model = model_value
    else:
        raise invalid("字段 model 必须是字符串")

    return SpeechRequest(
        model=model,
        input=input_text,
        voice=voice,
        language=language,
        response_format=response_format,
        speed=speed,
        pitch=pitch,
        volume=volume,
        emotion=emotion,
        instructions=instructions,
        reference_audio=reference_audio,
        reference_text=reference_text,
        task=task,
        seed=seed,
        stream=stream,
    )
