// 영상 시연용 프론트엔드 — 실제 frontend/ 코드를 그대로 띄우되, API 를 테스트 백엔드(8800)로 보낸다.
//   (frontend 폴더에서) npx vite --config ../video/school-demo/vite.demo.config.mjs
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "../../frontend");
const require = createRequire(path.join(frontend, "package.json"));
const react = (await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)).default;

export default {
  root: frontend,
  plugins: [react()],
  cacheDir: path.join(here, "data/.vite"),
  server: {
    host: "127.0.0.1",
    port: 5190,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8800", changeOrigin: true } },
  },
};
