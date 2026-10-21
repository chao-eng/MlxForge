# AGENTS.md —— 前端工程约束规范

适用于 `web/` 目录。仓库级约定见 [../AGENTS.md](../AGENTS.md)，两边冲突时以本文件为准。

## 🚫 硬性红线（违反即错）

| 编号 | 红线 | 判定标准 |
| --- | --- | --- |
| RL-01 | 类型必须完整 | 出现 `any`、`as any`、`@ts-ignore`、`@ts-nocheck` 即违规；类型不确定先用 `unknown` 再收窄 |
| RL-02 | UI 库唯一 | `package.json` 出现 TDesign 之外的组件库（Element Plus、Ant Design Vue、Naive UI 等）即违规 |
| RL-03 | 不引入状态库和路由 | 安装或 import `pinia`、`vuex`、`vue-router` 即违规 |
| RL-04 | 流式只能用 fetch | 用 `EventSource` 调 `/v1/chat/completions` 即违规，它不支持 POST |
| RL-05 | 地址不得硬编码 | `src/` 出现 `http://`、`https://`、`127.0.0.1`、`localhost` 即违规，测试文件除外 |
| RL-06 | 不直接操作 DOM | 组件出现 `document.`、`querySelector`、`innerHTML`、`outerHTML` 即违规 |
| RL-07 | 基础控件用 TDesign | 用原生 `button`、`input`、`select`、`dialog` 替代 TDesign 对应组件即违规，纯语义容器除外 |
| RL-08 | 原文译文不落盘 | 用 `localStorage`、`sessionStorage`、`indexedDB`、cookie 存原文或译文即违规 |
| RL-09 | 不引外部资源 | 引用 CDN、外部字体、第三方脚本、远程图片即违规 |
| RL-10 | 验证闸门 | `pnpm typecheck` 或 `pnpm build` 失败仍提交即违规 |
| RL-11 | 日志不碰内容 | `console` 输出原文、译文、完整请求体或响应体即违规 |
| RL-12 | 请求必须封装 | 组件内直接 `fetch`，或绕过 `src/api/client.ts` 即违规 |
| RL-13 | 统一组件写法 | 使用 Options API，或 `.vue` 文件不用 `<script setup lang="ts">` 即违规 |
| RL-14 | 文件不超 300 行 | 单个 `.vue` 或 `.ts` 超过 300 行即违规，超出按职责拆分 |
| RL-15 | 产物不入库 | 提交 `node_modules/`、`dist/`、`.env*`、`.DS_Store` 即违规 |

## ⚙️ 编码原则

1. **方案先行**：动前端先读 `docs/hy-mt2-prd.md` 的 UC-08、第 5 章和 BR-35～BR-40，接口字段和状态文案以 PRD 为准。
2. **简洁至上**：单页能解决就不加路由、不加全局状态；新抽象至少有两个使用方，否则就近写在组件里。
3. **精准修改**：只改与需求相关的文件和样式，不顺手重构，不调整无关间距和颜色。
4. **目标驱动**：改动前写清验收点，例如「能翻译」「能复制」「错误提示正确」，完成后逐条自测。
5. **文档先行**：新增接口字段、状态名或用户文案，先改 PRD 再改代码；PRD 未定义的交互不自行发明。
6. **红线优先**：既有代码与本文件冲突时，按本文件执行，不复制旧写法扩散问题。

## 🧩 技术选型与设计约定

1. **运行时与包管理**：Node 20 LTS 及以上；只用 `pnpm`，提交 `pnpm-lock.yaml`；禁止混用 npm、yarn、bun。
2. **框架**：Vue 3 + Composition API，所有组件使用 `<script setup lang="ts">`；入口 `src/main.ts`，根组件 `src/App.vue`。
3. **构建**：Vite；`vite.config.ts` 只把 `/v1` 和 `/health` 代理到 `http://127.0.0.1:8000`，业务代码不出现该地址；生产环境同源部署。
4. **类型**：`tsconfig.json` 开启 `strict`；`typecheck` 脚本固定为 `vue-tsc --noEmit`。
5. **UI**：只用 `tdesign-vue-next` 和 `tdesign-icons-vue-next`，按需引入；颜色、圆角、间距取 TDesign 变量，组件内不手写十六进制色值。PRD 5.3 的视觉规范例外：允许在 `src/styles/app.css` 的 `:root` 中集中覆盖 `--td-*` 变量，组件内仍禁止写色值。
6. **样式**：组件样式写在 `<style scoped>`；全局样式只放 `src/styles/app.css`；不引入 Tailwind、UnoCSS、Sass 预处理框架。
7. **接口类型**：请求和响应类型集中在 `src/api/types.ts`，字段与 PRD UC-04、UC-06 一一对应；错误统一按 `{"error": {"type", "message"}}` 解析。
8. **流式**：用 `fetch` 读取 `ReadableStream`，按行解析 `data:`；必须处理 `[DONE]` 和服务端错误事件；界面只描述为「分块显示」，不得宣称逐 token 输出。
9. **翻译交互**：默认目标语言中文；不提供源语言选择，由模型自动判断；请求期间禁用翻译按钮；复制失败时自动选中译文并提示手动复制。
10. **状态展示**：`/health` 的 `state` 直接映射页面文案，映射关系以 PRD 9.5 为准，组件内不另造状态名。
11. **文案**：界面文案中文硬编码，不引入 i18n 库；错误提示不出现堆栈、绝对路径和内部类型名。
12. **隐私**：不持久化原文和译文，不埋点，不读取本地文件，运行期不发外部请求。
13. **目录**：新增文件按第 4 节放置；不建 `utils/`、`helpers/` 这类边界不清的目录。
14. **验证**：交付前执行 `pnpm typecheck` 和 `pnpm build`，结果写进回复或提交说明。

## 📁 目录结构示例 + 错误示例对照表

✅ 推荐结构

```text
web/
├── AGENTS.md
├── index.html
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── vite.config.ts
├── .gitignore
└── src/
    ├── main.ts
    ├── App.vue
    ├── api/
    │   ├── client.ts
    │   └── types.ts
    ├── components/
    │   ├── TranslatePanel.vue
    │   └── ServiceStatus.vue
    ├── composables/
    │   └── useTranslation.ts
    └── styles/
        └── app.css
```

❌ 错误示例

| 错误示例 | 原因 |
| --- | --- |
| `const data: any = await res.json()` | RL-01，响应类型必须显式声明 |
| `import ElementPlus from 'element-plus'` | RL-02，UI 库只允许 TDesign |
| `import { createPinia } from 'pinia'` | RL-03，单页不引入状态库 |
| `new EventSource('/v1/chat/completions')` | RL-04，EventSource 只能 GET |
| `fetch('http://127.0.0.1:8000/v1/chat/completions')` | RL-05，地址只能来自同源或代理 |
| `document.getElementById('output')!.innerHTML = text` | RL-06，用响应式数据渲染 |
| `<button class="primary">翻译</button>` | RL-07，用 `t-button` |
| `localStorage.setItem('draft', text)` | RL-08，原文不得持久化 |
| `<link href="https://fonts.googleapis.com/...">` | RL-09，字体走系统字体 |
| 跳过 `pnpm typecheck` 直接提交 | RL-10，验证闸门必须通过 |
| `console.log(prompt, translation)` | RL-11，日志不得含原文和译文 |
| 在点击处理函数里直接 `await fetch(...)` | RL-12，请求统一走 `src/api/client.ts` |
| `export default { data() { return { text: '' } } }` | RL-13，统一 `<script setup lang="ts">` |
| 把全部逻辑塞进 500 行的 `App.vue` | RL-14，按职责拆分 |
| `git add web/node_modules` | RL-15，依赖和产物不入库 |
| 在页面加「源语言」下拉框 | 约定 9，PRD BR-17 规定源语言自动判断 |
| 把流式描述成「逐字输出」 | 约定 8，PRD BR-24 规定整段生成后分块下发 |
