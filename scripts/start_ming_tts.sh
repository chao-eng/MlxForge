#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/envs/ming-tts/bin/python"
HOST="127.0.0.1"
PORT="8000"
MLX_CACHE_LIMIT_MB=""

usage() {
  cat <<'EOF'
用法：./scripts/start_ming_tts.sh [--host 127.0.0.1] [--port 8000] [--mlx-cache-limit-mb 512]

--mlx-cache-limit-mb 限制 MLX 缓存池大小，默认 512，0 表示禁用缓存。
默认只监听本机。服务没有鉴权，开放局域网必须同时设置 MING_TTS_ALLOW_REMOTE=1。
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      HOST="${2:?--host 需要参数}"
      shift 2
      ;;
    --host=*)
      HOST="${1#*=}"
      shift
      ;;
    --port)
      PORT="${2:?--port 需要参数}"
      shift 2
      ;;
    --port=*)
      PORT="${1#*=}"
      shift
      ;;
    --mlx-cache-limit-mb)
      MLX_CACHE_LIMIT_MB="${2:?--mlx-cache-limit-mb 需要参数}"
      shift 2
      ;;
    --mlx-cache-limit-mb=*)
      MLX_CACHE_LIMIT_MB="${1#*=}"
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

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "端口不合法：$PORT" >&2
  exit 2
fi

if [ -n "$MLX_CACHE_LIMIT_MB" ]; then
  if ! [[ "$MLX_CACHE_LIMIT_MB" =~ ^[0-9]+$ ]]; then
    echo "缓存上限不合法：$MLX_CACHE_LIMIT_MB" >&2
    exit 2
  fi
  export MING_TTS_MLX_CACHE_LIMIT_MB="$MLX_CACHE_LIMIT_MB"
fi

if [ ! -x "$PYTHON" ]; then
  echo "环境不存在，请先运行 ./scripts/setup_ming_tts.sh" >&2
  exit 1
fi

# 启动前复核依赖版本，0.6.0 及更早的 mlx-audio 会念错词
if ! (cd "$ROOT" && "$PYTHON" -m runtimes.ming_tts.env_check); then
  echo "运行环境校验未通过，请重跑 ./scripts/setup_ming_tts.sh" >&2
  exit 1
fi

CHECK_HOST="$HOST"
case "$CHECK_HOST" in
  0.0.0.0|::) CHECK_HOST="127.0.0.1" ;;
esac

if "$PYTHON" - "$CHECK_HOST" "$PORT" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)
try:
    busy = sock.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0
finally:
    sock.close()
raise SystemExit(0 if busy else 1)
PY
then
  echo "端口 $PORT 已被占用，请换一个端口或先停止占用进程。" >&2
  exit 1
fi

# BR-86：非回环地址必须显式授权，否则直接失败，不静默降级
case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [ "${MING_TTS_ALLOW_REMOTE:-}" != "1" ]; then
      echo "拒绝监听 ${HOST}：服务没有鉴权，开放远程访问必须显式授权。" >&2
      echo "确认网络环境后这样启动：MING_TTS_ALLOW_REMOTE=1 ./scripts/start_ming_tts.sh --host ${HOST}" >&2
      exit 1
    fi
    echo "警告：服务没有鉴权，当前监听 ${HOST}，同网段设备都可以访问。" >&2
    ;;
esac

cd "$ROOT"
# BR-13：模型权重与采样噪声都是进程内状态，只允许单 worker
exec "$PYTHON" -m uvicorn runtimes.ming_tts.app:create_app \
  --factory \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1
