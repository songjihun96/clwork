# 검색엔진 등록 가이드 (네이버 · 구글)

이 프로젝트에 추가된 SEO 구성과, 네이버 서치어드바이저 / 구글 서치콘솔 등록 방법입니다.

## 추가된 것
- `frontend/public/robots.txt` — 크롤링 허용/차단 규칙 + 사이트맵 위치
- `GET /sitemap.xml` — 백엔드가 노출(is_visible) 학교 상세 페이지를 모두 포함해 **자동 생성** (nginx가 프록시)
- `frontend/index.html` — 기본 메타(description/keywords/canonical), Open Graph, 트위터 카드, **소유확인 메타 자리**
- `frontend/src/seo.js` — 페이지 이동 시 제목·설명을 갱신(구글 등 JS 크롤러 대응). Home/Search/Quiz/학교상세에 적용됨

## 0. 배포 전 도메인 확인
아래 파일에 도메인이 `https://udjschool.ggm.kr` 로 박혀 있습니다. **실제 서비스 도메인이 다르면 전부 바꾸세요.**
- `frontend/public/robots.txt` (Sitemap 줄)
- `frontend/index.html` (canonical, og:url, og:image)
- `frontend/src/seo.js` (BASE 상수)

그리고 **라이브 nginx 설정**(`/etc/nginx/sites-available/udt`)에도 sitemap 프록시를 추가해야 합니다.
`deploy/nginx-udt.conf` 를 참고해 아래 블록을 `location /api/` 옆에 넣고 `sudo nginx -t && sudo systemctl reload nginx`:

```nginx
location = /sitemap.xml {
    proxy_pass http://127.0.0.1:8000/api/sitemap.xml;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 1. 배포 후 동작 확인
브라우저나 curl로 아래 세 개가 정상 응답하는지 확인:
```bash
curl -s https://udjschool.ggm.kr/robots.txt
curl -s https://udjschool.ggm.kr/sitemap.xml | head
```
- robots.txt: 텍스트 규칙이 나와야 함
- sitemap.xml: `<urlset>` 안에 학교 URL들이 들어 있어야 함

## 2. 네이버 서치어드바이저 등록
1. https://searchadvisor.naver.com → 로그인 → **웹마스터 도구**
2. 사이트 추가: `https://udjschool.ggm.kr` 입력
3. 소유확인 방법 중 **HTML 태그** 선택 → 나오는 `<meta name="naver-site-verification" content="..." />` 복사
4. `frontend/index.html` 의 주석 처리된 네이버 줄을 실제 코드로 교체:
   ```html
   <meta name="naver-site-verification" content="발급받은코드" />
   ```
5. 다시 빌드·배포 후, 서치어드바이저에서 **소유확인**
6. 확인되면 **요청 → 사이트맵 제출** 에 `https://udjschool.ggm.kr/sitemap.xml` 등록
7. (선택) **요청 → 웹페이지 수집**에 주요 URL 몇 개 수동 제출하면 색인이 빨라짐

## 3. 구글 서치콘솔 등록
1. https://search.google.com/search-console → 속성 추가
2. **URL 접두어** 방식으로 `https://udjschool.ggm.kr` 입력
3. 소유확인: **HTML 태그** 선택 → `<meta name="google-site-verification" content="..." />` 복사
4. `frontend/index.html` 의 주석 처리된 구글 줄을 실제 코드로 교체
5. 빌드·배포 후 **확인** 클릭
6. 왼쪽 메뉴 **Sitemaps** → `sitemap.xml` 입력 후 제출

## 4. (선택) 공유 미리보기 이미지
index.html 이 `og:image` 로 `/og-image.png` 를 가리킵니다. 카카오톡·구글에서 링크 공유 시 썸네일로 쓰이니,
1200×630 PNG를 만들어 `frontend/public/og-image.png` 로 넣으면 됩니다. (없어도 사이트는 정상 동작)

## 참고: 색인은 즉시가 아니다
소유확인·사이트맵 제출 후에도 실제 검색 노출까지는 보통 며칠~2주 걸립니다. 서치콘솔의 **URL 검사** 로 개별 페이지 색인을 요청하면 조금 더 빠릅니다.
