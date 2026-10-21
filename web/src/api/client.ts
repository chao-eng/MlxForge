import {
  ApiError,
  isChatStreamChunk,
  isErrorResponse,
  isHealthResponse,
  readJson,
  toApiError,
} from './http'
import type { ChatRequest, HealthResponse } from './types'

const CHAT_ENDPOINT = '/v1/chat/completions'
const HEALTH_ENDPOINT = '/health'
const MODEL_ID = 'Hy-MT2'

export { ApiError } from './http'

function buildPrompt(text: string, target: string): string {
  // 官方中文指令格式：中文提示词配中文语言名，且只输出译文
  return `将以下文本翻译为 ${target}，注意只需要输出翻译后的结果，不要额外解释：\n${text}`
}

function buildRequest(text: string, target: string, stream: boolean): ChatRequest {
  return {
    model: MODEL_ID,
    messages: [{ role: 'user', content: buildPrompt(text, target) }],
    stream,
  }
}

/**
 * 解析一行 SSE 数据。返回 true 表示收到了 [DONE]。
 */
function consumeDataLine(line: string, onChunk: (chunk: string) => void): boolean {
  if (!line.startsWith('data:')) return false
  const payload = line.slice('data:'.length).trim()
  if (payload.length === 0) return false
  if (payload === '[DONE]') return true

  let parsed: unknown
  try {
    parsed = JSON.parse(payload)
  } catch {
    // 跳过无法解析的行，避免单个坏块中断整段译文
    return false
  }

  if (isErrorResponse(parsed)) {
    throw new ApiError(parsed.error.type, parsed.error.message)
  }
  if (!isChatStreamChunk(parsed)) return false

  const choice = parsed.choices[0]
  if (choice === undefined) return false
  const content = choice.delta.content
  if (typeof content === 'string' && content.length > 0) {
    onChunk(content)
  }
  return false
}

export async function streamTranslate(
  text: string,
  target: string,
  onChunk: (chunk: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(CHAT_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(buildRequest(text, target, true)),
    signal,
  })

  if (!response.ok) {
    throw await toApiError(response)
  }

  const body = response.body
  if (body === null) {
    throw new ApiError('stream_error', '服务没有返回可读取的数据流')
  }

  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finished = false

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, { stream: true })

      if (finished) {
        // 已收到 [DONE]，继续把剩余字节读完，避免浏览器把连接记为 ERR_ABORTED
        buffer = ''
        continue
      }

      let lineEnd = buffer.indexOf('\n')
      while (lineEnd !== -1) {
        const line = buffer.slice(0, lineEnd).trim()
        buffer = buffer.slice(lineEnd + 1)
        if (consumeDataLine(line, onChunk)) {
          finished = true
          buffer = ''
          break
        }
        lineEnd = buffer.indexOf('\n')
      }
    }

    // 处理末尾没有换行的最后一块
    const tail = buffer.trim()
    if (!finished && tail.length > 0) {
      consumeDataLine(tail, onChunk)
    }
  } finally {
    reader.releaseLock()
  }
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(HEALTH_ENDPOINT, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw await toApiError(response)
  }

  const data = await readJson(response)
  if (!isHealthResponse(data)) {
    throw new ApiError('invalid_response', '健康状态数据无法解析')
  }
  return data
}
