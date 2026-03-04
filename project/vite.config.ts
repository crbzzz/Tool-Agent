import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  base: './',
  plugins: [react()],
  optimizeDeps: {
    exclude: ['lucide-react'],
  },
  server: {
    proxy: {
      '/chat': 'http://127.0.0.1:8002',
      '/health': 'http://127.0.0.1:8002',
      '/tools': 'http://127.0.0.1:8002',
      '/oauth': 'http://127.0.0.1:8002',
      '/auth': 'http://127.0.0.1:8002',
    },
  },
});
