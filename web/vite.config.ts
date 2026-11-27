import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development Vite serves the app on 5173 and passes API and guide requests to the api, so the
// browser sees one origin, as it does when the api serves the built app.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://localhost:8000', ws: true }, '/docs': 'http://localhost:8000' },
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 6000 },
  test: { environment: 'jsdom' },
})
