import { ApiError, toApiError } from './http'
import type { AudioFormat, SpeechRequest, SpeechResult } from './types'

const SPEECH_ENDPOINT = '/v1/audio/speech'
const MODEL_ID = 'Ming-3.0-tts'

export class SpeechAbortError extends Error {
  constructor() {
    super('请求已中止')
    this.name = 'SpeechAbortError'
  }
}

function parseDuration(value: string | null): number | null {
  if (value === null) return null
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : null
}

function parseFormat(value: string | null, contentType: string): AudioFormat {
  if (value === 'pcm' || contentType.includes('pcm')) return 'pcm'
  return 'wav'
}

/**
 * 调用非流式合成接口，返回音频 Blob 与响应头里的元信息（BR-42）。
 * 超时与取消都用 AbortSignal 表示，由调用方区分场景。
 */
export async function synthesizeSpeech(
  request: SpeechRequest,
  signal: AbortSignal,
): Promise<SpeechResult> {
  const started = performance.now()
  let response: Response
  try {
    response = await fetch(SPEECH_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'audio/wav, audio/pcm',
      },
      body: JSON.stringify(request),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new SpeechAbortError()
    }
    throw error
  }

  if (!response.ok) {
    throw await toApiError(response)
  }

  const blob = await response.blob()
  if (blob.size === 0) {
    throw new ApiError('empty_audio', '服务返回了空音频，请稍后重试')
  }

  const headers = response.headers
  const format = parseFormat(headers.get('X-Audio-Format'), blob.type)
  return {
    blob,
    format,
    durationSeconds: parseDuration(headers.get('X-Audio-Duration')),
    elapsedMs: performance.now() - started,
    requestId: headers.get('X-Request-Id') ?? '',
    resolvedTask: headers.get('X-Resolved-Task') ?? '',
  }
}

export { MODEL_ID as SPEECH_MODEL_ID }
