<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getHealth } from './api/client'
import type { HealthState } from './api/types'
import ServiceStatus from './components/ServiceStatus.vue'
import TranslatePanel from './components/TranslatePanel.vue'

const POLL_INTERVAL_MS = 5000

const healthState = ref<HealthState | null>(null)
const reachable = ref(true)
let timer: ReturnType<typeof setInterval> | null = null

async function refresh(): Promise<void> {
  try {
    const health = await getHealth()
    healthState.value = health.state
    reachable.value = true
  } catch {
    // 服务未启动时只更新徽标和按钮状态，不打断页面其他操作
    healthState.value = null
    reachable.value = false
  }
}

onMounted(() => {
  void refresh()
  timer = setInterval(() => {
    void refresh()
  }, POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div>
        <h1 class="app-title">Hy-MT2 本地翻译</h1>
        <p class="app-subtitle">运行在 Apple Silicon 上的本地翻译服务</p>
      </div>
      <ServiceStatus :state="healthState" :reachable="reachable" />
    </header>

    <main class="app-main">
      <TranslatePanel :service-available="reachable" />
    </main>

    <footer class="app-footer">原文和译文只留在当前页面，刷新即清空</footer>
  </div>
</template>
