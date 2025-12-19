import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Forward the upload request to your new Docker backend (Port 8000)
      '/upload_cad': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      // Keep everything else working as normal
    }
  }
})
