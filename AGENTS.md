# AGENTS.md

给在本仓库工作的编码代理看的约定。面向使用者的介绍在 [README.md](README.md)，两边各写各的，不要互相抄。

## 项目现状

仓库里现在有 Hy-MT2 运行时（`runtimes/hy_mt2/`）和单页 Web UI（`web/`），`server/` 还没开始。两个运行时都是 Python，Swift 运行时只有下面这套约定，还没有模型接入。`models/` 和 `envs/` 不入库。

## 目标

在 Apple Silicon 上提供一套原生 MLX 运行时。范围先收窄，先接 Hy-MT2 翻译和 Ming-3.0-tts 语音合成，其余模型后面再说。每个模型独立依赖环境，对外共用 HTTP API 和 Web UI。上游只提供 Swift 版 MLX 实现的模型，作为独立 Swift 运行时接入，不硬塞进 Python。

## 硬性约束

| 约束 | 说明 |
| --- | --- |
| 不用容器 | 只支持 macOS 原生运行，不写 Dockerfile，不依赖 Linux 环境 |
| 推理走 MLX | 不把 PyTorch 当推理后端，torch 只允许出现在音频编解码等必要环节；Swift 运行时用 mlx-swift |
| 复用现成推理实现 | Python 侧模型加载和生成走 mlx-lm 的 `load` / `generate`；Swift 侧优先复用 mlx-swift-examples 的实现，不自己写权重解析和采样循环 |
| Swift 运行时独立进程 | 上游只有 Swift 实现的模型用 SwiftPM 构建成独立可执行服务，实现同一套 `/v1` 接口，不经 Python 转发 |
| 接口兼容 OpenAI | 翻译服务保持 `/v1/chat/completions` 的请求与响应格式，已有客户端不改配置 |
| 权重不入库 | `models/` 下的文件一律不进 git |
| 环境不入库 | `envs/` 下的 venv 和 Swift 运行时的 `.build/` 不进 git |
| 不编数据 | 没实测过的延迟、吞吐、内存数字，不写进 README 或文档 |
| 单模型推进 | 一个模型跑通再动下一个，不并行开三个运行时 |

## 目标目录

```text
MlxForge/
├── models/                # 权重与转换产物，不进 git
├── envs/                  # 每个 Python 模型一个 venv，不进 git
├── runtimes/
│   ├── hy_mt2/
│   ├── ming_tts/
│   └── <swift 模型>/       # SwiftPM 工程：Package.swift + Sources/
├── server/                # 统一 API、模型调度
├── web/                   # Web UI
├── scripts/               # 建环境、转权重、压测
└── docs/
```

`runtimes/<name>/` 只放这个模型的加载、推理和预处理代码。跨模型共用的东西放 `server/`，两边不要互相 import。Python 运行时是 Python 包，Swift 运行时是 SwiftPM 工程，两者目录名同样与清单里的 `name` 一致。

`web/` 的前端工程约束单独写在 `web/AGENTS.md`，动前端代码前先读它。

## 环境隔离

- 每个 Python 运行时用 `uv venv` 建独立环境，路径为 `envs/<name>/`
- Python 依赖写进 `runtimes/<name>/requirements.txt` 或 `pyproject.toml`，锁文件一起提交
- Swift 运行时不建 venv，用 SwiftPM 管理依赖，`Package.resolved` 一起提交，`.build/` 和 `.swiftpm/` 不进 git
- 卸载就是把 `envs/<name>/`、`models/<name>/` 和 Swift 运行时的 `.build/` 删掉，不留全局状态
- 不要在系统 Python 里装模型依赖
- Swift 运行时不要提交 Xcode 工程文件，构建和运行统一走 `swift build` / `swift run`

## 清单驱动

调度器只读清单，不认识具体模型。接新模型就是加一个目录和一份清单，`server/` 不用动。

清单字段先按下面这套来，落地后以代码为准。

```toml
name = "hy-mt2"
runtime = "python"        # python | swift，省略时按 python 处理
python = "3.11"
entry = "runtimes.hy_mt2.app:create_app"
weights = "models/hy-mt2/4bit"
idle_timeout = 1200
```

Swift 运行时的清单把 `runtime` 写成 `swift`，用 `build` 描述构建命令，`entry` 指向构建出的可执行文件。

```toml
name = "<model>"
runtime = "swift"
build = "swift build -c release"
entry = "runtimes/<model>/.build/release/<target>"
weights = "models/<model>/<quant>"
idle_timeout = 1200
```

| 字段 | 用途 |
| --- | --- |
| `name` | 模型标识，与 `runtimes/` 下的目录名一致 |
| `runtime` | 运行时类型，`python` 或 `swift` |
| `python` | 建环境使用的 Python 版本，仅 Python 运行时需要 |
| `build` | 构建命令，仅 Swift 运行时需要 |
| `entry` | 启动入口：Python 是导入路径，Swift 是可执行文件路径 |
| `weights` | 权重目录，相对仓库根目录 |
| `idle_timeout` | 空闲多少秒后释放，0 表示常驻 |

## 调度器职责

- 常驻一个进程，按清单加载和卸载模型
- 按清单的 `runtime` 决定拉起方式：Python 导入 `entry`，Swift 先执行 `build` 再启动 `entry` 指向的可执行文件
- 空闲超时后释放内存，再次被调用时重新加载
- 卸载时先解除模型引用，再 `gc.collect()` 和 `mx.clear_cache()`，只删对象不清缓存，内存不会还回去
- 模型报告自己的内存占用，调度器据此决定要不要腾位置
- 不把 tokenizer、预处理、采样这些逻辑写进调度器

## API

统一挂在 `/v1` 下，路径沿用 OpenAI 的命名习惯。

```http
GET  /v1/models
POST /v1/chat/completions
POST /v1/audio/speech
GET  /health
```

翻译接口沿用 `chat.completions` 的格式，请求体里放 `messages`。现有实现的 `stream` 是先生成完整译文再切片下发，SSE 只是传输形式。要做逐 token 流式，得改 mlx-lm 的生成循环，单独评估。

- 错误响应统一成 `{"error": {"type": ..., "message": ...}}`
- Swift 运行时实现同一套路径、请求字段和错误格式，不另开一套接口
- 字段确定后先写进 `docs/api.md`，再同步 README
- 不为兼容旧字段保留废弃路径

## 编码约定

- Python 3.11 起，公开函数带类型标注
- Swift 公开类型和函数带类型标注，依赖走 SwiftPM
- 配置用 TOML，不用 YAML
- 日志走标准库 `logging`，不 print；Swift 侧用 `os.Logger`
- 注释用中文，解释为什么这么做，不复述代码
- 新增依赖前先确认 MLX 或标准库能不能解决

## 验证

- 所有性能结论必须在 Apple Silicon 上实测，记录芯片型号、内存大小和量化精度
- 改运行时时先跑通命令行入口，再接 API
- API 冒烟测试至少覆盖 `/health`、`/v1/models` 和一次 `chat.completions`，空闲释放可以把 `HY_MT2_IDLE_TIMEOUT` 调小后等一轮检查
- Swift 运行时按同样三项冒烟测试验收，首次运行先 `swift build -c release`，再启动清单里的可执行文件
- 验证三件事：冷启动耗时、空闲释放后内存是否归零、SSE 输出格式是否还能被 CalmBar 接受
- README 的状态表只在功能跑通后更新

## 不要做

- 不要在空目录里补假实现
- 不要把模型权重、日志、生成的音频提交进仓库
- 不要把 Swift 运行时的 `.build/`、`.swiftpm/` 和 Xcode 工程文件提交进仓库
- 不要为尚未存在的需求加抽象层
