import type {
  ChatStreamChunk,
  ErrorResponse,
  HealthResponse,
  HealthState,
} from './types'

const HEALTH_STATES: readonly HealthState[] = [
  'unloaded',
  'loading',
  'ready',
  'generating',
  'unloading',
  'failed',
]

export class ApiError extends Error {
  readonly type: string

  constructor(type: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.type = type
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isErrorResponse(value: unknown): value is ErrorResponse {
  if (!isRecord(value)) return false
  const error = value.error
  if (!isRecord(error)) return false
  return typeof error.type === 'string' && typeof error.message === 'string'
}

export async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body: unknown = await response.json()
    if (isErrorResponse(body)) {
      return new ApiError(body.error.type, body.error.message)
    }
  } catch {
    // 错误响应不是 JSON 时按状态码兜底
  }
  return new ApiError('http_error', `服务返回了异常状态码 ${response.status}`)
}

export async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new ApiError('invalid_response', '服务返回的数据无法解析')
  }
}

export function isChatStreamChunk(value: unknown): value is ChatStreamChunk {
  if (!isRecord(value)) return false
  const choices = value.choices
  if (!Array.isArray(choices)) return false
  return choices.every((choice: unknown) => {
    if (!isRecord(choice)) return false
    const delta = choice.delta
    if (!isRecord(delta)) return false
    return delta.content === undefined || typeof delta.content === 'string'
  })
}

export function isHealthState(value: unknown): value is HealthState {
  return typeof value === 'string' && HEALTH_STATES.some((state) => state === value)
}

export function isHealthResponse(value: unknown): value is HealthResponse {
  if (!isRecord(value)) return false
  return (
    (value.status === 'ok' || value.status === 'degraded') &&
    isHealthState(value.state) &&
    typeof value.model_loaded === 'boolean' &&
    typeof value.idle_seconds === 'number' &&
    typeof value.idle_timeout_seconds === 'number' &&
    (value.last_error === undefined ||
      value.last_error === null ||
      typeof value.last_error === 'string')
  )
}

/**
 * 把任意异常收敛成可以展示给用户的中文提示（BR-66），不暴露类型名和堆栈。
 */
export function errorMessageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  return '请求失败，请检查服务是否仍在运行'
}
