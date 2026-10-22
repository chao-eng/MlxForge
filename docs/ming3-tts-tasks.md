# Ming-3.0-tts 开发任务拆解清单

| 项目 | 内容 |
| --- | --- |
| 文档版本 | v1.0 |
| 日期 | 2026-10-21 |
| 依据 | [ming3-tts-prd.md](ming3-tts-prd.md) v0.4 |
| 任务总数 | 55（T-01 ~ T-55） |
| 用法 | 完成一项勾选一项；勾选前必须满足该项的验收依据，未实测不勾 |

## 进度总览

| 阶段 | 范围 | 任务数 | 完成 |
| --- | --- | --- | --- |
| 0 | Spike 阻塞验证 | 9（T-01~T-09） | 8 / 9 |
| 1 | 环境与权重 | 6（T-10~T-15） | 6 / 6 |
| 2 | 模型管理与状态机 | 7（T-16~T-22） | 7 / 7 |
| 3 | 请求校验与任务解析 | 5（T-23~T-27） | 5 / 5 |
| 4 | 音频与 HTTP 接口 | 9（T-28~T-36） | 9 / 9 |
| 5 | 命令行 | 2（T-37~T-38） | 2 / 2 |
| 6 | Web UI | 7（T-39~T-45） | 7 / 7 |
| 7 | 性能与验收 | 7（T-46~T-52） | 6 / 7 |
| 8 | 文档 | 3（T-53~T-55） | 3 / 3 |
| 合计 | — | 55 | 53 / 55 |

## 拆解原则

| 原则 | 说明 |
| --- | --- |
| Spike 前置 | §6.5 的 32 项验证是能力开关的前提（BR-82/BR-83），必须先做，否则 UI 与 API 的字段范围无法定稿 |
| 骨架先行 | 环境、模型管理、状态机落地后，CLI、API、UI 才能并行 |
| 单模型推进 | 按 AGENTS.md，不与 Hy-MT2 交叉 import，`server/` 本期不动 |
| 每项可验收 | 每项都有明确的验证命令或测试点，不写未实测结论 |

---

## 阶段 0：Spike 阻塞验证

- [x] **T-01** 搭 `envs/ming-tts`，安装 mlx-audio 到含 PR #1047 的提交，写版本自检
  - 依赖：无 ｜ 依据：BR-03、§6.5-1
  - 结论：PR #1047 已合入（`3530c33`），首个包含它的发行版为 0.6.1；已装 0.6.1，`runtimes/ming_tts/env_check.py` 通过
- [x] **T-02** 跑通 8bit 权重加载与 10 次连续合成
  - 依赖：T-01 ｜ 依据：§6.5-2
  - 结论：加载 3.45 s，10 次连续合成无崩溃，RTF 0.83~0.98，MLX 峰值 1.80 GB
- [x] **T-03** 按 A-6 逐条验证 8 种任务模式与七项冲突检查，记录结果
  - 依赖：T-02 ｜ 依据：§6.5-6、BR-31~BR-38
  - 结论：8 种模式模型侧均可合成；七项冲突检查属 API 层，待 T-24 落地后验证；效果听感待人工
- [x] **T-04** 组合能力验证：克隆 + 多语言、内置音色 + 显式 `multilingual`、指令 + 多语言
  - 依赖：T-03 ｜ 依据：§6.5-32
  - 结论：三条组合均可执行；语言正确性与音色保持待人工试听
- [ ] **T-05** 逐项 Spike 情绪 5 取值、属性三参数上/下限、两种方言、IP 角色
  - 依赖：T-03 ｜ 依据：§6.5-7~10
  - 进度：15 条样本已合成（`/tmp/ming_spike_out/t05_*.wav`），客观测量见 `docs/benchmarks.md` §1.10；语速/音高/音量已可测生效，情绪可辨性与方言特征待人工试听
- [x] **T-06** 确认 mlx-audio 是否暴露内置音色枚举，产出音色清单或「不可枚举」结论
  - 依赖：T-02 ｜ 依据：§6.5-5、A-8
  - 结论：不可枚举，仅按正则透传；UI 保持自由输入，API 只能校验命名形式
- [x] **T-07** 参考音频解码边界验证（WAV/FLAC、5/30 秒、单双声道）
  - 依赖：T-02 ｜ 依据：§6.5-4
  - 结论：WAV/FLAC、单双声道、48 kHz 均可解码，立体声自动混单；静音补齐的参考音频出现 0.30 s 异常输出，列为待查风险
- [x] **T-08** 长文本能力验证：1000 码点、1001 码点、耗时与内存
  - 依赖：T-02 ｜ 依据：§6.5-21、BR-94
  - 结论：1000 码点完成，130.0 s 生成 159.8 s 音频，RTF 0.81，峰值 1.97 GB；1001 码点由 API 层拒绝
- [x] **T-09** seed 可复现、停止头尾部噪声、14 种内联标签逐条记录
  - 依赖：T-02 ｜ 依据：§6.5-11/13/14
  - 结论：`mx.random.seed` 下同 seed 逐字节一致；停止头异常 1/14；14 种标签均透传并合成，效果待试听

> 阶段 0 出口：`docs/benchmarks.md` 的 Spike 结论段完成，§1.7 能力状态表按结论回写。T-05 未通过的项直接决定 UI 是否渲染对应控件。

---

## 阶段 1：环境与权重（UC-01）

- [x] **T-10** 建 `runtimes/ming_tts/` 目录与 `runtime.toml`（A-1 字段）
  - 依赖：无 ｜ 依据：A-1、BR-12
  - 结论：`runtimes/ming_tts/runtime.toml` 已建，字段与 A-1 一致
- [x] **T-11** `requirements.txt` 锁定完整解析结果，含 `mlx`、`numpy` 等间接依赖
  - 依赖：T-01 ｜ 依据：BR-03、BR-91
  - 结论：`uv pip freeze` 导出 51 个包，含 mlx-audio 0.6.1、mlx 0.32.4、fastapi、uvicorn
- [x] **T-12** `scripts/setup_ming_tts.sh`：架构检查、venv、依赖安装、PR #1047 校验
  - 依赖：T-10、T-11 ｜ 依据：UC-01 主流程 1~4、BR-02
  - 结论：脚本幂等，安装后调用 `runtimes.ming_tts.env_check`，非 Apple Silicon 与缺 uv 均非零退出
- [x] **T-13** 权重下载：ModelScope 锁定 revision、断点续传、SHA-256 逐文件校验、原子替换、写 `.revision`/`.checksums`
  - 依赖：T-12 ｜ 依据：UC-01 5~6、BR-90
  - 结论：`scripts/ming_tts_weights.py` 负责；ModelScope 接口不返回哈希，按 A-3 首次下载后本地计算；下载中断由 modelscope `file_download` 的 Range 续传
- [x] **T-14** 必需文件清单校验与失败回滚（保留旧权重）
  - 依赖：T-13 ｜ 依据：BR-05、UC-01 6a
  - 结论：必需文件、revision、逐文件哈希三项都过才替换；替换失败恢复旧目录，已用临时目录验证
- [x] **T-15** `scripts/start_ming_tts.sh`：环境、依赖、端口、远程门禁检查
  - 依赖：T-12 ｜ 依据：BR-12、BR-15、BR-86
  - 结论：默认回环地址；非回环且无 `MING_TTS_ALLOW_REMOTE=1` 退出码 1；端口占用退出码 1；非法参数退出码 2

---

## 阶段 2：模型管理与状态机（UC-07）

- [x] **T-16** `model_manager.py`：六状态机（进入/退出/异常恢复），状态名唯一来源
  - 依赖：T-02 ｜ 依据：§4.4、BR-55、BR-88
  - 结论：`runtimes/ming_tts/model_manager.py` 只有六个状态常量；加载失败由 worker 置 `failed` 并写 `last_error`，卸载失败回退 `unloaded`
- [x] **T-17** 懒加载与加载失败 5 秒冷却，冷却期共享失败结果
  - 依赖：T-16 ｜ 依据：BR-14、BR-54
  - 结论：启动只校验 config.json 与 tokenizer 文件；失败后 5 秒内 `submit` 直接抛 `ModelUnavailableError`，冷却结束自动重试
- [x] **T-18** 单 worker 串行队列：等待上限 8（不含在途）、入队与余量检查同锁、第 9 个 429
  - 依赖：T-16 ｜ 依据：BR-56、BR-57、BR-87
  - 结论：`submit` 在同一把锁内检查余量并入队；上限只计等待任务，实测第 3 个等待请求（上限 2）被拒
- [x] **T-19** 排队超时：从入队成功计时、超时与出队同临界区移除
  - 依赖：T-18 ｜ 依据：BR-58、§4.9-4
  - 结论：`wait` 在锁内判定超时并出队，已出队任务不再触发超时；实测 1.5 秒上限下准时返回 `QueueTimeoutError`
- [x] **T-20** 空闲卸载：计时起点、卸载顺序（解引用→`gc.collect()`→`mx.clear_cache()`）、失败回退
  - 依赖：T-16 ｜ 依据：BR-50~BR-53、UC-07
  - 结论：空闲检查线程只投递请求，worker 在队列为空时卸载；实测 `idle_timeout=1` 时 3.5 秒后状态回到 `unloaded`
- [x] **T-21** 客户端断开处理：排队移出并取消 Future，在途走完丢弃
  - 依赖：T-18 ｜ 依据：BR-59、BR-89、§4.9-5/6
  - 结论：`cancel` 返回 True 表示仍在队列（调用方负责清理临时文件），在途返回 False 且不打断合成
- [x] **T-22** SIGTERM 关闭流程：停接新请求、排队 503、在途最多等 120 秒
  - 依赖：T-20、T-21 ｜ 依据：BR-60、§4.9-8/14
  - 结论：`begin_shutdown` 取消全部排队 Future 并抛 `ServiceClosedError`；`shutdown(120)` 等待在途，已完成任务立即返回

---

## 阶段 3：请求校验与任务解析

- [x] **T-23** `schema.py`：字段范围、请求体 20MB/413、码点计数 1~1000
  - 依赖：T-10 ｜ 依据：BR-17、BR-18、BR-94
  - 结论：`runtimes/ming_tts/schema.py` 按 Unicode 码点计数；`BodyLimitMiddleware`（`middleware.py`）在解析前拦 20MB，Content-Length 预判与流式累计两条路径均实测 413；`voice` 用与 `bailingmm.py` 相同的命名正则，OpenAI 默认音色名显式拒绝；参考音频此处只校验成对出现与编码后体积，格式/时长/采样率留给 T-28
- [x] **T-24** 任务模式解析器：默认值归一化 → 七项冲突检查 → 八步优先级
  - 依赖：T-23、T-03 ｜ 依据：§4.3、A-6、BR-75
  - 结论：`runtimes/ming_tts/tasks.py` 的 `resolve_task` 先做七项冲突检查，再按 A-6 八步取第一条命中；临时脚本覆盖 8 种模式、三种「情绪/指令/音色优先于多语言」组合与七项冲突，共 74 项断言通过
- [x] **T-25** 显式 task 校验：按 A-6 必填/允许/禁止列逐条实现
  - 依赖：T-24 ｜ 依据：BR-32~BR-36、BR-77、BR-78
  - 结论：8 种显式任务的必填项、禁止项逐条实现；显式 `freeform` 允许参考音频、`multilingual` 允许内置音色、`dialect` 不传 language ID；`basic` 只允许 `voice=auto` 与 `language∈{auto,zh,en}`
- [x] **T-26** 能力状态到 API 行为映射：实验透传、不支持/未开放 400
  - 依赖：T-05、T-24 ｜ 依据：§1.7 映射表、BR-82
  - 结论：`runtimes/ming_tts/capabilities.py` 是状态唯一来源；当前情绪、属性、方言、IP 均为 `experimental`，原样透传不拦截。T-05 结论出来后只改 `CAPABILITY_STATUS`、§1.7 与 `docs/api.md`，解析逻辑不动
- [x] **T-27** 错误统一结构 `{"error":{"type","message"}}`，message 中文、type 英文，422→400 映射
  - 依赖：T-23 ｜ 依据：BR-45、BR-46、A-4
  - 结论：`runtimes/ming_tts/errors.py` 登记 A-4 全部 7 种 type 与状态码；已实测 404/405、非法 JSON 的 422→400、413；429 带 `Retry-After: 5`，未预期异常只记类型不记消息

---

## 阶段 4：音频与 HTTP 接口（UC-04/05/06/09）

- [x] **T-28** `audio.py`：参考音频解码（WAV/FLAC）、WAV/PCM 编码、时长计算
  - 依赖：T-07 ｜ 依据：BR-24、BR-41
  - 结论：`runtimes/ming_tts/audio.py` 只解析容器头，不解码 PCM；实测 7 秒单声道 WAV、立体声 WAV、48 kHz WAV、FLAC 全部接受，30.50 秒与 4.90 秒均 400，解码后超过 10MB 与截断 WAV 均 400。输出侧 `afinfo` 识别为 44.1 kHz/16-bit/单声道
- [x] **T-29** 临时目录安全：0700 创建、禁跟随符号链接、真实路径与所有者校验、只清自有文件、失败禁用克隆
  - 依赖：T-28 ｜ 依据：§4.7、BR-61、BR-84
  - 结论：`runtimes/ming_tts/tempfiles.py` 实测 14 项：目录强制 0700、文件 0600、符号链接目录与普通文件路径均拒绝、启动只清自有普通文件（保留无关文件与符号链接）、删除幂等、关闭后拒绝创建。所有者校验需 root 才能构造，未实测
- [x] **T-30** 临时文件删除权实现：worker 读取后删除，handler 仅在确认未出队时删除
  - 依赖：T-29、T-19 ｜ 依据：BR-97
  - 结论：正常流程由 worker 的 `finally` 删除；实测排队中断开后 1 秒内文件被 handler 删除且该请求未进入合成；`MING_TTS_QUEUE_TIMEOUT=3` 时排队超时返回 429 且文件立即清理
- [x] **T-31** 重 CPU/IO 操作放线程池（base64 解码、音频解码、临时写入、编码）
  - 依赖：T-28 ｜ 依据：BR-98、§4.8
  - 结论：base64 解码、参考音频校验、临时写入、`manager.wait` 与 WAV 编码均走 `run_in_threadpool`；32 秒合成期间 `/health` 延迟中位 1.2 ms、最大 5.8 ms，事件循环未阻塞
- [x] **T-32** `POST /v1/audio/speech`：入队、等待 Future、返回二进制
  - 依赖：T-18、T-25、T-28 ｜ 依据：UC-04 主流程、BR-40
  - 结论：实测 8 种任务解析结果与 A-6 一致（BASIC/TTS/EMOTION/DIALECT/MULTILINGUAL/IP/VOICE_DESIGN/FREEFORM）；克隆在 PCM 与 WAV 下均 200；参考音频缺转录、非音频、过短均 400。另发现 `reference_text` 必须与参考音频内容一致，否则模型只生成 0.3 秒音频，需写入 `docs/api.md`
- [x] **T-33** 响应头组装：`X-Request-Id`、`X-Resolved-Task`、`X-Seed`、四个 `X-Audio-*`、`Content-Disposition`、`Cache-Control`
  - 依赖：T-32 ｜ 依据：BR-42、§6.2 PCM 行
  - 结论：WAV 与 PCM 响应逐项核对通过，`X-Audio-Duration` 两位小数，`X-Audio-Format` 与响应体格式一致，`Content-Disposition` 文件名使用请求 ID
- [x] **T-34** `GET /health`、`GET /v1/models`，不触发加载，`idle_seconds` 起点定义
  - 依赖：T-16 ｜ 依据：BR-47~BR-49、UC-06
  - 结论：冷启动后连续调用 `/health` 与 `/v1/models` 不加载权重，状态保持 `unloaded`；`/health` 字段齐全，合成期间状态为 `generating`
- [x] **T-35** 日志脱敏：任何级别不记文本/参考音频/请求体；DEBUG 只加诊断字段
  - 依赖：T-32 ｜ 依据：BR-62、A-2
  - 结论：以 `MING_TTS_LOG_LEVEL=DEBUG` 提交含特征文本的克隆请求，日志只出现「文本 21 码点，参考音频 有」，全文检索无输入文本与 base64
- [x] **T-36** Host 头校验与远程门禁（含 `0.0.0.0` 规则）
  - 依赖：T-15 ｜ 依据：BR-69、§6.3
  - 结论：`Host: evil.example` 与 `Host: 0.0.0.0` 返回 400 `invalid_request_error`；`localhost`、回环 IP、本机各网卡 IPv4（含 utun）和主机名（`bujic`、`bujic.local`）放行。主机名和网卡地址都要枚举，否则用第二块网卡或 VPN 地址访问时会被误拒

---

## 阶段 5：命令行（UC-02）

- [x] **T-37** `cli.py`：复用 T-23~T-25 的校验与解析，不写第二套实现
  - 依赖：T-25、T-28 ｜ 依据：BR-09
  - 结论：`runtimes/ming_tts/cli.py` 把参数组装成与 API 相同的请求对象，直接调用 `parse_speech_request`、`resolve_task`、`synthesize`；参考音频先读文件再用 `inspect_reference` 校验，不复制第二套规则
- [x] **T-38** 参数、默认值、扩展名推断、退出码 0/1/2、stdout 只输出路径
  - 依赖：T-37 ｜ 依据：BR-07、BR-08、BR-10、UC-02
  - 结论：实测缺 `--text`、空文本、格式冲突、未知扩展名、任务冲突、参考音频过短均退出 2；权重目录缺失退出 1；成功时 stdout 只有绝对路径、日志走 stderr。默认输出 `output/ming-tts-<时间戳>.<格式>`，`--format pcm` 时扩展名随之变化，输出为 44.1 kHz/16-bit/单声道

---

## 阶段 6：Web UI（UC-08）

- [x] **T-39** 页面骨架：三页签、状态徽标（六状态文案对齐 §9.5）、同源挂载 `/`
  - 依赖：T-34 ｜ 依据：BR-63、BR-68、§5.2
  - 结论：顶部模型页签同时保留「语音合成」「文本翻译」两套页面，按 `/v1/models` 自动判定当前模型，未运行模型的页面可打开但按钮禁用并提示；`runtimes/ming_tts/app.py` 在存在 `web/dist` 时挂载 `/` 与 `/assets`，缺失时 `/` 返回 503 并提示先构建。实测六状态文案与 §9.5 一致，`unloaded` 显示「已就绪（首次生成需准备模型）」
- [x] **T-40** 内置音色页：文本、码点计数 `Array.from`、语言下拉、音色组合框
  - 依赖：T-39、T-32 ｜ 依据：BR-94、§5.2
  - 结论：码点计数实测 emoji 文本显示 25（UTF-16 长度 26）；语言下拉为 A-5 的 7 项加自动，音色为可筛选可新建的组合框；内置音色实测生成音频 3.6 秒、生成耗时 7.1 秒，播放器时长与 `X-Audio-Duration` 一致
- [x] **T-41** 克隆页：音频上传校验、参考文本、授权勾选、三项齐全才提交
  - 依赖：T-40、T-29 ｜ 依据：BR-64、BR-72
  - 结论：前端只解析 WAV/FLAC 容器头取时长，校验格式、5~30 秒、≤10MB；实测 `ref_real_7s.wav` 显示「6.9 秒 · 0.6 MB」，缺参考音频、参考文本或授权任一项按钮均禁用。提交成功，音频 0.3 秒；参考文本与音频内容不匹配时输出偏短，与阶段 4 结论一致
- [x] **T-42** 声音设计页：声音描述必填 ≤500 字符、示例文案
  - 依赖：T-40 ｜ 依据：§5.2
  - 结论：描述与文本各自计数，描述为空或超 500 码点时禁用；三条示例可一键填充并立即可提交；该页不渲染音色、参考音频、参考文本和授权勾选，请求固定 `voice=design` 加 `instructions`
- [x] **T-43** 播放与下载：Blob URL 播放、覆盖/卸载时释放旧 URL
  - 依赖：T-40、T-33 ｜ 依据：BR-67、§6.5-26
  - 结论：结果区展示播放器、音频时长、生成耗时和下载链接，下载名形如 `ming-tts-20261021-181321.wav`；第二次生成前撤销旧 URL，实测旧 blob 再取返回 ERR_FILE_NOT_FOUND，新 URL 正常播放
- [x] **T-44** 异常态：180 秒超时文案、断线重连、重复提交二次确认
  - 依赖：T-39 ｜ 依据：BR-93、BR-96、§5.4
  - 结论：把 180000ms 定时器缩短到 1.5 秒模拟超时，出现「等待时间较长，请检查服务状态。当前合成可能仍在后台继续」，按钮变「再次提交」；点击只弹二次确认、不立即发新请求（拦截到的请求体数量不变）。停服后连续 2 次轮询（约 10 秒）徽标变「服务未启动」、按钮禁用、已输入文本保留；重启后自动恢复「已就绪（首次生成需准备模型）」且输入仍在。期间控制台仅有 `ERR_CONNECTION_REFUSED`，无脚本异常
- [x] **T-45** 字段可见性门禁：未通过 Spike 的字段不渲染，且不可通过 URL/本地存储恢复
  - 依赖：T-05、T-39 ｜ 依据：BR-82、§5.5
  - 结论：三个页签均无情绪、语速、音高、音量、方言控件（无滑杆，语言下拉仅 7 项不含方言）；带 `emotion/speed/pitch/volume/dialect/voice` 查询参数打开页面，音色仍为 `auto`，页面无对应控件；预先写入 localStorage/sessionStorage 后刷新同样不恢复。实测请求体只含 `model`、`input`、`voice`、`language`、`response_format` 五个字段。声音设计页的说明与示例文案提到「语速/情绪」，属描述引导语，不是可提交字段

---

## 阶段 7：性能与验收（§6）

- [x] **T-46** 基准脚本：按 §6.1.1 协议采集（预热、轮次、nearest-rank、1Hz 采样、原始值）
  - 依赖：T-32 ｜ 依据：BR-92
  - 结论：`scripts/bench_ming_tts.py` 提供 `load`/`cold`/`hot`/`memory` 四个模式，每项 1 次预热后采集 5 轮，nearest-rank 分位数并保留每轮原始值；RSS 用 `ps -o rss=`，MLX 用 `mx.get_active_memory()`/`mx.get_cache_memory()`，采样 1 Hz。Apple M2 16GB 实测：加载 P50 1.059s / P95 1.335s；冷启动首请求 P50 3.829s / P95 3.894s；热启动首请求 P50 2.527s / P95 2.661s；40 字 RTF P50 0.853 / P95 0.881
- [x] **T-47** 内存验收：MLX active/cache + 进程 RSS，基线/峰值/0-5-30-60 秒观测
  - 依赖：T-46、T-20 ｜ 依据：G3、§6.1 基线定义
  - 结论：基线 RSS 59.7MB、active/cache 0；峰值 RSS 297.8MB、active 1517.2MB、cache 337.8MB；卸载后 0/5/30/60 秒 active 与 cache 均为 0，RSS 依次 170.5/170.6/170.6/158.1MB，满足 MLX 增量 ≤10% 与 RSS ≤ 基线 + max(200MB, 峰值增量×20%)。过程中发现 `mlx_audio` 的 bailingmm 包把 onnx 导入异常存在模块全局，traceback 会钉住首次导入所在栈帧；若导入发生在 `load_model` 内部，权重字典无法释放，卸载后 active 仍为 1507.4MB。已在 `model_manager.py` 模块导入阶段预先触发该导入，复测回落为 0
- [x] **T-48** 并发与队列验收：20 并发 → 恰好 9 成功、11 个 429；排队超时
  - 依赖：T-46、T-18 ｜ 依据：§6.1、§6.5-18
  - 结论：`scripts/test_ming_tts_concurrency.py` 实测默认队列下 20 并发得到 9 个 200、11 个 429，`Retry-After` 均为 5，成功响应均为完整 WAV 且 `X-Request-Id` 唯一；把 `MING_TTS_QUEUE_TIMEOUT` 调为 2 秒后 9 并发长文本得到 1 个 200、8 个 429「排队等待超时」，无重复处理。说明：串线只做了响应头与音频完整性核验，未做听感内容比对
- [ ] **T-49** 质量抽检：50 条样本、双人评分、与 mlx-audio CLI 同参数对比
  - 依赖：T-37 ｜ 依据：G5、§6.1.2
  - 执行包：[ming3-tts-t49-eval.md](ming3-tts-t49-eval.md)，含 50 条样本清单、A/B 评分表、CLI 对照表和汇总模板
  - 结论：待人工。脚本无法替代双人独立评分，50 条样本与评分表需由两名评分者完成后再回填
- [x] **T-50** OpenAI SDK 验收：`audio.speech.create` 显式传 `voice` 和 `response_format`
  - 依赖：T-33 ｜ 依据：BR-81、§6.2
  - 结论：临时环境安装 `openai==1.109.1`，以任意 `api_key` 调用 `audio.speech.create(model="Ming-3.0-tts", voice="auto", input=..., response_format="wav")` 成功，返回 44.1kHz/16-bit/单声道 WAV（3.6 秒）；显式 `response_format="mp3"` 返回 400「response_format 只支持 wav 和 pcm」。该版本 SDK 不传 `response_format` 时会省略字段，服务端按默认 wav 返回，与 PRD §6.2 原表述不同，已在 PRD 中修正
- [x] **T-51** 断网验收：首次加载、失败重试、健康检查、UI 合成与播放
  - 依赖：T-32、T-44 ｜ 依据：G6、BR-95
  - 结论：本机未物理断网，改用运行期连接观测替代：服务进程仅有 `127.0.0.1` 监听，合成期间连续 12 次 `lsof` 采样无任何非回环连接。权重目录指向不存在路径时 `/health` 返回 `degraded` 与中文 `last_error`，请求立即、立即、冷却 7 秒后三次均返回 503 `model_unavailable`，无外部下载尝试；UI 由本地 `web/dist` 提供，合成与播放已在 T-43 实测。说明：物理断网场景未执行
- [x] **T-52** 端到端冒烟：`/health`、`/v1/models`、一次合成、空闲释放（调小 timeout）
  - 依赖：全部 ｜ 依据：AGENTS.md 验证节
  - 结论：`MING_TTS_IDLE_TIMEOUT=3` 启动后依次验证：`/health` 返回 `unloaded`、`/v1/models` 返回 `Ming-3.0-tts`、合成 200（148220B，3.58 秒，RIFF/WAVE）；等待 8 秒后状态回到 `unloaded`，进程 RSS 从 305MB 降到 230MB；再次合成 200（2.08 秒），重载成功

---

## 阶段 8：文档

- [x] **T-53** `docs/api.md`：字段、任务模式、实验/不支持标注、计数口径、`Retry-After` 说明
  - 依赖：T-50 ｜ 依据：BR-73、BR-80、BR-94
  - 结论：`api.md` 调整为多模型文档，按 Hy-MT2 与 Ming-3.0-tts 分节。Ming 节覆盖 `/v1/models`、`/v1/audio/speech` 全字段与上限、A-6 任务模式摘要与 `auto` 顺序、七项冲突检查、Unicode 码点计数口径（Python `len` / JS `Array.from`）、1000 码点临时上限、能力状态表（实验能力透传，流式与 mp3/opus/aac/flac 不支持）、全部响应头、`Retry-After: 5` 固定值不保证余量、错误表、运行约束、curl 与 `openai==1.109.1` SDK 示例。`/health` 补 `sample_rate`，并说明两个运行时默认同端口、同一时间跑一个
- [x] **T-54** `docs/benchmarks.md`：Spike 结论 + 性能原始值 + 已实测机型
  - 依赖：T-46~T-49 ｜ 依据：BR-83、BR-92
  - 结论：新增 §2，记录 Apple M2 16GB / macOS 15.7.9 / Python 3.11.3 / mlx 0.32.4 / mlx-audio 0.6.1 的采集命令、加载/冷启动/热启动/RTF 原始值与分位数、内存基线-峰值-0/5/30/60 秒回落、并发 9×200 + 11×429、排队超时、空闲卸载重载、SDK 结果。写明 M2 不是 PRD 的 M4 Pro 24GB 基准机，数值不外推；列出未覆盖项（克隆 10 段样本、T-49 质量评分、物理断网、M4 Pro 复测）。同时保留修复前 active 不回落的现象与根因对照
- [x] **T-55** README：启动命令、远程门禁、非流式说明、临时上限、许可证
  - 依赖：T-53、T-54 ｜ 依据：§9.6 全部 README 条目
  - 结论：README 补 Ming-3.0-tts 的 `setup_ming_tts.sh`、CLI、`start_ming_tts.sh` 命令；写明非回环监听必须 `MING_TTS_ALLOW_REMOTE=1` 且服务无鉴权；写明 v1 不支持流式音频、只输出 wav/pcm；标注 1~1000 Unicode 码点为临时上限及计数口径；补 `mlx-audio==0.6.1` 与 PR #1047 要求、Ming 权重 MIT 许可证与来源、SHA-256 + 不可变 revision 的供应链边界；新增已实测机型表（Apple M2 16GB），更新支持模型、磁盘占用和进度表

---

## 关键路径

```text
T-01 → T-02 → T-03 ─┬→ T-05 ─┐
                    ├→ T-06  │
                    └→ T-07 ─┼→ 阶段1(T-10~T-15)
                             │
                             ▼
阶段2(T-16~T-22) → 阶段3(T-23~T-27) ─┬→ 阶段4(T-28~T-36) ─┬→ 阶段5 CLI(T-37~T-38)
                                      │                     ├→ 阶段6 UI(T-39~T-45)
                                      └→ T-46 基准 ────────┴→ 阶段7/8
```

| 泳道 | 可并行任务 | 前置汇合点 |
| --- | --- | --- |
| A 后端核心 | T-16~T-27 | 阶段 0 完成 |
| B 音频与安全 | T-28~T-31 | T-07 |
| C API 层 | T-32~T-36 | 泳道 A + B |
| D 前端 | T-39~T-45 | T-34 + T-05 |
| E 验收文档 | T-46~T-55 | 功能冻结后 |

---

## 风险与管控点

| 风险 | 触发点 | 管控 |
| --- | --- | --- |
| PR #1047 未合入或行为不符 | T-01 | 失败即改用 fork + 指定 commit，并把结论写进 BR-03 |
| 属性控制与情绪 Spike 均不通过 | T-05 | 按 BR-82 撤下 UI 控件，A-6 触发条件按联动说明同步修订 |
| 卸载后 RSS 不回落 | T-47 | 按 G3 三项分开判定，不达标即算失败，不得用 MLX 指标替代 |
| 内置音色无法枚举 | T-06 | 保持自由输入 + BR-22 回显有效音色文案 |
| 临时文件竞态实现偏差 | T-30 | 必须按 BR-97 做临界区判断，列为代码评审重点项 |
| 1000 码点上限不成立 | T-08 | 按 BR-94 冻结实测值，同步 README 与 `docs/api.md` |
