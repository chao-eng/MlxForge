#!/usr/bin/env bash
set -euo pipefail

# 为 Swift 运行时生成 MLX 需要的 mlx.metallib。
#
# 为什么需要这一步：SwiftPM 的 native 构建系统不编译 MLX 依赖里的 Metal 源码，
# 而 Xcode 26.2 的 `swift build --build-system swiftbuild` 又因 Metal 工具链定位
# 问题无法调起编译器，所以只能自己收集 mlx-swift 检出里的 .metal 编译成 metallib，
# 放到可执行文件同目录，运行期才找得到。
#
# 用法：
#   scripts/build_metallib.sh                 # 自动找 runtimes/* 下已 resolve 的 mlx-swift
#   scripts/build_metallib.sh runtimes/birefnet

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -ge 1 ]; then
  RUNTIME_DIR="$1"
  case "$RUNTIME_DIR" in
    /*) ;;
    *) RUNTIME_DIR="$ROOT/$RUNTIME_DIR" ;;
  esac
else
  # 只允许一个候选，避免把脚本变成隐式多模型构建器
  candidates=()
  for checkout in "$ROOT"/runtimes/*/.build/checkouts/mlx-swift; do
    [ -d "$checkout" ] && candidates+=("$(cd "$checkout/../.." && pwd)")
  done
  if [ "${#candidates[@]}" -eq 0 ]; then
    echo "没找到已 resolve 的 mlx-swift，请先执行 swift build -c release" >&2
    exit 1
  fi
  if [ "${#candidates[@]}" -gt 1 ]; then
    echo "发现多个 Swift 运行时，请显式指定目录：${candidates[*]}" >&2
    exit 1
  fi
  RUNTIME_DIR="${candidates[0]}"
fi

SRC_DIR="$RUNTIME_DIR/.build/checkouts/mlx-swift/Source/Cmlx/mlx-generated/metal"
OUT_DIR="$RUNTIME_DIR/.build/release"

if [ ! -d "$SRC_DIR" ]; then
  echo "缺少 Metal 源码：${SRC_DIR}（先执行 swift build -c release 拉取依赖）" >&2
  exit 1
fi

if [ ! -d "$OUT_DIR" ]; then
  echo "缺少构建产物目录：${OUT_DIR}（先执行 swift build -c release）" >&2
  exit 1
fi

# 用 xcrun 解析 metal，绕开 Xcode 自带 shim 的工具链定位 bug
if ! METAL="$(xcrun --sdk macosx -f metal 2>/dev/null)" || [ ! -x "$METAL" ]; then
  echo "找不到 Metal 编译器，先执行：xcodebuild -downloadComponent MetalToolchain" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

count=0
while IFS= read -r file; do
  name="$(printf '%s' "${file#"$SRC_DIR"/}" | sed 's|/|_|g; s|\.metal$||')"
  "$METAL" -O2 -c "$file" -o "$WORK_DIR/$name.air"
  count=$((count + 1))
done < <(find "$SRC_DIR" -name '*.metal' | sort)

if [ "$count" -eq 0 ]; then
  echo "在 $SRC_DIR 下没找到 .metal 源码" >&2
  exit 1
fi

"$METAL" -o "$WORK_DIR/mlx.metallib" "$WORK_DIR"/*.air

OUT_FILE="$OUT_DIR/mlx.metallib"
cp "$WORK_DIR/mlx.metallib" "$OUT_FILE"

size="$(stat -f%z "$OUT_FILE")"
if [ "$size" -le 0 ]; then
  echo "生成的 mlx.metallib 为空：$OUT_FILE" >&2
  exit 1
fi

echo "已生成 ${OUT_FILE}（${count} 个 Metal 源码，$((size / 1024)) KB）"
