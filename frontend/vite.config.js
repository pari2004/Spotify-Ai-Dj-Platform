import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies REST + WebSocket to the FastAPI backend on :8008 so the client can
// use same-origin relative URLs (/api/..., /ws/...) in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8008', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8008', ws: true },
      '/health': { target: 'http://127.0.0.1:8008', changeOrigin: true },
    },
  },
})
