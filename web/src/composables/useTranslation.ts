import { computed, ref } from 'vue'
import { ApiError, streamTranslate } from '../api/client'

// 官方支持语言表，顺序与模型卡一致；中文提示词要求语言名也用中文
export const TARGET_LANGUAGES: readonly string[] = [
  '中文',
  '英语',
  '法语',
  '葡萄牙语',
  '西班牙语',
  '日语',
  '土耳其语',
  '俄语',
  '阿拉伯语',
  '韩语',
  '泰语',
  '意大利语',
  '德语',
  '越南语',
  '马来语',
  '印尼语',
  '菲律宾语',
  '印地语',
  '繁体中文',
  '波兰语',
  '捷克语',
  '荷兰语',
  '高棉语',
  '缅甸语',
  '波斯语',
  '古吉拉特语',
  '乌尔都语',
  '泰卢固语',
  '马拉地语',
  '希伯来语',
  '孟加拉语',
  '泰米尔语',
  '乌克兰语',
  '藏语',
  '哈萨克语',
  '蒙古语',
  '维吾尔语',
  '粤语',
]

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.type) {
      case 'invalid_request_error':
        return '原文太长或参数不符合要求，请调整后重试'
      case 'queue_full':
        return '当前请求太多，请稍后重试'
      case 'model_unavailable':
        return '翻译模型暂不可用，请稍后重试'
      case 'internal_error':
        return '服务暂时不可用，请查看服务日志'
      default:
        return '翻译失败，请稍后重试'
    }
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '翻译已取消'
  }
  if (error instanceof TypeError) {
    return '无法连接翻译服务，请确认服务已启动'
  }
  return '翻译失败，请稍后重试'
}

export function useTranslation() {
  const sourceText = ref('')
  const targetLanguage = ref<string>('中文')
  const translatedText = ref('')
  const isTranslating = ref(false)
  const errorMessage = ref('')
  const elapsedMs = ref<number | null>(null)

  const canTranslate = computed(
    () => sourceText.value.trim().length > 0 && !isTranslating.value,
  )

  async function runTranslation(): Promise<void> {
    const text = sourceText.value.trim()
    if (text.length === 0 || isTranslating.value) return

    isTranslating.value = true
    errorMessage.value = ''
    translatedText.value = ''
    elapsedMs.value = null

    const startedAt = performance.now()
    try {
      // 服务端整段生成后分块下发，这里按块追加，只做展示不做逐 token 承诺
      await streamTranslate(text, targetLanguage.value, (chunk) => {
        translatedText.value += chunk
      })
      elapsedMs.value = Math.round(performance.now() - startedAt)
    } catch (error) {
      translatedText.value = ''
      errorMessage.value = describeError(error)
    } finally {
      isTranslating.value = false
    }
  }

  return {
    sourceText,
    targetLanguage,
    translatedText,
    isTranslating,
    errorMessage,
    elapsedMs,
    canTranslate,
    runTranslation,
  }
}
