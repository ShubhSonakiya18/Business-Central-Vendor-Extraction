import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/extract': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/results': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/download': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/template-sheets': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/process-vendor': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
