import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendHost = process.env.BACKEND_HOST ?? '127.0.0.1'
const backendPort = process.env.BACKEND_PORT ?? '8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': `http://${backendHost}:${backendPort}`
    }
  },
  preview: {
    host: '0.0.0.0',
    port: 4173
  }
})
