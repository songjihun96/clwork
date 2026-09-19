"""오디오 지문 검사 — 숏츠가 롱폼의 몇 초에서 잘렸는지 소리로 찾기.

실제 영상 없이 돈다. 소리 신호를 직접 만들어 넣으므로 ffmpeg 없이도
알고리즘 자체를 검증할 수 있다(ffmpeg 는 파일에서 소리를 꺼내는 데만 쓴다).

여기서 확인하는 것은 두 가지다.
  1) 편집을 거친 숏츠도 제자리를 찾는가 — 음량·배경음악·잡음·인트로
  2) **관계없는 소리에는 답을 내놓지 않는가** — 이게 더 중요하다.
     엉뚱한 구간을 확신 있게 내놓으면 아무 연결도 없느니만 못하다.
"""
import sys

sys.path.insert(0, ".")

OK = []


def chk(name, cond, extra=""):
    OK.append(bool(cond))
    print(("  OK  " if cond else "  FAIL") + f"  {name}" + (f"  {extra}" if not cond and extra else ""))


try:
    import numpy as np
except ImportError:
    print("numpy 가 없어 건너뜁니다(pip install numpy).")
    sys.exit(0)

from app import fingerprint as fp   # noqa: E402

SR = fp.SAMPLE_RATE


def speechlike(sec, seed):
    """말소리 비슷한 신호. 기본 주파수가 흔들리는 배음 + 사이사이 쉼."""
    r = np.random.default_rng(seed)
    n = int(SR * sec)
    t = np.arange(n) / SR
    sig = np.zeros(n, dtype="float32")
    for k in range(1, 6):
        f = 110 + 60 * np.sin(2 * np.pi * 0.7 * t + r.uniform(0, 6))
        sig += (0.6 / k) * np.sin(2 * np.pi * f * k * t + r.uniform(0, 6))
    env = (np.sin(2 * np.pi * 1.7 * t + r.uniform(0, 6)) > -0.3).astype("float32")
    return (sig * env + 0.01 * r.standard_normal(n)).astype("float32")


def fpof(sig):
    spec = fp._spectrogram(sig)
    h, t = fp._hashes(fp._peaks(spec))
    return fp.Fingerprint(hashes=h, times=t, frames=int(spec.shape[0]))


def bgm(n, amp):
    return (amp * np.sin(2 * np.pi * 440 * np.arange(n) / SR)).astype("float32")


LONG = speechlike(240, 1)          # 4분짜리 롱폼
TRUE = 137.0
SEG = LONG[int(TRUE * SR):int((TRUE + 18) * SR)].copy()
L = fpof(LONG)

print("=== 1. 색인 만들기 ===")
chk("지문이 만들어진다", L.count > 1000, str(L.count))
chk("칸 수가 길이와 맞는다", abs(fp.duration_sec(L) - 240) < 1.0, str(fp.duration_sec(L)))

print("=== 2. 편집을 거쳐도 제자리를 찾는가 ===")
CASES = [
    ("그대로 잘라냄", SEG, TRUE),
    ("음량 절반", SEG * 0.5, TRUE),
    ("배경음악", SEG + bgm(len(SEG), 0.25), TRUE),
    ("배경음악 크게", SEG + bgm(len(SEG), 0.75), TRUE),
    ("잡음 섞임", SEG + 0.05 * np.random.default_rng(4).standard_normal(len(SEG)).astype("float32"), TRUE),
    ("무음 인트로 3초", np.concatenate([np.zeros(int(3 * SR), dtype="float32"), SEG]), TRUE - 3.0),
    ("인트로+아웃트로", np.concatenate([speechlike(2.5, 88), SEG, speechlike(2, 77)]), TRUE - 2.5),
]
for label, sig, want in CASES:
    o = fp.locate(L, fpof(sig))
    chk(f"{label} 찾음", o is not None, "못 찾음")
    if o:
        err = abs(o.start_sec - want)
        # 대본 매칭은 STT 시각 때문에 0.1~0.5초가 한계다. 지문은 그보다
        # 한 자릿수 더 정밀해야 붙일 값어치가 있다.
        chk(f"{label} 오차 0.1초 이내", err < 0.1, f"{err * 1000:.0f}ms")
        chk(f"{label} 뚜렷함 충분", o.prominence >= fp.MIN_PROMINENCE, str(o.prominence))

print("=== 3. 관계없는 소리에는 답하지 않는가 ===")
# 이쪽이 더 중요하다. 엉뚱한 자리를 확신 있게 내놓으면 학생이 아무 상관
# 없는 대목부터 영상을 보게 된다.
chk("다른 소리는 못 찾음", fp.locate(L, fpof(speechlike(18, 555))) is None)
chk("또 다른 소리도 못 찾음", fp.locate(L, fpof(speechlike(12, 999))) is None)
chk("무음은 못 찾음",
    fp.locate(L, fpof(np.zeros(int(15 * SR), dtype="float32"))) is None)
chk("빈 지문은 못 찾음", fp.locate(L, None) is None)

print("=== 4. 저장하고 되살리기 ===")
raw = L.to_bytes()
back = fp.Fingerprint.from_bytes(raw)
chk("왕복해도 해시 수 유지", back is not None and back.count == L.count)
chk("왕복해도 칸 수 유지", back is not None and back.frames == L.frames)
o = fp.locate(back, fpof(SEG))
chk("되살린 색인으로도 찾는다", o is not None and abs(o.start_sec - TRUE) < 0.1,
    str(o.start_sec if o else None))
chk("망가진 값은 None", fp.Fingerprint.from_bytes(b"garbage") is None)
# 1시간이면 이것의 15배쯤. 몇 MB 안에 들어와야 DB 에 넣을 만하다.
chk("4분짜리 색인이 3MB 이하", len(raw) < 3_000_000, f"{len(raw):,} 바이트")

print("=== 5. 환경이 없으면 조용히 물러나는가 ===")
chk("available 은 참/거짓만 준다", isinstance(fp.available(), bool))
chk("없는 파일이면 None", fp.build("없는파일.mp4") is None)

print(f"\n===== {sum(OK)}/{len(OK)} 통과 =====")
sys.exit(0 if all(OK) else 1)
