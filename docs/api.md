# Hy-MT2 API

本地服务的 HTTP 接口。默认监听 `127.0.0.1:8000`，没有鉴权，默认不启用 CORS；Web UI 与接口同源。字段定义以 [hy-mt2-prd.md](hy-mt2-prd.md) 的 UC-04、UC-05、UC-06 为准。

## GET /v1/models

```json
{
  "object": "list",
  "data": [{"id": "Hy-MT2", "object": "model", "owned_by": "local"}]
}
```

不触发模型加载。`id` 固定为 `Hy-MT2`。

## POST /v1/chat/completions

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

### 非流式响应

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

### 流式响应

`text/event-stream`。服务端先完成整段生成，再把译文切成中文单字、英文单词、标点和空白逐块下发，不是逐 token 生成。

```text
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1792566510,"model":"Hy-MT2","choices":[{"index":0,"delta":{"content":"早"},"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1792566510,"model":"Hy-MT2","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

生成失败时下发一条 `data: {"error": {"type": "...", "message": "..."}}` 后关闭连接，不再下发 `[DONE]`。

## GET /health

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

## 错误

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

## 运行约束

- 单 worker 串行推理，等待队列默认 8，可用 `HY_MT2_MAX_QUEUE` 调整。
- 客户端在排队时断开，请求移出队列；已开始生成时不中断，完成后丢弃结果。
- 收到 SIGTERM 后排队请求立即返回 503，在途生成最多等待 30 秒。
