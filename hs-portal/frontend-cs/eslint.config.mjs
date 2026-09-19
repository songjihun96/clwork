import js from "@eslint/js";
export default [
  js.configs.recommended,
  {
    files: ["**/*.jsx", "**/*.js"],
    languageOptions: {
      ecmaVersion: 2022, sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: {
        window: "readonly", document: "readonly", localStorage: "readonly",
        fetch: "readonly", FormData: "readonly", console: "readonly",
        setTimeout: "readonly", clearTimeout: "readonly", alert: "readonly",
        confirm: "readonly", prompt: "readonly", navigator: "readonly",
        URL: "readonly", Blob: "readonly", FileReader: "readonly",
        setInterval: "readonly", clearInterval: "readonly",
        getComputedStyle: "readonly", Image: "readonly", location: "readonly",
        IntersectionObserver: "readonly", ResizeObserver: "readonly",
        AbortController: "readonly", Intl: "readonly", requestAnimationFrame: "readonly",
        URLSearchParams: "readonly", CustomEvent: "readonly", Event: "readonly",
        history: "readonly", matchMedia: "readonly", performance: "readonly",
        // 전화 상담 화면이 쓴다: 실시간 통로와 마이크 입력 미터.
        WebSocket: "readonly", cancelAnimationFrame: "readonly",
        MediaStream: "readonly", Uint8Array: "readonly",
        // 통화 음성을 직접 다루는 화면이 쓴다(base64·μ-law 변환).
        btoa: "readonly", atob: "readonly", Int16Array: "readonly",
        Audio: "readonly", Float32Array: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "off",
      "no-useless-assignment": "off",
    },
  },
];
