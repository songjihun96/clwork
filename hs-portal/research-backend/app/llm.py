"""외부 AI 를 부르는 자리.

AI 호출을 코드 곳곳에 흩어 두면 실패 처리와 동시 실행 제한을 곳곳에
다시 써야 한다. 여기 한 곳에서만 부른다.

**서비스가 먼저다**

AI 가 죽어도 일지 쓰기·자소서 쓰기·로그인은 그대로 돌아야 한다.
그래서 이 파일의 모든 함수는 예외를 밖으로 던지지 않고
`LLMResult` 로 성공·실패를 알려 준다. 부르는 쪽은 실패를 보고
"AI 를 쓸 수 없습니다" 라고만 말하면 된다.

**동시에 여러 개를 부르지 않는다**

돈이 나가는 일이고, 한 학생이 버튼을 연타하면 그만큼 청구된다.
동시 실행 수를 막아 둔다.

**개인정보를 로그에 남기지 않는다**

방침에 그렇게 적었다. 로그에는 무엇을 했는지와 얼마나 걸렸는지만
남기고, 글 내용은 남기지 않는다.
"""

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import requests

# ── 설정 ────────────────────────────────────────────────────
# 키는 서버 .env 에만 둔다. 코드에도 화면에도 두지 않는다.
#
# 여러 계정의 키를 함께 등록하려면 ANTHROPIC_API_KEYS 에 쉼표로 나눠 적는다
# (예: "sk-ant-...111,sk-ant-...222"). 이건 반드시 실제로 별도 조직·사업자로
# 존재하는 정당한 계정들이어야 한다 — 한 서비스 트래픽을 한도 회피 목적으로
# 여러 계정에 나누는 건 Anthropic 이용 정책 위반 소지가 있다. 안 정하면
# 기존처럼 ANTHROPIC_API_KEY 하나만 쓴다.
API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
_extra_keys = os.getenv("ANTHROPIC_API_KEYS", "").strip()
if _extra_keys:
    API_KEYS = [k.strip() for k in _extra_keys.split(",") if k.strip()]
elif API_KEY:
    API_KEYS = [API_KEY]
else:
    API_KEYS = []

API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
MODEL = os.getenv("AI_MODEL", "claude-sonnet-4-6")
# 정형화된 짧은 작업(초안 채우기, 요약 등)은 더 빠른 모델로도 품질 차이가
# 크지 않다. 대화·비판적 검토·논문처럼 판단이 중요한 곳은 계속 MODEL을 쓴다.
FAST_MODEL = os.getenv("AI_FAST_MODEL", "claude-haiku-4-5-20251001")
TIMEOUT = int(os.getenv("AI_TIMEOUT", "120"))
# 키를 여러 개 등록했으면 그만큼 동시에 처리할 여유가 생긴다 — 키 하나당
# 2건씩을 기본으로 잡는다(명시적으로 AI_MAX_CONCURRENT 를 주면 그 값을 그대로 쓴다).
MAX_CONCURRENT = int(os.getenv("AI_MAX_CONCURRENT", str(2 * max(len(API_KEYS), 1))))
MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT", "12000"))
MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT", "2000"))

# 동시에 도는 요청 수를 막는다. 웹 요청이 AI 때문에 밀리면 안 된다.
_gate = threading.Semaphore(MAX_CONCURRENT)

# ── 회로 차단기(circuit breaker) ────────────────────────────
# Anthropic 쪽이 통째로 죽거나 느려지면, 요청마다 TIMEOUT(기본 120초)을
# 다 채우고서야 실패를 알게 된다 — 그 사이 학생들이 계속 눌러 대기열만
# 쌓인다. 최근에 실패가 몰리면 잠깐 동안 API를 아예 부르지 않고 바로
# "잠시 후 다시 시도해주세요"를 돌려줘, 대기열이 밀리는 걸 막는다.
CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("AI_CIRCUIT_FAILURE_THRESHOLD", "5"))
CIRCUIT_WINDOW_SECONDS = float(os.getenv("AI_CIRCUIT_WINDOW_SECONDS", "60"))
CIRCUIT_COOLDOWN_SECONDS = float(os.getenv("AI_CIRCUIT_COOLDOWN_SECONDS", "30"))
# 회로 차단에 셀 실패 종류 — 우리 쪽 잘못(형식 오류 등)이 아니라 Anthropic
# 인프라 문제로 보이는 것만 센다.
_CIRCUIT_ERROR_TYPES = {"timeout", "connection_error",
                        "http_429", "http_500", "http_502", "http_503", "http_529"}


class _CircuitBreaker:
    def __init__(self, threshold: int, window: float, cooldown: float):
        self._threshold = threshold
        self._window = window
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._failures: list = []
        self._open_until = 0.0

    def is_open(self) -> bool:
        with self._lock:
            return time.time() < self._open_until

    def record(self, error_type: str = "") -> None:
        if error_type and error_type not in _CIRCUIT_ERROR_TYPES:
            return
        with self._lock:
            now = time.time()
            if not error_type:  # 성공
                self._failures.clear()
                return
            self._failures = [t for t in self._failures if now - t < self._window]
            self._failures.append(now)
            if len(self._failures) >= self._threshold:
                self._open_until = now + self._cooldown
                self._failures = []
                print(f"[AI] 회로 차단 — 최근 {self._threshold}건 연속 실패, "
                      f"{self._cooldown:.0f}초간 신규 요청을 바로 거절합니다.", flush=True)


_breaker = _CircuitBreaker(CIRCUIT_FAILURE_THRESHOLD, CIRCUIT_WINDOW_SECONDS, CIRCUIT_COOLDOWN_SECONDS)

# 요청 제한(429)에 걸렸을 때 몇 번까지 다른 키로/잠깐 쉬었다 다시 시도할지.
# 키가 많다고 한없이 재시도하면 요청 하나가 너무 오래 붙잡고 있으니 3번까지만.
_RATE_LIMIT_RETRIES = int(os.getenv("AI_RATE_LIMIT_RETRIES", str(min(max(len(API_KEYS), 1), 3))))


class _KeyPool:
    """여러 계정의 키를 돌아가며 쓴다.

    한 키가 요청 제한(429)에 걸리면 잠깐 그 키를 쉬게 하고 다음 키로
    넘어간다 — 계정 하나가 막혀도 나머지 계정으로 계속 처리된다.
    """

    def __init__(self, keys):
        self._keys = list(keys)
        self._idx = 0
        self._lock = threading.Lock()
        self._cooldown_until = {k: 0.0 for k in self._keys}

    def pick(self) -> Optional[str]:
        if not self._keys:
            return None
        with self._lock:
            now = time.time()
            n = len(self._keys)
            for i in range(n):
                k = self._keys[(self._idx + i) % n]
                if self._cooldown_until.get(k, 0.0) <= now:
                    self._idx = (self._idx + i + 1) % n
                    return k
            # 전부 쉬는 중이어도 요청은 보내야 하니, 가장 먼저 풀리는 키를 쓴다.
            k = min(self._keys, key=lambda x: self._cooldown_until.get(x, 0.0))
            self._idx = (self._keys.index(k) + 1) % n
            return k

    def cooldown(self, key: str, seconds: float = 30.0) -> None:
        with self._lock:
            self._cooldown_until[key] = time.time() + seconds


_key_pool = _KeyPool(API_KEYS)


def available() -> bool:
    """AI 를 쓸 수 있는 상태인가. 키가 하나도 없으면 못 쓴다."""
    return bool(API_KEYS)


def status() -> dict:
    """관리자·화면이 확인할 상태. 키 자체는 절대 내보내지 않는다."""
    return {
        "available": available(),
        "model": MODEL if available() else "",
        "max_concurrent": MAX_CONCURRENT,
        "key_count": len(API_KEYS),
        "circuit_open": _breaker.is_open(),
    }


@dataclass
class LLMResult:
    """AI 호출 결과. 예외 대신 이것을 돌려준다."""

    ok: bool
    text: str = ""
    data: Optional[dict] = None
    error: str = ""          # 화면에 보여줄 말
    error_type: str = ""     # 로그용 갈래
    duration_ms: int = 0
    meta: dict = field(default_factory=dict)


# 화면에 보여줄 말. 내부 사정을 그대로 보이면 안 된다.
_USER_MESSAGE = {
    "no_key": "AI 기능이 아직 준비되지 않았습니다.",
    "busy": "AI 요청이 몰려 있습니다. 잠시 뒤에 다시 눌러주세요.",
    "timeout": "AI 분석이 오래 걸려 멈췄습니다. 잠시 뒤에 다시 시도해주세요.",
    "too_long": "글이 너무 깁니다. 나누어서 분석해주세요.",
    "bad_json": "AI 응답을 읽지 못했습니다. 다시 시도해주세요.",
    "empty": "AI 가 답을 주지 않았습니다. 다시 시도해주세요.",
    "http": "AI 서버에 연결하지 못했습니다. 잠시 뒤에 다시 시도해주세요.",
    "circuit_open": "AI 서버 상태가 불안정합니다. 잠시 후 다시 시도해주세요.",
}


def _log(request_id: str, op: str, ok: bool, ms: int, err: str = "", model: str = "") -> None:
    """무엇을 얼마나 했는지만 남긴다. 글 내용은 남기지 않는다."""
    tail = f" error={err}" if err else ""
    print(f"[AI] id={request_id} op={op} ok={ok} ms={ms} model={model or MODEL}{tail}",
          flush=True)


def _call(prompt: str, op: str, temperature: float = 0.2,
          max_tokens: Optional[int] = None,
          image_b64: Optional[str] = None, image_media_type: str = "image/jpeg",
          model: Optional[str] = None, system: Optional[str] = None) -> LLMResult:
    """AI 를 한 번 부른다. 어떤 경우에도 예외를 던지지 않는다.

    image_b64 를 주면 사진 설명(caption) 처럼 이미지를 함께 보내는 요청이
    된다 — 사용자가 명시적으로 "사진 설명 생성" 을 눌렀을 때만 이 값이
    채워지고, 사진을 올렸다고 자동으로 불리지는 않는다(부르는 쪽 책임).

    system 을 주면 그 부분을 캐시 가능한(cache_control: ephemeral) 블록으로
    따로 보낸다 — 여러 학생이 같은 프롬프트 틀(지시문)로 짧은 시간 안에
    여러 번 부르는 작업(예: 연구 코치 대화)에서, 매번 똑같이 반복되는
    지시문 부분을 다시 처리하지 않아도 되어 비용·응답속도가 줄어든다.
    한 번의 요청 안에서 바뀌는 내용(대화 기록 등)은 여기 넣지 말고
    prompt 쪽에 둬야 한다 — 그래야 캐시가 계속 재사용된다.
    """
    request_id = uuid.uuid4().hex[:8]

    if not available():
        _log(request_id, op, False, 0, "no_key", model=model)
        return LLMResult(False, error=_USER_MESSAGE["no_key"], error_type="no_key")

    if len(prompt) > MAX_INPUT_CHARS:
        _log(request_id, op, False, 0, "too_long", model=model)
        return LLMResult(False, error=_USER_MESSAGE["too_long"],
                         error_type="too_long")

    if _breaker.is_open():
        _log(request_id, op, False, 0, "circuit_open", model=model)
        return LLMResult(False, error=_USER_MESSAGE["circuit_open"],
                         error_type="circuit_open")

    # 자리가 날 때까지 기다린다. 너무 오래 기다리면 포기한다.
    if not _gate.acquire(timeout=30):
        _log(request_id, op, False, 0, "busy", model=model)
        return LLMResult(False, error=_USER_MESSAGE["busy"], error_type="busy")

    if image_b64:
        content = [
            {"type": "image", "source": {"type": "base64",
             "media_type": image_media_type, "data": image_b64}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt

    started = time.time()
    try:
        res = None
        for attempt in range(_RATE_LIMIT_RETRIES):
            key = _key_pool.pick()
            res = requests.post(
                API_URL,
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model or MODEL,
                    "max_tokens": max_tokens or MAX_OUTPUT_TOKENS,
                    "temperature": temperature,
                    **({"system": [{"type": "text", "text": system,
                                    "cache_control": {"type": "ephemeral"}}]}
                       if system else {}),
                    "messages": [{"role": "user", "content": content}],
                },
                timeout=TIMEOUT,
            )
            if res.status_code != 429 or attempt == _RATE_LIMIT_RETRIES - 1:
                break
            # 이 계정이 지금 요청 제한에 걸렸다. 잠깐 쉬게 해 두고(키가
            # 여럿이면 다음 바퀴에 다른 키를 고르게 된다) 짧게 기다린 뒤 다시 시도한다.
            _key_pool.cooldown(key)
            try:
                wait = min(float(getattr(res, "headers", {}).get("retry-after", 1)), 3.0)
            except (TypeError, ValueError, AttributeError):
                wait = 1.0
            time.sleep(wait)
        ms = int((time.time() - started) * 1000)

        if res.status_code != 200:
            # 응답 본문에 글 내용이 섞여 있을 수 있어 상태 코드만 남긴다.
            _breaker.record(f"http_{res.status_code}")
            _log(request_id, op, False, ms, f"http_{res.status_code}", model=model)
            return LLMResult(False, error=_USER_MESSAGE["http"],
                             error_type=f"http_{res.status_code}",
                             duration_ms=ms)

        body = res.json()
        text = "".join(
            part.get("text", "")
            for part in (body.get("content") or [])
            if part.get("type") == "text"
        ).strip()

        if not text:
            _log(request_id, op, False, ms, "empty", model=model)
            return LLMResult(False, error=_USER_MESSAGE["empty"],
                             error_type="empty", duration_ms=ms)

        usage = body.get("usage") or {}
        _breaker.record()
        _log(request_id, op, True, ms, model=model)
        return LLMResult(
            True, text=text, duration_ms=ms,
            meta={"in_tokens": usage.get("input_tokens"),
                  "out_tokens": usage.get("output_tokens"),
                  "stop_reason": body.get("stop_reason")},
        )

    except requests.Timeout:
        ms = int((time.time() - started) * 1000)
        _breaker.record("timeout")
        _log(request_id, op, False, ms, "timeout", model=model)
        return LLMResult(False, error=_USER_MESSAGE["timeout"],
                         error_type="timeout", duration_ms=ms)
    except requests.RequestException as exc:
        ms = int((time.time() - started) * 1000)
        # 연결 자체가 안 되는 경우(DNS·연결거부·SSL 등) — Anthropic 쪽 장애일
        # 가능성이 높은 신호라 회로 차단 카운트에 넣는다.
        _breaker.record("connection_error")
        _log(request_id, op, False, ms, type(exc).__name__, model=model)
        return LLMResult(False, error=_USER_MESSAGE["http"],
                         error_type=type(exc).__name__, duration_ms=ms)
    except Exception as exc:
        ms = int((time.time() - started) * 1000)
        # 예외 메시지에 글 내용이 들어갈 수 있어 갈래만 남긴다. 우리 쪽
        # 버그일 수도 있어 회로 차단 카운트에는 넣지 않는다.
        _log(request_id, op, False, ms, type(exc).__name__, model=model)
        return LLMResult(False, error=_USER_MESSAGE["http"],
                         error_type=type(exc).__name__, duration_ms=ms)
    finally:
        _gate.release()


# JSON 만 달라고 해도 앞뒤에 설명을 붙여 오는 일이 있다.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> Optional[dict]:
    """답에서 JSON 을 꺼낸다. 앞뒤에 군더더기가 붙어 있어도 찾아낸다."""
    if not text:
        return None

    # 1) 통째로 JSON 인 경우
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else None
    except ValueError:
        pass

    # 2) ```json ... ``` 로 감싼 경우
    m = _FENCE.search(text)
    if m:
        try:
            out = json.loads(m.group(1))
            return out if isinstance(out, dict) else None
        except ValueError:
            pass

    # 3) 첫 { 부터 마지막 } 까지
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            out = json.loads(text[start:end + 1])
            return out if isinstance(out, dict) else None
        except ValueError:
            pass
    return None


def generate(prompt: str, temperature: float = 0.2,
             max_tokens: Optional[int] = None, op: str = "generate",
             model: Optional[str] = None, system: Optional[str] = None) -> LLMResult:
    """글을 받아 온다."""
    return _call(prompt, op, temperature, max_tokens, model=model, system=system)


def generate_json(prompt: str, temperature: float = 0.1,
                  max_tokens: Optional[int] = None,
                  op: str = "generate_json", retry: int = 1,
                  image_b64: Optional[str] = None,
                  image_media_type: str = "image/jpeg",
                  model: Optional[str] = None, system: Optional[str] = None) -> LLMResult:
    """JSON 을 받아 온다.

    형식이 어긋나면 한 번 더 물어본다. 그 이상은 하지 않는다.
    부를 때마다 돈이 나가고, 두 번 실패하면 세 번째도 실패하기 쉽다.

    model 을 안 주면 기본 MODEL(정확도 우선)을 쓴다. llm.FAST_MODEL 을
    넘기면 정형화된 짧은 작업을 더 빠르게 처리할 수 있다.

    system 을 주면 캐시 가능한 지시문 블록으로 따로 보낸다(_call 설명 참고).
    """
    call_tokens = max_tokens or MAX_OUTPUT_TOKENS
    for attempt in range(retry + 1):
        r = _call(prompt, op, temperature, call_tokens, image_b64, image_media_type,
                  model=model, system=system)
        if not r.ok:
            return r

        data = _extract_json(r.text)
        if data is not None:
            r.data = data
            return r

        if attempt >= retry:
            _log("-", op, False, r.duration_ms, "bad_json", model=model)
            return LLMResult(False, text=r.text, error=_USER_MESSAGE["bad_json"],
                             error_type="bad_json", duration_ms=r.duration_ms)

        # JSON이 안 읽히는 흔한 이유 중 하나는 "형식을 안 지켜서"가 아니라
        # "다 쓰기도 전에 max_tokens에 걸려 끊겨서"다. 그때는 같은 한도로
        # 다시 물어도 똑같이 끊긴다 — 한도를 늘려야 실제로 고쳐진다.
        if r.meta.get("stop_reason") == "max_tokens":
            call_tokens = min(call_tokens * 2, 8000)
        else:
            # 형식만 어긋난 경우에는 짧게 다시 일러 준다.
            prompt = prompt + "\n\n반드시 JSON 만 출력하십시오. 다른 말을 붙이지 마십시오."

    return LLMResult(False, error=_USER_MESSAGE["bad_json"], error_type="bad_json")
