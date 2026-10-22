# MlxForge

在 Apple Silicon 上原生运行 MLX 模型。先接机器翻译和语音合成，再用同样的方式接更多模型。

不用 Docker，只跑 macOS 原生环境。每个模型有自己的 Python 环境，对外共用一套 HTTP API 和一个 Web UI。

> 项目刚起步，目前有 Hy-MT2 翻译和 Ming-3.0-tts 语音合成两个运行时，各自独立环境、独立进程，Web UI 同时保留两套模型页面；统一调度器还没开始。

## 能做什么

- 本地翻译。贴一段文本，选目标语言（官方支持语言表，含繁体中文和粤语），源语言由模型自动判断，拿到译文。权重放在本机，断网也能用。
- 浏览器翻译。服务启动后在页面里完成翻译和复制，页面与接口同源，不需要另起前端服务。
- 本地配音。输入台词，挑一个音色，输出 wav。也可以用一段参考音频来定音色。
- 统一调用。两个模型在同一个界面里使用，能对比译文，也能试听生成结果。

## 支持的模型

| 模型 | 任务 | 尺寸 | 权重 |
| --- | --- | --- | --- |
| [Hy-MT2](https://huggingface.co/collections/tencent/hy-mt2) | 多语种翻译 | 1.8B（4-bit） | 官方支持 4-bit 量化 |
| [Ming-3.0-tts](https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B) | 语音合成 | 0.5B | mlx-community 8-bit（约 1.57 GB） |

Hy-MT2 是腾讯混元 2026 年 5 月开源的翻译模型，覆盖 33 种语言，另有 5 种民汉语言和方言。官方提供 4-bit、8-bit、FP16 和 1.25-bit 几档量化，本项目只取 1.8B 的 4-bit 版本。

Ming-3.0-tts 来自蚂蚁百灵 2026 年 10 月的语音系列。除了常规的文本转语音，它支持用文字描述音色，也支持导演模式，可以写明情绪怎么走、哪个词要重读。台词里还能插 `[Laughter]`、叹息这类标签。本项目的权重用 mlx-community 的 8-bit 转换版，来源见文末许可证一节。想先试听效果，可以用 Poli 提供的在线测试 demo：<https://huggingface.co/spaces/hugging-apps/ming-3-tts-05b>。

项目只覆盖端侧尺寸：Hy-MT2 的 1.8B，以及 Ming-3.0-tts 的 0.5B（当前实测 8-bit 版本）。更大的版本不在本期范围内。

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

## 接口

```http
GET  /v1/models
POST /v1/chat/completions
POST /v1/audio/speech
GET  /health
```

翻译接口兼容 OpenAI 的 `chat.completions` 格式，请求体里放 `messages`，已有的 OpenAI 客户端改个地址就能接。流式响应是整段译文生成完成后再分块下发，不是逐 token 推流，客户端收到的仍是标准 SSE。

语音合成只实现 OpenAI Audio Speech 的**非流式兼容子集**：输出 `wav` 或 `pcm`，不支持流式音频，也不支持 MP3、Opus、AAC、FLAC。字段、任务模式、响应头和 SDK 示例见 [docs/api.md](docs/api.md)。

## 环境要求

- Apple Silicon Mac，M1 及以上
- macOS 14 或更新
- Python 3.11 及以上
- `uv`
- 磁盘空间按模型算：Hy-MT2-1.8B-4bit 权重约 1 GB，Ming-3.0-tts-0.5B-8bit 权重约 1.57 GB，另需留出各自独立环境的依赖空间

## 本地运行

两个运行时各自独立，默认都监听 `127.0.0.1:8000`，同一时间跑一个；同时使用时给其中一个加 `--port`。

Web UI 两个模型共用，构建一次即可。用 pnpm，构建产物在 `web/dist`，服务启动时自动挂到 `/`。单模型启动时 `/` 会 307 跳转到对应页面（Ming 是 `/?page=tts`，Hy-MT2 是 `/?page=translate`），带 `page` 参数进入会锁定该页面并隐藏另一个页签；不带参数时按 `/v1/models` 自动判断。

```bash
cd web && pnpm install && pnpm build && cd ..
```

### Hy-MT2

首次运行先建环境、装依赖并下载权重。

```bash
./scripts/setup_hy_mt2.sh
```

命令行翻译。

```bash
envs/hy-mt2/bin/python -m runtimes.hy_mt2.cli --text "Hello world." --target 中文
```

启动 API 和 Web UI。

```bash
./scripts/start_hy_mt2.sh
```

脚本默认监听 `127.0.0.1:8000`，可用 `--host`、`--port` 覆盖。端口被占用会直接报错，不自动换端口。默认只监听本机；需要局域网访问时把 host 改成 `0.0.0.0`，服务没有鉴权，开放前先确认网络环境。

模型在第一次请求时加载，`HY_MT2_IDLE_TIMEOUT` 控制空闲多少秒后释放，默认 1200 秒，`0` 表示常驻。MLX 缓存池上限默认 512MB，可用 `--mlx-cache-limit-mb` 调整，`0` 表示禁用缓存。

### Ming-3.0-tts

首次运行同样先建环境、装依赖并下载权重。依赖固定 `mlx-audio==0.6.1`（必须包含 PR #1047；0.6.0 及更早版本会念错词，安装和启动时都会校验）。

```bash
./scripts/setup_ming_tts.sh
```

命令行合成，标准输出只打印输出文件路径。

```bash
envs/ming-tts/bin/python -m runtimes.ming_tts.cli --text "今天下午三点我们在楼下咖啡店见面。" --output output/demo.wav
```

启动 API 和 Web UI。

```bash
./scripts/start_ming_tts.sh
```

默认监听 `127.0.0.1:8000`。开放局域网必须同时显式授权，否则启动直接失败：

```bash
MING_TTS_ALLOW_REMOTE=1 ./scripts/start_ming_tts.sh --host 0.0.0.0
```

服务没有鉴权，同网段设备都能调用合成接口和上传参考音频，开放前先确认网络环境。

输入上限是 **1~1000 个 Unicode 码点**，按码点计数（不是字节，也不是 JavaScript 的 `text.length`），1000 是**临时上限**，长文本能力和耗时确认后冻结。v1 不支持流式音频，只输出 `wav` 或 `pcm`。

Web UI 提供内置音色、声音克隆、声音设计三个页签。内置音色覆盖官方 482 个音色（5 个英文、48 个中文、429 个中文情绪变体）；声音设计页可在「声音设计」和「自由指令」之间切换，前者描述谁在说话，后者描述怎么说。台词里可以直接写 `[Laughter]`、`[Sigh]` 等 14 个副语言标签。CFG scale 和 Sigma 默认 2.0 / 0.25，与官方一致，一般不用改。

声音克隆不能叠加情绪、方言或语速/音高/音量：官方依赖的 CAM++ 说话人嵌入尚未在 mlx-audio 中实现，本服务直接返回 400，不做静默降级。

常用环境变量：`MING_TTS_IDLE_TIMEOUT`（默认 1200 秒，`0` 常驻）、`MING_TTS_MAX_QUEUE`（等待队列，默认 8）、`MING_TTS_QUEUE_TIMEOUT`（排队超时，默认 120 秒）、`MING_TTS_MLX_CACHE_LIMIT_MB`（MLX 缓存上限，默认 512，`0` 禁用）、`MING_TTS_TEMP_DIR`（参考音频临时目录）、`MING_TTS_LOG_LEVEL`。接口字段见 [docs/api.md](docs/api.md)。

### 已实测机型

| 机型 | 系统 | 记录 |
| --- | --- | --- |
| Apple M2，16GB 统一内存 | macOS 15.7.9 | Ming-3.0-tts 的加载、RTF、内存与并发数据见 [docs/benchmarks.md](docs/benchmarks.md) |

其他 Apple Silicon 机型只保证功能可运行，不承诺具体耗时。PRD 里的性能门槛以 M4 Pro 24GB 为基准机，本仓库尚未在该机型实测。

开发前端时可以让 Vite 代理接口，另开一个终端跑后端：

```bash
cd web && pnpm dev
```

## 进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 0.1 | 仓库骨架、环境脚本、权重下载 | 完成 |
| 0.2 | Hy-MT2 运行时，命令行、OpenAI 兼容接口和单页 Web UI | 完成 |
| 0.3 | 统一调度器接管多模型加载与端口 | 计划 |
| 0.4 | Ming-3.0-tts 命令行推理跑通，输出 wav | 完成 |
| 0.5 | Web UI 支持试听和译文对比 | 完成 |

## 参与

项目还在早期，目录结构和接口都可能大改。想认领某一块，先开个 issue 说一声，免得重复劳动。跑出实测数据，或者发现文档里说过头的地方，也欢迎直接提。

## 许可证

仓库代码的许可证待定，第一版代码落地时补。

Hy-MT2-1.8B 权重来自 ModelScope 的 `bujidc/mlx-community_Hy-MT2-1.8B-4bit`，由腾讯混元开源，采用 Apache License 2.0，许可证原文随权重保存在 `models/hy-mt2/4bit/LICENSE.txt`，权重本身不入库。

Ming-3.0-tts-0.5B-8bit 权重来自 ModelScope 的 `bujidc/mlx-community_Ming-3.0-tts-0.5B-8bit`，revision `049da49260b32e19fe8336ecd9b38a89f490dc1d`，由蚂蚁百灵开源，采用 MIT 许可证，`LICENSE` 随权重保存在 `models/ming-tts/8bit/`，权重本身不入库。

安装时用来源提供的 SHA-256 和不可变 revision 校验文件与发布版本一致。本地 `.checksums` 只用于后续文件完整性复核，不能证明首次下载的来源可信，不等同于完成供应链安全验证。
