import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发环境把接口请求转发到本机后端，业务代码只使用相对路径
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
