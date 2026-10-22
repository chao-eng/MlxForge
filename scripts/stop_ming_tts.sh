#!/usr/bin/env bash
# 停止 start_ming_tts.sh --daemon 拉起的后台服务
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT/run/ming-tts.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "没有 PID 文件，服务可能没在后台运行。前台启动的请直接 Ctrl-C。" >&2
  exit 1
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "进程已不存在，PID 文件已清理。"
  exit 0
fi

# 系统复用 PID 时别误杀，确认命令对得上再动手
if ! ps -p "$PID" -o command= | grep -q "runtimes.ming_tts.app:create_app"; then
  rm -f "$PID_FILE"
  echo "PID ${PID} 不是 Ming-3.0-tts 服务，已清理 PID 文件。" >&2
  exit 1
fi

kill -TERM "$PID"
# uvicorn 收到 SIGTERM 会走优雅退出，给它 10 秒
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done

if kill -0 "$PID" 2>/dev/null; then
  echo "进程 ${PID} 10 秒内没退出，请手动检查。" >&2
  exit 1
fi

rm -f "$PID_FILE"
echo "已停止，PID ${PID}。"
