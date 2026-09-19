import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 상담 사이트. 본 사이트와 같은 백엔드(8000)를 쓴다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,   // 본 사이트(5173)·기록해(5174)와 겹치지 않게
    proxy: {
      // ws: true 가 없으면 전화 알림용 WebSocket(/api/cs/ws/calls)이
      // 개발 서버에서 연결되지 않는다. HTTP 만 프록시되기 때문이다.
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true },
    },
  },
})
