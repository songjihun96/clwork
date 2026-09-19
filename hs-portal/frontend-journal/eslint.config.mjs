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
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "off",
      "no-useless-assignment": "off",
    },
  },
];
