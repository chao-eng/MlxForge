import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, errorMessageOf } from '../api/http'
import { SPEECH_MODEL_ID, SpeechAbortError, synthesizeSpeech } from '../api/speech'
import type { SpeechRequest, SpeechResult } from '../api/types'
import { useReferenceAudio } from './useReferenceAudio'

export type SpeechMode = 'builtin' | 'clone' | 'design'
export type DesignMode = 'voice_design' | 'freeform'

const MAX_TEXT_CODEPOINTS = 1000
const MAX_DESCRIPTION_CODEPOINTS = 500
const MAX_REFERENCE_TEXT_CODEPOINTS = 500
const DEFAULT_CFG = 2.0
const DEFAULT_SIGMA = 0.25
const REQUEST_TIMEOUT_MS = 180_000
const TIMEOUT_MESSAGE = '等待时间较长，请检查服务状态。当前合成可能仍在后台继续'

function timestamp(): string {
  const now = new Date()
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

export function useSpeech() {
  const mode = ref<SpeechMode>('builtin')
  const text = ref('')
  const language = ref('auto')
  const voice = ref('auto')
  const description = ref('')
  const designMode = ref<DesignMode>('voice_design')
  const cfg = ref(DEFAULT_CFG)
  const sigma = ref(DEFAULT_SIGMA)
  const refText = ref('')
  const authorized = ref(false)
  const reference = useReferenceAudio()

  const isSubmitting = ref(false)
  const errorMessage = ref('')
  const unknownOutcome = ref(false)
  const audioUrl = ref('')
  const downloadName = ref('')
  const audioDurationSeconds = ref<number | null>(null)
  const elapsedMs = ref<number | null>(null)

  const codepoints = computed(() => Array.from(text.value).length)
  const descriptionCodepoints = computed(() => Array.from(description.value).length)

  const canSubmit = computed(() => {
    if (isSubmitting.value) return false
    if (text.value.trim().length === 0 || codepoints.value > MAX_TEXT_CODEPOINTS) return false
    if (mode.value === 'clone') {
      return (
        reference.ready.value &&
        refText.value.trim().length > 0 &&
        Array.from(refText.value).length <= MAX_REFERENCE_TEXT_CODEPOINTS &&
        authorized.value
      )
    }
    if (mode.value === 'design') {
      return (
        description.value.trim().length > 0 &&
        descriptionCodepoints.value <= MAX_DESCRIPTION_CODEPOINTS
      )
    }
    return true
  })

  let controller: AbortController | null = null
  let timer: ReturnType<typeof setTimeout> | null = null

  function buildRequest(): SpeechRequest {
    const base: SpeechRequest = {
      model: SPEECH_MODEL_ID,
      input: text.value.trim(),
      voice: voice.value.trim() || 'auto',
      language: language.value,
      response_format: 'wav',
      cfg: cfg.value,
      sigma: sigma.value,
    }
    if (mode.value === 'clone') {
      return {
        ...base,
        voice: 'auto',
        reference_audio: reference.base64.value,
        reference_text: refText.value.trim(),
      }
    }
    if (mode.value === 'design') {
      // 声音设计和自由指令是两套训练输入，必须显式指定 task
      return {
        ...base,
        voice: designMode.value === 'voice_design' ? 'design' : 'auto',
        task: designMode.value,
        instructions: description.value.trim(),
      }
    }
    return base
  }

  function applyResult(result: SpeechResult): void {
    releaseAudioUrl()
    audioUrl.value = URL.createObjectURL(result.blob)
    downloadName.value = `ming-tts-${timestamp()}.${result.format}`
    audioDurationSeconds.value = result.durationSeconds
    elapsedMs.value = result.elapsedMs
  }

  function releaseAudioUrl(): void {
    if (audioUrl.value.length > 0) {
      URL.revokeObjectURL(audioUrl.value)
      audioUrl.value = ''
    }
  }

  async function submit(force = false): Promise<void> {
    if (unknownOutcome.value && !force) return
    if (!canSubmit.value) return

    isSubmitting.value = true
    errorMessage.value = ''
    controller = new AbortController()
    let timedOut = false
    timer = setTimeout(() => {
      timedOut = true
      controller?.abort()
    }, REQUEST_TIMEOUT_MS)

    try {
      const result = await synthesizeSpeech(buildRequest(), controller.signal)
      applyResult(result)
      unknownOutcome.value = false
    } catch (error) {
      if (error instanceof SpeechAbortError) {
        if (timedOut) {
          // 前端只放弃等待，服务端任务仍可能继续（BR-93）
          errorMessage.value = TIMEOUT_MESSAGE
          unknownOutcome.value = true
        }
        return
      }
      errorMessage.value = errorMessageOf(error)
      // 服务端明确拒绝时结果确定；网络类错误无法判断是否已入队
      unknownOutcome.value = !(error instanceof ApiError)
    } finally {
      if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
      controller = null
      isSubmitting.value = false
    }
  }

  onBeforeUnmount(() => {
    if (timer !== null) clearTimeout(timer)
    controller?.abort()
    releaseAudioUrl()
  })

  return {
    mode,
    text,
    language,
    voice,
    description,
    designMode,
    cfg,
    sigma,
    refText,
    authorized,
    reference,
    isSubmitting,
    errorMessage,
    unknownOutcome,
    codepoints,
    descriptionCodepoints,
    canSubmit,
    audioUrl,
    downloadName,
    audioDurationSeconds,
    elapsedMs,
    submit,
  }
}
