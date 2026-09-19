import { getToken } from "./api";

/** SIP 없이 브라우저로 통화하기.
 *
 *  전화망의 음성이 우리 서버를 거쳐 WebSocket 으로 온다. 8kHz G.711 μ-law,
 *  20ms(160바이트)씩. 우리가 할 일은 세 가지다.
 *
 *    받기 : base64 → μ-law 해독 → 스피커
 *    보내기: 마이크 → 8kHz → μ-law 부호화 → base64 → 전송
 *    맞추기: 도착이 들쭉날쭉해도 끊기지 않게 조금 모아뒀다 내보낸다
 *
 *  음질의 천장은 우리가 정하지 못한다. 전화망이 8kHz 협대역이고 사업자도
 *  G.711 로 보내기 때문이다. 여기서 할 수 있는 일은 **우리가 덧붙이는 잡음을
 *  없애는 것**뿐이고, 아래 세 가지가 그 잡음의 원인이었다.
 *
 *  1) 리샘플링 — 48kHz 를 여섯 칸 평균으로 줄이면 4kHz 위 소리가 접혀 들어와
 *     쇳소리가 난다. 이제 오디오 컨텍스트 자체를 8kHz 로 열어 브라우저가
 *     제대로 된 필터로 줄이게 한다. 브라우저가 거절하면 그때만 우리가 줄이되,
 *     저역통과 필터를 먼저 물려 접힘을 막는다.
 *
 *  2) 메인 스레드 — ScriptProcessor 는 화면과 같은 스레드에서 돈다. 상담원이
 *     상담 내용을 타자하는 동안 소리가 끊겼다. AudioWorklet 은 오디오 전용
 *     스레드에서 돌아 화면이 바빠도 끊기지 않는다.
 *
 *  3) 지연 누적 — 보내는 쪽 시계가 조금만 빨라도 재생 예약이 계속 밀려 통화가
 *     점점 늦어졌다. 앞선 정도가 일정 선을 넘으면 따라잡도록 했다.
 */

const RATE = 8000;
const FRAME = 160;          // 20ms

// 도착이 조금 늦어도 소리가 끊기지 않게 이만큼 앞서 예약해 둔다.
// 늘리면 안 끊기지만 대화가 굼떠진다. 0.12초가 통화에서 견딜 만한 선이다.
const JITTER_SEC = 0.12;
// 이보다 더 앞서 있으면 지연이 쌓이고 있다는 뜻이다. 따라잡는다.
const MAX_LEAD_SEC = 0.32;

// 전화 대역. 이 위는 8kHz 로 줄일 때 접혀 들어와 쇳소리가 된다.
const LOWPASS_HZ = 3400;

// ── G.711 μ-law ────────────────────────────────────────────────

const ULAW_DECODE = new Int16Array(256);
for (let i = 0; i < 256; i += 1) {
  const u = ~i & 0xff;
  const sign = u & 0x80;
  const exponent = (u >> 4) & 0x07;
  const mantissa = u & 0x0f;
  let sample = ((mantissa << 3) + 0x84) << exponent;
  sample -= 0x84;
  ULAW_DECODE[i] = sign ? -sample : sample;
}

function linearToUlaw(sample) {
  const BIAS = 0x84;
  const CLIP = 32635;
  let s = sample;
  const sign = s < 0 ? 0x80 : 0;
  if (sign) s = -s;
  if (s > CLIP) s = CLIP;
  s += BIAS;
  let exponent = 7;
  let mask = 0x4000;
  while (exponent > 0 && (s & mask) === 0) {
    exponent -= 1;
    mask >>= 1;
  }
  const mantissa = (s >> (exponent + 3)) & 0x0f;
  return ~(sign | (exponent << 4) | mantissa) & 0xff;
}

const b64ToBytes = (b64) => {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
};

const bytesToB64 = (bytes) => {
  let s = "";
  for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i]);
  return btoa(s);
};

/** 마이크를 오디오 전용 스레드에서 퍼 올리는 작은 프로그램.
 *
 *  별도 파일로 두면 배포할 것이 하나 늘고 경로가 어긋날 여지가 생긴다.
 *  문자열로 만들어 그 자리에서 불러온다. */
const CAPTURE_WORKLET = `
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(new Float32Array(ch));
    return true;
  }
}
registerProcessor('cs-capture', CaptureProcessor);
`;

// ── 전화기 ─────────────────────────────────────────────────────

export class AudioPhone {
  constructor(handlers = {}) {
    this.handlers = handlers;    // { onState, onError }
    this.attempts = 0;
    this.callId = null;
    this.ws = null;
    this.ctx = null;
    this.stream = null;
    this.nodes = [];
    this.playAt = 0;
    this.muted = false;
    this.pending = [];           // 아직 한 프레임(160)을 못 채운 마이크 조각
    this.carry = 0;              // 리샘플 소수점 나머지
    this.stopped = false;
    this.nativeRate = false;
  }

  _emit(state, extra) {
    this.handlers.onState?.(state, extra);
  }

  async start(callId) {
    this.stopped = false;
    this.callId = callId;
    this._emit("connecting");

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch (e) {
      const msg = e?.name === "NotAllowedError"
        ? "마이크 사용을 허용해야 통화할 수 있습니다."
        : `마이크를 열 수 없습니다: ${e?.message || ""}`;
      this._emit("failed", msg);
      this.handlers.onError?.(msg);
      return false;
    }

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    // 8kHz 로 열어달라고 부탁한다. 되면 브라우저가 제대로 된 필터로 줄여주므로
    // 우리가 손댈 일이 없다. 크롬·엣지는 들어준다.
    try {
      this.ctx = new AudioCtx({ sampleRate: RATE });
    } catch {
      this.ctx = new AudioCtx();
    }
    this.nativeRate = Math.abs(this.ctx.sampleRate - RATE) < 1;

    if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => {});
    this.playAt = this.ctx.currentTime + JITTER_SEC;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(`${proto}//${window.location.host}/api/cs/ws/audio`);
    url.searchParams.set("token", getToken() || "");
    url.searchParams.set("call_id", String(callId));

    this.ws = new WebSocket(url.toString());
    this.ws.onopen = () => {
      this._emit("in-call");
      this._startMic();
    };
    this.ws.onmessage = (ev) => this._onMessage(ev);
    this.ws.onclose = (ev) => {
      // 4404 = 아직 통화 음성 다리가 없다. 발신에서는 상대가 받아야 다리가
      // 생기므로, 우리가 조금 빨리 붙은 것뿐일 수 있다. 몇 번 더 시도한다.
      if (!this.stopped && ev?.code === 4404 && this.attempts < 8) {
        this.attempts += 1;
        setTimeout(() => {
          if (!this.stopped) this._retry();
        }, 600);
        return;
      }
      if (!this.stopped) this._emit("ended");
      this.stop();
    };
    this.ws.onerror = () => {
      const msg = "통화 음성 연결이 끊겼습니다.";
      this._emit("failed", msg);
      this.handlers.onError?.(msg);
    };
    return true;
  }

  _retry() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(`${proto}//${window.location.host}/api/cs/ws/audio`);
    url.searchParams.set("token", getToken() || "");
    url.searchParams.set("call_id", String(this.callId));
    this.ws = new WebSocket(url.toString());
    this.ws.onopen = () => {
      this.attempts = 0;
      this._emit("in-call");
    };
    this.ws.onmessage = (ev) => this._onMessage(ev);
    this.ws.onclose = (ev) => {
      if (!this.stopped && ev?.code === 4404 && this.attempts < 8) {
        this.attempts += 1;
        setTimeout(() => {
          if (!this.stopped) this._retry();
        }, 600);
        return;
      }
      if (!this.stopped) this._emit("ended");
      this.stop();
    };
  }

  // ── 받기 ─────────────────────────────────────────────────

  _onMessage(ev) {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.t === "ended") {
      this.stop();
      return;
    }
    if (msg.t !== "audio" || !msg.p || !this.ctx) return;

    const bytes = b64ToBytes(msg.p);
    const buf = this.ctx.createBuffer(1, bytes.length, RATE);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < bytes.length; i += 1) ch[i] = ULAW_DECODE[bytes[i]] / 32768;

    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);

    const now = this.ctx.currentTime;
    if (this.playAt < now + 0.005) {
      // 소리가 끊겼다(네트워크가 밀렸다). 다시 여유를 두고 시작한다.
      this.playAt = now + JITTER_SEC;
    } else if (this.playAt > now + MAX_LEAD_SEC) {
      // 예약이 계속 앞서 쌓이고 있다. 그대로 두면 통화가 점점 늦어진다.
      // 여기서 한 번 따라잡는다. 짧게 한 번 튈 수 있지만 지연이 눌린다.
      this.playAt = now + JITTER_SEC;
    }
    src.start(this.playAt);
    this.playAt += buf.duration;
  }

  // ── 보내기 ───────────────────────────────────────────────

  async _startMic() {
    const ctx = this.ctx;
    const source = ctx.createMediaStreamSource(this.stream);
    let tail = source;

    if (!this.nativeRate) {
      // 브라우저가 8kHz 를 거절했다. 우리가 줄여야 하므로, 줄이기 전에
      // 전화 대역 위를 잘라낸다. 이걸 안 하면 그 소리가 접혀 들어와
      // 쇳소리·치찰음이 된다.
      for (let i = 0; i < 2; i += 1) {
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.value = LOWPASS_HZ;
        lp.Q.value = 0.707;
        tail.connect(lp);
        this.nodes.push(lp);
        tail = lp;
      }
    }

    const onSamples = (input) => this._encodeAndSend(input);

    let captured = false;
    if (ctx.audioWorklet) {
      try {
        const blobUrl = URL.createObjectURL(
          new Blob([CAPTURE_WORKLET], { type: "application/javascript" })
        );
        await ctx.audioWorklet.addModule(blobUrl);
        URL.revokeObjectURL(blobUrl);
        const node = new window.AudioWorkletNode(ctx, "cs-capture");
        node.port.onmessage = (e) => onSamples(e.data);
        tail.connect(node);
        this.nodes.push(node);
        captured = true;
      } catch {
        // 지원하지 않는 브라우저다. 아래 예전 방식으로 내려간다.
        captured = false;
      }
    }

    if (!captured) {
      const node = ctx.createScriptProcessor(1024, 1, 1);
      node.onaudioprocess = (e) => onSamples(e.inputBuffer.getChannelData(0));
      tail.connect(node);
      // ScriptProcessor 는 출력에 이어야 돈다. 소리는 내지 않게 0으로 막는다.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      node.connect(mute);
      mute.connect(ctx.destination);
      this.nodes.push(node, mute);
    }
  }

  _encodeAndSend(input) {
    if (!this.ws || this.ws.readyState !== 1) return;

    if (this.nativeRate) {
      for (let i = 0; i < input.length; i += 1) {
        const v = this.muted ? 0 : Math.max(-1, Math.min(1, input[i]));
        this.pending.push(linearToUlaw(Math.round(v * 32767)));
      }
    } else {
      // 소수점 비율(44100/8000 = 5.5125 같은)에서도 음이 밀리지 않도록
      // 나머지를 다음 덩어리로 넘긴다. 반올림해 버리면 조금씩 어긋나
      // 음높이가 흔들린다.
      const step = this.ctx.sampleRate / RATE;
      let pos = this.carry;
      while (pos < input.length) {
        const i0 = Math.floor(pos);
        const frac = pos - i0;
        const a = input[i0] || 0;
        const b = input[i0 + 1] !== undefined ? input[i0 + 1] : a;
        const v = this.muted ? 0 : Math.max(-1, Math.min(1, a + (b - a) * frac));
        this.pending.push(linearToUlaw(Math.round(v * 32767)));
        pos += step;
      }
      this.carry = pos - input.length;
    }

    while (this.pending.length >= FRAME) {
      const frame = Uint8Array.from(this.pending.splice(0, FRAME));
      try {
        this.ws.send(JSON.stringify({ t: "audio", p: bytesToB64(frame) }));
      } catch {
        break;
      }
    }
  }

  setMuted(muted) {
    this.muted = !!muted;
    // 트랙 자체도 끈다. 인코딩 전에 막아야 확실하다.
    this.stream?.getAudioTracks().forEach((t) => {
      t.enabled = !this.muted;
    });
  }

  stop() {
    if (this.stopped) return;
    this.stopped = true;
    this.nodes.forEach((n) => {
      try {
        n.disconnect();
      } catch { /* 이미 끊겼다 */ }
    });
    this.nodes = [];
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch { /* 이미 닫혔다 */ }
      this.ws = null;
    }
    if (this.ctx) {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
    this.pending = [];
    this.carry = 0;
    this._emit("idle");
  }
}
