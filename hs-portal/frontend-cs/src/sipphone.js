import JsSIP from "jssip";
import { api } from "./api";

/** 브라우저를 전화기로 만든다.
 *
 *  전화 사업자의 SIP 게이트웨이에 등록해 두면, 걸려온 전화가 이 브라우저로
 *  직접 온다. 상담원은 헤드셋만 꽂으면 되고 휴대폰이 필요 없다.
 *
 *  까다로운 지점이 하나 있다. **등록 토큰의 수명이 5~7분이다.**
 *  만료되면 등록이 풀려 전화가 안 온다. 그래서 만료 전에 다시 받아 재등록해야
 *  하는데, 통화 중에 재등록하면 통화가 끊긴다. 그래서 통화 중에는 미뤘다가
 *  끝난 뒤에 한다.
 *
 *  받을지 말지는 이 파일이 정하지 않는다. 화면의 [받기] 버튼이 정한다.
 *  자동으로 받아버리면 상담원이 준비되기 전에 통화가 시작된다.
 */

// 토큰 수명의 몇 %가 지났을 때 새로 받을지. 만료 직전에 받으면
// 네트워크가 한 번만 느려도 등록이 끊긴 채로 남는다.
const REFRESH_RATIO = 0.6;
const MIN_REFRESH_MS = 60 * 1000;

export class SipPhone {
  constructor(handlers = {}) {
    this.ua = null;
    this.session = null;
    this.audio = null;
    this.refreshTimer = null;
    this.stopped = false;
    this.handlers = handlers;   // { onState, onIncoming, onEnded, onError }
    this.state = "idle";        // idle | connecting | registered | ringing | in-call | failed
  }

  _emit(state, extra) {
    this.state = state;
    this.handlers.onState?.(state, extra);
  }

  /** 원격 오디오를 흘려보낼 자리. 화면에 보일 필요는 없다. */
  _ensureAudio() {
    if (this.audio) return this.audio;
    const el = document.createElement("audio");
    el.autoplay = true;
    el.setAttribute("aria-hidden", "true");
    el.style.display = "none";
    document.body.appendChild(el);
    this.audio = el;
    return el;
  }

  async start() {
    this.stopped = false;
    await this._connect();
  }

  async _connect() {
    if (this.stopped) return;
    this._emit("connecting");

    let creds;
    try {
      creds = await api.webrtcToken();
    } catch (e) {
      this._emit("failed", e.message);
      this.handlers.onError?.(e.message);
      return;
    }

    if (!creds.ws_url || !creds.sip_username) {
      const msg = "전화 사업자가 접속 정보를 주지 않았습니다.";
      this._emit("failed", msg);
      this.handlers.onError?.(msg);
      return;
    }

    // 이전 등록이 남아 있으면 먼저 정리한다. 두 번 등록돼 있으면
    // 전화가 어느 쪽으로 갈지 알 수 없다.
    this._stopUA();

    const socket = new JsSIP.WebSocketInterface(creds.ws_url);
    this.ua = new JsSIP.UA({
      sockets: [socket],
      uri: `sip:${creds.sip_username}@${creds.realm}`,
      password: creds.sip_password,
      register: true,               // 받으려면 반드시 등록해야 한다
      session_timers: false,
    });

    this.iceServers = creds.ice_servers || [];

    this.ua.on("registered", () => this._emit("registered"));
    this.ua.on("unregistered", () => {
      if (!this.stopped) this._emit("connecting");
    });
    this.ua.on("registrationFailed", (e) => {
      const msg = `SIP 등록에 실패했습니다: ${e?.cause || "알 수 없는 이유"}`;
      this._emit("failed", msg);
      this.handlers.onError?.(msg);
    });

    this.ua.on("newRTCSession", ({ session, originator }) => {
      if (originator !== "remote") return;   // 발신은 서버가 만든다
      if (this.session) {
        // 이미 통화 중인데 또 왔다. 받을 수 없으니 정중히 거절한다.
        try {
          session.terminate({ status_code: 486 });   // Busy Here
        } catch {
          /* 이미 끊겼다 */
        }
        return;
      }
      this.session = session;
      this._bindSession(session);
      this._emit("ringing", session.remote_identity?.uri?.user || "");
      this.handlers.onIncoming?.(session.remote_identity?.uri?.user || "");
    });

    this.ua.start();
    this._scheduleRefresh(creds.expires_at);
  }

  _bindSession(session) {
    session.on("failed", () => this._clearSession("failed"));
    session.on("ended", () => this._clearSession("ended"));
    session.on("accepted", () => this._emit("in-call"));
    session.on("confirmed", () => this._emit("in-call"));

    // 상대 목소리를 오디오 요소에 붙인다. 이게 없으면 연결은 되는데
    // 아무 소리도 안 들린다.
    session.on("peerconnection", ({ peerconnection }) => {
      peerconnection.addEventListener("track", (ev) => {
        const [stream] = ev.streams;
        if (stream) this._ensureAudio().srcObject = stream;
      });
    });
  }

  _clearSession(why) {
    this.session = null;
    if (this.audio) this.audio.srcObject = null;
    this._emit(this.ua ? "registered" : "idle", why);
    this.handlers.onEnded?.(why);
    // 통화 중이라 미뤄둔 재등록이 있으면 지금 한다.
    if (this.pendingRefresh) {
      this.pendingRefresh = false;
      this._connect();
    }
  }

  /** 화면의 [받기] 가 부른다. */
  async answer() {
    if (!this.session) return false;
    this.session.answer({
      mediaConstraints: { audio: true, video: false },
      pcConfig: { iceServers: this.iceServers },
    });
    return true;
  }

  /** [거절] 과 [통화 종료] 가 같이 쓴다. 진행 단계에 따라 알아서 갈린다. */
  hangup() {
    if (!this.session) return false;
    try {
      this.session.terminate();
    } catch {
      /* 이미 끝났다 */
    }
    this.session = null;
    return true;
  }

  setMuted(muted) {
    if (!this.session) return;
    try {
      if (muted) this.session.mute({ audio: true });
      else this.session.unmute({ audio: true });
    } catch {
      /* 통화가 아직 붙지 않았다 */
    }
  }

  _scheduleRefresh(expiresAt) {
    clearTimeout(this.refreshTimer);
    const exp = expiresAt ? new Date(expiresAt).getTime() : 0;
    const life = exp ? exp - Date.now() : 0;
    const wait = Math.max(MIN_REFRESH_MS, (life > 0 ? life : 5 * 60 * 1000) * REFRESH_RATIO);
    this.refreshTimer = setTimeout(() => {
      if (this.stopped) return;
      if (this.session) {
        // 통화 중에 재등록하면 그 통화가 끊긴다. 끝난 뒤로 미룬다.
        this.pendingRefresh = true;
        this._scheduleRefresh(null);
        return;
      }
      this._connect();
    }, wait);
  }

  _stopUA() {
    if (this.ua) {
      try {
        this.ua.stop();
      } catch {
        /* 이미 멈췄다 */
      }
      this.ua = null;
    }
  }

  async stop() {
    this.stopped = true;
    clearTimeout(this.refreshTimer);
    this.hangup();
    this._stopUA();
    if (this.audio) {
      this.audio.remove();
      this.audio = null;
    }
    this._emit("idle");
    // 서버에도 등록을 지운다. 안 그러면 아무도 없는 주소로 전화가 돌아가
    // 고객이 20초를 헛되이 기다린다.
    await api.dropWebrtcToken().catch(() => {});
  }
}
