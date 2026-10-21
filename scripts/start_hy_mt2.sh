#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/envs/hy-mt2/bin/python"
HOST="127.0.0.1"
PORT="8000"

usage() {
  cat <<'EOF'
用法：./scripts/start_hy_mt2.sh [--host 127.0.0.1] [--port 8000]

默认只监听本机。服务没有鉴权，改成 0.0.0.0 前先确认网络环境。
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

if [ ! -x "$PYTHON" ]; then
  echo "环境不存在，请先运行 ./scripts/setup_hy_mt2.sh" >&2
  exit 1
fi

CHECK_HOST="$HOST"
if [ "$CHECK_HOST" = "0.0.0.0" ] || [ "$CHECK_HOST" = "::" ]; then
  CHECK_HOST="127.0.0.1"
fi

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

if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ]; then
  echo "警告：服务没有鉴权，当前监听 $HOST，同网段设备都可以访问。" >&2
fi

cd "$ROOT"
exec "$PYTHON" -m uvicorn runtimes.hy_mt2.app:create_app \
  --factory \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1
