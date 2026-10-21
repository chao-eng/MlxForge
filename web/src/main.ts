import { createApp } from 'vue'
import { Alert, Button, Option, Select, Tag, Textarea } from 'tdesign-vue-next'
import 'tdesign-vue-next/es/style/index.css'
import App from './App.vue'
import './styles/app.css'

const app = createApp(App)

// 只注册页面用到的组件，不整库挂载
app.use(Button)
app.use(Select)
app.use(Option)
app.use(Textarea)
app.use(Tag)
app.use(Alert)

app.mount('#app')
