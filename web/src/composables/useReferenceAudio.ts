import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'

const MIN_SECONDS = 5
const MAX_SECONDS = 30
const MAX_BYTES = 10 * 1024 * 1024
const SUPPORTED_EXTENSIONS = ['wav', 'flac']

export interface ReferenceAudioController {
  fileName: Ref<string>
  durationSeconds: Ref<number | null>
  sizeBytes: Ref<number>
  errorMessage: Ref<string>
  base64: Ref<string>
  ready: ComputedRef<boolean>
  select: (file: File) => Promise<void>
  clear: () => void
}

function ascii(view: DataView, offset: number, length: number): string {
  let text = ''
  for (let index = 0; index < length; index += 1) {
    text += String.fromCharCode(view.getUint8(offset + index))
  }
  return text
}

function parseWavDuration(view: DataView): number | null {
  if (view.byteLength < 44 || ascii(view, 0, 4) !== 'RIFF' || ascii(view, 8, 4) !== 'WAVE') {
    return null
  }
  let offset = 12
  let byteRate = 0
  while (offset + 8 <= view.byteLength) {
    const id = ascii(view, offset, 4)
    const size = view.getUint32(offset + 4, true)
    if (id === 'fmt ' && offset + 20 <= view.byteLength) {
      byteRate = view.getUint32(offset + 16, true)
    }
    if (id === 'data') {
      if (byteRate === 0) return null
      return size / byteRate
    }
    offset += 8 + size + (size % 2)
  }
  return null
}

function parseFlacDuration(bytes: Uint8Array): number | null {
  // STREAMINFO 必须是第一个元数据块，采样率与总样本数按位打包在第 18~25 字节
  if (bytes.length < 42 || (bytes[4] & 0x7f) !== 0) return null
  const sampleRate = (bytes[18] << 12) | (bytes[19] << 4) | (bytes[20] >> 4)
  const totalSamples =
    (bytes[21] & 0x0f) * 2 ** 32 +
    bytes[22] * 2 ** 24 +
    bytes[23] * 2 ** 16 +
    bytes[24] * 2 ** 8 +
    bytes[25]
  if (sampleRate === 0 || totalSamples === 0) return null
  return totalSamples / sampleRate
}

function parseDuration(bytes: ArrayBuffer): number | null {
  const view = new DataView(bytes)
  if (view.byteLength < 4) return null
  const magic = ascii(view, 0, 4)
  if (magic === 'RIFF') return parseWavDuration(view)
  if (magic === 'fLaC') return parseFlacDuration(new Uint8Array(bytes))
  return null
}

function toBase64(bytes: ArrayBuffer): string {
  const data = new Uint8Array(bytes)
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < data.length; offset += chunkSize) {
    const chunk = data.subarray(offset, offset + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}

function formatSeconds(value: number): string {
  return value.toFixed(1)
}

/**
 * 参考音频只做容器头解析，不依赖后端就能给出格式、时长和体积提示（§5.2）。
 * 参考音频与文本一样不落盘，只在当前页面内存中保留。
 */
export function useReferenceAudio(): ReferenceAudioController {
  const fileName = ref('')
  const durationSeconds = ref<number | null>(null)
  const sizeBytes = ref(0)
  const errorMessage = ref('')
  const base64 = ref('')

  const ready = computed(() => base64.value.length > 0 && errorMessage.value === '')

  function clear(): void {
    fileName.value = ''
    durationSeconds.value = null
    sizeBytes.value = 0
    errorMessage.value = ''
    base64.value = ''
  }

  async function select(file: File): Promise<void> {
    clear()
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!SUPPORTED_EXTENSIONS.includes(extension)) {
      errorMessage.value = '只支持 WAV 或 FLAC 格式的参考音频'
      return
    }
    if (file.size > MAX_BYTES) {
      errorMessage.value = '参考音频不能超过 10MB'
      return
    }

    let buffer: ArrayBuffer
    try {
      buffer = await file.arrayBuffer()
    } catch {
      errorMessage.value = '无法读取该文件，请重新选择'
      return
    }

    const duration = parseDuration(buffer)
    if (duration === null) {
      errorMessage.value = '无法解析音频，请确认文件是完整的 WAV 或 FLAC'
      return
    }
    if (duration < MIN_SECONDS || duration > MAX_SECONDS) {
      errorMessage.value = `参考音频时长需在 ${MIN_SECONDS}~${MAX_SECONDS} 秒之间，当前 ${formatSeconds(duration)} 秒`
      return
    }

    fileName.value = file.name
    durationSeconds.value = duration
    sizeBytes.value = file.size
    base64.value = toBase64(buffer)
  }

  return { fileName, durationSeconds, sizeBytes, errorMessage, base64, ready, select, clear }
}
