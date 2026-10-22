<script setup lang="ts">
import { computed, ref } from 'vue'
import AudioResult from './AudioResult.vue'
import CloneFields from './CloneFields.vue'
import DesignFields from './DesignFields.vue'
import ParalinguisticTags from './ParalinguisticTags.vue'
import { useSpeech } from '../composables/useSpeech'
import { VOICE_OPTION_GROUPS } from '../api/voices'

const MAX_TEXT_CODEPOINTS = 1000

const props = defineProps<{
  serviceAvailable: boolean
  modelAvailable: boolean
}>()

const {
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
  canSubmit,
  audioUrl,
  downloadName,
  audioDurationSeconds,
  elapsedMs,
  submit,
} = useSpeech()

// 方言在 Spike 通过前不显示，只保留 A-5 的七种语言（T-45）
const LANGUAGE_OPTIONS = [
  { label: '自动', value: 'auto' },
  { label: '中文', value: 'zh' },
  { label: '英语', value: 'en' },
  { label: '德语', value: 'de' },
  { label: '西班牙语', value: 'es' },
  { label: '法语', value: 'fr' },
  { label: '韩语', value: 'ko' },
  { label: '日语', value: 'ja' },
]

const VOICE_OPTIONS = [
  { label: 'auto（由模型决定）', value: 'auto' },
  ...VOICE_OPTION_GROUPS,
]

// 官方支持的 14 个副语言标签，说明放在折叠面板里，标签需要嵌在台词中
const PARALINGUISTIC_HINT = '支持 [Laughter]、[Sigh] 等 14 个副语言标签，展开下方查看说明'

const modeTabs = computed(() => [
  { value: 'builtin', label: '内置音色', disabled: isSubmitting.value },
  { value: 'clone', label: '声音克隆', disabled: isSubmitting.value },
  { value: 'design', label: '声音设计', disabled: isSubmitting.value },
])

const textTooLong = computed(() => codepoints.value > MAX_TEXT_CODEPOINTS)

const confirmVisible = ref(false)

const buttonLabel = computed(() => {
  if (isSubmitting.value) return '合成中'
  if (unknownOutcome.value) return '再次提交'
  return '生成语音'
})

const canGenerate = computed(
  () => canSubmit.value && props.serviceAvailable && props.modelAvailable,
)

function handleModeChange(value: string | number): void {
  if (value === 'builtin' || value === 'clone' || value === 'design') {
    mode.value = value
  }
}

function handleGenerate(): void {
  if (unknownOutcome.value) {
    confirmVisible.value = true
    return
  }
  void submit()
}

function handleConfirm(): void {
  confirmVisible.value = false
  void submit(true)
}
</script>

<template>
  <section class="speech-panel">
    <t-tabs :value="mode" :list="modeTabs" @change="handleModeChange" />

    <CloneFields
      v-if="mode === 'clone'"
      :reference="reference"
      v-model:ref-text="refText"
      :disabled="isSubmitting"
    />

    <DesignFields
      v-if="mode === 'design'"
      v-model:description="description"
      v-model:mode="designMode"
      :disabled="isSubmitting"
    />

    <div class="field">
      <span class="field-label">文本</span>
      <t-textarea
        v-model="text"
        placeholder="输入要朗读的内容，数字请写成文字"
        :autosize="{ minRows: 5, maxRows: 12 }"
        :disabled="isSubmitting"
      />
      <span class="field-hint" :class="{ 'field-error': textTooLong }">
        {{ codepoints }}/{{ MAX_TEXT_CODEPOINTS }}
        <template v-if="textTooLong">，已超出上限</template>
      </span>
      <span class="field-hint">{{ PARALINGUISTIC_HINT }}</span>
      <ParalinguisticTags />
    </div>

    <div class="params">
      <div class="param">
        <span class="field-label">语言</span>
        <t-select v-model="language" :options="LANGUAGE_OPTIONS" :disabled="isSubmitting" />
      </div>
      <div v-if="mode === 'builtin'" class="param">
        <span class="field-label">音色</span>
        <t-select
          v-model="voice"
          :options="VOICE_OPTIONS"
          filterable
          creatable
          :disabled="isSubmitting"
        />
      </div>
    </div>

    <t-collapse :borderless="true">
      <t-collapse-panel header="高级参数（CFG / Sigma）" value="advanced">
        <div class="params">
          <div class="param">
            <span class="field-label">CFG scale</span>
            <t-input-number
              v-model="cfg"
              theme="normal"
              :min="1"
              :max="5"
              :step="0.1"
              :decimal-places="2"
              :disabled="isSubmitting"
            />
          </div>
          <div class="param">
            <span class="field-label">Sigma（采样噪声）</span>
            <t-input-number
              v-model="sigma"
              theme="normal"
              :min="0"
              :max="1"
              :step="0.05"
              :decimal-places="2"
              :disabled="isSubmitting"
            />
          </div>
          <span class="field-hint">默认 2.0 / 0.25，与官方一致；调高 CFG 更贴近描述，调高 Sigma 更多变化</span>
        </div>
      </t-collapse-panel>
    </t-collapse>

    <div v-if="mode === 'clone'" class="field">
      <t-checkbox v-model="authorized" :disabled="isSubmitting">
        我确认拥有该声音的使用权，且不用于冒充他人
      </t-checkbox>
    </div>

    <t-alert v-if="errorMessage" theme="error" :message="errorMessage" />

    <div class="actions">
      <t-button
        theme="primary"
        :disabled="!canGenerate"
        :loading="isSubmitting"
        @click="handleGenerate"
      >
        {{ buttonLabel }}
      </t-button>
    </div>

    <AudioResult
      :url="audioUrl"
      :download-name="downloadName"
      :duration-seconds="audioDurationSeconds"
      :elapsed-ms="elapsedMs"
      :is-submitting="isSubmitting"
    />

    <t-dialog
      v-model:visible="confirmVisible"
      header="上次结果未知，确认再次提交？"
      :confirm-btn="{ content: '再次提交' }"
      @confirm="handleConfirm"
    >
      上一次合并没有拿到结果，服务端任务可能仍在继续。新的请求会排在仍在进行的任务之后。
    </t-dialog>
  </section>
</template>

<style scoped>
.speech-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 24px;
  background-color: var(--td-bg-color-container);
  border: 1px solid var(--td-border-level-1-color);
  border-radius: var(--td-radius-large);
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

.field-error {
  color: var(--td-error-color);
}

.params {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.param {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 180px;
}

.actions {
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 640px) {
  .speech-panel {
    padding: 16px;
  }

  .param {
    flex: 1;
  }
}
</style>
