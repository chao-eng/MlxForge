"""Ming-3.0-tts 权重的下载、校验与原子替换。

由 scripts/setup_ming_tts.sh 调用，也可单独执行 `--check` 复核现有权重。
ModelScope 接口不返回文件 SHA-256，因此首次下载后把本地计算的哈希写入
`.checksums`：它只能证明后续文件与首次下载一致，不能证明来源可信。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

DEFAULT_MODEL_ID = "bujidc/mlx-community_Ming-3.0-tts-0.5B-8bit"
DEFAULT_HF_MODEL_ID = "mlx-community/Ming-3.0-tts-0.5B-8bit"
# 不可变 revision，换权重必须同时更新这里与 PRD 附录 A-3
DEFAULT_REVISION = "049da49260b32e19fe8336ecd9b38a89f490dc1d"

REVISION_FILE = ".revision"
CHECKSUM_FILE = ".checksums"
MODEL_FILE = "model.safetensors"
MODEL_INDEX = "model.safetensors.index.json"

# BR-05：这些文件缺一不可，其余文件不参与校验
REQUIRED_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "special_tokens_map.json",
    "added_tokens.json",
    "LICENSE",
)
# campplus.safetensors 是 CAM++ 说话人嵌入，当前 MLX 转换版未使用，缺失只警告
OPTIONAL_FILES = ("campplus.safetensors",)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_files(root: Path) -> list[Path]:
    """列出参与校验和记录的文件，排除脚本自己写入的元数据。"""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name not in {REVISION_FILE, CHECKSUM_FILE}
    )


def write_checksums(root: Path) -> None:
    lines = [f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in data_files(root)]
    (root / CHECKSUM_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_checksums(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    text = (root / CHECKSUM_FILE).read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        result[name.strip()] = digest.strip()
    return result


def missing_required(root: Path) -> list[str]:
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    has_weights = (root / MODEL_FILE).is_file() or (
        (root / MODEL_INDEX).is_file() and any(root.glob("model-*.safetensors"))
    )
    if not has_weights:
        missing.append(f"{MODEL_FILE}（或分片加 {MODEL_INDEX}）")
    if not (root / REVISION_FILE).is_file():
        missing.append(REVISION_FILE)
    return missing


def verify(target: Path, revision: str) -> list[str]:
    """校验权重的必需文件、revision 与逐文件校验和，返回问题列表。"""
    if not target.is_dir():
        return [f"权重目录不存在：{target}"]

    problems = [f"缺少 {name}" for name in missing_required(target)]

    revision_path = target / REVISION_FILE
    if revision_path.is_file():
        recorded_revision = revision_path.read_text(encoding="utf-8").strip()
        if recorded_revision != revision:
            problems.append(f"revision 不一致：记录 {recorded_revision or '空'}，期望 {revision}")

    if not (target / CHECKSUM_FILE).is_file():
        problems.append(f"缺少 {CHECKSUM_FILE}")
    else:
        for name, expected in read_checksums(target).items():
            path = target / name
            if not path.is_file():
                problems.append(f"校验和记录的文件不存在：{name}")
            elif sha256_file(path) != expected:
                problems.append(f"校验和不匹配：{name}")

    for name in OPTIONAL_FILES:
        if not (target / name).is_file():
            print(f"警告：缺少可选文件 {name}，克隆相关能力可能受限", file=sys.stderr)
    return problems


def download(model_id: str, revision: str, staging: Path, source: str) -> None:
    """下载到临时目录；已有同名文件会从断点继续。"""
    staging.mkdir(parents=True, exist_ok=True)
    if source == "modelscope":
        from modelscope import snapshot_download

        snapshot_download(model_id, revision=revision, local_dir=str(staging))
        return
    from huggingface_hub import snapshot_download as hf_snapshot_download

    hf_snapshot_download(repo_id=model_id, revision=revision, local_dir=str(staging))


def swap_into_place(staging: Path, target: Path) -> None:
    """把下载完成的目录原子换到目标位置，失败时恢复旧权重。"""
    backup: Path | None = None
    if target.exists():
        backup = target.with_name(f"{target.name}.old-{int(time.time())}")
        target.rename(backup)
    try:
        staging.rename(target)
    except OSError:
        if backup is not None:
            backup.rename(target)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def install(
    target: Path,
    model_id: str,
    revision: str,
    source: str,
    force: bool,
) -> int:
    if not force:
        problems = verify(target, revision)
        if not problems:
            print(f"权重已就绪，跳过下载：{target}")
            return 0
        if target.exists():
            print("现有权重不满足要求，重新下载：", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)

    staging = target.parent / f".{target.name}.download"
    print(f"下载权重 {model_id}@{revision} -> {staging}")
    try:
        download(model_id, revision, staging, source)
    except Exception as exc:  # 网络或仓库异常，保留已下载分片以便续传
        print(f"下载失败：{exc}", file=sys.stderr)
        print(
            "可从 Hugging Face 的 mlx-community/Ming-3.0-tts-0.5B-8bit 手动下载，"
            f"放入 {staging} 后重跑本脚本；已下载的部分会从断点继续。",
            file=sys.stderr,
        )
        return 1

    missing = [name for name in REQUIRED_FILES if not (staging / name).is_file()]
    if missing:
        print(f"下载结果缺少必需文件：{', '.join(missing)}", file=sys.stderr)
        print(f"临时目录 {staging} 已保留，重跑可继续下载。", file=sys.stderr)
        return 1

    write_checksums(staging)
    (staging / REVISION_FILE).write_text(revision, encoding="utf-8")

    problems = verify(staging, revision)
    if problems:
        print("下载结果校验失败，保留原有权重：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    swap_into_place(staging, target)
    print(f"权重已就绪：{target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ming-3.0-tts 权重下载与校验")
    parser.add_argument("--model-dir", required=True, help="权重目标目录")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID, help="权重仓库 ID")
    parser.add_argument("--revision", default=DEFAULT_REVISION, help="锁定的权重 revision")
    parser.add_argument(
        "--source",
        choices=("modelscope", "huggingface"),
        default="modelscope",
        help="下载来源，默认 ModelScope",
    )
    parser.add_argument("--check", action="store_true", help="只校验现有权重，不下载")
    parser.add_argument("--force", action="store_true", help="忽略现有权重强制重新下载")
    args = parser.parse_args(argv)

    target = Path(args.model_dir).expanduser().resolve()
    if args.check:
        problems = verify(target, args.revision)
        if problems:
            print("权重校验失败：", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"权重校验通过：{target}")
        return 0

    model_id = DEFAULT_HF_MODEL_ID if args.source == "huggingface" else args.model_id
    return install(target, model_id, args.revision, args.source, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
