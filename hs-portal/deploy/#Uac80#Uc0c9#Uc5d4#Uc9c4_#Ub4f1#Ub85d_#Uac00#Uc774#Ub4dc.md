# 검색엔진 등록 가이드 (우리동네 직업계고)

새 도메인 **https://udjschool.ggm.kr** 기준으로 구글 서치콘솔·네이버 서치어드바이저에 등록하는 순서입니다.
소유확인 방식은 **HTML 태그**(index.html에 메타태그 1줄 삽입)로 통일했습니다. 코드에 이미 자리가 준비돼 있습니다.

---

## 사전 준비 — 배포 후 3가지 정상 확인
등록 전, 아래 3개가 새 도메인에서 정상 응답해야 합니다. (서버에서 실행)

```bash
curl -sI https://udjschool.ggm.kr/            # HTTP/2 200
curl -s  https://udjschool.ggm.kr/robots.txt  # 규칙 + Sitemap 줄
curl -s  https://udjschool.ggm.kr/sitemap.xml | head   # <?xml ...><urlset>
```

셋 다 정상이면 등록을 시작합니다.

---

## A. 구글 서치콘솔 (Google Search Console)

1. https://search.google.com/search-console 접속 → 구글 계정 로그인
2. **속성 추가** → **URL 접두어** 선택 → `https://udjschool.ggm.kr` 입력 → 계속
3. 소유확인 방법에서 **HTML 태그** 펼치기 → 아래 형태의 코드가 나옵니다:
   `<meta name="google-site-verification" content="여기에_고유코드" />`
   → `content="..."` 안의 **고유코드만** 복사 (또는 태그 전체 복사)
4. `frontend/index.html` 을 열어 **17번째 줄 부근** 주석을 실제 코드로 교체:

   바꾸기 전:
   ```html
   <!-- <meta name="google-site-verification" content="여기에_구글_인증코드" /> -->
   ```
   바꾼 후 (주석 `<!-- -->` 제거 + 코드 삽입):
   ```html
   <meta name="google-site-verification" content="복사한_고유코드" />
   ```
5. 저장 → 재빌드·배포 (아래 "배포 명령" 참고)
6. 서치콘솔로 돌아와 **확인** 클릭 → "소유권이 확인되었습니다" 뜨면 성공
7. 왼쪽 메뉴 **Sitemaps** → 새 사이트맵 추가에 `sitemap.xml` 입력 → 제출
   (전체 주소 `https://udjschool.ggm.kr/sitemap.xml` 로 인식됩니다)
8. (선택) **URL 검사** 창에 주요 페이지 주소를 넣고 "색인 생성 요청" 하면 더 빨리 잡힙니다

---

## B. 네이버 서치어드바이저 (Naver Search Advisor)

1. https://searchadvisor.naver.com 접속 → 네이버 로그인 → **웹마스터 도구**
2. 사이트 입력란에 `https://udjschool.ggm.kr` 입력 → 추가
3. 소유확인 방법에서 **HTML 태그** 선택 → 나오는 코드:
   `<meta name="naver-site-verification" content="여기에_고유코드" />`
   → 고유코드(또는 태그 전체) 복사
4. `frontend/index.html` **15번째 줄 부근** 주석을 실제 코드로 교체:

   바꾸기 전:
   ```html
   <!-- <meta name="naver-site-verification" content="여기에_네이버_인증코드" /> -->
   ```
   바꾼 후:
   ```html
   <meta name="naver-site-verification" content="복사한_고유코드" />
   ```
5. 저장 → 재빌드·배포
6. 서치어드바이저에서 **소유확인** 클릭 → 확인되면 성공
7. 좌측 **요청 → 사이트맵 제출** → `https://udjschool.ggm.kr/sitemap.xml` 입력 후 확인
8. (선택) **요청 → 웹페이지 수집** 에 주요 URL을 수동 제출하면 색인이 빨라짐

> 네이버는 구글보다 색인이 느린 편입니다. robots.txt에 네이버 로봇(Yeti)을 이미 허용해 두었습니다.

---

## 두 메타태그를 넣은 최종 index.html 예시 (해당 부분)

```html
<meta name="naver-site-verification" content="네이버에서_받은_코드" />
<meta name="google-site-verification" content="구글에서_받은_코드" />
```
두 줄 모두 `<head>` 안에 있으면 되고, 순서는 상관없습니다.

---

## 배포 명령 (메타태그 넣은 뒤)

```bash
cd ~
cp ~/hs-portal/backend/.env ~/env.backup
unzip -o hs-portal.zip                      # 로컬에서 index.html 수정 후 다시 올린 경우
cp ~/env.backup ~/hs-portal/backend/.env
cd ~/hs-portal/frontend && npm run build
sudo systemctl restart udt-backend
```

> index.html만 서버에서 직접 수정하는 경우엔 `~/hs-portal/frontend/index.html` 을 편집하고
> `npm run build` 만 다시 하면 됩니다 (백엔드 재시작 불필요).

배포 후 소유확인 태그가 반영됐는지 확인:
```bash
curl -s https://udjschool.ggm.kr/ | grep -i "site-verification"
```
두 메타태그가 보이면 각 사이트에서 "확인"을 누르면 됩니다.

---

## 색인까지 걸리는 시간
소유확인·사이트맵 제출 후에도 실제 검색 노출까지는 보통 **며칠 ~ 2주** 걸립니다.
- 구글: URL 검사 → 색인 요청으로 개별 페이지를 앞당길 수 있음
- 네이버: 웹페이지 수집 요청 활용

## 기존 도메인(udtschool)을 함께 등록해도 되나?
새 도메인으로 옮기는 중이라면 **새 도메인(udjschool)만 등록**하는 것을 권장합니다.
기존 도메인은 새 도메인으로 301 리다이렉트만 걸어두면, 검색엔진이 자연스럽게 새 주소로 이전을 인식합니다.
