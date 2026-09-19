import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 기록해(일지·자소서·연구) 전용 앱. UDJ(본 사이트)와는 서버·DB가 완전히 분리된
// 별도 서비스라 자체 백엔드(diary-backend, :8100)를 쓴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,   // 본 사이트(5173)와 겹치지 않게
    proxy: {
      '/api': { target: 'http://localhost:8100', changeOrigin: true },
    },
  },
})
