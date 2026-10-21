# AGENTS.md

给在本仓库工作的编码代理看的约定。面向使用者的介绍在 [README.md](README.md)，两边各写各的，不要互相抄。

## 项目现状

仓库里现在有 Hy-MT2 运行时（`runtimes/hy_mt2/`）和单页 Web UI（`web/`），`server/` 还没开始。`models/` 和 `envs/` 不入库。Hy-MT2 另有一套能跑的单模型服务，在 `~/HyMT2-Server`，部署文档在 CalmBar 仓库的 `doc/HyMT2部署/`。动 Hy-MT2 之前先读这两处，不要从零重写。

## 目标

在 Apple Silicon 上提供一套原生 MLX 运行时。范围先收窄，先接 Hy-MT2 翻译和 Ming-3.0-tts 语音合成，其余模型后面再说。每个模型独立依赖环境，对外共用 HTTP API 和 Web UI。

## 硬性约束

| 约束 | 说明 |
| --- | --- |
| 不用容器 | 只支持 macOS 原生运行，不写 Dockerfile，不依赖 Linux 环境 |
| 推理走 MLX | 不把 PyTorch 当推理后端，torch 只允许出现在音频编解码等必要环节 |
| 复用 mlx-lm | 模型加载和生成走 mlx-lm 的 `load` / `generate`，不自己写权重解析和采样循环 |
| 接口兼容 OpenAI | 翻译服务保持 `/v1/chat/completions` 的请求与响应格式，已有客户端不改配置 |
| 权重不入库 | `models/` 下的文件一律不进 git |
| 环境不入库 | `envs/` 下的 venv 不进 git |
| 不编数据 | 没实测过的延迟、吞吐、内存数字，不写进 README 或文档 |
| 单模型推进 | 一个模型跑通再动下一个，不并行开三个运行时 |

## 目标目录

```text
MlxForge/
├── models/                # 权重与转换产物，不进 git
├── envs/                  # 每个模型一个 venv，不进 git
├── runtimes/
│   ├── hy_mt2/
│   └── ming_tts/
├── server/                # 统一 API、模型调度
├── web/                   # Web UI
├── scripts/               # 建环境、转权重、压测
└── docs/
```

`runtimes/<name>/` 只放这个模型的加载、推理和预处理代码。跨模型共用的东西放 `server/`，两边不要互相 import。

`web/` 的前端工程约束单独写在 `web/AGENTS.md`，动前端代码前先读它。

## 环境隔离

- 每个运行时用 `uv venv` 建独立环境，路径为 `envs/<name>/`
- 依赖写进 `runtimes/<name>/requirements.txt` 或 `pyproject.toml`，锁文件一起提交
- 卸载就是把 `envs/<name>/` 和 `models/<name>/` 删掉，不留全局状态
- 不要在系统 Python 里装模型依赖

## 清单驱动

调度器只读清单，不认识具体模型。接新模型就是加一个目录和一份清单，`server/` 不用动。

清单字段先按下面这套来，落地后以代码为准。

```toml
name = "hy-mt2"
python = "3.11"
entry = "runtimes.hy_mt2.app:create_app"
weights = "models/hy-mt2/4bit"
idle_timeout = 1200
```

| 字段 | 用途 |
| --- | --- |
| `name` | 模型标识，与 `runtimes/` 下的目录名一致 |
| `python` | 建环境使用的 Python 版本 |
| `entry` | 启动入口，调度器按需拉起 |
| `weights` | 权重目录，相对仓库根目录 |
| `idle_timeout` | 空闲多少秒后释放，0 表示常驻 |

## 调度器职责

- 常驻一个进程，按清单加载和卸载模型
- 空闲超时后释放内存，再次被调用时重新加载
- 卸载时先解除模型引用，再 `gc.collect()` 和 `mx.clear_cache()`，只删对象不清缓存，内存不会还回去
- 模型报告自己的内存占用，调度器据此决定要不要腾位置
- 不把 tokenizer、预处理、采样这些逻辑写进调度器

## 参考实现

`~/HyMT2-Server` 里的单模型服务可以直接跑，关键信息如下。

- Python 3.11，venv 在 `runtime/venv`，依赖版本锁在 `requirements.txt`
- 权重来自 ModelScope 的 `bujidc/mlx-community_Hy-MT2-1.8B-4bit`，放在 `models/Hy-MT2-1.8B-4bit`
- `app/server.py` 的 `ModelManager` 负责加载、刷新活跃时间和空闲卸载，后台线程每 10 秒检查一次
- 推理过程用锁串行化，避免并发请求同时进 Metal
- 启动时预加载一次，之后按需重新加载
- `start.sh` 和 `stop.sh` 用 PID 文件管理，端口 8000

搬进 MlxForge 时保留这些行为，替换掉写死的路径和单模型假设。

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
- 字段确定后先写进 `docs/api.md`，再同步 README
- 不为兼容旧字段保留废弃路径

## 编码约定

- Python 3.11 起，公开函数带类型标注
- 配置用 TOML，不用 YAML
- 日志走标准库 `logging`，不 print
- 注释用中文，解释为什么这么做，不复述代码
- 新增依赖前先确认 MLX 或标准库能不能解决

## 验证

- 所有性能结论必须在 Apple Silicon 上实测，记录芯片型号、内存大小和量化精度
- 改运行时时先跑通命令行入口，再接 API
- API 冒烟测试至少覆盖 `/health`、`/v1/models` 和一次 `chat.completions`，空闲释放可以把 `HY_MT2_IDLE_TIMEOUT` 调小后等一轮检查
- 迁移后对照参考实现验证三件事，冷启动耗时、空闲释放后内存是否归零、SSE 输出格式是否还能被 CalmBar 接受
- README 的状态表只在功能跑通后更新

## 不要做

- 不要在空目录里补假实现
- 不要把模型权重、日志、生成的音频提交进仓库
- 不要为尚未存在的需求加抽象层
