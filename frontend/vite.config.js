import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy API requests to the backend server during development
    proxy: {
      // string shorthand: '/api' -> 'http://localhost:8000/api'
      '/api': {
           target: 'http://localhost:8000',
           changeOrigin: true, // Recommended for virtual hosted sites
           secure: false,      // Optional: Set to false if backend is not HTTPS
           // rewrite: (path) => path.replace(/^\/api/, '') // Uncomment if backend doesn't expect /api prefix
         }
    }
  }
}) 