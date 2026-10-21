<script setup lang="ts">
import { computed } from 'vue'

const MAX_DESCRIPTION_CODEPOINTS = 500

const EXAMPLES = [
  '温柔成熟的女声，像深夜电台主播，语速舒缓',
  '活泼清亮的少年音，语速偏快，情绪兴奋',
  '低沉磁性的男声，纪录片旁白风格，字正腔圆',
]

const props = defineProps<{
  description: string
  disabled: boolean
}>()

const emit = defineEmits<{
  'update:description': [value: string]
}>()

const descriptionModel = computed<string>({
  get: () => props.description,
  set: (value) => emit('update:description', value),
})

const count = computed<number>(() => Array.from(props.description).length)
const tooLong = computed<boolean>(() => count.value > MAX_DESCRIPTION_CODEPOINTS)

function applyExample(example: string): void {
  emit('update:description', example)
}
</script>

<template>
  <div class="design-fields">
    <div class="field">
      <span class="field-label">声音描述（必填）</span>
      <t-textarea
        v-model="descriptionModel"
        placeholder="例如：温柔成熟的女声，像深夜电台主播，语速舒缓"
        :autosize="{ minRows: 3, maxRows: 6 }"
        :disabled="disabled"
      />
      <span class="field-hint" :class="{ 'field-error': tooLong }">
        {{ count }}/{{ MAX_DESCRIPTION_CODEPOINTS }}，描述音色、年龄感、语速和情绪
      </span>
    </div>

    <div class="examples">
      <span class="field-hint">示例</span>
      <t-button
        v-for="example in EXAMPLES"
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
