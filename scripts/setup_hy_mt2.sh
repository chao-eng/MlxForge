#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/envs/hy-mt2"
MODEL_DIR="$ROOT/models/hy-mt2/4bit"
MODEL_ID="bujidc/mlx-community_Hy-MT2-1.8B-4bit"

if ! command -v uv >/dev/null 2>&1; then
  echo "需要先安装 uv，参考 https://docs.astral.sh/uv/"
  exit 1
fi

if [ ! -x "$ENV_DIR/bin/python" ]; then
  uv venv --python 3.11 "$ENV_DIR"
fi

uv pip install --python "$ENV_DIR/bin/python" -r "$ROOT/runtimes/hy_mt2/requirements.txt"

if [ ! -f "$MODEL_DIR/config.json" ]; then
  mkdir -p "$MODEL_DIR"
  "$ENV_DIR/bin/python" - "$MODEL_ID" "$MODEL_DIR" <<'PY'
import sys
from modelscope import snapshot_download

snapshot_download(sys.argv[1], local_dir=sys.argv[2])
PY
fi

echo "环境：$ENV_DIR"
echo "权重：$MODEL_DIR"
