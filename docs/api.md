# MlxForge API

两个运行时各自启动一个进程，默认都监听 `127.0.0.1:8000`，没有鉴权，默认不启用 CORS；Web UI 与接口同源，同一时间只能启动一个运行时。

- Hy-MT2：字段定义以 [hy-mt2-prd.md](hy-mt2-prd.md) 的 UC-04、UC-05、UC-06 为准
- Ming-3.0-tts：字段定义以 [ming3-tts-prd.md](ming3-tts-prd.md) 的 §4、§6.2 和附录 A-6 为准

## Hy-MT2

### GET /v1/models

```json
{
  "object": "list",
  "data": [{"id": "Hy-MT2", "object": "model", "owned_by": "local"}]
}
```

不触发模型加载。`id` 固定为 `Hy-MT2`。

### POST /v1/chat/completions

请求体上限 1MB。未识别字段忽略，`model` 原样回显，服务端不改写消息内容。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `model` | string | 否 | `Hy-MT2` | 原样回显 |
| `messages` | array | 是 | 无 | 至少 1 条，`role` 取 `system`、`user`、`assistant` |
| `stream` | bool | 否 | `false` | `true` 时返回 SSE |
| `max_tokens` | int | 否 | `4096` | 1~8192 |
| `temperature` | float | 否 | `0.7` | 0~2 |
| `top_p` | float | 否 | `0.6` | 0~1 |
| `top_k` | int | 否 | `20` | 0~100 |
| `repetition_penalty` | float | 否 | `1.05` | 0.5~2.0 |

目标语言写进最后一条 user 消息。服务端用启动时加载的 tokenizer 计算输入 token 数，输入长度加 `max_tokens` 超过上下文时返回 400，不加载权重。

官方默认提示词格式（中文提示词配中文语言名，英文提示词配英文语言名，二者不要混用）：

```text
将以下文本翻译为 {target_lang}，注意只需要输出翻译后的结果，不要额外解释：
{source_text}
```

```text
Translate the following text into {target_lang}. Note that you should only output the translated result without any additional explanation:
{source_text}
```

CLI 和 Web UI 使用中文格式，语言名取官方中文名；CLI 也接受英文名和缩写，内部会归一成中文名。

#### 非流式响应

```json
{
  "id": "chatcmpl-2c0a0816-3be5-41a7-b073-fcdd29e79a2e",
  "object": "chat.completion",
  "created": 1792566510,
  "model": "Hy-MT2",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "早上好。"},
      "finish_reason": "stop"
    }
  ]
}
```

不返回 `usage`。`finish_reason` 正常结束为 `stop`，达到 `max_tokens` 为 `length`。

#### 流式响应

`text/event-stream`。服务端先完成整段生成，再把译文切成中文单字、英文单词、标点和空白逐块下发，不是逐 token 生成。

```text
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1792566510,"model":"Hy-MT2","choices":[{"index":0,"delta":{"content":"早"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1792566510,"model":"Hy-MT2","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

生成失败时下发一条 `data: {"error": {"type": "...", "message": "..."}}` 后关闭连接，不再下发 `[DONE]`。

### GET /health

不触发模型加载，不暴露本地路径。

```json
{
  "status": "ok",
  "state": "ready",
  "model_loaded": true,
  "idle_seconds": 12.3,
  "idle_timeout_seconds": 1200
}
```

| 字段 | 说明 |
| --- | --- |
| `status` | `ok` 可服务；`degraded` 表示加载失败 |
| `state` | `unloaded`、`loading`、`ready`、`generating`、`unloading`、`failed` |
| `model_loaded` | 权重是否在内存，`loading` 期间为 `false` |
| `idle_seconds` | 距最后一次生成完成的秒数 |
| `idle_timeout_seconds` | 空闲阈值，`0` 表示常驻 |
| `last_error` | 仅 `failed` 时出现，中文说明，不含堆栈 |

### 错误

所有错误响应统一为：

```json
{"error": {"type": "invalid_request_error", "message": "原文太长，请分段翻译"}}
```

| HTTP | `error.type` | 场景 |
| --- | --- | --- |
| 400 | `invalid_request_error` | 字段缺失、参数越界、输入超长 |
| 404 | `not_found` | 接口不存在 |
| 405 | `method_not_allowed` | 请求方法不允许 |
| 413 | `payload_too_large` | 请求体超过 1MB |
| 429 | `queue_full` | 等待队列已满，带 `Retry-After: 1` |
| 503 | `model_unavailable` | 权重缺失、加载失败、服务正在停止 |
| 500 | `internal_error` | 未预期异常，堆栈只进日志 |

### 运行约束

- 单 worker 串行推理，等待队列默认 8，可用 `HY_MT2_MAX_QUEUE` 调整。
- 客户端在排队时断开，请求移出队列；已开始生成时不中断，完成后丢弃结果。
- 收到 SIGTERM 后排队请求立即返回 503，在途生成最多等待 30 秒。

## Ming-3.0-tts

只实现 OpenAI Audio Speech 的非流式兼容子集。矩阵外的行为不承诺兼容，`stream=true` 返回 400。

### GET /v1/models

```json
{
  "object": "list",
  "data": [
    {
      "id": "Ming-3.0-tts",
      "object": "model",
      "created": 1792566510,
      "owned_by": "mlxforge"
    }
  ]
}
```

不触发模型加载。`created` 是进程启动时间。

### POST /v1/audio/speech

请求体上限 20MB，超出返回 413 且不解析正文。未识别字段忽略；`model` 接受任意字符串，实际只服务 `Ming-3.0-tts`，不因未知模型名返回 400。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `model` | string | 否 | `Ming-3.0-tts` | 不校验取值 |
| `input` | string | 是 | 无 | 去除首尾空白后 1~1000 个 Unicode 码点，见下方计数口径 |
| `voice` | string | 否 | `auto` | `auto`、`design` 或内置音色名 |
| `language` | string | 否 | `auto` | `auto`、`zh`、`en`、`de`、`es`、`fr`、`ko`、`ja`、`sichuanese`、`cantonese` |
| `response_format` | string | 否 | `wav` | 只支持 `wav`、`pcm` |
| `speed` | float | 否 | `1.0` | 0.5~2.0，实验能力 |
| `pitch` | int | 否 | `0` | -12~12，实验能力 |
| `volume` | float | 否 | `1.0` | 0.5~2.0，实验能力 |
| `cfg` | float | 否 | `2.0` | 1.0~5.0，流匹配头的 CFG scale，越大越贴近描述 |
| `sigma` | float | 否 | `0.25` | 0~1，流匹配头的采样噪声，越大变化越多 |
| `emotion` | string | 否 | 空 | 1~32 个码点，实验能力 |
| `instructions` | string | 否 | 空 | 1~500 个码点，映射到自由指令、声音设计或 IP 模式 |
| `reference_audio` | string | 否 | 空 | base64 或 `data:<类型>;base64,<数据>`，必须与 `reference_text` 成对出现 |
| `reference_text` | string | 否 | 空 | 参考音频的逐字转录，1~500 个码点 |
| `task` | string | 否 | `auto` | `auto`、`tts`、`freeform`、`voice_design`、`multilingual`、`basic`、`emotion`、`dialect`、`ip` |
| `seed` | int | 否 | 随机 | 0~2147483647，实际值见响应头 `X-Seed` |
| `stream` | bool | 否 | `false` | v1 只支持非流式，`true` 返回 400 |

参考音频限制：WAV 或 FLAC，5~30 秒，采样率 16k~48kHz，单声道或双声道，解码后不超过 10MB。不合格返回 400。

`voice` 只校验命名形式（`US_*`、`UK_*` 或纯中文名），无法判断「名字合法但音色不存在」；这类值会原样透传给模型，不报错。OpenAI 默认音色名（`alloy`、`echo`、`nova` 等）显式返回 400，不静默回退。官方内置音色共 482 个（5 个英文、48 个中文、429 个中文情绪变体），完整清单见 [voices.md](voices.md)。

`cfg` 和 `sigma` 只影响流匹配头的采样，不算「控制项」，不参与任务模式解析和冲突检查；改这两个值不会改变解析出的 `task`。

`instructions` 在 `task=voice_design` 下按官方协议组装成结构化 caption（描述写入「风格」字段），在 `task=freeform` 下作为纯文本指令原样传入，两者训练输入不同，不要混用。

台词里可以直接写副语言标签：`[Breathing]`、`[Cough]`、`[Sigh]`、`[Laughter]`、`[Surprise-ah]`、`[Surprise-oh]`、`[Dissatisfaction-hnn]`、`[Uhm]`、`[Confirmation-en]`、`[Question-ei]`、`[Question-ah]`、`[Question-en]`、`[Question-oh]`、`[Question-huh]`。

#### 输入计数口径

`input`、`instructions`、`emotion`、`reference_text` 的长度都按 **Unicode 码点** 计数，不是 UTF-16 码元，也不是字节。

- Python：`len(text)`
- JavaScript：`Array.from(text).length`，不要用 `text.length`（会把 emoji 等算成两个）

1000 个码点是**临时上限**，Spike 确认长文本能力和耗时后冻结。超出上限返回 400。

#### 任务模式

`task` 的权威定义见 PRD 附录 A-6，这里只列摘要。`auto` 是请求值，不会出现在响应头 `X-Resolved-Task` 中。

| `task` | 模型侧任务 | `auto` 触发条件 | 必填 | 禁止（400） |
| --- | --- | --- | --- | --- |
| `tts` | `TTS` | 有 `reference_audio`；或 `voice` 为内置音色且无其他控制项 | `input`；克隆时 `reference_text` | `voice=design`、`instructions`、`emotion`、非默认属性、方言 |
| `freeform` | `FREEFORM` | 有 `instructions`，且无音色、参考音频、情绪、属性、方言 | `instructions` | 内置音色、`voice=design`、`emotion`、非默认属性、方言 |
| `voice_design` | `VOICE_DESIGN` | `voice=design` | `instructions` | 参考音频、内置音色、`emotion`、非默认属性、方言 |
| `multilingual` | `MULTILINGUAL` | `language` 为 de/es/fr/ko/ja，且无音色、指令、情绪、属性 | `language` | `instructions`、`emotion`、非默认属性、方言、参考音频、`voice=design` |
| `basic` | `BASIC` | 无任何控制项 | `input` | `voice`≠`auto`、`instructions`、`emotion`、非默认属性、参考音频、方言、de/es/fr/ko/ja |
| `emotion` | `EMOTION` | `emotion` 或属性非默认，且无指令、方言、参考音频 | `emotion` 或至少一项非默认属性 | `instructions`、方言、参考音频、`voice=design` |
| `dialect` | `DIALECT` | `language` 为 sichuanese/cantonese，且无指令、情绪、属性、参考音频 | `language` | `instructions`、`emotion`、非默认属性、参考音频、`voice=design` |
| `ip` | `IP` | 仅显式 `task=ip` | `instructions` | 参考音频、内置音色、`emotion`、非默认属性、方言 |

`auto` 解析顺序：参考音频 → `voice=design` → 方言 → 情绪或非默认属性 → `instructions` → 内置音色 → de/es/fr/ko/ja → `basic`。

解析前先做七项冲突检查，命中任一直接 400，不做静默降级。参数冲突要么显式选择任务模式，要么移除冲突字段。`freeform` 带参考音频只能显式指定，`auto` 不会推断出这一组合。

#### 能力状态

| 能力 | 状态 | API 行为 |
| --- | --- | --- |
| 基础合成、内置音色、声音克隆、声音设计、多语言 | 已验证 | 正常处理 |
| `emotion`、`speed`、`pitch`、`volume`、方言、`task=ip` | 实验 | 原样透传，不返回 400，也不承诺效果；模型不识别时按默认语气合成 |
| 流式音频、MP3/Opus/AAC/FLAC 输出 | 不支持 | 返回 400 |

情绪是自由字符串，建议值：中性、高兴、悲伤、愤怒、惊讶、恐惧、厌恶、温柔、严肃。服务端不校验具体词。

声音克隆不能叠加 `emotion`、方言或 `speed`/`pitch`/`volume`：官方实现依赖 CAM++ 说话人嵌入，mlx-audio 尚未移植，本服务保持 400 拒绝，不做效果打折的静默降级。

#### 响应头

成功响应是纯二进制，`Content-Type` 为 `audio/wav` 或 `audio/pcm`。

| 响应头 | 说明 |
| --- | --- |
| `X-Request-Id` | 请求标识，UUID |
| `X-Resolved-Task` | 实际使用的模型侧任务：`TTS`、`FREEFORM`、`VOICE_DESIGN`、`MULTILINGUAL`、`BASIC`、`EMOTION`、`DIALECT`、`IP` |
| `X-Seed` | 本次使用的随机种子，未传时为服务生成的值 |
| `X-Audio-Sample-Rate` | 固定 `44100` |
| `X-Audio-Bits` | 固定 `16` |
| `X-Audio-Channels` | 固定 `1` |
| `X-Audio-Byte-Order` | 固定 `little`，PCM 为小端裸字节流 |
| `X-Audio-Duration` | 音频时长，秒，保留两位小数 |
| `X-Audio-Format` | `wav` 或 `pcm` |
| `Content-Disposition` | `attachment; filename="speech-<request_id>.wav"`，扩展名随格式变化 |
| `Cache-Control` | `no-store` |

输出固定 44.1kHz、16-bit、单声道。裸 PCM 没有容器头，必须靠 `X-Audio-*` 判断格式。

#### 示例

curl：

```bash
curl http://127.0.0.1:8000/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"Ming-3.0-tts","input":"今天下午三点我们在楼下咖啡店见面。","voice":"auto","response_format":"wav"}' \
  -o speech.wav
```

OpenAI Python SDK（`openai==1.109.1` 实测）：

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-needed")

response = client.audio.speech.create(
    model="Ming-3.0-tts",
    voice="auto",
    input="今天下午三点我们在楼下咖啡店见面。",
    response_format="wav",
)
response.write_to_file("speech.wav")
```

`voice`、`response_format` 应显式传入。不同 SDK 版本对 `response_format` 的默认处理不一致（实测 `1.109.1` 未显式传时会省略该字段，服务端按 `wav` 处理），显式传值才不会随版本变化。`api_key` 填任意非空值即可，服务端不校验鉴权。

### GET /health

不触发模型加载，不暴露本地路径。

```json
{
  "status": "ok",
  "state": "ready",
  "model_loaded": true,
  "idle_seconds": 12.3,
  "idle_timeout_seconds": 1200,
  "sample_rate": 44100
}
```

| 字段 | 说明 |
| --- | --- |
| `status` | `ok` 可服务；`degraded` 表示权重缺失或加载失败 |
| `state` | `unloaded`、`loading`、`ready`、`generating`、`unloading`、`failed` |
| `model_loaded` | 权重是否在内存，`loading` 期间为 `false` |
| `idle_seconds` | 距最后一次生成完成的秒数 |
| `idle_timeout_seconds` | 空闲阈值，`0` 表示常驻 |
| `sample_rate` | 固定 `44100` |
| `last_error` | 仅失败时出现，中文说明，不含堆栈 |

### 错误

结构与 Hy-MT2 一致：

```json
{"error": {"type": "invalid_request_error", "message": "input 必填，去除首尾空白后不能为空"}}
```

| HTTP | `error.type` | 场景 |
| --- | --- | --- |
| 400 | `invalid_request_error` | 字段缺失、参数越界、任务模式冲突、参考音频不合格、不支持的格式或流式、Host 头不被允许 |
| 404 | `not_found` | 接口不存在 |
| 405 | `method_not_allowed` | 请求方法不允许 |
| 413 | `payload_too_large` | 请求体超过 20MB |
| 429 | `queue_full` | 等待队列已满或排队超时，带 `Retry-After: 5` |
| 503 | `model_unavailable` | 权重缺失、加载失败、参考音频临时目录不可用、服务正在停止 |
| 500 | `internal_error` | 未预期异常，堆栈只进日志 |

`Retry-After` 是固定值 5 秒，不保证重试时队列已有余量。

### 运行约束

- 单 worker 串行推理，避免并发进入 Metal；采样噪声是全局状态，并发会串线。
- 1 个在途任务 + 默认 8 个等待任务，可用 `MING_TTS_MAX_QUEUE` 调整；第 9 个等待请求返回 429。
- 排队超时默认 120 秒，从入队成功开始计时，可用 `MING_TTS_QUEUE_TIMEOUT` 调整；超时返回 429，不重复处理。
- 客户端排队时断开，请求移出队列；已开始合成不中断，完成后丢弃结果。
- 参考音频只在不持久化的临时目录中处理，请求结束即删除；目录不可用时克隆返回 503，其他模式不受影响。
- 默认只监听 `127.0.0.1`，开放局域网必须同时设置 `MING_TTS_ALLOW_REMOTE=1`，否则启动失败。服务没有鉴权，同网段设备都能调用。
- 收到 SIGTERM 后排队请求返回 503，在途合成最多等待 120 秒。
- 模型空闲默认 1200 秒后卸载，`MING_TTS_IDLE_TIMEOUT` 可调，`0` 表示常驻。
