"""배경음악(BGM)을 직접 합성한다 — 외부 음원을 쓰지 않으므로 저작권 문제가 없다.

    python script/build_bgm.py

밝고 담백한 D장조 112BPM, I–V–vi–IV(D–A–Bm–G) 진행.
패드(화음) + 플럭 아르페지오 + 베이스 + 아주 작은 킥/하이햇. 나레이션을 가리지 않도록
중음역을 비워 두고, 볼륨은 영상 쪽에서 나레이션 구간마다 더 낮춘다(ducking).
버전마다 길이에 맞춰 만들고 끝을 으뜸화음(D)으로 맺는다.
"""
import json
import wave
from pathlib import Path

import numpy as np

SR = 48000
BPM = 112
BEAT = 60 / BPM
SRC = Path(__file__).resolve().parents[1]
VIDEO = SRC.parent

# MIDI 음 번호
CHORDS = {
    "D":  [50, 54, 57, 62],   # D3 F#3 A3 D4
    "A":  [45, 52, 57, 61],   # A2 E3 A3 C#4
    "Bm": [47, 54, 59, 62],   # B2 F#3 B3 D4
    "G":  [43, 50, 55, 59],   # G2 D3 G3 B3
}
PROG = ["D", "A", "Bm", "G"]   # 한 화음 = 2마디(8박)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n, a, r):
    e = np.ones(n)
    na = min(int(a * SR), n // 2)
    nr = min(int(r * SR), n - na)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def add(buf, start_s, sig, pan=0.0):
    i = int(start_s * SR)
    if i >= buf.shape[0]:
        return
    sig = sig[: buf.shape[0] - i]
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * l
    buf[i:i + len(sig), 1] += sig * r


def tone(f, dur, harmonics=((1, 1.0),), decay=None, attack=0.005, release=0.05):
    t = np.arange(int(dur * SR)) / SR
    s = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in harmonics)
    e = env_adsr(len(t), attack, release)
    if decay:
        e *= np.exp(-t / decay)
    return s * e


def make(seconds: float, seed=7):
    rng = np.random.default_rng(seed)
    n = int((seconds + 0.5) * SR)
    pad = np.zeros((n, 2))
    pluck = np.zeros((n, 2))
    bass = np.zeros((n, 2))
    drums = np.zeros((n, 2))

    chord_len = 8 * BEAT
    n_chords = int(np.ceil(seconds / chord_len))
    if seconds - (n_chords - 1) * chord_len < 3.0 and n_chords > 1:
        n_chords -= 1   # 마지막 화음이 너무 짧으면 앞 화음에서 맺는다
    # 끝이 D 로 맺도록 진행의 시작점을 맞춘다
    offset = (-(n_chords - 1)) % 4
    final_start = (n_chords - 1) * chord_len
    for c in range(n_chords):
        name = PROG[(c + offset) % 4]
        if c == n_chords - 1:
            name = "D"
        t0 = c * chord_len
        notes = CHORDS[name]
        last = c == n_chords - 1
        # 패드
        for m in notes[1:]:
            dur = chord_len + 0.6 if not last else seconds - t0 + 0.4
            p = tone(hz(m + 12), dur, harmonics=((1, 1.0), (2, 0.18), (3, 0.05)), attack=0.9, release=1.2)
            add(pad, t0, p * 0.055, pan=rng.uniform(-0.4, 0.4))
        # 베이스 (1, 3박 + 마지막 박 앞 8분)
        for b in ([0, 2, 4, 6, 7.5] if not last else [0]):
            d = 0.9 * BEAT if not last else 3.0
            add(bass, t0 + b * BEAT, tone(hz(notes[0]), d, ((1, 1), (2, 0.25)), decay=0.5, release=0.08) * 0.16)
        # 플럭 아르페지오 (8분음표)
        arp = [notes[1] + 12, notes[2] + 12, notes[3] + 12, notes[2] + 24, notes[3] + 12, notes[2] + 12, notes[1] + 24, notes[3] + 12]
        steps = 16 if not last else 1
        for k in range(steps):
            m = arp[k % len(arp)]
            vel = 0.9 if k % 4 == 0 else 0.65
            s = tone(hz(m), 0.6, ((1, 1.0), (2, 0.35), (3, 0.12)), decay=0.17, release=0.04)
            add(pluck, t0 + k * BEAT / 2, s * 0.06 * vel, pan=-0.35 if k % 2 else 0.35)
        if last:
            s = tone(hz(notes[3] + 12), 2.5, ((1, 1.0), (2, 0.35)), decay=0.9, release=0.3)
            add(pluck, t0, s * 0.07)
        # 드럼 — 첫 화음 동안은 쉬고 마지막 화음에서는 뺀다
        if c >= 1 and not last:
            for b in range(8):
                if b % 2 == 0:  # 킥
                    t = np.arange(int(0.22 * SR)) / SR
                    f = 48 + 70 * np.exp(-t / 0.03)
                    k_sig = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.09)
                    add(drums, t0 + b * BEAT, k_sig * 0.11)
                # 하이햇 (엇박)
                hn = int(0.035 * SR)
                noise = rng.standard_normal(hn)
                noise = np.diff(noise, prepend=0)  # 고역 위주
                add(drums, t0 + (b + 0.5) * BEAT, noise * np.exp(-np.arange(hn) / (0.008 * SR)) * 0.018,
                    pan=0.25)

    # 플럭에 가벼운 딜레이(점8분)
    d = int(0.75 * BEAT * SR)
    echo = np.zeros_like(pluck)
    echo[d:] = pluck[:-d] * 0.32
    echo[2 * d:] += pluck[:-2 * d] * 0.12
    pluck = pluck + echo[:, ::-1]

    mix = pad + pluck + bass + drums
    mix = mix[: int(seconds * SR)]
    # 페이드 인/아웃
    fi, fo = int(0.8 * SR), int(2.2 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
    mix /= np.max(np.abs(mix)) + 1e-9
    mix *= 10 ** (-1 / 20)
    return mix


def write_wav(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    tl = json.loads((SRC / "remotion/timeline.json").read_text(encoding="utf-8"))
    for ver, v in tl.items():
        sec = v["frames"] / v["fps"]
        data = make(sec)
        for out in (SRC / f"public/audio/bgm_{ver}.wav", VIDEO / f"assets/audio/bgm_{ver}.wav"):
            write_wav(out, data)
        print("bgm", ver, f"{sec:.2f}s")
    # 학교·교사용 영상
    stl_path = SRC / "remotion/school_timeline.json"
    if stl_path.exists():
        for ver, v in json.loads(stl_path.read_text(encoding="utf-8")).items():
            sec = v["frames"] / v["fps"]
            data = make(sec, seed=11)
            for out in (SRC / f"public/audio/bgm_school_{ver}.wav", VIDEO / f"assets/audio/bgm_school_{ver}.wav"):
                write_wav(out, data)
            print("bgm school", ver, f"{sec:.2f}s")
