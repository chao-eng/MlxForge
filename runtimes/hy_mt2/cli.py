"""Hy-MT2 命令行翻译入口。"""

from __future__ import annotations

import argparse
import logging
import os

from runtimes.hy_mt2.app import DEFAULT_IDLE_TIMEOUT, DEFAULT_MODEL_PATH, build_prompt
from runtimes.hy_mt2.model_manager import ModelManager


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Hy-MT2 翻译一段文本")
    parser.add_argument("--text", required=True, help="待翻译的原文")
    parser.add_argument("--target", default="中文", help="目标语言，默认中文")
    parser.add_argument("--max-tokens", type=int, default=1024, help="最大生成 token 数")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    manager = ModelManager(
        model_path=os.environ.get("HY_MT2_MODEL_PATH", DEFAULT_MODEL_PATH),
        idle_timeout=int(os.environ.get("HY_MT2_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)),
    )

    instruction = (
        f"Translate the following segment into {args.target}, "
        f"without additional explanation:\n\n{args.text}"
    )
    prompt = build_prompt(
        [{"role": "user", "content": instruction}],
        manager.tokenizer(),
    )
    print(manager.generate(prompt, max_tokens=args.max_tokens))


if __name__ == "__main__":
    main()
