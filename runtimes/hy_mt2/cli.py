"""Hy-MT2 命令行翻译入口。"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from runtimes.hy_mt2.app import DEFAULT_IDLE_TIMEOUT, DEFAULT_MODEL_PATH, build_prompt
from runtimes.hy_mt2.model_manager import ModelManager

MAX_TARGET_LENGTH = 32

# 官方支持语言表（含中文名、英文名、缩写），中文提示词要求使用中文语言名
_LANGUAGE_ROWS = [
    ("中文", "Chinese", "zh"),
    ("英语", "English", "en"),
    ("法语", "French", "fr"),
    ("葡萄牙语", "Portuguese", "pt"),
    ("西班牙语", "Spanish", "es"),
    ("日语", "Japanese", "ja"),
    ("土耳其语", "Turkish", "tr"),
    ("俄语", "Russian", "ru"),
    ("阿拉伯语", "Arabic", "ar"),
    ("韩语", "Korean", "ko"),
    ("泰语", "Thai", "th"),
    ("意大利语", "Italian", "it"),
    ("德语", "German", "de"),
    ("越南语", "Vietnamese", "vi"),
    ("马来语", "Malay", "ms"),
    ("印尼语", "Indonesian", "id"),
    ("菲律宾语", "Filipino", "tl"),
    ("印地语", "Hindi", "hi"),
    ("繁体中文", "Traditional Chinese", "zh-hant"),
    ("波兰语", "Polish", "pl"),
    ("捷克语", "Czech", "cs"),
    ("荷兰语", "Dutch", "nl"),
    ("高棉语", "Khmer", "km"),
    ("缅甸语", "Burmese", "my"),
    ("波斯语", "Persian", "fa"),
    ("古吉拉特语", "Gujarati", "gu"),
    ("乌尔都语", "Urdu", "ur"),
    ("泰卢固语", "Telugu", "te"),
    ("马拉地语", "Marathi", "mr"),
    ("希伯来语", "Hebrew", "he"),
    ("孟加拉语", "Bengali", "bn"),
    ("泰米尔语", "Tamil", "ta"),
    ("乌克兰语", "Ukrainian", "uk"),
    ("藏语", "Tibetan", "bo"),
    ("哈萨克语", "Kazakh", "kk"),
    ("蒙古语", "Mongolian", "mn"),
    ("维吾尔语", "Uyghur", "ug"),
    ("粤语", "Cantonese", "yue"),
]
_LANGUAGE_ALIASES = {
    alias.lower(): name
    for name, english, code in _LANGUAGE_ROWS
    for alias in (name, english, code)
}


def _positive_int(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 8192:
        raise argparse.ArgumentTypeError("max-tokens 必须在 1 到 8192 之间")
    return number


def _target(value: str) -> str:
    target = value.strip()
    if not target:
        raise argparse.ArgumentTypeError("target 不能为空")
    if "\n" in target or "\r" in target:
        raise argparse.ArgumentTypeError("target 不能包含换行")
    if len(target) > MAX_TARGET_LENGTH:
        raise argparse.ArgumentTypeError(f"target 不能超过 {MAX_TARGET_LENGTH} 个字符")
    # 中文提示词要求语言名也用中文，英文名和缩写统一换成官方中文名
    return _LANGUAGE_ALIASES.get(target.lower(), target)


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Hy-MT2 翻译一段文本")
    parser.add_argument("--text", required=True, help="待翻译的原文")
    parser.add_argument(
        "--target",
        default="中文",
        type=_target,
        help="目标语言，默认中文，支持官方语言表的中文名、英文名或缩写",
    )
    parser.add_argument(
        "--max-tokens",
        type=_positive_int,
        default=1024,
        help="最大生成 token 数，默认 1024",
    )
    args = parser.parse_args()

    if not args.text.strip():
        parser.error("text 不能为空")

    log_level = os.environ.get("HY_MT2_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        manager = ModelManager(
            model_path=os.environ.get("HY_MT2_MODEL_PATH", DEFAULT_MODEL_PATH),
            idle_timeout=int(
                os.environ.get("HY_MT2_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)
            ),
        )
        instruction = (
            f"将以下文本翻译为 {args.target}，"
            f"注意只需要输出翻译后的结果，不要额外解释：\n{args.text}"
        )
        prompt = build_prompt(
            [{"role": "user", "content": instruction}],
            manager.tokenizer(),
        )
        result = manager.generate(prompt, max_tokens=args.max_tokens)
    except Exception as exc:
        print(f"翻译失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(result.text)


if __name__ == "__main__":
    main()
