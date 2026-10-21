#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/envs/hy-mt2"
MODEL_DIR="$ROOT/models/hy-mt2/4bit"
MODEL_ID="bujidc/mlx-community_Hy-MT2-1.8B-4bit"
REVISION="master"

if ! command -v uv >/dev/null 2>&1; then
  echo "需要先安装 uv，参考 https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [ ! -x "$ENV_DIR/bin/python" ]; then
  uv venv --python 3.11 "$ENV_DIR"
fi

uv pip install --python "$ENV_DIR/bin/python" -r "$ROOT/runtimes/hy_mt2/requirements.txt"

needs_download() {
  [ ! -f "$MODEL_DIR/config.json" ] && return 0
  [ ! -f "$MODEL_DIR/.revision" ] && return 0
  [ "$(cat "$MODEL_DIR/.revision")" != "$REVISION" ] && return 0
  return 1
}

if needs_download; then
  mkdir -p "$MODEL_DIR"
  "$ENV_DIR/bin/python" - "$MODEL_ID" "$MODEL_DIR" "$REVISION" <<'PY'
import sys

from modelscope import snapshot_download

snapshot_download(sys.argv[1], revision=sys.argv[3], local_dir=sys.argv[2])
PY
  printf '%s' "$REVISION" > "$MODEL_DIR/.revision"
fi

missing=()
[ -f "$MODEL_DIR/config.json" ] || missing+=("config.json")
[ -f "$MODEL_DIR/tokenizer.json" ] || [ -f "$MODEL_DIR/tokenizer.model" ] || missing+=("tokenizer 文件")
compgen -G "$MODEL_DIR/*.safetensors" >/dev/null || missing+=("*.safetensors")
[ -f "$MODEL_DIR/.revision" ] || missing+=(".revision")
[ -f "$MODEL_DIR/LICENSE.txt" ] || missing+=("LICENSE.txt")

if [ "${#missing[@]}" -gt 0 ]; then
  echo "权重目录缺少必需文件：${missing[*]}" >&2
  echo "请删除 $MODEL_DIR 后重新运行本脚本。" >&2
  exit 1
fi

echo "环境：$ENV_DIR"
echo "权重：$MODEL_DIR"
echo "revision：$REVISION"
