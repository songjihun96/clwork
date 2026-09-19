import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, callsSocketUrl } from "./api";
import { AudioPhone } from "./audiophone";
import { Ringer } from "./ringer";
import { SipPhone } from "./sipphone";

/** 전화 상태를 화면 전체가 함께 본다.
 *
 *  상담원은 고객 화면을 보다가도 전화를 받아야 한다. 그래서 통화 상태는
 *  /calls 페이지가 아니라 앱 전체가 들고 있고, 어느 화면에 있든 벨이 울린다.
 *
 *  실시간 통로는 WebSocket 이지만, 화면의 진실은 늘 서버에서 다시 받아온다.
 *  이벤트 하나를 놓쳤다고 상담원 화면이 서버와 어긋나 있으면 안 되기 때문이다.
 *  WebSocket 은 "지금 다시 물어보라"는 신호로만 쓴다.
 */

const Ctx = createContext(null);

const RECONNECT_MAX = 15000;

export function CallCenterProvider({ children }) {
  const [connected, setConnected] = useState(false);
  const [calls, setCalls] = useState([]);
  const [me, setMe] = useState(null);
  const [settings, setSettings] = useState(null);
  const [lastEvent, setLastEvent] = useState(null);
  // 상담 상태·우선순위의 이름은 관리자가 바꿀 수 있다. 화면마다 따로
  // 불러오면 한 화면만 옛 이름을 쓰는 일이 생기므로 여기서 한 번만 받는다.
  const [options, setOptions] = useState({ statuses: [], priorities: [] });

  const wsRef = useRef(null);
  const retryRef = useRef(500);
  const aliveRef = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const r = await api.activeCalls();
      setCalls(r.items || []);
    } catch {
      /* 잠깐 끊긴 것뿐일 수 있다. 다음 신호 때 다시 맞춘다. */
    }
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      setMe(await api.myCounselor());
    } catch {
      /* 무시 */
    }
  }, []);

  // ── 실시간 통로 ─────────────────────────────────────────────
  useEffect(() => {
    aliveRef.current = true;

    const connect = () => {
      if (!aliveRef.current) return;
      let ws;
      try {
        ws = new WebSocket(callsSocketUrl());
      } catch {
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 500;
        refresh();
      };

      ws.onmessage = (ev) => {
        let data;
        try {
          data = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (data.type === "PONG" || data.type === "CONNECTED") return;
        setLastEvent(data);
        // 어떤 사건이든 서버에 다시 물어본다. 사건마다 화면을 직접 고치면
        // 놓친 사건 하나가 그대로 화면의 거짓말이 된다.
        refresh();
        if (data.type === "CALL_ANSWERED" || data.type === "CALL_ENDED") refreshMe();
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!aliveRef.current) return;
        // 끊기면 점점 뜸하게 다시 붙는다. 서버가 재시작 중일 때
        // 초당 수십 번 두드리지 않기 위해서다.
        const wait = retryRef.current;
        retryRef.current = Math.min(wait * 2, RECONNECT_MAX);
        setTimeout(connect, wait);
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* onclose 가 뒷정리를 한다 */
        }
      };
    };

    connect();
    refresh();
    refreshMe();
    api.phoneSettings().then(setSettings).catch(() => {});
    api.consultationOptions().then(setOptions).catch(() => {});

    // WebSocket 이 조용히 죽는 경우(프록시 유휴 종료)를 대비한 안전망.
    // 실시간 통로를 못 믿을 때도 최소한 15초마다는 화면이 맞춰진다.
    const safety = setInterval(refresh, 15000);

    return () => {
      aliveRef.current = false;
      clearInterval(safety);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* 이미 닫혔다 */
        }
      }
    };
  }, [refresh, refreshMe]);

  // ── 조작 ────────────────────────────────────────────────────
  const answer = async (id) => {
    const r = await api.answerCall(id);
    await refresh();
    await refreshMe();
    return r;
  };

  const reject = async (id) => {
    await api.rejectCall(id);
    await refresh();
  };

  const hangup = async (id) => {
    const r = await api.hangupCall(id);
    await refresh();
    await refreshMe();
    return r;
  };

  const setStatus = async (status) => {
    setMe(await api.setMyStatus(status));
    await refresh();
  };

  const ringing = calls.find((c) => c.ringing_for_me) || null;
  const inCall =
    calls.find((c) => c.session_state === "ANSWERED" && c.counselor_id === me?.id) || null;
  // 내가 건 전화. 아직 상대가 받기 전이면 통화가 아니라 발신 중이다.
  const outbound = calls.find((c) => c.outbound_for_me && c.session_state === "RINGING") || null;
  const queued = calls.filter((c) => c.session_state === "QUEUED");

  const reloadOptions = () => api.consultationOptions().then(setOptions).catch(() => {});

  return (
    <Ctx.Provider
      value={{
        connected, calls, ringing, inCall, outbound, queued,
        me, settings, lastEvent, options, reloadOptions,
        refresh, refreshMe, answer, reject, hangup, setStatus,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useCallCenter = () => useContext(Ctx);

/** 마이크. 통화 전에 헤드셋이 살아 있는지 상담원이 직접 확인할 수 있어야 한다.
 *
 *  지금 단계에서 진짜인 것은 여기까지다. 마이크를 잡고, 음소거하고, 입력이
 *  들어오는지 눈으로 본다. 이 소리가 고객에게 가려면 전화 사업자의
 *  WebRTC 게이트웨이가 있어야 한다(phoneSettings().audio_ready 로 확인).
 */
export function useMicrophone() {
  const [stream, setStream] = useState(null);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [level, setLevel] = useState(0);
  const rafRef = useRef(null);
  const ctxRef = useRef(null);

  const stop = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (ctxRef.current) {
      ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    setStream((s) => {
      if (s) s.getTracks().forEach((t) => t.stop());
      return null;
    });
    setLevel(0);
  }, []);

  const start = useCallback(async () => {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("이 브라우저는 마이크를 지원하지 않습니다. Chrome 또는 Edge를 쓰세요.");
      return null;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      setStream(s);
      setMuted(false);

      // 입력 크기를 그려준다. 마이크가 잡혔는지 말로만 알리면 믿기 어렵다.
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        const ctx = new AudioCtx();
        ctxRef.current = ctx;
        const src = ctx.createMediaStreamSource(s);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        const buf = new Uint8Array(analyser.frequencyBinCount);
        const loop = () => {
          analyser.getByteTimeDomainData(buf);
          let peak = 0;
          for (let i = 0; i < buf.length; i += 1) {
            peak = Math.max(peak, Math.abs(buf[i] - 128));
          }
          setLevel(Math.min(100, Math.round((peak / 128) * 220)));
          rafRef.current = requestAnimationFrame(loop);
        };
        loop();
      }
      return s;
    } catch (e) {
      setError(
        e?.name === "NotAllowedError"
          ? "마이크 사용을 허용해야 전화를 받을 수 있습니다. 주소창의 자물쇠에서 허용하세요."
          : "마이크를 열 수 없습니다: " + (e?.message || "알 수 없는 오류")
      );
      return null;
    }
  }, []);

  const toggleMute = useCallback(() => {
    setStream((s) => {
      if (s) {
        const next = !s.getAudioTracks()[0]?.enabled;
        s.getAudioTracks().forEach((t) => {
          t.enabled = !t.enabled;
        });
        setMuted(next);
      }
      return s;
    });
  }, []);

  useEffect(() => stop, [stop]);

  return { stream, error, muted, level, start, stop, toggleMute, ready: !!stream };
}

/** 통화 시간. 초 단위로 흘려보낸다. */
export function useElapsed(startedAt) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!startedAt) {
      setSeconds(0);
      return undefined;
    }
    const base = new Date(startedAt).getTime();
    const tick = () => setSeconds(Math.max(0, Math.floor((Date.now() - base) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  return seconds;
}

export const fmtDuration = (sec) => {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const two = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${two(m % 60)}:${two(s % 60)}` : `${two(m)}:${two(s % 60)}`;
};

/** 관리자가 정한 이름으로 상태·우선순위를 옮긴다.
 *  설정을 아직 못 받았을 때는 코드값이라도 보여준다. 빈칸보다 낫다. */
export function labelOf(list, code) {
  const hit = (list || []).find((o) => o.code === code);
  return hit ? hit.label : code || "";
}

/** 드롭다운에 띄울 것만 고른다. 지금 이 건이 쓰고 있는 값은 감춰져 있어도
 *  남겨둔다. 그러지 않으면 저장할 때 값이 조용히 바뀐다. */
export function activeOptions(list, keepCode = "") {
  return (list || []).filter((o) => o.is_active || o.code === keepCode);
}

/** 브라우저 전화기. 사업자가 SIP 연결을 지원할 때만 켠다.
 *
 *  켜지지 않아도 화면은 그대로 돈다. 그때는 전화가 상담원 휴대폰으로 울리고,
 *  이 화면은 고객정보와 상담기록만 맡는다. 그래서 여기서 실패해도 조용히
 *  물러나고 업무를 막지 않는다.
 */
export function useSipPhone(enabled) {
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const phoneRef = useRef(null);

  useEffect(() => {
    if (!enabled) return undefined;
    const phone = new SipPhone({
      onState: (s) => setState(s),
      onError: (msg) => setError(msg),
    });
    phoneRef.current = phone;
    setError("");
    phone.start();
    return () => {
      phoneRef.current = null;
      phone.stop();
    };
  }, [enabled]);

  return {
    state,
    error,
    // 등록까지 끝나야 전화를 받을 수 있다.
    ready: state === "registered" || state === "ringing" || state === "in-call",
    ringing: state === "ringing",
    inCall: state === "in-call",
    answer: () => phoneRef.current?.answer(),
    hangup: () => phoneRef.current?.hangup(),
    setMuted: (m) => phoneRef.current?.setMuted(m),
  };
}

/** SIP 없이 브라우저로 통화하기(stream 모드).
 *
 *  SipPhone 과 달리 미리 등록해 둘 것이 없다. 전화를 받는 순간 우리 서버에
 *  붙어 음성을 주고받기 시작한다. 그래서 통화가 없을 때는 아무 자원도 쓰지
 *  않고, 마이크도 그때 잡는다.
 */
export function useAudioPhone(enabled) {
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const phoneRef = useRef(null);

  const stop = useCallback(() => {
    phoneRef.current?.stop();
    phoneRef.current = null;
    setState("idle");
  }, []);

  const begin = useCallback(async (callId) => {
    if (!enabled || !callId) return false;
    stop();
    setError("");
    const phone = new AudioPhone({
      onState: (s) => setState(s),
      onError: (msg) => setError(msg),
    });
    phoneRef.current = phone;
    return phone.start(callId);
  }, [enabled, stop]);

  useEffect(() => stop, [stop]);

  return {
    state,
    error,
    inCall: state === "in-call",
    begin,
    stop,
    setMuted: (m) => phoneRef.current?.setMuted(m),
  };
}

/** 상담원이 듣는 소리를 상황에 맞게 튼다.
 *
 *  전화가 왔는데 아무 소리도 안 나면, 다른 창을 보던 상담원은 그냥 놓친다.
 *  화면에 배너가 떠도 소용이 없다. 그래서 소리는 화면과 별개로 챙긴다.
 */
export function useRinger({ ringing, outbound, inCall }) {
  const ringerRef = useRef(null);

  useEffect(() => {
    if (!ringerRef.current) ringerRef.current = new Ringer();
    return () => {
      ringerRef.current?.stop();
      ringerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const r = ringerRef.current;
    if (!r) return;
    // 통화가 시작되면 무조건 멎어야 한다. 통화 중에 벨이 계속 울리면
    // 상대 목소리를 덮는다.
    if (inCall) r.stop();
    else if (ringing) r.play("ring");
    else if (outbound) r.play("dial");
    else r.stop();
  }, [ringing, outbound, inCall]);
}
