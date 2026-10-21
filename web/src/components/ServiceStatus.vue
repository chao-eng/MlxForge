<script setup lang="ts">
import { computed } from 'vue'
import type { HealthState } from '../api/types'

const props = defineProps<{
  state: HealthState | null
  reachable: boolean
}>()

// 文案映射与 PRD 9.5 保持一致，组件内不另造状态名
const STATE_LABELS: Record<HealthState, string> = {
  unloaded: '已就绪',
  loading: '正在准备模型',
  ready: '已就绪',
  generating: '正在翻译',
  unloading: '正在释放内存',
  failed: '模型加载失败',
}

type TagTheme = 'default' | 'primary' | 'warning' | 'danger' | 'success'

const label = computed<string>(() => {
  if (!props.reachable) return '服务未启动'
  if (props.state === null) return '正在检查'
  return STATE_LABELS[props.state]
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
</script>

<template>
  <t-tag :theme="theme" variant="light-outline">{{ label }}</t-tag>
</template>
