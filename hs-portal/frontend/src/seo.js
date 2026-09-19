import { useEffect } from "react";

const SITE = "우리동네 직업계고 · ㅇㅈ";
const BASE = "https://udjschool.ggm.kr";

function setMeta(selector, attr, value) {
  if (!value) return;
  let el = document.head.querySelector(selector);
  if (!el) {
    el = document.createElement("meta");
    const [key, val] = selector.replace(/meta\[|\]/g, "").split("=");
    el.setAttribute(key, val.replace(/["']/g, ""));
    document.head.appendChild(el);
  }
  el.setAttribute(attr, value);
}

function setCanonical(path) {
  let el = document.head.querySelector('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  el.setAttribute("href", BASE + (path || "/"));
}

/**
 * 페이지별 제목·설명·canonical을 갱신한다. (React Router 이동 시 SEO 대응)
 * SPA라 구글 등 JS 렌더링 크롤러에 도움을 준다. 네이버용 기본값은 index.html에 있다.
 */
export function useSeo({ title, description, path }) {
  useEffect(() => {
    const fullTitle = title ? `${title} | ${SITE}` : SITE;
    document.title = fullTitle;
    setMeta('meta[name="description"]', "content", description);
    setMeta('meta[property="og:title"]', "content", fullTitle);
    setMeta('meta[property="og:description"]', "content", description);
    if (path !== undefined) {
      setMeta('meta[property="og:url"]', "content", BASE + path);
      setCanonical(path);
    }
  }, [title, description, path]);
}
