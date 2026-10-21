# MlxForge

在 Apple Silicon 上原生运行 MLX 模型。先接机器翻译和语音合成，再用同样的方式接更多模型。

不用 Docker，只跑 macOS 原生环境。每个模型有自己的 Python 环境，对外共用一套 HTTP API 和一个 Web UI。

> 项目刚起步，目前只有 Hy-MT2 运行时，语音合成和统一调度还没开始。

## 能做什么

- 本地翻译。贴一段文本，指定源语言和目标语言，拿到译文。权重放在本机，断网也能用。
- 本地配音。输入台词，挑一个音色，输出 wav。也可以用一段参考音频来定音色。
- 统一调用。两个模型在同一个界面里使用，能对比译文，也能试听生成结果。

## 支持的模型

| 模型 | 任务 | 尺寸 | 权重 |
| --- | --- | --- | --- |
| [Hy-MT2](https://huggingface.co/collections/tencent/hy-mt2) | 多语种翻译 | 1.8B（4-bit） | 官方支持 4-bit 量化 |
| [Ming-3.0-tts](https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B) | 语音合成 | 0.5B / tiny | transformers，需转 MLX |

Hy-MT2 是腾讯混元 2026 年 5 月开源的翻译模型，覆盖 33 种语言，另有 5 种民汉语言和方言。官方提供 4-bit、8-bit、FP16 和 1.25-bit 几档量化，本项目只取 1.8B 的 4-bit 版本。

Ming-3.0-tts 来自蚂蚁百灵 2026 年 10 月的语音系列。除了常规的文本转语音，它支持用文字描述音色，也支持导演模式，可以写明情绪怎么走、哪个词要重读。台词里还能插 `[Laughter]`、叹息这类标签。

项目只覆盖端侧尺寸：Hy-MT2 的 1.8B，以及 Ming-3.0-tts 的 0.5B 和 tiny。更大的版本不在本期范围内。

## 为什么不用 Docker

macOS 上的容器跑在 Linux 虚拟机里，拿不到 Metal，MLX 用不上。项目直接跑在系统上，依赖隔离交给独立 venv。

同一个环境里装两个模型，依赖版本经常对不上，音频编解码和推理框架是重灾区。一个模型一套环境，装坏了删目录重来，不牵连另一个。

## 架构

```text
浏览器 / HTTP 客户端
        │
    API 服务
        │
   模型调度器
   ├── Hy-MT2 运行时（独立 venv）
   └── Ming-3.0-tts 运行时（独立 venv）
        │
  models/ 权重与 MLX 转换产物
```

调度器按需加载模型。首次请求时把权重读进内存，默认 20 分钟没有请求就卸载，同时清掉 Metal 缓存。每个运行时的依赖、权重路径和启动命令写在清单里，接新模型时不用改调度器。

## 接口（草案）

```http
GET  /v1/models
POST /v1/chat/completions
POST /v1/audio/speech
GET  /health
```

翻译接口兼容 OpenAI 的 `chat.completions` 格式，请求体里放 `messages`，已有的 OpenAI 客户端改个地址就能接。流式响应是整段译文生成完成后再分块下发，不是逐 token 推流，客户端收到的仍是标准 SSE。语音合成是新增的，字段还没定，接进运行时后再补文档。

## 环境要求

- Apple Silicon Mac，M1 及以上
- macOS 14 或更新
- Python 3.11 及以上
- `uv`
- 磁盘空间按模型算，Hy-MT2-1.8B-4bit 的权重约 1 GB，另需留出独立环境的依赖空间

## 本地运行

首次运行先建环境、装依赖并下载权重。

```bash
./scripts/setup_hy_mt2.sh
```

命令行翻译。

```bash
envs/hy-mt2/bin/python -m runtimes.hy_mt2.cli --text "Hello world." --target 中文
```

启动 API。

```bash
envs/hy-mt2/bin/python -m uvicorn runtimes.hy_mt2.app:create_app --factory --host 127.0.0.1 --port 8000
```

默认只监听本机。需要局域网访问时把 host 改成 `0.0.0.0`，服务没有鉴权，开放前先确认网络环境。

模型在第一次请求时加载，`HY_MT2_IDLE_TIMEOUT` 控制空闲多少秒后释放，默认 1200 秒。

## 进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 0.1 | 仓库骨架、环境脚本、权重下载 | 完成 |
| 0.2 | Hy-MT2 运行时，命令行与 OpenAI 兼容接口 | 完成 |
| 0.3 | 统一调度器接管多模型加载与端口 | 计划 |
| 0.4 | Ming-3.0-tts 命令行推理跑通，输出 wav | 计划 |
| 0.5 | Web UI，支持试听和译文对比 | 计划 |

## 参与

项目还在早期，目录结构和接口都可能大改。想认领某一块，先开个 issue 说一声，免得重复劳动。跑出实测数据，或者发现文档里说过头的地方，也欢迎直接提。

## 许可证

待定，第一版代码落地时补。
