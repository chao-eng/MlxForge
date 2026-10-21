export type ChatRole = 'system' | 'user' | 'assistant'

export type FinishReason = 'stop' | 'length'

export interface Message {
  role: ChatRole
  content: string
}

export interface ChatRequest {
  model: string
  messages: Message[]
  stream: boolean
  max_tokens?: number
}

export interface ChatChoice {
  index: number
  message: {
    role: ChatRole
    content: string
  }
  finish_reason: FinishReason | null
}

export interface ChatResponse {
  id: string
  object: string
  created: number
  model: string
  choices: ChatChoice[]
}

export interface ChatStreamDelta {
  role?: ChatRole
  content?: string
}

export interface ChatStreamChoice {
  index: number
  delta: ChatStreamDelta
  finish_reason: FinishReason | null
}

export interface ChatStreamChunk {
  id: string
  object: string
  created: number
  model: string
  choices: ChatStreamChoice[]
}

export type HealthState =
  | 'unloaded'
  | 'loading'
  | 'ready'
  | 'generating'
  | 'unloading'
  | 'failed'

export interface HealthResponse {
  status: 'ok' | 'degraded'
  state: HealthState
  model_loaded: boolean
  idle_seconds: number
  idle_timeout_seconds: number
  last_error?: string | null
}

export interface ErrorResponse {
  error: {
    type: string
    message: string
  }
}
