<script setup lang="ts">
import { computed } from 'vue'
import type { DesignMode } from '../composables/useSpeech'

const MAX_DESCRIPTION_CODEPOINTS = 500

// 两种模式的训练输入不同，示例也分开给，避免把「怎么说」写成「谁在说」
const EXAMPLES: Record<DesignMode, string[]> = {
  voice_design: [
    '一位年轻的女性，声音温柔成熟，像深夜电台主播，语速舒缓',
    '活泼清亮的少年音，语速偏快，情绪兴奋',
    '低沉磁性的中年男性，纪录片旁白风格，字正腔圆',
  ],
  freeform: [
    '用讲故事的口吻，语速偏慢，句尾轻轻收住',
    '像在安慰朋友，语气温和，不要太用力',
    '播报新闻，吐字清晰，节奏平稳',
  ],
}

const PLACEHOLDERS: Record<DesignMode, string> = {
  voice_design: '例如：一位年轻的女性，声音温柔成熟，像深夜电台主播，语速舒缓',
  freeform: '例如：用讲故事的口吻，语速偏慢，句尾轻轻收住',
}

const props = defineProps<{
  description: string
  mode: DesignMode
  disabled: boolean
}>()

const emit = defineEmits<{
  'update:description': [value: string]
  'update:mode': [value: DesignMode]
}>()

const descriptionModel = computed<string>({
  get: () => props.description,
  set: (value) => emit('update:description', value),
})

const count = computed<number>(() => Array.from(props.description).length)
const tooLong = computed<boolean>(() => count.value > MAX_DESCRIPTION_CODEPOINTS)
const examples = computed<string[]>(() => EXAMPLES[props.mode])

function handleModeChange(value: string | number): void {
  if (value === 'voice_design' || value === 'freeform') {
    emit('update:mode', value)
  }
}

function applyExample(example: string): void {
  emit('update:description', example)
}
</script>

<template>
  <div class="design-fields">
    <div class="field">
      <span class="field-label">模式</span>
      <t-radio-group :value="mode" :disabled="disabled" @change="handleModeChange">
        <t-radio-button value="voice_design">声音设计</t-radio-button>
        <t-radio-button value="freeform">自由指令</t-radio-button>
      </t-radio-group>
      <span class="field-hint">
        <template v-if="mode === 'voice_design'">描述谁在说话：性别、年龄感、音色、语速</template>
        <template v-else>描述怎么说：语气、节奏、重音，不改变音色</template>
      </span>
    </div>

    <div class="field">
      <span class="field-label">
        {{ mode === 'voice_design' ? '声音描述（必填）' : '演绎指令（必填）' }}
      </span>
      <t-textarea
        v-model="descriptionModel"
        :placeholder="PLACEHOLDERS[mode]"
        :autosize="{ minRows: 3, maxRows: 6 }"
        :disabled="disabled"
      />
      <span class="field-hint" :class="{ 'field-error': tooLong }">
        {{ count }}/{{ MAX_DESCRIPTION_CODEPOINTS }}
      </span>
    </div>

    <div class="examples">
      <span class="field-hint">示例</span>
      <t-button
        v-for="example in examples"
        :key="example"
        size="small"
        variant="outline"
        :disabled="disabled"
        @click="applyExample(example)"
      >
        {{ example }}
      </t-button>
    </div>
  </div>
</template>

<style scoped>
.design-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
</style>
