import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 연구·논문 서비스 전용 앱.
// 기록해(5174/:8100)와도, UDJ(5173/:8000)와도 서버·DB가 완전히 분리돼 있다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,   // 5173(UDJ) · 5174(기록해) · 5175(상담콘솔) 과 겹치지 않게
    proxy: {
      '/api': { target: 'http://localhost:8200', changeOrigin: true },
    },
  },
})
