/** 음원을 전화망이 알아듣는 형태(8kHz G.711 μ-law)로 바꾼다.
 *
 *  왜 브라우저에서 바꾸는가 — 파이썬 3.13 에서 오디오 변환 표준 라이브러리
 *  (audioop)가 사라졌다. 서버 파이썬 버전이 올라갈 때마다 대기음이 깨지는
 *  일을 만들고 싶지 않고, ffmpeg 같은 것을 서버에 새로 깔게 하고 싶지도 않다.
 *
 *  브라우저는 mp3·m4a·wav 를 이미 해독할 줄 안다. 여기서 8kHz 로 줄이는
 *  일까지 브라우저가 제대로 해주므로(OfflineAudioContext), 우리는 결과를
 *  μ-law 한 바이트씩으로 옮기기만 하면 된다.
 */

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

/**
 * @param {File} file  올린 음원
 * @param {number} maxSeconds  이보다 길면 잘라낸다
 * @returns {{ blob: Blob, seconds: number }}
 */
export async function toUlaw8k(file, maxSeconds = 90) {
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const OfflineCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!AudioCtx || !OfflineCtx) {
    throw new Error("이 브라우저는 음원 변환을 지원하지 않습니다. Chrome 이나 Edge 를 쓰세요.");
  }

  const bytes = await file.arrayBuffer();

  // 해독은 아무 샘플레이트로나 할 수 있다. 여기서는 원본 그대로 읽는다.
  const tmp = new AudioCtx();
  let decoded;
  try {
    decoded = await tmp.decodeAudioData(bytes);
  } catch {
    throw new Error("음원을 읽지 못했습니다. mp3·m4a·wav 파일인지 확인해 주세요.");
  } finally {
    tmp.close().catch(() => {});
  }

  const seconds = Math.min(decoded.duration, maxSeconds);
  const frames = Math.floor(seconds * 8000);
  if (frames <= 0) throw new Error("소리가 너무 짧습니다.");

  // 8kHz 한 채널로 다시 그린다. 줄이는 일(안티에일리어싱 포함)은 브라우저가 한다.
  const off = new OfflineCtx(1, frames, 8000);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start(0);
  const rendered = await off.startRendering();

  const ch = rendered.getChannelData(0);
  const out = new Uint8Array(ch.length);
  for (let i = 0; i < ch.length; i += 1) {
    const v = Math.max(-1, Math.min(1, ch[i]));
    out[i] = linearToUlaw(Math.round(v * 32767));
  }

  return {
    blob: new Blob([out], { type: "application/octet-stream" }),
    seconds: ch.length / 8000,
  };
}
