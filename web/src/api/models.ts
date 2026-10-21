import { ApiError, isRecord, readJson, toApiError } from './http'
import type { ModelListResponse } from './types'

const MODELS_ENDPOINT = '/v1/models'

export type ModelKey = 'hy-mt2' | 'ming'

// 两个运行时各自返回自己的模型 ID，据此判断当前服务实际在跑哪个模型
const MODEL_KEYS: Record<string, ModelKey> = {
  'Hy-MT2': 'hy-mt2',
  'Ming-3.0-tts': 'ming',
}

export interface ModelAvailability {
  hyMt2: boolean
  ming: boolean
}

function isModelListResponse(value: unknown): value is ModelListResponse {
  if (!isRecord(value)) return false
  const data = value.data
  if (!Array.isArray(data)) return false
  return data.every((item: unknown) => isRecord(item) && typeof item.id === 'string')
}

export async function getModelAvailability(): Promise<ModelAvailability> {
  const response = await fetch(MODELS_ENDPOINT, {
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw await toApiError(response)
  }

  const data = await readJson(response)
  if (!isModelListResponse(data)) {
    throw new ApiError('invalid_response', '模型列表数据无法解析')
  }

  const availability: ModelAvailability = { hyMt2: false, ming: false }
  for (const model of data.data) {
    const key = MODEL_KEYS[model.id]
    if (key === 'hy-mt2') availability.hyMt2 = true
    if (key === 'ming') availability.ming = true
  }
  return availability
}
