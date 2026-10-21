<script setup lang="ts">
import { computed, ref } from 'vue'
import type { UploadChangeContext, UploadFile } from 'tdesign-vue-next/es/upload/type'
import type { ReferenceAudioController } from '../composables/useReferenceAudio'

const MAX_REFERENCE_TEXT_CODEPOINTS = 500

const props = defineProps<{
  reference: ReferenceAudioController
  refText: string
  disabled: boolean
}>()

const emit = defineEmits<{
  'update:refText': [value: string]
}>()

const files = ref<UploadFile[]>([])

const refTextModel = computed<string>({
  get: () => props.refText,
  set: (value) => emit('update:refText', value),
})

const referenceInfo = computed<string>(() => {
  const { fileName, durationSeconds, sizeBytes } = props.reference
  if (fileName.value.length === 0) return ''
  const duration = (durationSeconds.value ?? 0).toFixed(1)
  const size = (sizeBytes.value / (1024 * 1024)).toFixed(1)
  return `${fileName.value} · ${duration} 秒 · ${size} MB`
})

const referenceError = computed<string>(() => props.reference.errorMessage.value)
const refTextCount = computed<number>(() => Array.from(props.refText).length)
const refTextTooLong = computed<boolean>(() => refTextCount.value > MAX_REFERENCE_TEXT_CODEPOINTS)

async function handleChange(_value: UploadFile[], context: UploadChangeContext): Promise<void> {
  const raw = context.file?.raw
  if (raw === undefined) return
  await props.reference.select(raw)
  // 校验失败时清空文件列表，避免 max=1 挡住下一次选择
  if (props.reference.errorMessage.value.length > 0) {
    files.value = []
  }
}

function handleRemove(): void {
  files.value = []
  props.reference.clear()
}
</script>

<template>
  <div class="clone-fields">
    <div class="field">
      <span class="field-label">参考音频（必填）</span>
      <t-upload
        v-model:files="files"
        :auto-upload="false"
        :max="1"
        accept=".wav,.flac"
        :disabled="disabled"
        @change="handleChange"
        @remove="handleRemove"
      >
        <t-button variant="outline" :disabled="disabled">选择 WAV / FLAC</t-button>
      </t-upload>
      <span v-if="referenceInfo" class="field-meta">{{ referenceInfo }}</span>
      <span v-if="referenceError" class="field-error">{{ referenceError }}</span>
      <span v-else class="field-hint">支持 WAV / FLAC，时长 5~30 秒，不超过 10MB</span>
    </div>

    <div class="field">
      <span class="field-label">参考文本（必填）</span>
      <t-textarea
        v-model="refTextModel"
        placeholder="逐字转录参考音频的内容，必须与音频里说的话完全一致"
        :autosize="{ minRows: 3, maxRows: 6 }"
        :disabled="disabled"
      />
      <span class="field-hint" :class="{ 'field-error': refTextTooLong }">
        {{ refTextCount }}/{{ MAX_REFERENCE_TEXT_CODEPOINTS }}，必须与参考音频逐字一致
      </span>
    </div>
  </div>
</template>

<style scoped>
.clone-fields {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.field-hint {
  font-size: 13px;
  color: var(--td-text-color-placeholder);
}

.field-meta {
  font-size: 13px;
  color: var(--td-text-color-primary);
}

.field-error {
  font-size: 13px;
  color: var(--td-error-color);
}
</style>
