"""Ming-3.0-tts 运行环境自检，安装脚本与服务启动共用同一份判定。"""

from __future__ import annotations

import importlib
import platform
import sys
from dataclasses import dataclass
from importlib import metadata

# PR #1047 于 2026-10-19 合入 main，0.6.1 是首个包含该提交的 PyPI 发行版。
# 0.6.0 及更早版本的 Ming-3.0 prompt 契约有误，合成时会念错词。
MIN_MLX_AUDIO = (0, 6, 1)
PR_1047_MERGE_COMMIT = "3530c33a5f5412dfbd1ea70fece3d867b4860c0a"
REQUIRED_PYTHON = (3, 11)
# mlx-audio 0.6.1 把 mlx 精确锁在 0.32.4，混装后模型类与权重会不匹配
REQUIRED_MLX = "0.32.4"
# 这两个符号是 PR #1047 引入的 Ming-3.0 入口，缺失说明装到了旧版本
REQUIRED_SYMBOLS = (
    ("mlx_audio.tts.utils", "load_model"),
    ("mlx_audio.tts.models.bailingmm.bailingmm", "ming3_instruction"),
)


class DependencyError(RuntimeError):
    """运行环境不满足 Ming-3.0-tts 的依赖要求。"""


@dataclass(frozen=True)
class EnvironmentReport:
    python: str
    mlx_audio: str
    mlx: str
    transformers: str
    platform: str

    def format(self) -> str:
        return (
            f"Python {self.python} | mlx-audio {self.mlx_audio} | "
            f"mlx {self.mlx} | transformers {self.transformers} | {self.platform}"
        )


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError as exc:
        raise DependencyError(f"缺少依赖 {name}，请先运行 scripts/setup_ming_tts.sh") from exc


def _release(version: str) -> tuple[int, ...]:
    """取版本号前三段数字，忽略预发布后缀。"""
    parts: list[int] = []
    for chunk in version.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def check_environment() -> EnvironmentReport:
    """校验 Python、mlx-audio、mlx 与关键符号，不满足时抛 DependencyError。"""
    if sys.version_info[:2] != REQUIRED_PYTHON:
        raise DependencyError(
            f"需要 Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}，"
            f"当前为 {sys.version_info.major}.{sys.version_info.minor}"
        )

    mlx_audio = _distribution_version("mlx-audio")
    if _release(mlx_audio) < MIN_MLX_AUDIO:
        raise DependencyError(
            f"mlx-audio {mlx_audio} 不含 PR #1047（合入提交 "
            f"{PR_1047_MERGE_COMMIT}），需要 {'.'.join(map(str, MIN_MLX_AUDIO))} 或更高"
        )

    mlx = _distribution_version("mlx")
    if _release(mlx) != _release(REQUIRED_MLX):
        raise DependencyError(
            f"需要 mlx {REQUIRED_MLX}，当前为 {mlx}，请重新安装依赖"
        )
    transformers = _distribution_version("transformers")

    for module_name, symbol in REQUIRED_SYMBOLS:
        module = importlib.import_module(module_name)
        if not hasattr(module, symbol):
            raise DependencyError(f"{module_name} 缺少 {symbol}，依赖版本不匹配")

    return EnvironmentReport(
        python=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        mlx_audio=mlx_audio,
        mlx=mlx,
        transformers=transformers,
        platform=f"macOS {platform.mac_ver()[0]} {platform.machine()}",
    )


def main() -> None:
    try:
        report = check_environment()
    except DependencyError as exc:
        print(f"环境自检失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"环境自检通过：{report.format()}")


if __name__ == "__main__":
    main()
