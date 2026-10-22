"""Ming-3.0-tts 命令行入口（UC-02）。

参数校验、任务解析与合成全部复用 API 同一套模块，不写第二套实现（BR-09）。
标准输出只放输出文件绝对路径，日志与错误写标准错误。
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from runtimes.ming_tts import audio
from runtimes.ming_tts.audio import ReferenceAudioError, inspect_reference
from runtimes.ming_tts.env_check import DependencyError, check_environment
from runtimes.ming_tts.errors import ApiError
from runtimes.ming_tts.schema import SUPPORTED_FORMATS, parse_speech_request
from runtimes.ming_tts.synth import SynthesisError, synthesize
from runtimes.ming_tts.tasks import resolve_task

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, "models", "ming-tts", "8bit")
DEFAULT_OUTPUT_DIR = Path("output")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger("runtimes.ming_tts.cli")


class UsageError(RuntimeError):
    """参数错误，退出码 2。"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m runtimes.ming_tts.cli",
        description="用 Ming-3.0-tts 合成语音并写入文件",
    )
    parser.add_argument("--text", required=True, help="合成文本，1~1000 个 Unicode 码点")
    parser.add_argument("--output", help="输出文件，扩展名 .wav 或 .pcm")
    parser.add_argument("--format", dest="response_format", type=str.lower, choices=SUPPORTED_FORMATS)
    parser.add_argument("--voice", default="auto", help="auto、design 或内置音色名")
    parser.add_argument("--language", default="auto", help="语言，默认 auto")
    parser.add_argument("--task", default="auto", help="任务模式，默认 auto")
    parser.add_argument("--ref-audio", dest="ref_audio", help="参考音频路径，WAV 或 FLAC")
    parser.add_argument("--ref-text", dest="ref_text", help="参考音频的逐字转录")
    parser.add_argument("--instruct", dest="instructions", help="自由指令或声音设计描述")
    parser.add_argument("--emotion", help="情绪，最多 32 个码点")
    parser.add_argument("--speed", type=float, help="语速，0.5~2.0，默认 1.0")
    parser.add_argument("--pitch", type=int, help="音高，-12~12，默认 0")
    parser.add_argument("--volume", type=float, help="音量，0.5~2.0，默认 1.0")
    parser.add_argument("--cfg", type=float, help="CFG scale，1.0~5.0，默认 2.0")
    parser.add_argument("--sigma", type=float, help="采样噪声，0~1，默认 0.25")
    parser.add_argument("--seed", type=int, help="随机种子，默认随机")
    return parser


def _resolve_output(
    output: Optional[str], response_format: Optional[str]
) -> Tuple[Path, str]:
    """按 BR-08 决定输出路径与格式，冲突与未知扩展名都是参数错误。"""
    if output:
        path = Path(output)
        extension = path.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_FORMATS:
            raise UsageError("--output 的扩展名必须是 .wav 或 .pcm")
        if response_format and response_format != extension:
            raise UsageError("--format 与 --output 的扩展名冲突")
        return path, extension

    chosen = response_format or "wav"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"ming-tts-{timestamp}.{chosen}", chosen


def _load_reference(path_value: str) -> str:
    """读取参考音频并转成 base64，交给 schema 与 audio 的同一套校验。"""
    path = Path(path_value)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UsageError(f"无法读取参考音频：{path}") from exc
    try:
        inspect_reference(data)
    except ReferenceAudioError as exc:
        raise UsageError(str(exc)) from exc
    return base64.b64encode(data).decode("ascii")


def _build_payload(args: argparse.Namespace, response_format: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "input": args.text,
        "voice": args.voice,
        "language": args.language,
        "task": args.task,
        "response_format": response_format,
    }
    optional = {
        "instructions": args.instructions,
        "emotion": args.emotion,
        "speed": args.speed,
        "pitch": args.pitch,
        "volume": args.volume,
        "cfg": args.cfg,
        "sigma": args.sigma,
        "seed": args.seed,
    }
    payload.update({key: value for key, value in optional.items() if value is not None})

    if args.ref_audio:
        payload["reference_audio"] = _load_reference(args.ref_audio)
        payload["reference_text"] = args.ref_text
    elif args.ref_text:
        payload["reference_text"] = args.ref_text
    return payload


def _write_output(path: Path, data: bytes) -> None:
    """目录不存在就创建；创建或写入失败都是运行错误（UC-02 5a）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise RuntimeError(f"写入输出文件失败：{path}（{type(exc).__name__}）") from exc


def run(args: argparse.Namespace) -> Path:
    output_path, response_format = _resolve_output(args.output, args.response_format)
    payload = _build_payload(args, response_format)

    # 参数校验先于任何重依赖导入，保证用法错误快速返回 2
    try:
        request = parse_speech_request(payload)
        task = resolve_task(request)
    except ApiError as exc:
        raise UsageError(exc.message) from exc

    try:
        report = check_environment()
    except DependencyError as exc:
        raise RuntimeError(f"环境自检失败：{exc}") from exc
    logger.debug("环境：%s", report.format())

    model_path = os.environ.get("MING_TTS_MODEL_PATH", DEFAULT_MODEL_PATH)
    if not os.path.isdir(model_path):
        raise RuntimeError(
            f"没有找到语音合成模型：{model_path}，请先运行 ./scripts/setup_ming_tts.sh"
        )

    from mlx_audio.tts.utils import load_model

    logger.info("加载权重：%s", model_path)
    try:
        model = load_model(model_path)
    except Exception as exc:  # noqa: BLE001 - 权重损坏的异常类型不固定
        raise RuntimeError(f"权重加载失败：{type(exc).__name__}") from exc

    reference_path = Path(args.ref_audio) if args.ref_audio else None
    try:
        result = synthesize(model, request, task, reference_path)
    except SynthesisError as exc:
        raise RuntimeError(f"合成失败：{exc}") from exc

    data = audio.encode_wav(result.pcm) if response_format == "wav" else result.pcm
    _write_output(output_path, data)
    logger.info(
        "合成完成：task=%s，seed=%s，音频 %.2f 秒，输出 %s",
        task.model_task,
        request.seed,
        result.duration,
        output_path,
    )
    return output_path


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format=LOG_FORMAT)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        path = run(args)
    except UsageError as exc:
        print(f"参数错误：{exc}", file=sys.stderr)
        return EXIT_USAGE
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_RUNTIME

    print(path.resolve())
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
