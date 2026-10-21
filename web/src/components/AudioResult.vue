<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  url: string
  downloadName: string
  durationSeconds: number | null
  elapsedMs: number | null
  isSubmitting: boolean
}>()

const meta = computed<string>(() => {
  const parts: string[] = []
  if (props.durationSeconds !== null) {
    parts.push(`音频 ${props.durationSeconds.toFixed(1)} 秒`)
  }
  if (props.elapsedMs !== null) {
    parts.push(`生成耗时 ${(props.elapsedMs / 1000).toFixed(1)} 秒`)
  }
  return parts.join(' · ')
})
</script>

<template>
  <section class="audio-result">
    <p v-if="isSubmitting" class="result-hint">正在合成，请稍候…</p>
    <template v-else-if="url">
      <audio class="audio-player" :src="url" controls />
      <div class="result-bar">
        <span class="result-meta">{{ meta }}</span>
        <t-link theme="primary" :href="url" :download="downloadName">下载 WAV</t-link>
      </div>
    </template>
    <p v-else class="result-hint">生成的音频会显示在这里</p>
  </section>
</template>

<style scoped>
.audio-result {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--td-border-level-1-color);
}

.audio-player {
  width: 100%;
}

.result-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.result-meta {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.result-hint {
  margin: 0;
  font-size: 13px;
  color: var(--td-text-color-placeholder);
}
</style>
