/** 상담원이 듣는 소리 — 수신 벨과 발신음.
 *
 *  고객이 듣는 대기음과는 다르다. 이건 브라우저에서만 나고 전화망으로
 *  나가지 않으므로, 관리자가 올린 파일을 그대로 재생하면 된다.
 *
 *  올린 파일이 없으면 소리를 직접 만들어 낸다. 전화가 왔는데 아무 소리도
 *  안 나면 다른 창을 보던 상담원은 그냥 놓친다. 기본값이 "무음"이면 안 된다.
 *
 *    수신 벨  1초 울리고 0.4초 쉼   (두 음을 겹쳐 전화기 느낌으로)
 *    발신음   1초 울리고 2초 쉼     (국내 통화연결음과 같은 박자)
 */

const TONES = {
  // [주파수들, 울리는 시간(초), 한 바퀴 길이(초)]
  ring: [[440, 480], 1.0, 1.4],
  dial: [[440, 480], 1.0, 3.0],
};

export class Ringer {
  constructor() {
    this.audio = null;
    this.ctx = null;
    this.timer = null;
    this.kind = null;
  }

  /** kind: "ring" | "dial" */
  async play(kind) {
    if (this.kind === kind) return;      // 이미 같은 소리가 나고 있다
    this.stop();
    this.kind = kind;

    // 관리자가 올린 파일이 있으면 그것부터.
    try {
      const res = await fetch(`/api/cs/phone/sounds/${kind}/file`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const blob = await res.blob();
        const el = new Audio(URL.createObjectURL(blob));
        el.loop = true;
        el.volume = 0.8;
        // 브라우저가 막으면(사용자 조작 전) 조용히 기본음으로 넘어간다.
        await el.play();
        this.audio = el;
        return;
      }
    } catch {
      /* 없거나 못 받았다. 아래 기본음으로 간다. */
    }

    if (this.kind === kind) this._playTone(kind);
  }

  _playTone(kind) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const [freqs, onSec, cycleSec] = TONES[kind] || TONES.ring;

    let ctx;
    try {
      ctx = new AudioCtx();
    } catch {
      return;
    }
    this.ctx = ctx;

    const beat = () => {
      if (this.ctx !== ctx) return;
      const now = ctx.currentTime;
      const gain = ctx.createGain();
      // 딱 소리가 나지 않게 시작과 끝을 부드럽게 여닫는다.
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(0.18, now + 0.02);
      gain.gain.setValueAtTime(0.18, now + onSec - 0.03);
      gain.gain.linearRampToValueAtTime(0, now + onSec);
      gain.connect(ctx.destination);

      freqs.forEach((f) => {
        const osc = ctx.createOscillator();
        osc.type = "sine";
        osc.frequency.value = f;
        osc.connect(gain);
        osc.start(now);
        osc.stop(now + onSec);
      });
    };

    beat();
    this.timer = setInterval(beat, cycleSec * 1000);
  }

  stop() {
    this.kind = null;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.audio) {
      try {
        this.audio.pause();
        URL.revokeObjectURL(this.audio.src);
      } catch { /* 이미 정리됐다 */ }
      this.audio = null;
    }
    if (this.ctx) {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
  }
}

function authHeaders() {
  const token = localStorage.getItem("udj_cs_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}
