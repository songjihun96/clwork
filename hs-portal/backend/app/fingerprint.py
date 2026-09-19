"""오디오 지문 — 숏츠가 롱폼의 몇 초에서 잘려 나왔는지 소리로 찾는다.

**왜 이걸 따로 두나**

대본 매칭은 STT 가 찍어 준 낱말 시각에 묶여 있어 0.1~0.5초가 한계다.
그리고 대본으로는 못 푸는 두 경우가 있다.
  - 말이 거의 없는 숏츠(음악·자막만) — 맞출 글자가 없다
  - 롱폼에서 같은 말을 여러 번 하는 경우 — 어느 쪽인지 못 가린다
지문은 소리 자체를 보므로 이 둘을 풀고, 정밀도도 수십 밀리초까지 간다.

**어떻게 동작하나 (Shazam 계열)**

소리를 스펙트로그램으로 펴고, 주변보다 튀는 **봉우리**만 골라낸다. 봉우리
둘을 짝지어 `(주파수1, 주파수2, 시간차)` 를 해시 하나로 만든다. 롱폼 전체를
이렇게 색인해 두고, 숏츠도 같은 방식으로 해시를 뽑아 조회한다.

핵심은 **시간차의 몰림**이다. 우연히 같은 해시가 여기저기서 걸리더라도,
진짜 자리에서만 "롱폼 시각 − 숏츠 시각" 이 하나의 값으로 몰린다. 그 몰린
값이 곧 숏츠가 시작된 지점이다.

봉우리만 보기 때문에 **소리가 덧붙어도 견딘다** — 배경음악이 깔려도 원본의
강한 봉우리는 여전히 봉우리로 남는다. 시끄러운 곳에서 노래를 찾아내라고
만든 기술이라 그렇다. 반대로 **속도를 바꾸면 무너진다**(주파수가 통째로
밀린다). 지금은 숏츠 편집에 배속을 쓰지 않는다는 전제로 넣었다.
"""

from __future__ import annotations

import io as _io
import math
import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import media as media_mod

# 소리를 얼마나 촘촘히 볼지.
#   16kHz 면 8kHz 까지 본다. 말소리(~4kHz)는 물론 배경음악의 배음까지 들어와
#   봉우리가 다양해지고, 그만큼 우연 일치가 줄어든다.
SAMPLE_RATE = 16000
N_FFT = 1024
HOP = 512                       # 32ms 마다 한 칸
SEC_PER_FRAME = HOP / SAMPLE_RATE

# 한 칸에서 봉우리를 몇 개까지 고를지. 많이 고르면 시끄러운 소리에 강해지지만
# 색인이 커지고 우연 일치도 늘어난다.
PEAKS_PER_FRAME = 5
PEAK_MIN_DB = -60.0             # 이보다 조용한 곳은 봉우리로 안 본다

# 짝지을 범위. 너무 좁으면 해시가 안 생기고, 너무 넓으면 폭발한다.
FAN_MIN_DT = 1
FAN_MAX_DT = 24                 # 약 0.77초
FAN_MAX_DF = 80                 # 주파수 칸 차이
FANOUT = 6                      # 봉우리 하나가 만들 짝의 최대 개수

# 이 정도는 몰려야 "찾았다"고 본다.
MIN_VOTES = 30

# **판정의 핵심.** 1위 자리가 2위보다 몇 배나 표를 받았는가.
#
# 표의 절대 개수로는 못 가른다 — 배경음악이 크게 깔린 진짜 매칭(278표)이
# 아무 상관 없는 소리(158표)와 비슷하게 나온다. 반면 '몰림의 뚜렷함'은
# 진짜 12~40배, 가짜 1.1배로 확연히 갈린다. 우연히 걸린 표는 여기저기
# 흩어지지만 진짜 자리는 한 곳에 쌓이기 때문이다.
MIN_PROMINENCE = 3.0

# 표를 셀 때 이웃 몇 칸까지 함께 볼지.
#
# 숏츠 앞에 3.0초짜리 인트로가 붙으면 32ms 칸 경계에 딱 안 맞아, 같은
# 자리의 표가 이웃한 두 칸으로 갈린다(2546표가 340+339 로 쪼개졌다).
# 이웃을 합쳐 세면 되살아난다.
SMOOTH_BINS = 1


def available() -> bool:
    """지문을 쓸 수 있는 상태인가(numpy·ffmpeg 둘 다 필요)."""
    if not media_mod.have_ffmpeg():
        return False
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def missing_reason() -> str:
    if not media_mod.have_ffmpeg():
        return "서버에 ffmpeg 이 없어 오디오 지문을 만들 수 없습니다."
    try:
        import numpy  # noqa: F401
    except ImportError:
        return "numpy 가 없어 오디오 지문을 만들 수 없습니다(pip install numpy)."
    return ""


def _read_pcm(path: str):
    """영상에서 16kHz 모노 PCM 을 통째로 읽는다."""
    import numpy as np

    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-f", "s16le",
           "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=media_mod.FFMPEG_TIMEOUT)
    except subprocess.SubprocessError:
        return None
    if r.returncode != 0 or not r.stdout:
        return None
    usable = len(r.stdout) - (len(r.stdout) % 2)
    return np.frombuffer(r.stdout[:usable], dtype="<i2").astype("float32") / 32768.0


def _spectrogram(samples):
    """세로는 주파수, 가로는 시간인 표를 만든다(단위: dB)."""
    import numpy as np

    if samples is None or len(samples) < N_FFT:
        return None
    n_frames = 1 + (len(samples) - N_FFT) // HOP
    if n_frames < 2:
        return None
    # 창을 옮겨 가며 잘라 내는 일을 복사 없이 한다. 1시간이면 10만 칸이라
    # 복사하면 메모리가 몇 배로 뛴다.
    strided = np.lib.stride_tricks.as_strided(
        samples, shape=(n_frames, N_FFT),
        strides=(samples.strides[0] * HOP, samples.strides[0]),
    )
    window = np.hanning(N_FFT).astype("float32")
    spec = np.abs(np.fft.rfft(strided * window, axis=1))
    return 20.0 * np.log10(spec + 1e-8)


def _peaks(spec) -> List[Tuple[int, int]]:
    """칸마다 튀는 봉우리를 골라 (시간칸, 주파수칸) 목록으로 돌려준다."""
    import numpy as np

    n_frames, n_bins = spec.shape
    # 각 칸에서 큰 순서로 몇 개만. argpartition 이 정렬보다 훨씬 빠르다.
    k = min(PEAKS_PER_FRAME, n_bins - 1)
    idx = np.argpartition(spec, -k, axis=1)[:, -k:]
    rows = np.repeat(np.arange(n_frames), k)
    cols = idx.reshape(-1)
    vals = spec[rows, cols]
    keep = vals > PEAK_MIN_DB
    return list(zip(rows[keep].tolist(), cols[keep].tolist()))


def _hashes(peaks: List[Tuple[int, int]]):
    """봉우리를 짝지어 해시와 그 시작 시각을 만든다.

    봉우리 하나만으로는 어디서나 나오는 흔한 값이라 못 쓴다. 둘을 짝지어
    '어떤 소리 뒤에 얼마 뒤 어떤 소리가 왔나' 를 담아야 특징이 된다.
    """
    import numpy as np

    peaks.sort()
    out_h: List[int] = []
    out_t: List[int] = []
    n = len(peaks)
    for i in range(n):
        t1, f1 = peaks[i]
        made = 0
        for j in range(i + 1, n):
            t2, f2 = peaks[j]
            dt = t2 - t1
            if dt < FAN_MIN_DT:
                continue
            if dt > FAN_MAX_DT:
                break
            if abs(f2 - f1) > FAN_MAX_DF:
                continue
            # 주파수는 9비트, 시간차는 5비트로 눌러 담는다.
            out_h.append(((f1 & 0x1FF) << 14) | ((f2 & 0x1FF) << 5) | (dt & 0x1F))
            out_t.append(t1)
            made += 1
            if made >= FANOUT:
                break
    return (np.asarray(out_h, dtype="int64"), np.asarray(out_t, dtype="int32"))


@dataclass
class Fingerprint:
    hashes: object          # numpy int64 배열
    times: object           # numpy int32 배열(시작 시각 칸)
    frames: int             # 전체 칸 수

    @property
    def count(self) -> int:
        return int(len(self.hashes))

    def to_bytes(self) -> bytes:
        import numpy as np
        buf = _io.BytesIO()
        np.savez_compressed(buf, h=self.hashes, t=self.times,
                            frames=np.asarray([self.frames], dtype="int64"))
        return buf.getvalue()

    @staticmethod
    def from_bytes(raw: bytes) -> Optional["Fingerprint"]:
        import numpy as np
        try:
            with np.load(_io.BytesIO(raw)) as z:
                return Fingerprint(hashes=z["h"], times=z["t"],
                                   frames=int(z["frames"][0]))
        except Exception:
            return None


def build(path: str) -> Optional[Fingerprint]:
    """영상 하나의 지문을 만든다. 못 만들면 None."""
    if not available() or not os.path.exists(path):
        return None
    spec = _spectrogram(_read_pcm(path))
    if spec is None:
        return None
    h, t = _hashes(_peaks(spec))
    if len(h) == 0:
        return None
    return Fingerprint(hashes=h, times=t, frames=int(spec.shape[0]))


@dataclass
class Offset:
    """숏츠가 롱폼의 어디서 시작하는지."""
    start_sec: float
    score: float            # 0~1. 숏츠 해시 중 몇 %가 이 자리로 몰렸나
    votes: int
    prominence: float       # 1위가 2위보다 몇 배인가. 이게 진짜/가짜를 가른다


def locate(longform: Fingerprint, shorts: Fingerprint) -> Optional[Offset]:
    """숏츠가 롱폼의 몇 초에서 시작하는지 찾는다.

    같은 해시가 우연히 여기저기서 걸려도, 진짜 자리에서만 시간차가 한 값으로
    몰린다. 그 몰림이 이 함수가 세는 것이다.
    """
    import numpy as np

    if longform is None or shorts is None:
        return None
    if longform.count == 0 or shorts.count == 0:
        return None

    # 롱폼 해시를 정렬해 두고, 숏츠 해시가 어디에 걸리는지 한 번에 찾는다.
    order = np.argsort(longform.hashes, kind="stable")
    lh = longform.hashes[order]
    lt = longform.times[order]

    left = np.searchsorted(lh, shorts.hashes, side="left")
    right = np.searchsorted(lh, shorts.hashes, side="right")
    counts = right - left
    if int(counts.sum()) == 0:
        return None

    # 한 해시가 롱폼 곳곳에 너무 많이 나오면(흔한 소리) 표를 흐린다. 버린다.
    usable = counts <= 40
    if not usable.any():
        return None

    deltas: List[object] = []
    for i in np.nonzero(usable)[0]:
        deltas.append(lt[left[i]:right[i]] - shorts.times[i])
    if not deltas:
        return None
    all_delta = np.concatenate(deltas)
    all_delta = all_delta[all_delta >= 0]      # 숏츠가 롱폼보다 앞설 수는 없다
    if all_delta.size == 0:
        return None

    # 이웃 칸을 합쳐 센다. 칸 경계에 안 맞아 갈라진 표를 되살리기 위해서다.
    hist = np.bincount(all_delta)
    smooth = hist.astype("int64").copy()
    for shift in range(1, SMOOTH_BINS + 1):
        smooth[shift:] += hist[:-shift]
        smooth[:-shift] += hist[shift:]

    best = int(np.argmax(smooth))
    votes = int(smooth[best])
    if votes < MIN_VOTES:
        return None

    # 2위는 1위 근처를 빼고 찾는다. 바로 옆 칸은 같은 자리의 잔여물이라
    # 2위로 치면 진짜 매칭이 스스로를 깎아내린다.
    guard = SMOOTH_BINS * 2 + 2
    masked = smooth.copy()
    masked[max(best - guard, 0):best + guard + 1] = 0
    second = int(masked.max()) if masked.size else 0
    prominence = votes / max(second, 1)
    if prominence < MIN_PROMINENCE:
        return None

    score = min(votes / max(shorts.count, 1), 1.0)
    return Offset(start_sec=round(float(best) * SEC_PER_FRAME, 3),
                  score=round(float(score), 4), votes=votes,
                  prominence=round(float(prominence), 2))


def duration_sec(fp: Fingerprint) -> float:
    return round(fp.frames * SEC_PER_FRAME, 3)
