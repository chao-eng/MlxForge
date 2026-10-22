<script setup lang="ts">
import { computed } from 'vue'
import type { HealthState, MemoryInfo } from '../api/types'

const props = defineProps<{
  state: HealthState | null
  reachable: boolean
  labels: Record<HealthState, string>
  memory: MemoryInfo | null
}>()

type TagTheme = 'default' | 'primary' | 'warning' | 'danger' | 'success'

const label = computed<string>(() => {
  if (!props.reachable) return '服务未启动'
  if (props.state === null) return '正在检查'
  return props.labels[props.state]
})

const theme = computed<TagTheme>(() => {
  if (!props.reachable) return 'danger'
  if (props.state === 'failed') return 'danger'
  if (
    props.state === 'loading' ||
    props.state === 'generating' ||
    props.state === 'unloading'
  ) {
    return 'warning'
  }
  if (props.state === 'ready' || props.state === 'unloaded') return 'success'
  return 'default'
})

const gb = (mb: number): string => (mb / 1024).toFixed(1)

// 进程 RSS 通常不到 1GB，统一按 GB 保留一位会显示成 0.0，小数值改用 MB
const size = (mb: number): string => (mb >= 1024 ? `${gb(mb)} GB` : `${Math.round(mb)} MB`)

// 展示给普通用户的文案，避免 RSS、MLX 这些术语，只说「程序占多少、模型占多少」
const memoryText = computed<string>(() => {
  if (!props.reachable || !props.memory) return ''
  return `内存占用 ${size(props.memory.footprint_mb)} · 模型 ${size(props.memory.mlx_active_mb)}`
})

const memoryDetail = computed<string>(() => {
  if (!props.memory) return ''
  return [
    `程序总共占用 ${size(props.memory.footprint_mb)}`,
    `模型最高用到过 ${size(props.memory.mlx_peak_mb)}`,
    `预留缓存 ${size(props.memory.mlx_cache_mb)}，可被下次复用`,
  ].join(' · ')
})
</script>

<template>
  <div class="status">
    <t-tag :theme="theme" variant="light-outline">{{ label }}</t-tag>
    <t-tooltip v-if="memoryText" :content="memoryDetail" placement="bottom-right">
      <span class="status-memory">{{ memoryText }}</span>
    </t-tooltip>
  </div>
</template>

<style scoped>
.status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.status-memory {
  font-size: 12px;
  color: var(--td-text-color-secondary);
  cursor: default;
}
</style>
