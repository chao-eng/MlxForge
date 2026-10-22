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
  sample_rate?: number
}

export interface ModelInfo {
  id: string
  object: string
  created?: number
  owned_by?: string
}

export interface ModelListResponse {
  object: string
  data: ModelInfo[]
}

export type AudioFormat = 'wav' | 'pcm'

/** 与 API 的请求字段一一对应，未使用的可选字段不发送（PRD 第 3 章）。 */
export interface SpeechRequest {
  model: string
  input: string
  voice: string
  language: string
  response_format: AudioFormat
  reference_audio?: string
  reference_text?: string
  instructions?: string
  task?: SpeechTask
  cfg?: number
  sigma?: number
}

export type SpeechTask =
  | 'auto'
  | 'tts'
  | 'freeform'
  | 'voice_design'
  | 'multilingual'
  | 'basic'
  | 'emotion'
  | 'dialect'
  | 'ip'

export interface SpeechResult {
  blob: Blob
  format: AudioFormat
  durationSeconds: number | null
  elapsedMs: number
  requestId: string
  resolvedTask: string
}

export interface ErrorResponse {
  error: {
    type: string
    message: string
  }
}
