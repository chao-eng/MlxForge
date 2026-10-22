#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/envs/ming-tts/bin/python"
HOST="127.0.0.1"
PORT="8000"
MLX_CACHE_LIMIT_MB=""
DAEMON=0
PID_FILE="$ROOT/run/ming-tts.pid"
LOG_FILE="$ROOT/logs/ming-tts.log"

# 启动过程带时间戳写到日志文件，前台运行也留一份，排查时能对上时间点
log() {
  local line
  line="$(date '+%Y-%m-%d %H:%M:%S') [start] $*"
  mkdir -p "$(dirname "$LOG_FILE")"
  printf '%s\n' "$line"
  printf '%s\n' "$line" >>"$LOG_FILE"
}

log_error() {
  local line
  line="$(date '+%Y-%m-%d %H:%M:%S') [start] $*"
  mkdir -p "$(dirname "$LOG_FILE")"
  printf '%s\n' "$line" >&2
  printf '%s\n' "$line" >>"$LOG_FILE"
}

usage() {
  cat <<'EOF'
用法：./scripts/start_ming_tts.sh [--host 127.0.0.1] [--port 8000] [--mlx-cache-limit-mb 512] [--daemon]

--mlx-cache-limit-mb 限制 MLX 缓存池大小，默认 512，0 表示禁用缓存。
--daemon 转到后台运行，关掉终端不退出，用 ./scripts/stop_ming_tts.sh 停止。
日志写到 logs/ming-tts.log，PID 写到 run/ming-tts.pid。
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
    --daemon)
      DAEMON=1
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
  log_error "环境不存在，请先运行 ./scripts/setup_ming_tts.sh"
  exit 1
fi

MODE="前台"
if [ "$DAEMON" -eq 1 ]; then
  MODE="后台"
fi
log "开始启动，模式=${MODE}，host=${HOST}，port=${PORT}，mlx_cache_limit_mb=${MLX_CACHE_LIMIT_MB:-默认}"
log "解释器 ${PYTHON}（$("$PYTHON" -V 2>&1)）"

# 启动前复核依赖版本，0.6.0 及更早的 mlx-audio 会念错词
if ! (cd "$ROOT" && "$PYTHON" -m runtimes.ming_tts.env_check); then
  log_error "运行环境校验未通过，请重跑 ./scripts/setup_ming_tts.sh"
  exit 1
fi

if [ "$DAEMON" -eq 1 ] && [ -f "$PID_FILE" ]; then
  RUNNING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$RUNNING_PID" ] && kill -0 "$RUNNING_PID" 2>/dev/null; then
    log_error "后台服务已在运行，PID ${RUNNING_PID}，先运行 ./scripts/stop_ming_tts.sh"
    exit 1
  fi
  log "PID 文件里的 ${RUNNING_PID:-空} 已失效，清理后继续"
  rm -f "$PID_FILE"
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
  log_error "端口 ${PORT} 已被占用，请换一个端口或先停止占用进程"
  exit 1
fi
log "端口 ${PORT} 可用"

# BR-86：非回环地址必须显式授权，否则直接失败，不静默降级
case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [ "${MING_TTS_ALLOW_REMOTE:-}" != "1" ]; then
      log_error "拒绝监听 ${HOST}：服务没有鉴权，开放远程访问必须显式授权"
      echo "确认网络环境后这样启动：MING_TTS_ALLOW_REMOTE=1 ./scripts/start_ming_tts.sh --host ${HOST}" >&2
      exit 1
    fi
    echo "警告：服务没有鉴权，当前监听 ${HOST}，同网段设备都可以访问。" >&2
    ;;
esac

cd "$ROOT"

if [ "$DAEMON" -eq 1 ]; then
  mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"
  # nohup 让它脱离当前终端，终端关掉也不收 SIGHUP
  nohup "$PYTHON" -m uvicorn runtimes.ming_tts.app:create_app \
    --factory \
    --host "$HOST" \
    --port "$PORT" \
    --workers 1 >>"$LOG_FILE" 2>&1 &
  SERVER_PID=$!
  echo "$SERVER_PID" >"$PID_FILE"
  # 起不来的话 uvicorn 会立刻退出，别留一个指向死进程的 PID 文件
  sleep 1
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    log_error "后台启动失败，PID ${SERVER_PID} 已退出，日志 ${LOG_FILE}"
    exit 1
  fi
  log "已后台运行，PID=${SERVER_PID}，日志 ${LOG_FILE}"
  echo "停止用 ./scripts/stop_ming_tts.sh"
  exit 0
fi

log "前台运行，PID=$$，按 Ctrl-C 停止"
# BR-13：模型权重与采样噪声都是进程内状态，只允许单 worker
exec "$PYTHON" -m uvicorn runtimes.ming_tts.app:create_app \
  --factory \
  --host "$HOST" \
  --port "$PORT" \
  --workers 1
