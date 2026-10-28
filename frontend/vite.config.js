import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the dashboard runs on :5173 and forwards API, stream and WebSocket calls to FastAPI on :8000.
const backend = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1500 },
  server: {
    proxy: {
      '/api': backend,
      '/stream': backend,
      '/ws': { target: backend, ws: true },
    },
  },
})
