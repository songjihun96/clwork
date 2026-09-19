# 서버 감시 위젯

바탕화면에 띄워 두고 보는 창. 서버의 `/api/monitor/snapshot` 을 몇 초마다
불러서 접속자·트래픽·서버 상태·경보를 한 화면에 보여 준다.

```
[내 PC]  monitor_widget.pyw  ──HTTPS──▶  [서버]  /api/monitor/snapshot
                                                  ├ nginx 접근 로그 (접속자·트래픽)
                                                  ├ /proc (CPU·메모리·부하)
                                                  ├ systemctl / 실제 요청 (서비스 생사)
                                                  ├ PostgreSQL 통계
                                                  └ journalctl (에러 로그)
```

---

## 1. 서버 쪽 준비 (한 번만)

배포 zip 을 `/root/hs-portal` 에 푼 다음:

**(1) 감시 토큰을 만든다.** 아무 긴 문자열이면 된다.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**(2) `/root/hs-portal/backend/.env` 맨 아래에 넣는다.**

```
MONITOR_TOKEN=위에서_나온_값
```

**(3) 재시작.**

```bash
systemctl restart udt-backend
```

**(4) 서버에서 먼저 확인한다.**

```bash
curl -s -H "X-Monitor-Token: 위에서_나온_값" http://127.0.0.1:8000/api/monitor/ping
```

`{"ok":true,...}` 가 나오면 된 것이다.

> `.env` 를 안 넣으면 이 API 는 토큰으로는 아예 안 열린다(관리자 로그인
> 상태로만 열린다). 빈 토큰으로 우회되는 일이 없도록 일부러 그렇게 뒀다.

---

## 2. 내 PC 쪽 — 보는 방법이 세 가지다

| 파일 | 무엇 | 언제 |
|---|---|---|
| **`위젯으로 열기.bat`** | 주소창 없는 작은 창, 항상 위에 고정 | 바탕화면 한쪽에 두고 곁눈질로 |
| **`대시보드 열기.bat`** | 브라우저 전체 화면 대시보드 | 자세히 들여다볼 때 |
| `서버감시 켜기.bat` | 파이썬으로 만든 초경량 위젯 | 브라우저도 띄우기 싫을 때 |

셋 다 같은 `config.json` 을 쓰므로 설정은 한 번만 하면 된다. 위 둘은 내 PC 에
아주 작은 웹서버(127.0.0.1:8777)를 띄우고 브라우저가 거기에 붙는 구조다 —
**감시 토큰은 `config.json` 에만 있고 브라우저로는 나가지 않는다.**

창 크기와 위치는 `config.json` 의 `widget_width` / `widget_height` /
`widget_x` / `widget_y` 로 바꾼다. 항상 위 고정을 끄려면
`"always_on_top": false`.

> 위젯 창 오른쪽 위 `⤢` 를 누르면 그 자리에서 전체 보기로 바뀐다.

## 2-0. 처음 설정

1. 파이썬이 없으면 <https://www.python.org/downloads/> 에서 설치한다.
   설치 화면에서 **"Add python.exe to PATH"** 를 반드시 켠다.
   (설치할 파이썬 패키지는 하나도 없다 — 표준 라이브러리만 쓴다.)
2. **`서버감시 켜기.bat`** 을 더블클릭한다.
3. 처음 켜면 설정 창이 뜬다. **서버 주소**와 **감시 토큰**을 넣고
   `연결 확인` → `저장`.

## 2-1. 사이트별로 나눠 보기 (우리동네 직업계고 / 기록해)

위젯 위쪽의 **사이트 탭**(`전체` `우리동네 직업계고` `기록해` `상담`)을
누르면 그 사이트만 따로 볼 수 있다. 접속자 수, 그래프, 트래픽 항목이 전부
고른 사이트 기준으로 바뀐다.

**단, nginx 가 사이트별로 로그를 나눠 써야 한다.** 기본 설정은 세 사이트가
전부 `/var/log/nginx/access.log` 한 파일에 섞여 들어가고, 그 형식에는 어느
도메인으로 들어온 요청인지가 안 남는다. 안 나눠져 있으면 위젯이
"사이트가 한 덩어리로 잡힌다" 라고 알려 준다.

지금 어떻게 돼 있는지 보기:

```bash
grep -n "access_log" /etc/nginx/sites-enabled/*
ls -la /var/log/nginx/
```

`access_log` 줄이 안 보이면, **각 사이트 설정의 `server { }` 안에** 한 줄씩
넣는다. `server_name` 바로 아래쯤이면 된다.

| 파일 | 넣을 줄 |
|---|---|
| 우리동네 직업계고 설정 | `access_log /var/log/nginx/udt.access.log;` |
| 기록해 설정 (`diary.ggm.kr`) | `access_log /var/log/nginx/diary.access.log;` |
| 상담 설정 (`udjcs.ggm.kr`) | `access_log /var/log/nginx/udjcs.access.log;` |

```bash
nginx -t && systemctl reload nginx
```

`nginx -t` 가 `syntax is ok` 를 내야 `reload` 가 돈다. 실패하면 아무것도
안 바뀌니 그대로 고쳐서 다시 하면 된다.

파일 이름의 `udt` / `diary` / `udjcs` 가 곧 사이트 이름표다. 다른 이름을
쓰고 싶으면 `.env` 에서 바꾼다:

```
MONITOR_SITES=우리동네 직업계고=udt,기록해=diary,상담=cs
```

왼쪽이 위젯에 보일 이름, 오른쪽이 로그 파일 이름에 들어 있는 조각이다.

### 특정 사이트를 아예 안 보고 싶으면

`MONITOR_NGINX_LOGS` 에 **볼 것만** 적는다. 여기 적으면 폴더 자동 탐색을
안 하고 적힌 파일만 읽는다.

```
MONITOR_NGINX_LOGS=/var/log/nginx/udt.access.log,/var/log/nginx/diary.access.log,/var/log/nginx/udjcs.access.log,/var/log/nginx/access.log
```

이렇게 두면 `univ.access.log`(연구·논문)는 통계에서 통째로 빠진다. 맨 끝에
`access.log` 를 같이 넣어 둔 건, 도메인 없이 IP 로 바로 들어오는 요청과
스캐너가 거기 쌓이기 때문이다 — 보안 항목의 재료라 빼지 않는 편이 낫다.

> 이 값을 쓰면 **사이트를 새로 만들 때 여기에도 한 줄 추가해야 한다.**
> 안 적으면 그 사이트는 계속 안 보인다.

> 로그 회전(logrotate)은 `/var/log/nginx/*.log` 를 통째로 잡고 있어서
> 새 파일도 알아서 같이 돌아간다. 따로 할 일은 없다.

---

### 조작

| 하고 싶은 것 | 방법 |
|---|---|
| 위치 옮기기 | 위쪽 제목 줄을 잡고 끌기 |
| 접기/펼치기 | 각 항목 제목(▾)을 클릭 |
| 작게 보기 | 오른쪽 위 `▭` — 큰 숫자와 경보만 남는다 |
| 항상 위에 두기 | 우클릭 메뉴 |
| 새로고침 | `F5` |
| 설정 | 오른쪽 위 `⚙` |
| 종료 | 오른쪽 위 `✕` 또는 `Esc` |

### 부팅할 때 자동으로 켜기

`Win + R` 에 `shell:startup` 을 넣어 열리는 폴더에,
**`서버감시 켜기.bat` 의 바로가기**를 넣어 둔다.

---

## 3. 보이는 것

| 항목 | 무엇 |
|---|---|
| **현재 접속자** | 최근 5분 안에 요청이 있었던 사람 수(봇 제외). 사이트 탭으로 서비스별 분리 |
| 트래픽 | 요청 수, 상태코드 분포, 전송량, 봇 비율, 응답시간 p50/p95, 많이 열린 곳, 유입 경로, 검색엔진 크롤러 |
| 서버 | CPU, 메모리, 디스크, 코어당 부하, 가동 시간 |
| 서비스 | udt-backend / diary-backend / udt-audio / diary-ai-worker / nginx / postgresql 의 생사 + 실제 요청 응답시간 |
| 디스크·백업 | 남은 용량, 하루 증가량, **며칠 뒤 가득 차는지**, 큰 폴더, 마지막 백업 시각 |
| 데이터베이스 | 응답, 연결 수, 용량, 5초 넘는 질의, 큰 테이블 |
| SSL 인증서 | 도메인별 남은 일수 |
| 외부 연동 | 문자, 메일(+발송 실패), 전화망, 결제, AI 키 |
| 보안 | 로그인 실패/성공, 실패 비율, 스캐너 IP, 404 많은 IP, 관리자 작업 |
| 에러 로그 | journalctl 에서 같은 예외끼리 묶어 상위 8개 |
| 오늘 | 가입·적성검사·문의·통화, 대기 중인 것들. **우리동네 직업계고 DB 기준** — 기록해는 DB가 따로라 안 들어온다 |
| 가동률 | 30일 가동률과 내려가 있던 시간 |

경보는 위젯 위쪽에 쌓이고, **처음 보는 심각 경보**일 때만 소리와 팝업이 뜬다.
같은 경보로 매번 울리면 금방 무시하게 되고, 그때부터 알림은 없는 것과 같다.

---

## 4. 알아 둘 것 두 가지

### (1) 응답시간이 "nginx 로그에 시간 없음" 으로 나오면

nginx 기본 로그 형식에는 응답시간이 안 들어 있다. 보고 싶으면
`/etc/nginx/nginx.conf` 의 `http { }` 안에 형식을 하나 더 만들고,

```nginx
log_format timed '$remote_addr - $remote_user [$time_local] "$request" '
                 '$status $body_bytes_sent "$http_referer" '
                 '"$http_user_agent" $request_time';
```

각 사이트 설정의 `access_log` 를 이 형식으로 바꾼다.

```nginx
access_log /var/log/nginx/access.log timed;
```

```bash
nginx -t && systemctl reload nginx
```

시간 칸이 없어도 나머지는 전부 그대로 나온다 — 이건 켤지 말지 선택이다.

### (2) 이 위젯만으로는 24시간 감시가 안 된다

내 PC 가 꺼져 있으면 아무것도 못 본다. **서버 바깥에서 도는 감시를 하나 더**
걸어 두는 게 맞다. 서버 안에 대시보드를 두면 서버가 죽었을 때 대시보드도
같이 죽어서 아무 신호가 안 온다.

[UptimeRobot](https://uptimerobot.com) 무료 계정이면 충분하다. 5분마다
아래 주소를 찔러 보게 하고, 실패하면 메일/문자로 알리게 해 두면 된다.

```
https://udjcs.ggm.kr/api/meta
https://diary.ggm.kr/api/health
```

---

## 5. 서버 쪽 설정을 바꾸고 싶을 때

전부 `.env` 로 덮을 수 있다. 기본값만으로 이 서버에서 돌게 해 뒀으니
보통은 `MONITOR_TOKEN` 하나만 넣으면 된다.

| 환경변수 | 기본값 | 뜻 |
|---|---|---|
| `MONITOR_TOKEN` | (없음) | 감시 토큰. 이게 없으면 토큰으로는 안 열린다 |
| `MONITOR_UNITS` | `udt-backend,diary-backend,udt-audio,diary-ai-worker,nginx,postgresql` | 생사를 볼 systemd 유닛 |
| `MONITOR_PROBES` | `UDJ=…:8000/api/meta,기록해=…:8100/api/health,음성중계=…:8010/api/meta` | 실제로 찔러 볼 곳 |
| `MONITOR_SITES` | `우리동네 직업계고=udt,기록해=diary,상담=cs` | 사이트 이름 = 로그 파일 이름 조각 |
| `MONITOR_NGINX_LOG_DIR` | `/var/log/nginx` | 접근 로그 폴더 |
| `MONITOR_NGINX_LOGS` | (자동 탐색) | 로그 파일을 직접 지정할 때 |
| `MONITOR_CERT_DIR` | `/etc/letsencrypt/live` | 인증서 폴더 |
| `MONITOR_BACKUP_DIRS` | `/root/backups,/var/backups/postgres` | 백업이 떨어지는 곳 |
| `MONITOR_WATCH_DIRS` | `…/backend/uploads,…/backend/media,/var/log` | 용량을 따로 볼 폴더 |
| `MONITOR_SAMPLE_SECONDS` | `60` | 이력을 몇 초마다 남길지 |
| `MONITOR_HISTORY_DAYS` | `30` | 이력 보관 기간 |
| `MONITOR_CACHE_SECONDS` | `4` | 수집 결과를 몇 초 캐시할지 |
| `MONITOR_SAMPLER` | `1` | `0` 이면 이력 기록을 끈다 |

`monitor_samples` 표는 1분에 한 줄씩 쌓인다. 30일이면 43,200 줄이라
용량은 몇 MB 수준이고, 기간이 지난 줄은 하루 한 번 알아서 지운다.
