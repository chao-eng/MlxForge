<script setup lang="ts">
import { TAGS } from '../api/paralinguistic'
</script>

<template>
  <t-collapse :borderless="true" class="tags-panel">
    <t-collapse-panel value="tags" header="副语言标签（14 个）说明">
      <ul class="tags-list">
        <li v-for="row in TAGS" :key="row.tag" class="tags-item">
          <code class="tags-code">{{ row.tag }}</code>
          <span class="tags-desc">{{ row.desc }}</span>
        </li>
      </ul>
      <p class="tags-note">
        标签要原样写进台词，保持英文半角方括号和大小写，不要翻译；写在希望发声的位置即可，例如
        「今天真是太开心了[Laughter]，好久没这么放松过。」
      </p>
    </t-collapse-panel>
  </t-collapse>
</template>

<style scoped>
.tags-panel {
  margin-top: -4px;
}

.tags-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.tags-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  color: var(--td-text-color-secondary);
}

.tags-code {
  flex: none;
  font-family: var(--td-font-family-mono, monospace);
  color: var(--td-text-color-primary);
}

.tags-note {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-placeholder);
}

@media (max-width: 640px) {
  .tags-list {
    grid-template-columns: 1fr;
  }
}
</style>
