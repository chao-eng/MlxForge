# MlxForge

在 Apple Silicon 上原生运行 MLX 模型。先接机器翻译、语音合成和抠图，再用同样的方式接更多模型。

不用 Docker，只跑 macOS 原生环境。每个模型有独立的运行环境：Python 模型用独立 venv，上游只提供 Swift 实现的模型用 SwiftPM 工程。对外共用一套 HTTP API 和一个 Web UI。

> 项目刚起步，目前有 Hy-MT2 翻译、Ming-3.0-tts 语音合成和 BiRefNet 抠图三个运行时：前两个是 Python，各自独立 venv；BiRefNet 是第一个 Swift 运行时，用 SwiftPM 构建成独立可执行服务。Web UI 保留对应模型页面；统一调度器还没开始。

## 能做什么

- 本地翻译。贴一段文本，选目标语言（官方支持语言表，含繁体中文和粤语），源语言由模型自动判断，拿到译文。权重放在本机，断网也能用。
- 浏览器翻译。服务启动后在页面里完成翻译和复制，页面与接口同源，不需要另起前端服务。
- 本地配音。输入台词，挑一个音色，输出 wav。也可以用一段参考音频来定音色。
- 本地抠图。把图片主体从背景里分离出来，得到透明底 PNG 或黑白遮罩，输出保持原图分辨率；抠图在 Swift 运行时里完成，权重同样放在本机。
- 同一套界面。翻译页和配音页在同一个前端工程里，但每个模型各自独立进程、各占一个端口，一次只能连其中一个；同屏使用和译文对比要等统一调度器。

## 支持的模型

| 模型 | 任务 | 尺寸 | 权重 |
| --- | --- | --- | --- |
| [Hy-MT2](https://huggingface.co/collections/tencent/hy-mt2) | 多语种翻译 | 1.8B（4-bit） | 官方支持 4-bit 量化 |
| [Ming-3.0-tts](https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B) | 语音合成 | 0.5B | mlx-community 8-bit（约 1.57 GB） |
| [BiRefNet](https://huggingface.co/ZhengPeng7/BiRefNet) | 前景分割 / 抠图 | Swin-L（fp16，约 440 MB） | ModelScope 的 mlx fp16 转换版 |

Hy-MT2 是腾讯混元 2026 年 5 月开源的翻译模型，覆盖 33 种语言，另有 5 种民汉语言和方言。官方提供 4-bit、8-bit、FP16 和 1.25-bit 几档量化，本项目只取 1.8B 的 4-bit 版本。

Ming-3.0-tts 来自蚂蚁百灵 2026 年 10 月的语音系列。除了常规的文本转语音，它支持用文字描述音色，也支持导演模式，可以写明情绪怎么走、哪个词要重读。台词里还能插 `[Laughter]`、叹息这类标签。本项目的权重用 mlx-community 的 8-bit 转换版，来源见文末许可证一节。想先试听效果，可以用 Poli 提供的在线测试 demo：<https://huggingface.co/spaces/hugging-apps/ming-3-tts-05b>。

BiRefNet 是 2024 年的前景分割模型，主打高分辨率二分图分割，发丝、眼镜这类细边也能保住软过渡。本项目的权重用 ModelScope 上 `bujidc/mlx-community_BiRefNet-fp16` 的转换版（单文件 `model.safetensors`，440,483,842 字节），加载走上游 Swift 端口 `mnmly/mlx-swift-BiRefNet`，模型和端口都是 MIT 许可证。

项目只覆盖端侧尺寸：Hy-MT2 的 1.8B，Ming-3.0-tts 的 0.5B（当前实测 8-bit 版本），以及 BiRefNet 的 Swin-L fp16。更大的版本不在本期范围内。

有些模型上游只提供 Swift 版 MLX 实现，没有对应的 Python 包。这类模型不硬塞进 Python，按 Swift 运行时接入：用 SwiftPM 构建成独立可执行服务，提供同一套 `/v1` 接口，Web UI 和客户端不用区分后端是哪种语言。BiRefNet 就是按这个方式接入的第一个模型，后续同类模型沿用同一套目录、构建脚本和清单约定。

## 为什么不用 Docker

macOS 上的容器跑在 Linux 虚拟机里，拿不到 Metal，MLX 用不上。项目直接跑在系统上，依赖隔离交给每个模型自己的独立环境。

同一个环境里装两个模型，依赖版本经常对不上，音频编解码和推理框架是重灾区。一个模型一套环境，装坏了删目录重来，不牵连另一个。

## 架构

```text
浏览器 / HTTP 客户端
        │
    API 服务
        │
   模型调度器
   ├── Hy-MT2 运行时（独立 venv）
   ├── Ming-3.0-tts 运行时（独立 venv）
   └── BiRefNet 运行时（SwiftPM 可执行文件）
        │
  models/ 权重与 MLX 转换产物
```

调度器按需加载模型。首次请求时把权重读进内存，默认 20 分钟没有请求就卸载，同时清掉 Metal 缓存。每个运行时的依赖、权重路径和启动命令写在清单里，清单用 `runtime` 区分 Python 和 Swift，调度器只按清单拉起，不认识具体模型，接新模型时不用改调度器。

## 接口

```http
GET  /v1/models
POST /v1/chat/completions
POST /v1/audio/speech
POST /v1/images/matting
GET  /health
```

翻译接口兼容 OpenAI 的 `chat.completions` 格式，请求体里放 `messages`，已有的 OpenAI 客户端改个地址就能接。流式响应是整段译文生成完成后再分块下发，不是逐 token 推流，客户端收到的仍是标准 SSE。

语音合成只实现 OpenAI Audio Speech 的**非流式兼容子集**：输出 `wav` 或 `pcm`，不支持流式音频，也不支持 MP3、Opus、AAC、FLAC。字段、任务模式、响应头和 SDK 示例见 [docs/api.md](docs/api.md)。

抠图接口是项目自定义的：`POST /v1/images/matting?output=cutout|mask`，请求体直接放图片字节，不套 JSON；`cutout` 返回透明底 RGBA PNG，`mask` 返回 8-bit 灰度 PNG，输出尺寸等于源图。字段、错误码和响应头见 [docs/birefnet-prd.md](docs/birefnet-prd.md)。

## 环境要求

- Apple Silicon Mac，M1 及以上
- macOS 14 或更新（Swift 运行时构建需要 15.6 或更新）
- Python 3.11 及以上
- `uv`
- Swift 工具链（仅 Swift 运行时需要）：Xcode 26.2（含 Swift 6.2.3），要求 macOS Sequoia 15.6 或更新。装好后执行 `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`，构建统一用 `swift build -c release`，再执行 `scripts/build_metallib.sh` 生成 MLX 需要的 `mlx.metallib`。Xcode 26.2 的 `--build-system swiftbuild` 实测无法调起 Metal 编译器，不采用
- 磁盘空间按模型算：Hy-MT2-1.8B-4bit 权重约 1 GB，Ming-3.0-tts-0.5B-8bit 权重约 1.57 GB，BiRefNet-fp16 权重约 440 MB，另需留出各自独立环境的依赖空间；Swift 运行时的构建产物在 `runtimes/<name>/.build/`，占用另算

`uv` 用官方脚本安装，脚本会自动识别芯片架构（Apple Silicon 或 Intel），把 `uv` 和 `uvx` 装到 `~/.local/bin`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

装完让当前 Shell 重新读一次环境变量，再确认版本：

```bash
source ~/.zshrc        # bash 用 source ~/.bash_profile
uv --version
```

## 本地运行

三个运行时各自独立，默认都监听 `127.0.0.1:8000`，同一时间跑一个；同时使用时给其中一个加 `--port`。

Web UI 由两个 Python 模型共用，构建一次即可。用 pnpm，构建产物在 `web/dist`，服务启动时自动挂到 `/`。单模型启动时 `/` 会 307 跳转到对应页面（Ming 是 `/?page=tts`，Hy-MT2 是 `/?page=translate`），带 `page` 参数进入会锁定该页面并隐藏另一个页签；不带参数时按 `/v1/models` 自动判断。BiRefNet 目前只有接口，没有专属页面。

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

要挂在后台、关掉终端也不退出，加 `--daemon`。

```bash
./scripts/start_hy_mt2.sh --daemon
./scripts/stop_hy_mt2.sh
```

日志追加到 `logs/hy-mt2.log`，PID 写在 `run/hy-mt2.pid`，两个目录都不入库。启动过程（时间、模式、host、端口、PID、解释器版本）带时间戳写入同一个日志，前台启动也留一份，端口占用、环境缺失这类失败同样落盘。这种方式不受终端生命周期影响，但注销或重启后要手动再启动一次。

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

后台运行同样用 `--daemon`，日志在 `logs/ming-tts.log`，PID 在 `run/ming-tts.pid`，启动时间、端口、PID 和失败原因都会带时间戳写进日志。

```bash
./scripts/start_ming_tts.sh --daemon
./scripts/stop_ming_tts.sh
```

输入上限是 **1~1000 个 Unicode 码点**，按码点计数（不是字节，也不是 JavaScript 的 `text.length`），1000 是**临时上限**，长文本能力和耗时确认后冻结。v1 不支持流式音频，只输出 `wav` 或 `pcm`。

Web UI 提供内置音色、声音克隆、声音设计三个页签。内置音色覆盖官方 482 个音色（5 个英文、48 个中文、429 个中文情绪变体）；声音设计页可在「声音设计」和「自由指令」之间切换，前者描述谁在说话，后者描述怎么说。台词里可以直接写 `[Laughter]`、`[Sigh]` 等 14 个副语言标签。CFG scale 和 Sigma 默认 2.0 / 0.25，与官方一致，一般不用改。

声音克隆不能叠加情绪、方言或语速/音高/音量：官方依赖的 CAM++ 说话人嵌入尚未在 mlx-audio 中实现，本服务直接返回 400，不做静默降级。

常用环境变量：`MING_TTS_IDLE_TIMEOUT`（默认 1200 秒，`0` 常驻）、`MING_TTS_MAX_QUEUE`（等待队列，默认 8）、`MING_TTS_QUEUE_TIMEOUT`（排队超时，默认 120 秒）、`MING_TTS_MLX_CACHE_LIMIT_MB`（MLX 缓存上限，默认 512，`0` 禁用）、`MING_TTS_TEMP_DIR`（参考音频临时目录）、`MING_TTS_LOG_LEVEL`。接口字段见 [docs/api.md](docs/api.md)。

### BiRefNet

Swift 运行时，用 SwiftPM 构建，和两个 Python 运行时不共享依赖。首次运行先构建：

```bash
./scripts/build_birefnet.sh
```

脚本跑 `swift build -c release`，再用 `scripts/build_metallib.sh` 从 mlx-swift 的 Metal 源码生成 `mlx.metallib`。产物在 `runtimes/birefnet/.build/release/`，`birefnet-cli` 和 `birefnet-server` 是软链，实际二进制叫 `birefnet-matte-cli` / `birefnet-matte-server`——上游包已经占用了 `birefnet-cli` 这个 target，同名产物会互相覆盖。

命令行抠图，`--mode` 可选 `cutout`（透明底 RGBA）或 `mask`（黑白遮罩），成功时标准输出只打印输出文件绝对路径，耗时写标准错误：

```bash
runtimes/birefnet/.build/release/birefnet-cli \
  --input 图片.jpg --output output/cutout.png --mode cutout
```

启动 API：

```bash
runtimes/birefnet/.build/release/birefnet-server \
  --host 127.0.0.1 --port 8000 --weights models/birefnet/fp16 --web-root web/dist
```

`web/dist` 不存在时接口照常工作，只是静态页面返回 404。模型内部默认按 512² 推理，峰值内存约 1.9GB；需要更细的边缘时用 `BIREFNET_INPUT_SIZE=1024` 启动，代价是峰值涨到约 4.9GB。`BIREFNET_IDLE_TIMEOUT` 控制空闲卸载，默认 1200 秒，`0` 表示常驻；MLX 缓存上限固定 256MB，超出的缓冲区直接还给系统。非回环监听必须显式授权，否则启动失败：

```bash
BIREFNET_ALLOW_REMOTE=1 runtimes/birefnet/.build/release/birefnet-server --host 0.0.0.0
```

日志走 `os.Logger`，subsystem 是 `com.mlxforge.birefnet`，每次请求按 `X-Request-Id` 串起入队、排队等待、解码、推理、编码和内存读数：

```bash
/usr/bin/log stream --level debug --predicate 'subsystem == "com.mlxforge.birefnet"'
```

### 已实测机型

| 机型 | 系统 | 记录 |
| --- | --- | --- |
| Apple M2，16GB 统一内存 | macOS 15.7.9 | Ming-3.0-tts 的加载、RTF、内存与并发数据见 [docs/benchmarks.md](docs/benchmarks.md) |
| Apple M2，16GB 统一内存 | macOS 15.7.9 | BiRefNet fp16：1279×1704 人像在 512² 档端到端 0.76~0.95 秒，MLX 峰值约 1.9GB，请求后进程 footprint 约 750MB；1024² 档约 2.4 秒、峰值 4.9GB（同一张图，热态） |

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
| 0.5 | Swift 运行时接入，上游仅有 Swift 实现的模型作为独立进程 | 完成（BiRefNet） |
| 0.6 | BiRefNet 的 Web UI 页面和安装脚本 | 计划 |

## 参与

项目还在早期，目录结构和接口都可能大改。想认领某一块，先开个 issue 说一声，免得重复劳动。跑出实测数据，或者发现文档里说过头的地方，也欢迎直接提。

## 许可证

仓库代码的许可证待定，第一版代码落地时补。

Hy-MT2-1.8B 权重来自 ModelScope 的 `bujidc/mlx-community_Hy-MT2-1.8B-4bit`，由腾讯混元开源，采用 Apache License 2.0，许可证原文随权重保存在 `models/hy-mt2/4bit/LICENSE.txt`，权重本身不入库。

Ming-3.0-tts-0.5B-8bit 权重来自 ModelScope 的 `bujidc/mlx-community_Ming-3.0-tts-0.5B-8bit`，revision `049da49260b32e19fe8336ecd9b38a89f490dc1d`，由蚂蚁百灵开源，采用 MIT 许可证，`LICENSE` 随权重保存在 `models/ming-tts/8bit/`，权重本身不入库。

BiRefNet-fp16 权重来自 ModelScope 的 `bujidc/mlx-community_BiRefNet-fp16`，revision `b9f39904c60ed2bc11c2fd5bdb005872a8eb2d34`，单文件 `model.safetensors` 的 SHA-256 为 `f1ba66260085fd8d471323dab098fabd36499ad54b0de8ca67deb5d1cf1f0c0e`。上游 BiRefNet 与 Swift 端口 `mnmly/mlx-swift-BiRefNet` 均为 MIT 许可证，权重本身不入库。

安装时用来源提供的 SHA-256 和不可变 revision 校验文件与发布版本一致。本地 `.checksums` 只用于后续文件完整性复核，不能证明首次下载的来源可信，不等同于完成供应链安全验证。
