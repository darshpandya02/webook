import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Built assets are served by Django's static files (Vercel CDN in production) under /static/.
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
}))
