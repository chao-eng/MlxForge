"""参考音频校验与输出编码（BR-24、BR-41）。

参考音频只解析容器头，不做音频解码；解码由推理 worker 在串行队列中完成，
避免在事件循环里执行重 CPU 操作（BR-98）。
"""

from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass

import numpy as np

from runtimes.ming_tts.schema import (
    MAX_REFERENCE_AUDIO_BYTES,
    MAX_REFERENCE_CHANNELS,
    MAX_REFERENCE_SAMPLE_RATE,
    MAX_REFERENCE_SECONDS,
    MIN_REFERENCE_SAMPLE_RATE,
    MIN_REFERENCE_SECONDS,
)

SAMPLE_RATE = 44100
BITS_PER_SAMPLE = 16
CHANNELS = 1


class ReferenceAudioError(ValueError):
    """参考音频不合格，调用方应返回 400。"""


@dataclass(frozen=True)
class ReferenceInfo:
    container: str
    sample_rate: int
    channels: int
    duration: float
    pcm16_bytes: int


def inspect_reference(data: bytes) -> ReferenceInfo:
    """读取 WAV/FLAC 头部并校验 BR-24 的格式、时长、采样率、声道与体积。"""
    if data[:4] == b"RIFF":
        info = _inspect_wav(data)
    elif data[:4] == b"fLaC":
        info = _inspect_flac(data)
    else:
        raise ReferenceAudioError("参考音频只支持 WAV 或 FLAC 格式")

    if info.channels < 1 or info.channels > MAX_REFERENCE_CHANNELS:
        raise ReferenceAudioError(
            f"参考音频必须是单声道或双声道，当前 {info.channels} 个声道"
        )
    if not MIN_REFERENCE_SAMPLE_RATE <= info.sample_rate <= MAX_REFERENCE_SAMPLE_RATE:
        raise ReferenceAudioError(
            "参考音频采样率必须在 16kHz~48kHz 之间，"
            f"当前 {info.sample_rate}Hz"
        )
    if not MIN_REFERENCE_SECONDS <= info.duration <= MAX_REFERENCE_SECONDS:
        raise ReferenceAudioError(
            f"参考音频时长必须在 5~30 秒之间，当前 {info.duration:.2f} 秒"
        )
    if info.pcm16_bytes > MAX_REFERENCE_AUDIO_BYTES:
        raise ReferenceAudioError("参考音频解码后不能超过 10MB")
    return info


def _inspect_wav(data: bytes) -> ReferenceInfo:
    if len(data) < 12 or data[8:12] != b"WAVE":
        raise ReferenceAudioError("参考音频不是有效的 WAV 文件")

    position = 12
    fmt: tuple[int, int, int, int] | None = None  # 声道、采样率、块对齐、位深
    data_size: int | None = None
    while position + 8 <= len(data):
        chunk_id = data[position : position + 4]
        size = struct.unpack("<I", data[position + 4 : position + 8])[0]
        body = position + 8
        if chunk_id == b"fmt ":
            if size < 16 or body + 16 > len(data):
                raise ReferenceAudioError("参考音频不是有效的 WAV 文件")
            audio_format, channels, sample_rate, _, block_align, bits = (
                struct.unpack("<HHIIHH", data[body : body + 16])
            )
            # 1=PCM、3=IEEE float、0xFFFE=WAVE_FORMAT_EXTENSIBLE
            if audio_format not in (1, 3, 0xFFFE):
                raise ReferenceAudioError("参考音频只支持未压缩的 WAV")
            fmt = (channels, sample_rate, block_align, bits)
        elif chunk_id == b"data":
            data_size = size
        position = body + size + (size & 1)

    if fmt is None or data_size is None:
        raise ReferenceAudioError("参考音频缺少 WAV 格式信息或音频数据")
    channels, sample_rate, block_align, _ = fmt
    if channels <= 0 or sample_rate <= 0 or block_align <= 0:
        raise ReferenceAudioError("参考音频不是有效的 WAV 文件")
    if data_size == 0xFFFFFFFF or data_size > len(data):
        raise ReferenceAudioError("参考音频数据不完整")

    frames = data_size // block_align
    duration = frames / sample_rate
    return ReferenceInfo(
        container="wav",
        sample_rate=sample_rate,
        channels=channels,
        duration=duration,
        pcm16_bytes=frames * channels * 2,
    )


def _inspect_flac(data: bytes) -> ReferenceInfo:
    position = 4
    if position + 4 > len(data):
        raise ReferenceAudioError("参考音频不是有效的 FLAC 文件")
    header = data[position]
    block_type = header & 0x7F
    length = int.from_bytes(data[position + 1 : position + 4], "big")
    body = position + 4
    if block_type != 0 or length < 34 or body + 34 > len(data):
        raise ReferenceAudioError("参考音频不是有效的 FLAC 文件")

    block = data[body : body + 34]
    packed = int.from_bytes(block[10:18], "big")
    sample_rate = (packed >> 44) & 0xFFFFF
    channels = ((packed >> 41) & 0x7) + 1
    total_samples = packed & ((1 << 36) - 1)
    if sample_rate <= 0 or total_samples <= 0:
        raise ReferenceAudioError("参考音频不是有效的 FLAC 文件")
    return ReferenceInfo(
        container="flac",
        sample_rate=sample_rate,
        channels=channels,
        duration=total_samples / sample_rate,
        pcm16_bytes=total_samples * channels * 2,
    )


TRIM_FRAME_SECONDS = 0.03
TRIM_HOP_SECONDS = 0.01
TRIM_RELATIVE_THRESHOLD = 0.04
TRIM_MIN_THRESHOLD = 0.004
TRIM_TAIL_SECONDS = 0.2
TRIM_FADE_SECONDS = 0.02


def trim_trailing_noise(
    samples: np.ndarray, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """裁掉尾部的低电平噪声，保留一段自然收尾。

    stop head 偶尔晚于语音内容结束才触发，多出来的 latent 会被声码器还原成
    持续的低电平噪声，听感像「电流声」。mlx-audio 自带的尾静音裁剪用 1e-3
    绝对门限，挡不住 2e-3 量级的噪声，所以在运行时按相对门限再裁一次。
    """
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    frame = max(1, int(sample_rate * TRIM_FRAME_SECONDS))
    hop = max(1, int(sample_rate * TRIM_HOP_SECONDS))
    keep = int(sample_rate * TRIM_TAIL_SECONDS)
    fade = min(int(sample_rate * TRIM_FADE_SECONDS), x.size)
    if x.size < frame + hop:
        return x

    windows = np.lib.stride_tricks.sliding_window_view(x, frame)[::hop]
    energy = np.abs(windows).mean(axis=1)
    # 用 99 分位而不是最大值，避免单个爆点把门限抬高
    threshold = max(
        float(np.percentile(energy, 99)) * TRIM_RELATIVE_THRESHOLD,
        TRIM_MIN_THRESHOLD,
    )
    loud = np.nonzero(energy > threshold)[0]
    if loud.size == 0:
        # 整段都没有明显有声段，不做裁剪，交给上层报错或原样输出
        return x

    end = int(loud[-1]) * hop + frame + keep
    if end >= x.size:
        return x
    trimmed = x[:end].copy()
    ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    trimmed[-fade:] *= ramp
    return trimmed


def encode_pcm(samples: np.ndarray) -> bytes:
    """把 [-1, 1] 的浮点波形转成 16-bit 小端单声道 PCM。"""
    clipped = np.clip(np.asarray(samples, dtype=np.float32).reshape(-1), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def encode_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(BITS_PER_SAMPLE // 8)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)
    return buffer.getvalue()


def duration_seconds(pcm: bytes) -> float:
    return len(pcm) / (SAMPLE_RATE * BITS_PER_SAMPLE // 8 * CHANNELS)
