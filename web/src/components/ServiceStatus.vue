<script setup lang="ts">
import { computed } from 'vue'
import type { HealthState } from '../api/types'

const props = defineProps<{
  state: HealthState | null
  reachable: boolean
  labels: Record<HealthState, string>
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
</script>

<template>
  <t-tag :theme="theme" variant="light-outline">{{ label }}</t-tag>
</template>
