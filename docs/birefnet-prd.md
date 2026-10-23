# BiRefNet-fp16 图片抠图运行时 PRD

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v0.4 |
| 日期 | 2026-10-23 |
| 状态 | 草案，待评审；阶段 0 Spike 已完成构建路径和权重严格加载验证，待验推理质量与 HTTP 层 |
| 对应实现 | `runtimes/birefnet/`（待实现） |
| 关联文档 | [README.md](../README.md)、[AGENTS.md](../AGENTS.md)、[api.md](api.md)、[hy-mt2-prd.md](hy-mt2-prd.md)、[ming3-tts-prd.md](ming3-tts-prd.md) |

> 本文引用的性能与质量数字分两类，必须区分：
>
> - **上游声明**：转换仓库和 Swift 端口给出的模型体积、IoU、耗时、峰值内存，只作可行性参考，不是本项目实测结论。
> - **本项目验收口径**：第 6.1 节定义的加载、单张推理、峰值内存和卸载回收指标，必须在 Apple Silicon 上按统一口径实测并写入 [benchmarks.md](benchmarks.md)。
>
> 实测完成前，README、Web UI 和对外文档不得宣称任何耗时、吞吐或内存结论。

### 评审修订记录

| 版本 | 结论 | 处理 |
| --- | --- | --- |
| v0.1 | 首版草案，尚未评审 | 建立需求基线、用例、接口、验收和风险清单；待开发者、并发和小白用户三轮评审后回填 |
| v0.2 | 系统门槛评审 | macOS 26.2 来自 MLXEngine 包装层（Neural Accelerators），不是模型本身。改为只依赖核心包 `mnmly/mlx-swift-BiRefNet`，运行门槛降为 macOS 14+，构建门槛独立表述为 Swift 6.2 / Xcode 26（宿主 macOS 15.6+）。同步 §1.1、§1.2、§1.6、§1.7、UC-01、UC-04、§4.1、§6.1.1、§6.2、§6.5、§7、BR-01~03、§9.6 |
| v0.3 | 阶段 0 Spike（部分） | 复测权重校验和通过；张量布局与核心包 key 声明全部对应；`macos_min` 依据收窄为核心包。构建与依赖解析因本机环境不足未验证，见下方进展 |
| v0.4 | 阶段 0 Spike（构建与加载） | 实测确认 `--build-system swiftbuild` 在 Xcode 26.2 上被 Metal 工具链定位 bug 卡死，改用「native 构建 + 脚本编译 metallib」；权重严格加载通过。同步 §1.2、§1.7、UC-01、§4.1、§6.2、§6.5、§7.1、A-1、BR-02、§9.6 |

### 阶段 0 Spike 进展（2026-10-23）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 权重下载与校验 | 通过。`model.safetensors` 440,483,842 字节，SHA-256 `f1ba66260085fd8d471323dab098fabd36499ad54b0de8ca67deb5d1cf1f0c0e`，与 §3 UC-01 记录一致；中途断流后续传成功 | `models/birefnet/fp16/model.safetensors`（不入库） |
| 张量布局 | 687 个张量，全部 F16；顶层 `bb` 333、`squeeze_module` 58、`decoder` 296；107 个 4 维权重末维为输入通道，符合 NHWC 转换约定 | safetensors header |
| key 兼容性（静态） | 全部 key 段都能在核心包 `@ModuleInfo/@ParameterInfo(key:)` 声明或标准叶子名（weight/bias/running_*）中找到，未知段 0；顶层键与 `BiRefNet.swift` 的三个模块键完全一致 | 核心包 0.1.1 源码 |
| 严格加载 | 通过。`BiRefNetPipeline.fromPretrained(dtype: .float16)` 对 `models/birefnet/fp16/model.safetensors` 加载成功，0.063 秒（Apple M2 / 16GB / macOS 15.7.9，非项目基准）；严格校验未报缺失或多余 key。风险 1 消除 | 探针工程 Release 产物运行输出 `LOAD_OK` |
| 构建与 metallib | 部分通过，改道。`--build-system swiftbuild` 在 Xcode 26.2（17C52）上无法调用 Metal 编译器：组件已下载并在 `xcodebuild -showComponent` 中显示 installed，但 Xcode 自带 `metal` shim 仍报 missing Metal Toolchain，复制到 `/Library/Developer/Toolchains/` 后依旧。改用 `swift build -c release`（native）+ 脚本把 `mlx-generated/metal` 的 9 个 `.metal` 编译链接为 `mlx.metallib`（3.8MB），与可执行文件同目录后加载成功；产物 `LC_BUILD_VERSION minos = 14.0`，`otool -L` 仅系统库 | 探针工程构建日志、`otool -l/-L`、运行输出 |
| 依赖解析 | 通过。Swift 6.2.3 下解析为 `mlx-swift` 0.31.4（tools 6.3 的 0.31.5+ 被自动跳过）、核心包 0.1.1、`swift-nio` 2.104.0。风险 2 在 Swift 6.2 上不触发，但升级到 Swift 6.3 会跳版，仍按 BR-03 锁定 | 探针工程的 `Package.resolved` |

---

## 0. 原始需求基线

| # | 原始诉求 | 拆解后的产品含义 | 对应章节 |
| --- | --- | --- | --- |
| R1 | 部署 ModelScope 上的 `bujidc/mlx-community_BiRefNet-fp16` | 在本机加载该 fp16 权重，完成图片抠图 | UC-01、UC-04 |
| R2 | 该模型只有 Swift 版 MLX 实现 | 作为独立 Swift 运行时接入，不硬塞进 Python | §1.2、UC-01 |
| R3 | 不依赖 Docker | 原生 macOS + SwiftPM；构建和运行都在系统上完成 | UC-01、BR-01 |
| R4 | 对外提供接口 | 提供本地 HTTP API，输入图片、输出透明底或遮罩 PNG | UC-04 |
| R5 | 提供 Web UI | 浏览器里选择图片、抠图、对比、下载，不写代码 | UC-07 |
| R6 | 空闲时释放内存 | 首次请求加载，空闲超时后卸载并清缓存 | UC-06 |
| R7 | 部署和排障要简单 | 一条安装脚本、一个健康检查、清晰的错误提示和日志 | UC-01、UC-03、UC-08 |
| R8 | 不编数据 | 上游数字只作参考，本项目性能必须实测后记录 | §6.1、BR-45 |
| R9 | 单模型推进 | 本期只做 BiRefNet fast 档，内部推理默认 1024²（`BIREFNET_INPUT_SIZE` 可调），不接 HR、Lucida 或其他模型 | §1.4 |
| R10 | 不破坏现有运行时 | Hy-MT2、Ming-3.0-tts 的接口、页面和依赖不受影响 | §1.6、BR-37 |

---

## 1. 产品概述

### 1.1 产品背景

MlxForge 已有两个 Python 运行时：Hy-MT2 翻译和 Ming-3.0-tts 语音合成。两者都验证了「独立环境 + MLX 推理 + HTTP 接口 + 单页 Web UI + 空闲卸载」这套骨架。

BiRefNet 是第三个候选模型，任务是把图片主体从背景中分离出来，输出软边缘的透明度信息。它的上游实现是 PyTorch；本项目采用 ModelScope 上的 MLX fp16 转换权重 `bujidc/mlx-community_BiRefNet-fp16`。

该模型的特殊之处是：**目前能直接消费这份权重的推理实现只有 Swift 版**。模型卡指向的 `mlx-birefnet-swift` 实际由两层组成：核心推理来自 `mnmly/mlx-swift-BiRefNet`（`MLXBiRefNet`，声明 `.macOS(.v14)`），外层是 MLXEngine 包装（`mlx-engine-swift`，声明 `.macOS(.v26)`，注释写明 26.2+ 才能用 Neural Accelerators）。本项目只需要核心推理，HTTP、队列和生命周期按本项目约定自研，因此**只依赖核心包，不引入 MLXEngine**，运行门槛按 macOS 14+ 计。选型依据见 §1.7 风险 1~3。

已核对的模型信息：

| 项目 | 内容 | 来源 |
| --- | --- | --- |
| 任务 | 前景分割 / 抠图，输出单通道软 alpha | 模型卡 |
| 骨干 | Swin-L + ASPP-Deformable | 模型卡、Swift 端口 |
| 输入尺寸 | 默认 1024×1024，`BIREFNET_INPUT_SIZE` 可在 256~2048 间调整（32 的倍数） | 本机实测：1024² 峰值约 5GB、768² 约 3.4GB、512² 约 1.8GB；512² 在低对比人像上会把脸部和发际留成大块半透明，故不作默认 |
| 输出 | 单通道软 alpha，白=前景；可回到源分辨率 | 模型卡、Swift 端口 |
| 权重文件 | 单文件 `model.safetensors`，440,483,842 字节（约 420 MiB） | ModelScope 文件元数据 |
| 权重 revision | `b9f39904c60ed2bc11c2fd5bdb005872a8eb2d34` | ModelScope |
| 权重 SHA-256 | `f1ba66260085fd8d471323dab098fabd36499ad54b0de8ca67deb5d1cf1f0c0e` | ModelScope |
| 上游质量声明 | 与 PyTorch 参考实现 IoU 0.9905，转换后 687 个张量 | 模型卡 |
| 许可证 | MIT（模型、Swift 端口均为 MIT） | 模型卡、仓库 README |

本 PRD 只定义 BiRefNet 这一个模型。统一调度器和多模型共存仍不在本期验收范围内。

### 1.2 第一性原则分析

回到用户点下「抠图」那一刻真正需要的东西，是**一张主体边缘干净、尺寸不被偷偷缩小的透明背景图片**，而不是权重文件、Swift 包或推理日志。

必要条件：

1. 图片和推理都在本机完成，不上传云端。
2. 输出保持原图分辨率，不能为了模型内部的缩放就把结果缩小。
3. 边缘是软过渡，头发、绒毛、半透明物体不能出现硬锯齿。
4. 既能下载透明底 PNG，也能拿到黑白遮罩做后续处理。
5. 服务能在一台 Apple Silicon Mac 上装好并稳定运行，空闲时让出内存。
6. 出错时用户能分清是图片太大、格式不支持、服务没起来，还是模型加载失败。
7. 图片只在内存中处理，不写仓库、不写用户目录、不进日志。

约束：

- 只支持 Apple Silicon 的 macOS，不覆盖 Intel Mac 和 Linux。
- 运行门槛按 macOS 14+ 计：这是 `mlx-swift-BiRefNet` 声明的 `.macOS(.v14)`，不是 MLXEngine 包装层的 26.2；`mlx-swift` 0.31.x 自身未声明 platforms。
- 构建门槛与运行门槛分开：构建机需 Swift 6.2 工具链（Xcode 26，宿主 macOS 15.6+）。Xcode 26.2 的 `--build-system swiftbuild` 因 Metal 工具链定位 bug 不可用（已实测），改为 `swift build -c release` 加脚本编译 `mlx.metallib`，详见 §6.5 与 A-1；产物可在 macOS 14+ 的机器上运行。
- 推理走 MLX；Swift 侧复用 `mlx-swift-BiRefNet` 核心，不自己写 Swin-L、DCNv2 和采样逻辑；不引入 MLXEngine。
- 不通过 Python 转发，不引入 PyTorch 推理后端。
- 单机单用户为主，不承诺多租户、鉴权、水平扩展。
- 本期只支持一个模型实例，切换模型需要重启进程。
- 不与 Hy-MT2、Ming-3.0-tts 互相 import；跨模型共用逻辑等 `server/` 落地后再抽取。

### 1.3 产品目标

| 编号 | 目标 | 度量方式 | 验收口径 |
| --- | --- | --- | --- |
| G1 | 一条脚本完成安装与构建 | 全新克隆到 CLI 产出第一张抠图 | 不手工装 Swift 包、不改代码；失败时脚本给出可执行的下一步 |
| G2 | CLI 与 API 结果一致 | 同一输入、同一输出形态分别走 CLI 和 API | 解码后的 alpha 像素最大差值 ≤1/255；PNG 容器字节不要求相同 |
| G3 | 接口稳定可编程 | curl 和 Web UI 均能完成抠图 | 路径、字段、错误结构与 [api.md](api.md) 一致 |
| G4 | 质量不低于上游端口 | 跑通核心包自带测试，并对固定回归图集做人工检查 | 测试通过；20 张回归图无肉眼可见的主体缺失、边缘断裂或方向错误 |
| G5 | 空闲后内存真的还回去 | 同时记录 MLX 缓存、进程物理内存和整机内存 | 卸载 60 秒后进程物理内存 ≤ 基线 + max(200MB, 峰值增量×20%)；MLX 缓存增量 ≤ 峰值增量的 10% |
| G6 | 运行期不联网 | 安装完成后断网验证 | 首次加载、重试、健康检查、Web UI 抠图和下载均无外发请求 |
| G7 | 错误可判断 | 逐条构造非法输入 | 每个失败场景返回文档定义的状态码和中文说明，不出现堆栈和绝对路径 |
| G8 | 能力承诺可追溯 | 每个能力标记为「上游已验证」「待 Spike」或「不承诺」 | 未通过 Spike 的能力不在 Web UI 暴露，也不写进 README |

### 1.4 系统范围

**本期包含**

- `bujidc/mlx-community_BiRefNet-fp16` 权重下载、revision 与 SHA-256 校验
- SwiftPM 工程、Release 构建、`mlx.metallib` 生成与自检门禁
- 模型加载、单张图片推理、空闲卸载
- 命令行抠图
- `POST /v1/images/matting`
- 透明底 PNG（cutout）和灰度遮罩 PNG（mask）两种输出
- 单页 Web UI 抠图页
- 健康检查、错误映射、日志
- 安装、启动、停止、排障文档

**本期不包含**

- BiRefNet-HR 2048² best 档
- Lucida 细调族
- bf16、fp32、4-bit 或其他精度
- 批量图片、文件夹监听、视频逐帧抠图
- 背景替换、背景模糊、颜色去污染、边缘细化、蒙版羽化
- 输入图片编辑、裁剪、旋转交互
- 流式进度、任务队列持久化、任务历史
- 多模型调度器、模型热切换
- 鉴权、计费、多租户、CORS
- Docker、Linux、Windows、Intel Mac
- 训练、微调、权重转换、量化

### 1.5 系统组件

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| 安装脚本 | `scripts/setup_birefnet.sh` | 检查平台与工具链、下载并校验权重、执行 Release 构建 |
| 启动脚本 | `scripts/start_birefnet.sh` | 检查产物和端口，启动服务，支持前台与 `--daemon` |
| 停止脚本 | `scripts/stop_birefnet.sh` | 读取 PID 文件，校验后优雅终止 |
| 运行时清单 | `runtimes/birefnet/runtime.toml` | 声明 Swift 运行时、构建命令、入口、权重路径、空闲超时、系统门槛 |
| SwiftPM 工程 | `runtimes/birefnet/Package.swift` | 锁定 Swift 包依赖，产出服务端和 CLI 两个可执行文件 |
| HTTP 服务 | `runtimes/birefnet/Sources/BiRefNetServer/` | 路由、请求校验、队列、静态 UI、错误映射、健康检查 |
| 推理服务层 | `runtimes/birefnet/Sources/BiRefNetCore/` | 图片解码、预处理、模型生命周期、alpha 后处理、PNG 编码 |
| 命令行 | `runtimes/birefnet/Sources/BiRefNetCLI/` | 单张图片抠图，便于排障和脚本调用 |
| Web UI | `web/`，构建后挂载在 `/` | 选择图片、预览、切换输出形态、下载结果 |
| 权重 | `models/birefnet/fp16/` | fp16 权重与许可证，不入库 |
| 构建产物 | `runtimes/birefnet/.build/` | SwiftPM 构建目录，不入库 |

### 1.6 现状与差距

| 能力 | 当前实现 | 本 PRD 要求 | 处理方式 |
| --- | --- | --- | --- |
| Swift 运行时 | 只有文档约定，没有可执行工程 | `runtimes/birefnet/` SwiftPM 工程 | 新建 |
| 权重 | 无 | `models/birefnet/fp16/model.safetensors` | 新建下载与校验 |
| 模型加载与推理 | 无 | 走 `mlx-swift-BiRefNet` 核心 | 新建服务层 |
| 命令行 | 无 | 单张图片，输出 PNG | 新建 CLI |
| API | 无图片接口 | `POST /v1/images/matting` | 新建服务 |
| Web UI | 已有翻译页和语音页 | 新增抠图页 | 扩展前端 |
| 队列与状态机 | Hy-MT2、Ming 已实现 | 同样的串行、队列、冷却和空闲卸载 | 按同样语义新建，不跨运行时 import |
| 错误结构 | 已统一 | 沿用 `{"error": {"type", "message"}}` | 复用约定 |
| 系统要求 | README 写 macOS 14+ | 运行门槛同为 macOS 14+，构建另需 Swift 6.2 / Xcode 26 | 文档把运行门槛和构建门槛分开标注 |
| 清单字段 | 无 `min_macos` | 增加 `min_macos`，取值 `14` | 同步更新 AGENTS 和调度器设计 |
| API 文档 | 只有翻译和语音 | 增加图片抠图接口 | 实现后同步 `docs/api.md` |

### 1.7 关键风险与前置决策

| # | 风险 | 判定 | 影响 | 处理 |
| --- | --- | --- | --- | --- |
| 1 | 权重 key 布局与核心包是否兼容：ModelScope 文件由 `mlx-birefnet-swift` 的转换器产出（754→687 张量），本项目改用 `mlx-swift-BiRefNet` 加载 | 已消除 | 无 | 已用 `BiRefNetPipeline.fromPretrained` 严格加载实测通过（§阶段 0 Spike）；剩余待验的是推理质量（IoU）而非加载 |
| 2 | 依赖解析会越界到 tools 6.3：核心包写 `mlx-swift from: "0.31.3"`，而 `mlx-swift` 0.31.5 起 tools-version 变为 6.3 | 中危 | 解析到 0.31.5+ 后需要 Swift 6.3 工具链，构建直接失败 | `Package.resolved` 锁定 `mlx-swift` 0.31.4（最后一个 tools 5.12 版本）；升级单独评审 |
| 3 | Metal 内核构建方式：Xcode 26.2 的 `--build-system swiftbuild` 实测无法调用 Metal 编译器（工具链定位 bug，复制组件后仍失效） | 中危 | 构建失败；若误用纯 `native` 构建，运行期报 `Failed to load the default metallib` | 构建固定为 `swift build -c release` + `scripts/build_metallib.sh` 产出 `mlx.metallib`；安装脚本校验该文件存在且与可执行文件同目录；mlx-swift 版本升级时重跑该脚本 |
| 3a | `mlx.metallib` 是独立产物，部署时容易漏拷 | 中危 | 目标机运行时报 metallib 缺失 | 部署单元明确为「可执行文件 + `mlx.metallib`」；冒烟测试第一条就是 Metal 初始化成功 |
| 4 | 上游声明 fp16 峰值约 4.9GB；验收机为 16GB 统一内存 | 中危 | 浏览器和大图同时处理时可能内存紧张 | 限制输入尺寸和并发；Spike 实测峰值；卸载验收按 §6.1 执行 |
| 5 | 输出保持源分辨率，大图会在合成和 PNG 编码阶段额外占用内存 | 中危 | 8K 图片可能瞬时占用数百 MB | 最长边和总像素双上限；超限 400；上限压测后调整 |
| 6 | 上游不做颜色去污染和边缘细化 | 低危，能力边界 | 透明边缘可能出现原背景色残留 | 在 §1.8 和 UI 说明中明确；不承诺「发丝级完美」 |
| 7 | 去掉引擎层后，加载、排队、卸载全部自研 | 中危 | 生命周期实现缺陷会表现为内存不回收或请求悬挂 | 复用 Hy-MT2、Ming 已验证的状态机与并发语义（§4.5），按 §6.5 第 12~15 项逐条验收 |
| 8 | 核心包停在 0.1.x，后续可能改名或改布局 | 低危 | 升级时编译失败或行为漂移 | 锁 `Package.resolved`；升级按独立任务处理 |
| 9 | 验收机为 macOS 15.7.9，与 macOS 14 运行门槛存在版本差 | 低危 | 未在 macOS 14 实机验证 | 验收记录写明实测系统版本；README 只承诺「macOS 14+」，不宣称已在 14 上验证 |

### 1.8 能力状态与承诺边界

| 能力 | 状态 | 依据 | v1 处理 |
| --- | --- | --- | --- |
| 单张图片抠图、输出软 alpha | 上游已验证 | 模型卡、Swift 端口 fixture | 开放 |
| 输出源分辨率 alpha | 上游已验证 | `maskAtSource`、`maskCGImage()` | 开放 |
| 透明底 PNG（cutout） | 待本项目验证 | 需要自行合成 RGBA | Spike 后开放，默认形态 |
| 灰度遮罩 PNG（mask） | 待本项目验证 | 上游直接给出 8-bit 灰度图 | Spike 后开放 |
| JPEG、PNG、WebP 输入 | 待本项目验证 | ImageIO 解码能力 | Spike 后开放 |
| 颜色去污染、边缘细化 | 不承诺 | 上游明确未移植 | 不实现，文档写明 |
| 2048² best 档 | 不承诺 | 需要 HR 权重和更高内存 | 不下载、不暴露 |
| Lucida 细调族 | 不承诺 | 另一套权重 | 不接入 |
| 批量、视频、背景替换 | 不承诺 | 超出本期范围 | 不实现 |

> 「上游已验证」只表示转换方给出过验证结果，本项目仍需在验收机上跑通核心包自带测试后才能把对应能力写进 README 状态表（BR-44、BR-45）。

---

## 2. UML 用例模型

### 2.1 系统用例图

```text
                    ┌──────────────────────────────────────┐
                    │      MlxForge BiRefNet 运行时         │
                    │                                      │
  ┌──────────┐      │  UC-01 安装环境与下载权重             │
  │  本机用户  │─────►│  UC-02 命令行抠图                     │
  └──────────┘      │  UC-03 启动与停止服务                 │
        │           │  UC-06 空闲释放与重新加载             │
        │           │  UC-07 在 Web UI 中抠图               │
        │           │                                      │
  ┌──────────┐      │  UC-04 调用抠图 API                   │
  │  下游应用  │─────►│  UC-05 查看服务状态                   │
  └──────────┘      │  UC-08 处理错误与排障                 │
                    └──────────────────────────────────────┘
```

### 2.2 参与者

| 参与者 | 描述 | 主要诉求 |
| --- | --- | --- |
| 本机用户 | 在 Mac 上安装、启动、排查服务的开发者或运维 | 装得上、看得见状态、出问题能定位 |
| 下游应用 | 通过 HTTP 上传图片并获取 PNG 的程序 | 接口稳定、输出尺寸明确、错误可判断 |
| Web 访问者 | 用浏览器抠图的普通用户 | 打开就能用，不需要理解模型和参数 |

### 2.3 用例列表

| 编号 | 名称 | 参与者 | 优先级 |
| --- | --- | --- | --- |
| UC-01 | 安装环境与下载权重 | 本机用户 | 高 |
| UC-02 | 命令行抠图 | 本机用户 | 高 |
| UC-03 | 启动与停止服务 | 本机用户 | 高 |
| UC-04 | 调用抠图 API | 下游应用 | 高 |
| UC-05 | 查看服务状态 | 本机用户、下游应用 | 高 |
| UC-06 | 空闲释放与重新加载 | 系统 | 高 |
| UC-07 | 在 Web UI 中抠图 | Web 访问者 | 中 |
| UC-08 | 处理错误与排障 | 本机用户、下游应用 | 高 |

### 2.4 用例关系

- UC-07 包含 UC-04，Web UI 不单独实现推理通道。
- UC-03 包含 UC-06，服务进程负责生命周期，用户不手工卸载。
- UC-02 与 UC-04 共用同一套预处理、推理和后处理，只替换 I/O 入口。
- UC-08 被 UC-01、UC-02、UC-03、UC-04、UC-07 共用。

---

## 3. 详细用例规格

### UC-01 安装环境与下载权重

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-01 |
| 参与者 | 本机用户 |
| 优先级 | 高 |
| 前置条件 | Apple Silicon Mac，macOS 14 及以上；构建机另需 macOS 15.6 及以上与 Xcode 26（Swift 6.2）；磁盘剩余空间不少于 5GB |
| 后置条件 | `runtimes/birefnet/.build/release/` 下有 `birefnet-server`、`birefnet-cli` 和 `mlx.metallib`；`models/birefnet/fp16/` 含完整权重和许可证 |
| 基本事件流 | 1. 用户执行 `./scripts/setup_birefnet.sh`<br>2. 脚本检查芯片架构、macOS ≥14、`swift --version` ≥6.2 和 Xcode 26 可用性，任一不满足则说明原因并退出<br>3. 脚本检查权重目录，缺失或不完整时按锁定 revision 从 ModelScope 下载到临时目录<br>4. 脚本校验 `model.safetensors` 的 SHA-256，通过后原子替换到 `models/birefnet/fp16/`，写入 `.revision` 和 `.checksums`<br>5. 脚本保存上游 README、许可证和来源说明<br>6. 脚本在 `runtimes/birefnet/` 执行 `swift build -c release`<br>7. 脚本执行 `scripts/build_metallib.sh`，把 `mlx-swift` 检出的 Metal 源码编译成 `mlx.metallib` 放到可执行文件同目录<br>8. 脚本自检 `mlx.metallib` 存在且非空，输出构建产物、权重路径和下一步命令 |
| 备选事件流 | 1a. Intel Mac：直接退出，说明只支持 Apple Silicon<br>2a. macOS 低于 14：直接退出，说明本运行时的运行门槛<br>2b. Swift 工具链低于 6.2 或 Xcode 26 缺失：说明需升级到 Xcode 26，并提示其宿主需 macOS 15.6+<br>2c. `swift build --build-system swiftbuild` 报 Metal 工具链错误：不阻塞，按固定流程走 `native` + `build_metallib.sh`<br>7a. `mlx.metallib` 未生成：视为构建失败，非零退出<br>3a. 权重已存在且 revision、校验和一致：跳过下载<br>3b. 权重存在但校验不一致：重新下载覆盖，不直接复用旧文件<br>3c. ModelScope 不可达：提示手动下载地址和放置路径，非零退出<br>3d. 下载中断：保留分片，重跑时继续<br>4a. SHA-256 不匹配：临时目录标记失败，保留原可用权重，非零退出<br>6a. 构建失败：保留日志，非零退出；不得留下半成品可执行文件冒充成功 |
| 业务规则 | BR-01、BR-02、BR-03、BR-04、BR-05、BR-06、BR-50 |

**数据说明表：环境与权重（install_state）**

| 字段 | 中文名 | 类型 | 取值范围 | 必填 | 说明 |
| --- | --- | --- | --- | --- | --- |
| platform | 平台 | string | `macOS` | 是 | 仅 Apple Silicon |
| macos_min | 运行门槛 | string | `14` | 是 | 来自 `mlx-swift-BiRefNet` 的 `.macOS(.v14)`；`mlx-swift` 0.31.x 未声明 platforms |
| build_host_macos | 构建机门槛 | string | `15.6` | 是 | Xcode 26 的宿主要求 |
| swift_version | Swift 版本 | string | `>=6.2` | 是 | 来自 Xcode 26 |
| build_command | 构建命令 | string | `swift build -c release && scripts/build_metallib.sh` | 是 | 两步：先出可执行文件，再出 `mlx.metallib` |
| metal_library | Metal 内核产物 | path | `runtimes/birefnet/.build/release/mlx.metallib` | 是 | 必须与可执行文件同目录，缺失则运行失败 |
| model_id | 权重来源 | string | `bujidc/mlx-community_BiRefNet-fp16` | 是 | ModelScope |
| revision | 权重版本 | string | `b9f39904c60ed2bc11c2fd5bdb005872a8eb2d34` | 是 | 锁定 revision |
| weights_dir | 权重目录 | path | `models/birefnet/fp16` | 是 | 不入库 |
| required_files | 必需文件 | list | `model.safetensors`、`README.md`、`LICENSE`、`.revision`、`.checksums` | 是 | 缺一不可 |
| weights_sha256 | 权重校验和 | string | `f1ba66260085fd8d471323dab098fabd36499ad54b0de8ca67deb5d1cf1f0c0e` | 是 | 安装时校验 |
| build_dir | 构建产物 | path | `runtimes/birefnet/.build/release/` | 是 | 不入库 |

**接口说明**：无外部接口，产出两个可执行文件和一个权重目录。

---

### UC-02 命令行抠图

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-02 |
| 参与者 | 本机用户 |
| 优先级 | 高 |
| 前置条件 | UC-01 完成 |
| 后置条件 | 生成一个 PNG 文件，标准输出打印文件路径，进程退出并释放内存 |
| 基本事件流 | 1. 用户执行 `runtimes/birefnet/.build/release/birefnet-cli --input photo.jpg --output cutout.png --mode cutout`<br>2. 程序解析参数并执行与 API 相同的图片校验<br>3. 程序按需加载模型<br>4. 程序解码图片、归一化方向、执行推理、编码 PNG<br>5. 文件写入 `--output`，日志写标准错误<br>6. 标准输出打印输出文件的绝对路径，退出码 0 |
| 备选事件流 | 1a. 缺少 `--input` 或文件不存在：打印用法，退出码 2<br>1b. `--mode` 不是 `cutout` 或 `mask`：参数错误，退出码 2<br>1c. 输入超过大小或像素上限：参数错误，退出码 2<br>1d. 输入格式不支持或解码失败：参数错误，退出码 2<br>3a. 权重缺失或损坏：输出可读错误，退出码 1<br>3b. 模型加载失败：输出可读错误，退出码 1<br>4a. 推理或编码失败：输出可读错误，退出码 1<br>5a. 输出目录不存在：创建目录；创建失败退出码 1 |
| 业务规则 | BR-07、BR-08、BR-09、BR-11、BR-12、BR-13、BR-14、BR-15、BR-16、BR-17、BR-18、BR-20、BR-21 |

**数据说明表：命令行参数（cli_args）**

| 参数 | 中文名 | 类型 | 取值范围 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `--input` | 输入图片 | path | 可读文件 | 是 | 无 | PNG、JPEG、WebP |
| `--output` | 输出文件 | path | 可写路径 | 是 | 无 | 只写 PNG；扩展名必须为 `.png` |
| `--mode` | 输出形态 | enum | `cutout`、`mask` | 否 | `cutout` | 透明底或灰度遮罩 |
| `--weights` | 权重路径 | path | 默认取清单 | 否 | `models/birefnet/fp16` | 排障时可覆盖 |
| `--verbose` | 详细日志 | bool | 无 | 否 | `false` | 只增加诊断信息，不打印图片内容 |

**接口说明**：CLI 不启动 HTTP 服务，不读取 `runtime.toml` 以外的调度配置。

---

### UC-03 启动与停止服务

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-03 |
| 参与者 | 本机用户 |
| 优先级 | 高 |
| 前置条件 | UC-01 完成，`web/dist` 已构建（可选） |
| 后置条件 | 服务监听指定地址，`/health` 可访问；停止后进程退出，PID 文件清理 |
| 基本事件流 | 1. 用户执行 `./scripts/start_birefnet.sh`<br>2. 脚本检查可执行文件、权重目录和端口<br>3. 脚本以 `127.0.0.1:8000` 启动 `birefnet-server`<br>4. 服务完成初始化，加载 HTTP 路由，不预加载模型<br>5. 服务把启动时间、模式、host、端口、PID 写入 `logs/birefnet.log`<br>6. 用户执行 `./scripts/stop_birefnet.sh`，脚本按 PID 优雅终止 |
| 备选事件流 | 1a. 可执行文件不存在：提示先运行安装脚本，非零退出<br>2a. 权重缺失：提示先运行安装脚本，非零退出<br>2b. 端口被占用：直接报错，不自动换端口<br>3a. 用户传 `--daemon`：用 `nohup` 脱离终端，日志和 PID 规则不变<br>3b. 非回环 `--host` 未设 `BIREFNET_ALLOW_REMOTE=1`：启动失败并说明原因<br>6a. PID 文件缺失或进程不存在：提示当前未运行，非零退出<br>6b. 进程不响应 SIGTERM：等待超时后提示手动处理，不自动 `kill -9` |
| 业务规则 | BR-06、BR-07、BR-31、BR-33、BR-34、BR-49 |

**数据说明表：启动参数（server_args）**

| 参数 | 中文名 | 类型 | 取值范围 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `--host` | 监听地址 | string | IPv4 或主机名 | 否 | `127.0.0.1` | 非回环需显式授权 |
| `--port` | 监听端口 | int | 1~65535 | 否 | `8000` | 占用不自动切换 |
| `--weights` | 权重目录 | path | 默认取清单 | 否 | `models/birefnet/fp16` | 启动时固定 |
| `--idle-timeout` | 空闲秒数 | int | ≥0 | 否 | `1200` | 0 表示常驻 |
| `--web-root` | 前端产物 | path | 默认 `web/dist` | 否 | `web/dist` | 不存在时只影响页面 |
| `--daemon` | 后台运行 | bool | 无 | 否 | `false` | 由启动脚本处理 |

**接口说明**：服务启动后提供 `GET /health`、`GET /v1/models`、`POST /v1/images/matting` 和静态页面。

---

### UC-04 调用抠图 API

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-04 |
| 参与者 | 下游应用 |
| 优先级 | 高 |
| 前置条件 | 服务已启动；模型可加载 |
| 后置条件 | 返回 PNG 二进制；模型状态回到 `ready`；空闲计时从响应完成开始 |
| 基本事件流 | 1. 客户端向 `POST /v1/images/matting?output=cutout` 发送图片二进制，`Content-Type` 为 `image/png`、`image/jpeg` 或 `image/webp`<br>2. 服务检查请求体大小、Content-Type 和队列余量<br>3. 服务解码图片，应用 EXIF 方向，检查像素上限，转换为 sRGB<br>4. 服务把任务入队；首次请求先加载模型<br>5. 推理串行执行，得到源分辨率软 alpha<br>6. 按 `output` 合成 RGBA 或灰度 PNG<br>7. 返回 `200 image/png`，带尺寸和耗时响应头 |
| 备选事件流 | 2a. 请求体超过 20MB：413，不解析正文<br>2b. Content-Type 不支持：415<br>2c. 队列已满：429，`Retry-After: 5`<br>2d. 排队超过 120 秒：429<br>3a. 图片损坏或截断：400<br>3b. 像素超过上限：400<br>4a. 模型加载失败：503；进入 5 秒冷却<br>4b. 客户端在排队时断开：请求移出队列<br>5a. 推理异常：500，状态回 `ready`<br>6a. PNG 编码失败：500，不返回空文件<br>7a. 客户端在推理中断开：完成推理后丢弃结果，不写响应 |
| 业务规则 | BR-10、BR-11、BR-12、BR-13、BR-14、BR-15、BR-16、BR-17、BR-18、BR-19、BR-20、BR-21、BR-24、BR-25、BR-26、BR-27、BR-32 |

#### 请求定义

```http
POST /v1/images/matting?output=cutout
Content-Type: image/jpeg

<图片二进制>
```

| 位置 | 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- | --- |
| query | `output` | string | 否 | `cutout` | `cutout` 或 `mask`；其他值 400 |
| header | `Content-Type` | string | 是 | 无 | `image/png`、`image/jpeg`、`image/webp` |
| body | 图片 | binary | 是 | 无 | 原始字节，不使用 multipart |

> 该接口没有对应的 OpenAI 标准。项目不把它伪装成 `/v1/images/edits`，也不承诺 OpenAI SDK 兼容（BR-10）。

#### 响应定义

成功时返回纯 PNG 二进制：

| 响应头 | 说明 |
| --- | --- |
| `Content-Type` | 固定 `image/png` |
| `X-Request-Id` | 请求标识，UUID |
| `X-Output-Mode` | `cutout` 或 `mask` |
| `X-Image-Width` | 输出宽度，像素 |
| `X-Image-Height` | 输出高度，像素 |
| `X-Elapsed-Ms` | 服务端从解码到编码完成的耗时，毫秒 |
| `Content-Disposition` | `attachment; filename="cutout-<request_id>.png"` 或 `matte-<request_id>.png` |
| `Cache-Control` | `no-store` |

`cutout` 输出 RGBA PNG，alpha 为直通非预乘，RGB 保留原图颜色；`mask` 输出 8-bit 灰度 PNG，255 表示前景。两种输出的宽高都等于方向归一化后的原图宽高（BR-17、BR-20）。

#### 示例

```bash
curl -X POST "http://127.0.0.1:8000/v1/images/matting?output=cutout" \
  -H "Content-Type: image/jpeg" \
  --data-binary @photo.jpg \
  --output cutout.png
```

```bash
curl -X POST "http://127.0.0.1:8000/v1/images/matting?output=mask" \
  -H "Content-Type: image/png" \
  --data-binary @photo.png \
  --output mask.png
```

---

### UC-05 查看服务状态

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-05 |
| 参与者 | 本机用户、下游应用 |
| 优先级 | 高 |
| 前置条件 | 服务进程已启动 |
| 后置条件 | 返回模型列表和健康状态，不触发模型加载 |
| 基本事件流 | 1. 客户端请求 `GET /v1/models`，服务返回 `BiRefNet-fp16`<br>2. 客户端请求 `GET /health`，服务返回状态、空闲时间、内存和系统门槛<br>3. Web UI 每 5 秒轮询一次，用于状态徽标 |
| 备选事件流 | 1a. 模型列表构造失败：500，不返回半截 JSON<br>2a. 内存指标采集失败：对应字段返回 `null`，其他字段照常返回<br>2b. 加载失败：`status=degraded`，`state=failed`，带 `last_error` |
| 业务规则 | BR-22、BR-23、BR-43 |

#### `GET /v1/models` 响应

```json
{
  "object": "list",
  "data": [
    {
      "id": "BiRefNet-fp16",
      "object": "model",
      "created": 1792742400,
      "owned_by": "mlxforge"
    }
  ]
}
```

不触发模型加载。`created` 是进程启动时间。

#### `GET /health` 响应

```json
{
  "status": "ok",
  "state": "unloaded",
  "model_loaded": false,
  "idle_seconds": 0,
  "idle_timeout_seconds": 1200,
  "min_macos": "14",
  "memory": {
    "mlx_active_mb": 0,
    "mlx_peak_mb": 0,
    "mlx_cache_mb": 0,
    "footprint_mb": 42.1,
    "system_used_mb": 9876.5,
    "system_total_mb": 16384.0
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `status` | `ok` 可服务；`degraded` 表示加载失败或权重缺失 |
| `state` | `unloaded`、`loading`、`ready`、`generating`、`unloading`、`failed` |
| `model_loaded` | 权重是否在内存，`loading` 期间为 `false` |
| `idle_seconds` | 距最后一次抠图完成的秒数 |
| `idle_timeout_seconds` | 空闲阈值，`0` 表示常驻 |
| `min_macos` | 本运行时要求的最低系统版本 |
| `memory` | 内存快照，单位 MB；采集失败时字段为 `null` |
| `last_error` | 仅 `failed` 时出现，中文说明，不含堆栈和本地路径 |

---

### UC-06 空闲释放与重新加载

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-06 |
| 参与者 | 系统 |
| 优先级 | 高 |
| 前置条件 | 模型已加载，`state=ready` |
| 后置条件 | 权重引用释放，MLX 缓存清空，状态回到 `unloaded`；下一次请求重新加载 |
| 基本事件流 | 1. 空闲计时达到 `idle_timeout`<br>2. 服务确认队列为空且无在途推理<br>3. 释放管线与权重引用<br>4. 调用 MLX 清缓存接口，记录卸载前后内存<br>5. 状态改为 `unloaded`，记录日志<br>6. 新请求到达，重新进入 `loading` 并加载权重 |
| 备选事件流 | 2a. 队列非空或有在途任务：跳过本轮，等下一轮<br>3a. 释放过程中新请求到达：请求排队，等卸载完成后重新加载<br>4a. 清缓存失败：状态回 `ready`，记录日志，下一轮再试<br>5a. 重新加载失败：状态 `failed`，进入 5 秒冷却 |
| 业务规则 | BR-28、BR-29、BR-30、BR-31 |

---

### UC-07 在 Web UI 中抠图

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-07 |
| 参与者 | Web 访问者 |
| 优先级 | 中 |
| 前置条件 | 服务已启动；`web/dist` 已构建；当前服务运行的是 BiRefNet |
| 后置条件 | 页面展示原图、抠图结果和尺寸；用户可下载；刷新后图片清空 |
| 基本事件流 | 1. 用户打开 `/`，服务 307 跳转到 `/?page=matting`<br>2. 页面显示抠图页，隐藏翻译和语音页签<br>3. 用户点击选择或拖入一张 PNG、JPEG、WebP 图片<br>4. 页面本地预览，显示尺寸和文件大小，不发送请求<br>5. 用户选择「透明背景」或「黑白遮罩」，点击「开始抠图」<br>6. 页面把图片二进制直接 POST 到 `/v1/images/matting`<br>7. 页面展示结果，透明背景用棋盘格衬底；显示耗时和输出尺寸<br>8. 用户点击下载，浏览器保存 PNG |
| 备选事件流 | 2a. 当前服务不是 BiRefNet：页面提示「当前服务运行的是其他模型，抠图不可用」<br>3a. 文件超过 20MB 或像素上限：本地提示，不发请求<br>3b. 格式不在支持列表：本地提示<br>4a. 图片解码失败：显示「这张图片打不开，请换一张」<br>6a. 429：提示「前面还有任务，请稍后再试」，保留当前图片<br>6b. 400/413/415：显示服务端中文说明<br>6c. 503：提示模型准备失败，可重试<br>7a. 用户切换输出形态但未重新生成：结果区继续显示上一次结果，并标注形态<br>7b. 用户清除图片：释放预览和结果的 Object URL，回到空状态 |
| 业务规则 | BR-37、BR-38、BR-39、BR-40、BR-41 |

---

### UC-08 处理错误与排障

| 项目 | 内容 |
| --- | --- |
| 用例编号 | UC-08 |
| 参与者 | 本机用户、下游应用 |
| 优先级 | 高 |
| 前置条件 | 任一用例执行失败 |
| 后置条件 | 用户能定位到平台、构建、权重、输入、队列或模型加载中的具体环节 |
| 基本事件流 | 1. 服务按统一结构返回错误，日志记录时间、请求标识、状态码和错误类型<br>2. 本机用户查看 `logs/birefnet.log` 和 `/health`<br>3. 用户按错误提示修复：升级系统、重跑安装、换图片、等队列或重启服务 |
| 备选事件流 | 1a. 未预期异常：返回 500，堆栈只进日志<br>1b. 权重缺失：503，提示运行安装脚本<br>1c. 系统版本不满足：服务启动阶段失败并写日志<br>1d. 端口占用：启动失败，提示换端口或停止占用进程 |
| 业务规则 | BR-32、BR-33、BR-34、BR-35、BR-36、BR-42、BR-47 |

---

## 4. 交互设计

### 4.1 整体流程

```text
安装（一次性）
  setup_birefnet.sh
    ├─ 检查 Apple Silicon / macOS 14+ / Swift 6.2+
    ├─ 下载并校验 models/birefnet/fp16
    └─ swift build -c release && scripts/build_metallib.sh

使用
  ├─ CLI ── 加载 ── 解码 ── 推理 ── 编码 ── 写文件 ── 退出
  └─ 服务 ── 启动（不加载）
              ├─ 请求 ── 校验 ── 入队 ── 加载（首次）── 推理 ── 响应
              ├─ 空闲到阈值 ── 卸载
              └─ 新请求 ── 重新加载
```

### 4.2 首次请求子流程

```text
请求到达
  │
  ├─ 请求体超过 20MB ──► 413（不解析正文）
  │
  ├─ Content-Type 不是 PNG/JPEG/WebP ──► 415
  │
  ├─ 解码失败或 EXIF 处理失败 ──► 400
  │
  ├─ 像素超过上限 ──► 400
  │
  ├─ output 不是 cutout/mask ──► 400
  │
  ├─ 队列已满 ──► 429
  │
  └─ 入队
        │
        ├─ 模型已加载 ──► 推理
        │
        └─ 模型未加载 ──► 加载 ──► 成功 ──► 推理
                              │
                              └─ 失败 ──► 503（冷却 5 秒）
```

### 4.3 图片数据流

```text
原始字节
  │
  ├─ SizeGuard：字节数、Content-Type
  ▼
ImageIO 解码
  │
  ├─ EXIF 方向归一化
  ├─ 色彩转换到 sRGB
  └─ 已有 alpha 合成到白底
  ▼
PixelGuard：最长边、总像素
  │
  ▼
BiRefNet 预处理：缩放到 1024×1024（`BIREFNET_INPUT_SIZE` 可调）
  │
  ▼
BiRefNet 推理：输出 1024×1024 sigmoid alpha
  │
  ├─ 重采样回源分辨率
  ▼
后处理
  ├─ cutout：源 RGB + alpha → RGBA PNG（直通 alpha）
  └─ mask：alpha → 8-bit 灰度 PNG
  ▼
PNG 二进制响应
```

### 4.4 状态机

```text
Unloaded ──首次请求──► Loading ──成功──► Ready ──请求──► Generating
   ▲                     │                 ▲                 │
   │                     │ 失败            │ 推理完成         │
   │                     ▼                 └─────────────────┘
   │                   Failed
   │
   └── Unloading ◄── 空闲达到阈值且无在途请求 ── Ready
```

| 状态 | 含义 | 进入条件 | 允许操作 | 退出条件 | 异常恢复 |
| --- | --- | --- | --- | --- | --- |
| `unloaded` | 进程已启动，权重不在内存 | 进程启动完成；卸载成功 | 接受请求，首个请求触发加载 | 收到抠图任务 → `loading` | — |
| `loading` | 正在读取权重并注册管线 | 首个请求；卸载后首个请求 | 新请求排队；`/health` 返回 `loading` | 加载成功 → `ready`；失败 → `failed` | 失败时释放半成品引用并清缓存，写入 `last_error` |
| `ready` | 权重在内存，可立即推理 | 加载成功；推理结束；卸载失败回退 | 接受请求；空闲检查可投递卸载任务 | 收到任务 → `generating`；空闲达阈值 → `unloading` | — |
| `generating` | 正在解码、推理或编码 | 从队列取出任务 | 新请求排队；`/health` 返回 `generating` | 成功或失败 → `ready` | 推理异常返回 500，状态回 `ready`，不触发卸载 |
| `unloading` | 正在释放权重和缓存 | 空闲达阈值，且队列为空、无在途任务 | 新请求排队，等待卸载后重新加载 | 释放完成 → `unloaded` | 释放异常回 `ready`，记录日志，下轮再试 |
| `failed` | 加载失败，处于 5 秒冷却 | 加载失败 | 冷却期内请求直接 503；`/health` 返回 `failed` | 冷却结束后的首个请求 → `loading` | `last_error` 保留到下次加载成功 |

> `state` 只允许表中六个取值，实现不得增加未登记状态（BR-29）。`unloading` 期间到达的请求不改变状态，由 worker 在卸载完成后接着加载。

### 4.5 非流式抠图时序

```text
客户端                SwiftNIO 事件循环          推理 Actor               MLXEngine / BiRefNet
  │ POST 图片               │                         │                         │
  │────────────────────────►│ 校验、解码、入队         │                         │
  │                         │────────────────────────►│ 加载（首次）             │
  │                         │                         │────────────────────────►│
  │                         │                         │ 推理 1024²              │
  │                         │                         │◄────────────────────────│
  │                         │                         │ 重采样、合成、PNG 编码   │
  │                         │◄────────────────────────│ PNG                     │
  │◄────────────────────────│ 200 image/png           │                         │
```

### 4.6 空闲卸载时序

```text
空闲计时器            推理 Actor              共享状态
  │ 每 10 秒检查           │                       │
  │───────────────────────►│ 队列空且在途为 0？      │
  │                        │──────────────────────►│
  │                        │◄──────────────────────│ 是，且空闲达到阈值
  │                        │ 释放引用、trimCaches() │
  │                        │──────────────────────►│ 状态改为 Unloaded
  │ 下一轮                 │                       │
```

### 4.7 线程模型

```text
SwiftNIO 事件循环（多个 EventLoop）
  ├─ 接收请求、Content-Type/大小校验、路由、错误映射
  ├─ 静态文件与 Web UI
  └─ 把图片解码、推理、PNG 编码投递到推理 Actor

推理 Actor（单实例，唯一持有管线与权重）
  ├─ 加载、推理、卸载
  ├─ 同一时刻只处理一个任务
  └─ 与事件循环通过有界队列和 continuation 通信

空闲计时器（独立 DispatchSourceTimer）
  └─ 到达阈值且队列为空时，向推理 Actor 投递卸载任务
```

> 图片解码和 PNG 编码属于 CPU 密集操作，不能放在 NIO 事件循环线程上执行（BR-46）；它们与推理一起进入同一个串行 Actor，避免并发进 Metal。

### 4.8 并发约束与竞态

| # | 场景 | 危害 | 规则 |
| --- | --- | --- | --- |
| 1 | 空闲卸载与在途推理重叠 | 推理中模型被释放，进程崩溃 | 卸载任务与推理任务同队列，队列为空且无在途时才卸载（BR-28、BR-29） |
| 2 | 多个请求同时到达 | 同时进 Metal，内存翻倍或结果串线 | 单 Actor 串行推理（BR-24） |
| 3 | 请求风暴 | 队列无限增长，内存和延迟失控 | 等待队列上限 8（不含在途），余量检查和入队原子完成，第 9 个 429（BR-25） |
| 4 | 排队超时与出队同时发生 | 请求被重复处理或状态错乱 | 出队与超时标记在同一临界区完成（BR-26） |
| 5 | 客户端排队时断开 | 无效任务占用推理时间 | 排队中的请求移出队列；已开始推理的走完并丢弃结果（BR-27） |
| 6 | 客户端推理时断开 | 推理继续占用资源 | v1 不取消，完成后丢弃结果（BR-27） |
| 7 | 加载失败后连续重试 | 每次请求都触发一次加载 | 失败后冷却 5 秒，冷却期内共享同一个失败结果（BR-30） |
| 8 | SIGTERM 时正在推理 | 结果丢失或进程卡住 | 停止接新请求，队列请求 503，在途最多等 120 秒（BR-31） |
| 9 | 两个进程抢同一端口 | 后启动的失败 | 启动时报错，不自动换端口（BR-49） |
| 10 | 运行中修改权重目录 | 新旧权重混用 | 权重路径启动时固定，修改需重启（BR-50） |
| 11 | 加载期间查询健康状态 | 页面误显示「已就绪」 | `/health` 必须返回 `state=loading`（BR-23） |
| 12 | 卸载过程中到达新请求 | 请求被拒绝或状态卡住 | 请求排队，卸载完成后由 Actor 重新加载（BR-29） |
| 13 | 大图解码后才发现超限 | 先吃满内存再拒绝 | 先查字节数和内容类型，解码后立即查像素；编码前再查输出尺寸（BR-12、BR-13） |
| 14 | 前端超时，服务端仍在推理 | 用户重复提交，队列堆满 | 前端只停止等待并提示结果未知；重复提交需二次确认（BR-40） |
| 15 | 关闭时队列 continuation 未完成 | 调用方一直等待，进程无法退出 | 关闭时取消所有排队 continuation 并返回 503（BR-31） |

---

## 5. UI 设计规范

### 5.1 线框图

```text
┌──────────────────────────────────────────────────────────────┐
│ BiRefNet 图片抠图                      [已就绪 · 内存 42 MB] │
│ 运行在 Apple Silicon 上的本地模型服务                         │
├──────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────┐  ┌────────────────────────┐  │
│  │  拖入图片，或点击选择       │  │  结果                  │  │
│  │  PNG / JPEG / WebP          │  │  ┌──────────────────┐  │  │
│  │  最大 20MB，最长边 8192     │  │  │  棋盘格 + 抠图    │  │  │
│  │                            │  │  └──────────────────┘  │  │
│  │  [缩略图预览]               │  │  1200×800 · 用时 0.8s   │  │
│  └────────────────────────────┘  └────────────────────────┘  │
│                                                              │
│  输出形态  ( 透明背景 | 黑白遮罩 )                            │
│  [开始抠图]  [下载 PNG]  [清除]                               │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 组件

| 组件 | 职责 | 交互 |
| --- | --- | --- |
| `MattingPanel.vue` | 页面容器、状态编排 | 选择图片、切换形态、发起/取消请求、下载 |
| `useMatting.ts` | 请求状态、Object URL 生命周期、错误文案 | 不直接操作 DOM |
| `api/matting.ts` | 封装 `POST /v1/images/matting` | 传入 Blob 和 output，返回 Blob 与头部信息 |
| `ServiceStatus.vue` | 复用现有状态徽标和内存提示 | 只增加抠图状态文案映射 |
| `App.vue` | 页面切换和 `?page=matting` 锁定 | 增加第三个页面 key 和模型可用性判断 |
| `api/models.ts` | 模型 ID 到可用性的映射 | 增加 `BiRefNet-fp16` → `birefnet` |

### 5.3 视觉规范

- 复用 TDesign 变量和现有 `app.css`，不新增主题色。
- 页面最大宽度与翻译页、语音页一致；窄屏时上下堆叠，结果区在图片区下方。
- 透明结果使用棋盘格背景，棋盘格用 CSS 渐变实现，不引用外部图片。
- 主按钮为「开始抠图」；处理中按钮显示加载态并禁用重复提交。
- 页面不展示模型文件名、权重路径、Swift 包名、张量形状、sigmoid 等技术术语。

### 5.4 页面状态

| 状态 | 页面表现 | 用户可操作 |
| --- | --- | --- |
| 服务不可达 | 顶部提示「服务未启动」 | 无法抠图 |
| 其他模型在跑 | 提示「当前服务运行的是其他模型，抠图不可用」 | 无法抠图 |
| 空状态 | 上传区高亮，结果区显示占位说明 | 选择或拖入图片 |
| 已选图片 | 显示预览、尺寸、文件大小 | 切换形态、开始抠图、清除 |
| 处理中 | 按钮加载态，结果区显示「正在抠图」 | 等待；可取消等待 |
| 成功 | 显示结果和尺寸、耗时 | 下载、切换形态后重新生成、清除 |
| 输入错误 | 上传区下方显示中文原因 | 换图或调整 |
| 服务错误 | 结果区显示错误提示，保留原图 | 重试或换图 |
| 等待超时 | 提示「等待时间较长，结果可能稍后完成」 | 二次确认后重试 |

### 5.5 字段可见性

| 字段 | 是否可见 | 说明 |
| --- | --- | --- |
| 输出形态 | 是 | 唯一用户配置项：透明背景 / 黑白遮罩 |
| 图片尺寸 | 是，只读 | 选择后显示，便于判断是否超限 |
| 文件大小 | 是，只读 | 选择后显示 |
| 处理耗时 | 是，只读 | 来自 `X-Elapsed-Ms` |
| 阈值、采样 | 否 | 不暴露，也没有可调参数 |
| 模型输入尺寸 | 否 | 只由部署方用 `BIREFNET_INPUT_SIZE` 调整，Web UI 和 API 都不暴露 |
| 权重路径、系统版本 | 否 | 只在日志和排障文档中出现 |

---

## 6. 非功能需求

### 6.1 性能

性能验收必须同时看 MLX 侧和进程侧：前者说明框架缓存是否清空，后者说明内存是否还给系统。

| 指标 | 测量口径 | 通过条件 |
| --- | --- | --- |
| 构建耗时 | 全新克隆后执行安装脚本，从开始到两个可执行文件可用 | 记录一次冷构建值，不设硬门槛 |
| 进程冷启动 | 启动服务到 `/health` 可响应，不触发加载 | 记录 P50/P95，连续 5 次 |
| 首次请求耗时 | 冷启动后，1024×1024 JPEG 请求到 PNG 返回，包含加载、推理和编码 | 单独记录，不与热请求混算 |
| 热请求耗时 | 权重已加载、`state=ready`，1024×1024 JPEG，预热 1 次后连续 5 轮 | 记录 P50/P95、最大值和最小值 |
| 大图耗时 | 4096×4096 JPEG，热状态，连续 5 轮 | 记录 P50/P95，同时记录峰值内存 |
| 峰值内存 | 推理期间 1Hz 采样，同时记录 MLX 指标和进程物理内存 | 记录绝对值，并与 420 MiB 权重对照 |
| 卸载后 MLX 缓存 | 卸载完成 0/5/30/60 秒各记录一次 | 相对加载前基线的增量 ≤ 峰值增量的 10% |
| 卸载后进程内存 | 卸载完成 0/5/30/60 秒各记录一次 | 60 秒时 ≤ 基线 + max(200MB, 峰值增量×20%) |
| 重载成功率 | 卸载后连续 5 次请求 | 5/5 成功 |
| 并发稳定性 | 20 个并发的 1024×1024 请求 | 恰好 9 个被接受（1 在途 + 8 等待）且全部成功；恰好 11 个 429，`Retry-After` 均为 5 秒 |
| 输出正确性 | 同输入分别走 CLI 和 API | alpha 最大差值 ≤1/255；尺寸一致 |
| 质量回归 | 核心包自带测试 + 20 张回归图 | 测试通过；人工无主体缺失、边缘断裂、方向错误 |

> 本 PRD 不为耗时设硬门槛。首次实测后，把结果写入 [benchmarks.md](benchmarks.md)，再决定是否冻结上限；在此之前 README 只写「待实测」。

#### 6.1.1 测量协议

| 项目 | 要求 |
| --- | --- |
| 硬件记录 | 芯片型号、统一内存大小、macOS 版本 |
| 软件记录 | Swift 与 Xcode 版本、SwiftPM 解析版本、`mlx-swift-BiRefNet`、`mlx-swift`、`swift-nio`、`swift-argument-parser` 版本 |
| 权重记录 | revision、SHA-256、文件大小、精度 |
| 预热 | 每个指标正式测量前先完成 1 次完整抠图，结果丢弃 |
| 轮次 | 早期验收每项 5 轮；对外公布 P95 至少 20 轮 |
| 统计方法 | 分位数采用 nearest-rank 法，即升序排列后取第 `ceil(p×n)` 个值；保留每轮原始值 |
| 采样 | 内存按 1Hz 采样，记录采样工具和命令 |
| 固定样本 | 1024×1024 人像、4096×4096 人像、透明物体、发丝、文字图各一组 |
| 冷热分离 | 冷启动必须重启进程；热启动必须确认 `state=ready` |
| 记录文件 | [benchmarks.md](benchmarks.md)，每轮一行，含日期、机器、参数和原始数值 |

**上游参考值（不是本项目实测）**

| 指标 | 上游声明 | 来源 |
| --- | --- | --- |
| 权重体积 | 440,483,842 字节 | ModelScope 文件元数据 |
| fp16 推理耗时（1024²） | 约 0.261 秒，mean，未指明芯片型号 | `mlx-swift-BiRefNet` 基准表 |
| fp16 端到端耗时（1024²） | 约 0.277 秒 | 同上 |
| fp16 冷加载 | 约 0.036 秒，仅模型加载 | 同上 |
| fp16 峰值内存 | 约 4.9GB | `mlx-birefnet-swift` README（含 MLXEngine 层开销，本项目只跑核心包，数值不可直接沿用） |
| 与 PyTorch 对齐 | IoU 0.9905 | 模型卡、Swift 端口 |

> 上游基准机只写「Apple Silicon m-series」，没有芯片型号和内存大小，不能作为本项目性能承诺，也不能外推到 M2 16GB。

### 6.2 兼容性

| 项目 | 要求 |
| --- | --- |
| 硬件 | Apple Silicon（M1 及以上）；M1 只保证功能可运行，性能另行实测 |
| 系统 | 运行 macOS 14 及以上；构建机 macOS 15.6 及以上 |
| 工具链 | Swift 6.2 / Xcode 26 及以上；构建产物可在 macOS 14+ 运行 |
| 构建系统 | `swift build`（native）+ `scripts/build_metallib.sh`；不用 `--build-system swiftbuild`（Xcode 26.2 上被 Metal 工具链 bug 阻塞） |
| 推理后端 | `mlx-swift-BiRefNet` + `mlx-swift`，全部走 MLX；不引入 `mlx-engine-swift` |
| HTTP | HTTP/1.1，SwiftNIO；不实现 HTTP/2、HTTP/3 |
| 输入图片 | PNG、JPEG、WebP；≤20MB；最长边 ≤8192；总像素 ≤3200 万 |
| 输出图片 | PNG；cutout 为 RGBA，mask 为 8-bit 灰度 |
| 浏览器 | Safari、Chrome、Edge 最近两个大版本 |
| 不支持 | Intel Mac、Linux、Windows、Docker、iOS、批量、视频、2048²、Lucida、流式进度 |

**功能兼容范围与性能验收基准分开**

| 类别 | 范围 | 承诺 |
| --- | --- | --- |
| 功能兼容 | Apple Silicon M1 及以上，macOS 14+ | 保证可启动、可抠图、UI 可用；不承诺具体耗时 |
| 性能验收 | 当前可用验收机（待确认芯片与内存） | §6.1 的指标只对记录中的机型生效 |
| 未实测机型 | 其他 Apple Silicon + macOS 14+ | 只保证功能，不引用他机数字 |

> README 必须分运行时列出系统要求。本运行时与 Hy-MT2、Ming-3.0-tts 的运行门槛同为 macOS 14+，但构建门槛不同：本运行时需要 Swift 6.2 / Xcode 26，且不引入 MLXEngine 的 26.2 要求。
>
> `min_macos` 只约束运行期。构建机的 macOS 版本不写进清单，由安装脚本按 Xcode 26 的宿主版本要求单独检查。

### 6.3 安全与隐私

**监听与访问控制**

- 默认只监听 `127.0.0.1`。
- 指定非回环 `--host` 时必须同时设置 `BIREFNET_ALLOW_REMOTE=1`，否则启动失败并说明原因（BR-33）。
- 默认不启用 CORS，不返回 `Access-Control-Allow-Origin`。
- 校验 `Host` 头，只接受回环地址、配置的监听地址、本机各网卡 IPv4、本机主机名和 `.local` 名称；`0.0.0.0` 本身不是合法 Host，不能作为放行依据（BR-34）。
- v1 没有鉴权，开放到局域网等于把抠图能力暴露给同网段，README 必须写明。

**图片与日志**

- 图片只在内存中解码和推理，不写仓库、`models/`、`output/` 或用户目录（BR-35）。
- 无论 INFO 还是 DEBUG，都不得记录图片字节、base64、完整请求体、输出图片和本地绝对路径（BR-35）。
- 日志只记录请求标识、状态码、错误类型、耗时、尺寸和模型状态。
- 不采集遥测，不调用外部服务；安装完成后运行期无外发请求（BR-36）。
- Web UI 不引用 CDN、外部字体或第三方脚本；图片刷新即清空（BR-39）。

**供应链**

- 权重只从锁定来源下载，安装时校验不可变 revision 与 SHA-256（BR-04）。
- Swift 包依赖提交 `Package.resolved`，构建前记录实际解析版本（BR-03）。
- 本地计算的校验和只证明完整性，不证明来源可信；README 必须区分这两件事。
- 安装后保留上游 `LICENSE`、`NOTICE` 和来源说明（BR-47）。

### 6.4 可靠性

- 单个请求失败不影响进程，后续请求可继续。
- 模型加载失败返回 503，允许重试，不需要重启进程。
- 健康检查不触发模型加载，不阻塞推理。
- 收到 SIGTERM 后停止接新请求，队列请求返回 503，在途任务最多等 120 秒（BR-31）。
- 崩溃后不自动重启，由用户或外部进程管理器决定。
- 输出为空、PNG 编码失败或尺寸不一致时返回 500，不返回 0 字节文件。
- v1 不设推理超时，只受排队超时和关闭等待约束。

### 6.5 技术验证清单

排期前必须完成以下验证，结论写入 [benchmarks.md](benchmarks.md)。未通过的项对应的能力从 UI 和 README 移除。

| # | 验证项 | 通过标准 |
| --- | --- | --- |
| 1 | Swift 6.2 构建 + macOS 14 运行门槛 | `swift build -c release` 成功，`scripts/build_metallib.sh` 产出非空 `mlx.metallib` 并与可执行文件同目录；`otool -l` 显示 `LC_BUILD_VERSION minos` ≤ 14；不带 metallib 启动必须明确报错 |
| 2 | 消费 ModelScope 权重 | `MLXBiRefNet.fromPretrained("models/birefnet/fp16/model.safetensors", dtype: .float16)` 加载成功，不触发运行期下载 |
| 3 | 权重 key 布局兼容 | 严格加载后 687 个张量全部匹配，无缺失或多余 key；实测输出与 PyTorch 参考的 IoU 达到上游声明量级 |
| 4 | 核心包测试 | 核心包自带测试通过；`birefnet-bench` 可在本机跑出 1024² 的耗时与峰值内存 |
| 5 | 源分辨率输出 | 1024²、1598×1600、4096×4096 输入都能得到同尺寸 mask |
| 6 | cutout 合成 | RGBA 直通 alpha 正确，棋盘格预览无黑边或白边 |
| 7 | 图片格式 | PNG、JPEG、WebP 均可解码；损坏文件返回 400 |
| 8 | EXIF 方向 | 带 90°/180°/270° 方向的手机照片输出方向正确 |
| 9 | 透明输入 | 已有 alpha 的 PNG 先合成白底再推理，不出现黑边 |
| 10 | 色彩管理 | sRGB 输入输出一致；不出现明显偏色 |
| 11 | 大图上限 | 8192 边界和 3200 万像素边界可判定；超限 400 |
| 12 | 内存与卸载 | 按 §6.1 测量；卸载后 MLX 缓存和进程内存均回落 |
| 13 | 队列语义 | 1 在途 + 8 等待正常；第 9 个等待 429；排队超时 429；`Retry-After` 为 5 秒 |
| 14 | 断开与退出 | 排队中断开不进入推理；推理中断开不崩溃；SIGTERM 后队列 503 且 continuation 清理 |
| 15 | 状态机 | 六个状态的进入、退出和异常恢复逐条验证；`/health` 与实际一致 |
| 16 | 健康内存字段 | MLX 指标、进程物理内存、整机内存均可采集；失败时字段为 `null` |
| 17 | 静态站点 | `web/dist` 存在时页面可访问；不存在时 API 正常、`/` 返回明确提示 |
| 18 | 页面锁定 | 单模型启动 `/` 307 到 `/?page=matting`，其他页签隐藏 |
| 19 | 远程门禁 | 未设 `BIREFNET_ALLOW_REMOTE=1` 时非回环 host 启动失败；默认无 CORS 头 |
| 20 | Host 校验 | `Host: 0.0.0.0` 被拒绝；`127.0.0.1`、`localhost`、本机网卡地址、`.local` 被接受 |
| 21 | 断网运行 | 安装完成后首次加载、失败重试、健康检查、UI 抠图和下载均可用 |
| 22 | 依赖复现与版本锁定 | 清空 `.build` 后重装，解析版本与 `Package.resolved` 一致；`mlx-swift` 固定在 0.31.4，未被解析到 0.31.5+ |
| 23 | 端口冲突 | 端口占用时启动失败，不自动换端口 |
| 24 | 前端资源 | 替换图片、清除、组件卸载时 Object URL 均被 revoke；刷新后无残留 |
| 25 | 错误映射 | 400/413/415/429/500/503 逐条构造验证，message 为中文且不含路径和堆栈 |
| 26 | 浏览器兼容 | Safari、Chrome、Edge 最近两个大版本均可选择、预览、抠图、下载 |
| 27 | 权重下载 | 断点续传、revision 校验、SHA-256 校验、原子替换均验证 |
| 28 | 内容不落盘 | 抠图前后检查仓库、`output/`、临时目录和日志，无图片残留 |

---

## 7. 附录

### 7.1 术语表

| 术语 | 含义 |
| --- | --- |
| MLX | Apple 为 Apple Silicon 提供的数组与机器学习框架 |
| mlx-swift | MLX 的 Swift 绑定 |
| mlx-swift-BiRefNet | BiRefNet 的 Swift/MLX 核心端口，提供 `MLXBiRefNet`、`BiRefNetPipeline`；本项目唯一的模型依赖 |
| mlx-birefnet-swift | 上游对同一核心的 MLXEngine 包装仓库，模型卡引用它；本项目不采用其包装层 |
| MLXEngine | `mlx-engine-swift` 提供的运行时协调器；声明 `.macOS(.v26)`，26.2+ 才能用 Neural Accelerators，本项目不引入 |
| BiRefNet | Swin-L + ASPP-Deformable 的前景分割模型，输出单通道软 alpha |
| 软 alpha | 0~1 的透明度值，不是非黑即白的硬边蒙版 |
| cutout | 源图 RGB 加 alpha 合成的透明底 PNG |
| mask | 单通道灰度 PNG，255 表示前景 |
| 直通 alpha | 非预乘 alpha，RGB 与透明度分开存储 |
| EXIF 方向 | 手机照片记录在元数据中的旋转信息 |
| SwiftPM | Swift 的包管理与构建工具 |
| `swiftbuild` | SwiftPM 的构建系统；本机实测在 Xcode 26.2 上无法调起 Metal 编译器，故不采用 |
| `mlx.metallib` | MLX 的 Metal 内核预编译产物，必须与可执行文件同目录，缺失则运行期初始化失败 |

### 7.2 数据对象

**A-1 运行时清单（runtime.toml）**

```toml
name = "birefnet"
runtime = "swift"
build = "swift build -c release && scripts/build_metallib.sh"
entry = "runtimes/birefnet/.build/release/birefnet-server"
weights = "models/birefnet/fp16"
idle_timeout = 1200
min_macos = "14"
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | string | 与 `runtimes/` 目录名一致 |
| `runtime` | string | 固定 `swift` |
| `build` | string | 构建命令，两步：native 构建可执行文件，再产出 `mlx.metallib` |
| `entry` | string | 服务可执行文件 |
| `weights` | string | 权重目录，相对仓库根目录 |
| `idle_timeout` | int | 空闲秒数，0 表示常驻 |
| `min_macos` | string | 本运行时最低 macOS 版本，只约束运行期 |

> `min_macos` 是新增字段，落地后需要同步 [AGENTS.md](../AGENTS.md) 的清单表；在 `server/` 落地前由启动脚本读取。构建机门槛（Xcode 26 宿主 macOS 15.6+）由安装脚本检查，不进清单。

**A-2 权重文件（weights）**

| 字段 | 值 | 说明 |
| --- | --- | --- |
| `model_id` | `bujidc/mlx-community_BiRefNet-fp16` | ModelScope |
| `revision` | `b9f39904c60ed2bc11c2fd5bdb005872a8eb2d34` | 不可变 revision |
| `file` | `model.safetensors` | 单文件权重 |
| `size` | 440,483,842 字节 | 约 420 MiB |
| `sha256` | `f1ba66260085fd8d471323dab098fabd36499ad54b0de8ca67deb5d1cf1f0c0e` | 安装时校验 |
| `license` | MIT | 上游模型与端口一致 |
| `source` | `https://www.modelscope.cn/models/bujidc/mlx-community_BiRefNet-fp16` | 主来源 |

**A-3 抠图请求（matting_request）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `image` | binary | 原始图片字节 |
| `content_type` | string | `image/png`、`image/jpeg`、`image/webp` |
| `output` | string | `cutout` 或 `mask` |
| `request_id` | string | 服务端生成 UUID |

**A-4 抠图响应（matting_response）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `body` | binary | PNG |
| `content_type` | string | 固定 `image/png` |
| `width` | int | 输出宽度 |
| `height` | int | 输出高度 |
| `mode` | string | `cutout` 或 `mask` |
| `elapsed_ms` | int | 服务端处理耗时 |

**A-5 健康状态（health）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | `ok` 或 `degraded` |
| `state` | string | 六个状态之一 |
| `model_loaded` | bool | 权重是否在内存 |
| `idle_seconds` | float | 空闲秒数 |
| `idle_timeout_seconds` | int | 空闲阈值 |
| `min_macos` | string | 最低系统版本 |
| `memory` | object | 六项内存指标，采集失败为 `null` |

**A-6 Web UI 状态（ui_state）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `image` | Blob | 当前选择图片 |
| `imageUrl` | string | 预览 Object URL，替换时释放 |
| `result` | Blob | 当前结果 PNG |
| `resultUrl` | string | 结果 Object URL，替换时释放 |
| `mode` | string | `cutout` 或 `mask` |
| `status` | string | `empty`、`selected`、`processing`、`success`、`error`、`timeout` |
| `error` | string | 中文错误说明 |

### 7.3 参考资料

- ModelScope 权重：<https://www.modelscope.cn/models/bujidc/mlx-community_BiRefNet-fp16>
- Hugging Face 转换版：<https://huggingface.co/mlx-community/BiRefNet-fp16>
- 原始模型：<https://github.com/ZhengPeng7/BiRefNet>
- Swift 引擎包：<https://github.com/xocialize/mlx-birefnet-swift>（只用于核对权重来源和 API 形态，其 MLXEngine 包装层不采用）
- 上游核心端口：<https://github.com/mnmly/mlx-swift-BiRefNet>
- MLXEngine：<https://github.com/xocialize/mlx-engine-swift>（仅作门槛对照，不引入）
- MLX Swift：<https://github.com/ml-explore/mlx-swift>
- SwiftNIO：<https://github.com/apple/swift-nio>

---

## 8. 业务规则汇总

| 编号 | 规则 |
| --- | --- |
| BR-01 | 本运行时只支持 Apple Silicon，运行门槛 macOS 14 及以上；不支持 Intel Mac、Linux、Windows 和 Docker。 |
| BR-02 | 构建使用 Swift 6.2 及以上工具链（Xcode 26，宿主 macOS 15.6+），命令固定为 `swift build -c release` 加 `scripts/build_metallib.sh` 产出 `mlx.metallib`；不使用 `--build-system swiftbuild`（Xcode 26.2 上被 Metal 工具链定位 bug 阻塞，已实测）。构建门槛只约束构建机，不写进清单。 |
| BR-03 | 依赖走 SwiftPM，提交 `Package.resolved`，锁定 `mlx-swift-BiRefNet`、`mlx-swift`（0.31.4）、`swift-nio`、`swift-argument-parser` 的实际解析版本；不得解析到 `mlx-swift` 0.31.5 及以上（该版本起需 Swift 6.3）。 |
| BR-04 | 权重只从 ModelScope 的 `bujidc/mlx-community_BiRefNet-fp16`、revision `b9f39904c60ed2bc11c2fd5bdb005872a8eb2d34` 下载，校验 SHA-256；运行期不得下载权重。 |
| BR-05 | 权重放在 `models/birefnet/fp16/`，必须包含 `model.safetensors`、`README.md`、`LICENSE`、`.revision`、`.checksums`；不入库。 |
| BR-06 | 一个进程只加载 BiRefNet，不与 Hy-MT2、Ming-3.0-tts 同进程；切换模型需要重启。 |
| BR-07 | 清单固定为 `runtimes/birefnet/runtime.toml`，字段为 `name`、`runtime`、`build`、`entry`、`weights`、`idle_timeout`、`min_macos`。 |
| BR-08 | CLI 和 API 必须共用同一套预处理、推理和后处理，不允许两套实现。 |
| BR-09 | CLI 成功时标准输出只打印输出文件的绝对路径；日志写标准错误；参数错误退出码 2，运行错误退出码 1，成功退出码 0。 |
| BR-10 | 抠图接口固定为 `POST /v1/images/matting`；项目明确它是自定义接口，不冒充 OpenAI `/v1/images/edits`。 |
| BR-11 | 请求体是原始图片二进制，不使用 multipart；`Content-Type` 只接受 `image/png`、`image/jpeg`、`image/webp`，其他返回 415。 |
| BR-12 | 请求体上限 20MB；超出返回 413，且不解析正文。 |
| BR-13 | 解码后最长边不得超过 8192 像素，总像素不得超过 3200 万；超限返回 400；上限为初版，压测后调整。 |
| BR-14 | 图片用 ImageIO 解码，必须应用 EXIF 方向；损坏、截断或无法解码返回 400。 |
| BR-15 | 输入统一转换到 sRGB；已有 alpha 的图片先合成到白底再推理，不把原 alpha 当作主体透明度。 |
| BR-16 | 查询参数 `output` 只接受 `cutout` 和 `mask`，默认 `cutout`；其他值返回 400。 |
| BR-17 | `cutout` 返回 RGBA PNG，alpha 为直通非预乘，RGB 保留源图颜色；`mask` 返回 8-bit 灰度 PNG，255 表示前景。 |
| BR-18 | v1 只返回 PNG；不支持 JPEG、WebP、AVIF 等输出格式。 |
| BR-19 | 成功响应必须带 `X-Request-Id`、`X-Output-Mode`、`X-Image-Width`、`X-Image-Height`、`X-Elapsed-Ms`、`Content-Disposition` 和 `Cache-Control: no-store`。 |
| BR-20 | 模型内部默认按 1024×1024 推理，可用 `BIREFNET_INPUT_SIZE` 调整（默认档位的取舍见 §1.2）；输出必须回到方向归一化后的源分辨率，不得静默裁剪或缩小。 |
| BR-21 | v1 只输出上游原始 sigmoid alpha；不做颜色去污染、边缘细化、羽化或背景替换，文档不得承诺这些效果。 |
| BR-22 | `GET /v1/models` 返回固定 id `BiRefNet-fp16`，不触发模型加载；`created` 为进程启动时间。 |
| BR-23 | `/health` 的 `state` 只允许 `unloaded`、`loading`、`ready`、`generating`、`unloading`、`failed`；不得暴露本地路径；加载失败带 `last_error`。 |
| BR-24 | 推理必须串行；同一时刻只允许一个任务进入 Metal。 |
| BR-25 | 等待队列上限 8（不含在途任务），第 9 个等待请求返回 429，`Retry-After: 5`。 |
| BR-26 | 排队超时默认 120 秒，超时返回 429；出队与超时标记必须在同一临界区完成。 |
| BR-27 | 客户端在排队时断开，请求移出队列；在推理时断开，推理继续，完成后丢弃结果，不写响应。 |
| BR-28 | 空闲卸载默认 1200 秒，可用 `BIREFNET_IDLE_TIMEOUT` 调整，0 表示常驻；只有队列为空且无在途任务时才卸载。 |
| BR-29 | 卸载顺序为释放管线与权重引用、清 MLX GPU 缓存、记录内存、改状态；失败回 `ready` 并下一轮重试。 |
| BR-30 | 加载失败进入 5 秒冷却；冷却期内请求直接 503；冷却结束后首个请求重新尝试。 |
| BR-31 | 收到 SIGTERM 后停止接新请求，排队请求返回 503 并取消 continuation，在途任务最多等 120 秒，退出前清缓存。 |
| BR-32 | 错误响应统一为 `{"error": {"type": ..., "message": ...}}`；400、404、405、413、415、429、500、503 按文档映射，message 为中文且不含堆栈和路径。 |
| BR-33 | 默认只监听 `127.0.0.1`；指定非回环地址必须设置 `BIREFNET_ALLOW_REMOTE=1`，否则启动失败；默认不启用 CORS。 |
| BR-34 | 校验 `Host` 头，只接受回环地址、监听地址、本机网卡 IPv4、本机主机名和 `.local`；`0.0.0.0` 不作为放行依据。 |
| BR-35 | 图片只在内存中处理，不写仓库、`models/`、`output/` 或用户目录；任何日志级别都不得记录图片字节、base64、完整请求体或本地绝对路径。 |
| BR-36 | 安装和构建阶段允许联网；运行期不得访问外部服务、采集遥测或自动下载权重。 |
| BR-37 | Web UI 新增抠图页；单模型启动时 `/` 307 到 `/?page=matting`；不引入 router、pinia 或额外 UI 库。 |
| BR-38 | Web UI 只暴露输出形态一项配置；不暴露阈值、模型输入尺寸、采样参数或批量选项。 |
| BR-39 | 预览和结果使用 Object URL，替换、清除和组件卸载时必须 revoke；不得用 localStorage 等持久化图片。 |
| BR-40 | Web UI 最多等待 180 秒；超时只停止前端等待并提示结果未知；重复提交需二次确认；服务端不取消在途任务。 |
| BR-41 | 服务挂载 `web/dist` 到 `/`；`/` 307 到 `/?page=matting`；`web/dist` 缺失时 `/` 返回 404 并提示先构建，API 不受影响。 |
| BR-42 | `/v1/images/matting` 只接受 POST；其他方法 405；未知路径 404。 |
| BR-43 | `/health` 返回 MLX 活动/峰值/缓存、进程物理内存、整机已用/总量；采集失败字段为 `null`，不得编造数值。 |
| BR-44 | 能力开放前必须跑通核心包自带测试，并用固定回归图集人工检查；结果写入 `docs/benchmarks.md`。 |
| BR-45 | 所有耗时、内存、吞吐数字必须在本项目验收机实测后写入 `docs/benchmarks.md`；未实测不得写进 README、UI 或对外文档；上游数字必须标注来源和「非本项目实测」。 |
| BR-46 | HTTP 服务使用 SwiftNIO；图片解码、推理和 PNG 编码不得在 NIO 事件循环线程执行；不引入 Web 框架和额外状态库。 |
| BR-47 | 模型与 Swift 端口均为 MIT；安装后保留 `LICENSE`、`NOTICE` 和来源说明，README 注明来源，不再分发权重。 |
| BR-48 | v1 不依赖统一调度器；`server/` 落地后只读清单拉起本运行时，不把图片处理逻辑写进调度器。 |
| BR-49 | 默认端口 8000；端口占用直接报错，不自动换端口；`--host`、`--port` 可覆盖。 |
| BR-50 | 权重路径启动时固定；运行中修改目录需要重启；权重缺失返回 503，并提示运行安装脚本，不自动下载。 |

---

## 9. 易用性设计原则

### 9.1 零配置开始

- 安装只需一条脚本；构建、下载、校验都在脚本内完成。
- 启动后打开 `/` 直接进入抠图页，不需要选模型、填端口或配置路径。
- 默认输出透明背景 PNG，这是多数用户的第一诉求。

### 9.2 用户可见配置不超过 4 项

| 配置 | 是否暴露 | 说明 |
| --- | --- | --- |
| 输出形态 | 是 | 透明背景 / 黑白遮罩 |
| 输入图片 | 是，选择文件 | 不是参数，是操作 |
| 下载文件名 | 否 | 由服务端给出默认名 |
| 尺寸、阈值、采样 | 否 | 固定或自动 |
| 端口、权重路径 | 否 | 只在启动脚本和排障文档中 |

### 9.3 不主动打扰

- 不在页面弹教程、公告或更新提示。
- 处理中只显示一次状态，不弹窗打断。
- 错误就地显示在对应区域，不跳转页面。
- 不引导用户上传到云端，不提供外部链接按钮。

### 9.4 小白语言规范

| 禁止出现在用户界面 | 替换为 |
| --- | --- |
| alpha matte、软 alpha | 透明程度 |
| sigmoid、logits | 不出现 |
| 1024×1024 推理尺寸 | 不出现；只说输出保持原图尺寸 |
| RGBA、直通 alpha | 透明背景图片 |
| EXIF 方向 | 不出现；自动处理 |
| 队列已满 | 前面还有图片在处理，请稍后再试 |
| 模型加载失败 | 模型没准备好，请稍后重试 |
| 415、413 | 这张图片的格式/大小不支持 |

> 只有排障文档和 API 文档可以保留技术名词；页面文案一律用人话。

### 9.5 状态表达简化

| `/health` 状态 | 页面文案 |
| --- | --- |
| `unloaded` | 已就绪（首次抠图需准备模型） |
| `loading` | 正在准备模型 |
| `ready` | 已就绪 |
| `generating` | 正在抠图 |
| `unloading` | 正在释放内存 |
| `failed` | 模型加载失败 |
| 服务不可达 | 服务未启动 |
| 当前是其他模型 | 当前服务运行的是其他模型，抠图不可用 |

### 9.6 一致性检查表

| 检查项 | 要求 | 落地位置 |
| --- | --- | --- |
| 系统门槛 | 运行门槛统一写 macOS 14+，构建门槛统一写 Swift 6.2 / Xcode 26（宿主 macOS 15.6+）；全文不再出现 macOS 26.2 门槛 | README、§6.2、UC-01、BR-01、BR-02 |
| 构建命令 | 所有文档都写「native 构建 + `build_metallib.sh`」，不再写 `--build-system swiftbuild` | AGENTS、§1.5、A-1、BR-02 |
| 权重体积 | 只写 440,483,842 字节 / 约 420 MiB，不写「约 1GB」 | §1.1、A-2、README |
| 性能数字 | 上游数字必须标注「非本项目实测」 | §6.1、README |
| 输出尺寸 | 所有描述都写源分辨率，不写固定 1024 输出 | §1.2、BR-20、UC-04 |
| 能力边界 | 不承诺颜色去污染、边缘细化、背景替换 | §1.4、§1.8、BR-21 |
| 接口命名 | 统一 `/v1/images/matting`，不出现 `/v1/images/edits` 兼容说法 | §1.6、UC-04、BR-10 |
| 页面入口 | 统一 `/?page=matting` | UC-07、BR-37、BR-41 |
| 错误结构 | 统一 `{"error":{"type","message"}}` | UC-05、BR-32 |
| 隐私 | 图片不落盘、不写日志、刷新清空 | §6.3、BR-35、BR-39 |
