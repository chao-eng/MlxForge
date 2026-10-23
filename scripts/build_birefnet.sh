#!/usr/bin/env bash
set -euo pipefail

# 构建 BiRefNet Swift 运行时，并把产物落到清单约定的路径。
#
# 为什么需要这一层：
# 1. 上游 mlx-swift-BiRefNet 也声明了名为 birefnet-cli 的可执行产物，
#    直接叫同名会让两个产物写到同一路径互相覆盖，所以本包产物用唯一名字，
#    构建后软链成 .build/release/birefnet-cli 和 birefnet-server。
# 2. SwiftPM 的 native 构建不产出 MLX 的 Metal 内核，必须再跑 build_metallib.sh。
#
# 用法：scripts/build_birefnet.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT/runtimes/birefnet"
BIN_DIR="$RUNTIME_DIR/.build/release"

cd "$RUNTIME_DIR"

# 只构建本包的两个产物，避免顺带构建上游同名可执行文件
swift build -c release --product birefnet-matte-cli
swift build -c release --product birefnet-matte-server

ln -sfn birefnet-matte-cli "$BIN_DIR/birefnet-cli"
ln -sfn birefnet-matte-server "$BIN_DIR/birefnet-server"

"$ROOT/scripts/build_metallib.sh" "$RUNTIME_DIR"

test -x "$BIN_DIR/birefnet-cli"
test -x "$BIN_DIR/birefnet-server"
test -s "$BIN_DIR/mlx.metallib"
echo "构建完成：$BIN_DIR/birefnet-cli、birefnet-server、mlx.metallib"
