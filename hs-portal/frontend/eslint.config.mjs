import js from "@eslint/js";
import react from "eslint-plugin-react";
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
        XMLHttpRequest: "readonly",
      },
    },
    plugins: { react },
    rules: {
      "no-undef": "error",
      // 화면에 쓴 컴포넌트가 정의·import 돼 있는지 본다.
      // no-undef 는 <Foo /> 를 못 잡는다 — 실제로 이것 때문에 지워진
      // 컴포넌트를 그대로 쓰는 코드가 검사를 통과해 배포된 적이 있다.
      "react/jsx-no-undef": "error",
      "no-unused-vars": "off",
      "no-useless-assignment": "off",
    },
  },
];
