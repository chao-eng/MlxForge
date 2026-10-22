<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getHealth } from './api/client'
import { getModelAvailability } from './api/models'
import type { ModelAvailability } from './api/models'
import type { HealthState } from './api/types'
import ServiceStatus from './components/ServiceStatus.vue'
import SpeechPanel from './components/SpeechPanel.vue'
import TranslatePanel from './components/TranslatePanel.vue'

const POLL_INTERVAL_MS = 5000
// 连续两次健康检查失败才判定连接中断，避免一次抖动就改状态（§5.4）
const UNREACHABLE_THRESHOLD = 2

const HY_LABELS: Record<HealthState, string> = {
  unloaded: '已就绪',
  loading: '正在准备模型',
  ready: '已就绪',
  generating: '正在翻译',
  unloading: '正在释放内存',
  failed: '模型加载失败',
}

const MING_LABELS: Record<HealthState, string> = {
  unloaded: '已就绪（首次生成需准备模型）',
  loading: '正在准备模型',
  ready: '已就绪',
  generating: '正在合成',
  unloading: '正在释放内存',
  failed: '模型加载失败',
}

type PageKey = 'speech' | 'translate'

// 服务端启动单模型时会把 / 重定向到 ?page=tts 或 ?page=translate，
// 带参数进入即锁定页面，避免首屏先渲染默认页再跳转
const PAGE_PARAMS: Record<string, PageKey> = { tts: 'speech', translate: 'translate' }
const pageParam = new URLSearchParams(window.location.search).get('page')
const forcedPage = ref<PageKey | null>(pageParam ? PAGE_PARAMS[pageParam] ?? null : null)

const page = ref<PageKey>(forcedPage.value ?? 'speech')
const pageChosen = ref(forcedPage.value !== null)
const availability = ref<ModelAvailability>({ hyMt2: false, ming: false })
const healthState = ref<HealthState | null>(null)
const reachable = ref(true)
const failures = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const title = computed(() =>
  page.value === 'speech' ? 'Ming-3.0-tts 语音合成' : 'Hy-MT2 本地翻译',
)

const labels = computed(() => (page.value === 'speech' ? MING_LABELS : HY_LABELS))

const currentModelAvailable = computed(() =>
  page.value === 'speech' ? availability.value.ming : availability.value.hyMt2,
)

const unavailableHint = computed(() => {
  if (!reachable.value) return '服务未启动，请先启动 Ming-3.0-tts 服务'
  if (!currentModelAvailable.value) {
    return page.value === 'speech'
      ? '当前服务运行的是 Hy-MT2，语音合成不可用'
      : '当前服务运行的是 Ming-3.0-tts，文本翻译不可用'
  }
  return ''
})

async function refresh(): Promise<void> {
  try {
    const [models, health] = await Promise.all([getModelAvailability(), getHealth()])
    availability.value = models
    healthState.value = health.state
    failures.value = 0
    reachable.value = true
    if (!pageChosen.value) {
      // 单模型服务只开放对应页面，用户切换后不再自动改写
      page.value = models.ming || !models.hyMt2 ? 'speech' : 'translate'
      pageChosen.value = true
    }
  } catch {
    failures.value += 1
    if (failures.value >= UNREACHABLE_THRESHOLD) {
      healthState.value = null
      reachable.value = false
    }
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
        <h1 class="app-title">{{ title }}</h1>
        <p class="app-subtitle">运行在 Apple Silicon 上的本地模型服务</p>
      </div>
      <ServiceStatus :state="healthState" :reachable="reachable" :labels="labels" />
    </header>

    <t-radio-group v-if="forcedPage === null" v-model="page" variant="default-filled">
      <t-radio-button value="speech">语音合成</t-radio-button>
      <t-radio-button value="translate">文本翻译</t-radio-button>
    </t-radio-group>

    <t-alert v-if="unavailableHint" theme="info" :message="unavailableHint" />

    <main class="app-main">
      <SpeechPanel
        v-if="page === 'speech'"
        :service-available="reachable"
        :model-available="availability.ming"
      />
      <TranslatePanel v-else :service-available="reachable && availability.hyMt2" />
    </main>

    <footer class="app-footer">文本、参考音频和生成音频只留在当前页面，刷新即清空</footer>
  </div>
</template>
