#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/envs/ming-tts"
MODEL_DIR="$ROOT/models/ming-tts/8bit"
PYTHON="$ENV_DIR/bin/python"

usage() {
  cat <<'EOF'
用法：./scripts/setup_ming_tts.sh [--source modelscope|huggingface] [--check]

  --source   权重下载来源，默认 modelscope；modelscope 不可达时改用 huggingface
  --check    只校验现有环境与权重，不安装、不下载
EOF
}

SOURCE="modelscope"
CHECK_ONLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE="${2:?--source 需要参数}"
      shift 2
      ;;
    --source=*)
      SOURCE="${1#*=}"
      shift
      ;;
    --check)
      CHECK_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$SOURCE" in
  modelscope|huggingface) ;;
  *)
    echo "--source 只接受 modelscope 或 huggingface，当前为 $SOURCE" >&2
    exit 2
    ;;
esac

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "仅支持 Apple Silicon 的 macOS，当前为 $(uname -s) $(uname -m)" >&2
  exit 1
fi

if [ "$CHECK_ONLY" -eq 0 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "需要先安装 uv，参考 https://docs.astral.sh/uv/" >&2
    exit 1
  fi

  if [ ! -x "$PYTHON" ]; then
    if ! uv venv --python 3.11 "$ENV_DIR"; then
      echo "创建 Python 3.11 环境失败，请先安装 Python 3.11：uv python install 3.11" >&2
      exit 1
    fi
  fi

  # 依赖固定完整解析结果，安装脚本工作目录固定在仓库根目录，保证模块可导入
  if ! uv pip install --python "$PYTHON" -r "$ROOT/runtimes/ming_tts/requirements.txt"; then
    echo "依赖安装失败，已下载的缓存会保留，可重跑本脚本" >&2
    exit 1
  fi
fi

if [ ! -x "$PYTHON" ]; then
  echo "环境不存在，请先运行 ./scripts/setup_ming_tts.sh" >&2
  exit 1
fi

# 安装与启动共用同一份版本判定，不满足 PR #1047 时直接失败
if ! (cd "$ROOT" && "$PYTHON" -m runtimes.ming_tts.env_check); then
  echo "运行环境校验未通过，请检查 mlx-audio 版本" >&2
  exit 1
fi

if [ "$CHECK_ONLY" -eq 0 ]; then
  "$PYTHON" "$ROOT/scripts/ming_tts_weights.py" \
    --model-dir "$MODEL_DIR" \
    --source "$SOURCE"
else
  "$PYTHON" "$ROOT/scripts/ming_tts_weights.py" --model-dir "$MODEL_DIR" --check
fi

cat <<EOF

环境：$ENV_DIR
权重：$MODEL_DIR
下一步：
  ./scripts/start_ming_tts.sh --port 8000
EOF
