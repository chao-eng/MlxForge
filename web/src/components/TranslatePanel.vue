<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { TARGET_LANGUAGES, useTranslation } from '../composables/useTranslation'
import { copyToClipboard } from '../composables/useClipboard'

defineProps<{
  serviceAvailable: boolean
}>()

const {
  sourceText,
  targetLanguage,
  translatedText,
  isTranslating,
  errorMessage,
  elapsedMs,
  canTranslate,
  runTranslation,
} = useTranslation()

const languageOptions = TARGET_LANGUAGES.map((language) => ({
  label: language,
  value: language,
}))

type CopyState = 'idle' | 'copied' | 'failed'

const copyState = ref<CopyState>('idle')
const translatedField = ref<{ focus: () => void } | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | null = null

function clearCopyTimer(): void {
  if (copyTimer !== null) {
    clearTimeout(copyTimer)
    copyTimer = null
  }
}

async function handleTranslate(): Promise<void> {
  clearCopyTimer()
  copyState.value = 'idle'
  await runTranslation()
}

async function handleCopy(): Promise<void> {
  if (translatedText.value.length === 0) return

  clearCopyTimer()
  try {
    await copyToClipboard(translatedText.value)
    copyState.value = 'copied'
    copyTimer = setTimeout(() => {
      copyState.value = 'idle'
      copyTimer = null
    }, 2000)
  } catch {
    // 剪贴板不可用时聚焦译文，提示用户手动选中复制
    copyState.value = 'failed'
    translatedField.value?.focus()
  }
}

onBeforeUnmount(clearCopyTimer)
</script>

<template>
  <section class="translate-panel">
    <div class="panel-field">
      <label class="field-label" for="source-text">原文</label>
      <t-textarea
        id="source-text"
        v-model="sourceText"
        placeholder="输入要翻译的内容"
        :autosize="{ minRows: 6, maxRows: 12 }"
      />
    </div>

    <div class="panel-actions">
      <label class="field-label" for="target-language">目标语言</label>
      <t-select
        id="target-language"
        v-model="targetLanguage"
        class="target-select"
        :options="languageOptions"
      />
      <t-button
        theme="primary"
        :disabled="!canTranslate || !serviceAvailable"
        :loading="isTranslating"
        @click="handleTranslate"
      >
        {{ isTranslating ? '翻译中' : '翻译' }}
      </t-button>
    </div>

    <t-alert v-if="errorMessage" theme="error" :message="errorMessage" />

    <div class="panel-field">
      <div class="field-header">
        <label class="field-label" for="translated-text">译文</label>
        <div class="copy-area">
          <span v-if="elapsedMs !== null" class="field-meta">
            耗时 {{ (elapsedMs / 1000).toFixed(1) }} 秒
          </span>
          <span v-if="copyState === 'failed'" class="copy-hint">复制失败，请手动全选译文后复制</span>
          <t-button
            variant="outline"
            size="small"
            :disabled="translatedText.length === 0"
            @click="handleCopy"
          >
            {{ copyState === 'copied' ? '已复制' : '复制' }}
          </t-button>
        </div>
      </div>
      <t-textarea
        id="translated-text"
        ref="translatedField"
        v-model="translatedText"
        :placeholder="isTranslating ? '翻译中…' : '译文会显示在这里'"
        readonly
        :autosize="{ minRows: 6, maxRows: 12 }"
      />
    </div>
  </section>
</template>

<style scoped>
.translate-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 24px;
  background-color: var(--td-bg-color-container);
  border: 1px solid var(--td-border-level-1-color);
  border-radius: var(--td-radius-large);
}

.panel-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.target-select {
  width: 180px;
}

.field-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.copy-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.copy-hint {
  font-size: 13px;
  color: var(--td-error-color);
}

.field-meta {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

@media (max-width: 640px) {
  .translate-panel {
    padding: 16px;
  }

  .panel-actions {
    flex-wrap: wrap;
  }

  .target-select {
    flex: 1;
    width: auto;
  }
}
</style>
