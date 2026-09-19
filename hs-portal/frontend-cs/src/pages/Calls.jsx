import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  activeOptions, fmtDuration, useAudioPhone, useCallCenter, useElapsed,
  useMicrophone, useRinger, useSipPhone,
} from "../callcenter";
import { Empty, Modal, Note, fmtDateTime } from "../components/ui";

/** 상담원 콜 콘솔.
 *
 *  전화가 울리는 20초 안에 상담원이 해야 할 일은 하나다 — 받는 것.
 *  그래서 벨이 울리면 다른 것은 다 밀어내고 [받기]/[거절]만 크게 보여준다.
 *  고객 정보는 그다음이다.
 */

const STATUS_LABEL = {
  AVAILABLE: "상담 가능",
  BUSY: "통화 중",
  AWAY: "자리 비움",
  OFFLINE: "오프라인",
};

const CUSTOMER_TYPE_LABEL = {
  STUDENT: "학생·학부모",
  TEACHER: "교사",
  SCHOOL: "학교",
  OTHER: "기타",
};

export default function Calls() {
  const { user } = useAuth();
  const cc = useCallCenter();
  const mic = useMicrophone();
  // 연결 방식에 따라 브라우저 전화기가 달라진다.
  //   sip    : 사업자 SIP 게이트웨이에 미리 등록해 두고 받는다
  //   stream : 받는 순간 우리 서버에 붙어 음성을 주고받는다(부가서비스 불필요)
  //   number : 브라우저는 전화기가 아니다. 휴대폰이 울린다
  const dialMode = cc.settings?.agent_dial_mode || "number";
  const sip = useSipPhone(dialMode === "sip" && !!cc.settings?.audio_ready);
  const audio = useAudioPhone(dialMode === "stream");

  // 수신이면 벨소리, 발신이면 발신음. 통화가 붙으면 멎는다.
  useRinger({
    ringing: !!cc.ringing,
    outbound: !!cc.outbound,
    inCall: !!cc.inCall,
  });
  const [types, setTypes] = useState([]);
  const [testOpen, setTestOpen] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.inquiryTypes().then((r) => setTypes(r.items || [])).catch(() => {});
  }, []);

  // 통화 중 > 걸려온 전화 > 내가 건 전화 순으로 가운데 화면을 차지한다.
  const focus = cc.inCall || cc.ringing || cc.outbound || null;
  const isMock = cc.settings?.provider === "mock";
  const audioReady = cc.settings?.audio_ready;

  // 발신 통화는 상대가 받아야 음성 다리가 생긴다. 그때 붙는다.
  // 수신은 [받기] 에서 이미 붙지만, 새로고침으로 끊긴 경우도 여기서 되살아난다.
  useEffect(() => {
    if (dialMode !== "stream") return;
    if (cc.inCall && audio.state === "idle") audio.begin(cc.inCall.id);
    if (!cc.inCall && audio.state !== "idle") audio.stop();
    // 의존 목록에 audio 객체 자체를 넣지 않는다. 매 렌더마다 새로 만들어져
    // 통화 중에 음성이 끊겼다 붙기를 되풀이한다. 통화 번호와 상태만 본다.
  }, [dialMode, cc.inCall?.id, audio.state]);

  const act = async (fn) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>전화 상담</h1>
        <p>
          걸려온 번호로 고객을 자동으로 찾습니다. 통화가 끝나기 전에 상담 내용을 저장하세요.
        </p>
      </div>

      <Note kind="bad">{error}</Note>

      {audioReady === false && (
        <Note kind="warn">
          지금 전화 사업자({cc.settings?.provider})는 브라우저 음성 연결을 제공하지 않습니다.
          분배·기록·화면은 실제와 똑같이 동작하지만 <b>목소리는 오가지 않습니다.</b>{" "}
          실제 통화는 전화 사업자를 연결한 뒤에 가능합니다.
        </Note>
      )}

      <CounselorBar cc={cc} user={user} mic={mic} sip={sip} audio={audio} />

      {cc.ringing && (
        <IncomingCall
          call={cc.ringing}
          onAnswer={() => act(async () => {
            // 음성을 먼저 잇고 기록을 남긴다. 순서가 바뀌면 화면에는
            // 통화 중인데 소리는 안 들리는 순간이 생긴다.
            // 음성을 먼저 잇고 기록을 남긴다. 순서가 바뀌면 화면에는
            // 통화 중인데 소리는 안 들리는 순간이 생긴다.
            const id = cc.ringing.id;
            if (sip.ringing) await sip.answer();
            else if (dialMode === "stream") await audio.begin(id);
            else if (!mic.ready) await mic.start();
            await cc.answer(id);
          })}
          onReject={() => act(async () => {
            if (sip.ringing) sip.hangup();
            audio.stop();
            await cc.reject(cc.ringing.id);
          })}
        />
      )}

      {cc.outbound && !cc.ringing && (
        <OutgoingCall
          call={cc.outbound}
          isMock={isMock}
          onHangup={() => act(() => cc.hangup(cc.outbound.id))}
          onMockAnswered={() => act(async () => {
            await api.mockAnswered(cc.outbound.id);
            await cc.refresh();
          })}
        />
      )}

      <div className="console">
        <section className="console-col">
          <h2>대기 중</h2>
          <QueuePanel cc={cc} />
          {isMock && (
            <button className="btn go" style={{ width: "100%", marginTop: 12 }}
                    onClick={() => setTestOpen(true)}>
              테스트 전화 걸기
            </button>
          )}
          {isMock && (
            <p className="tiny muted" style={{ marginTop: 8 }}>
              실제 전화망 대신 Mock Provider 로 돌고 있습니다. 순차분배·대기열·기록은
              실제와 동일하게 동작합니다.
            </p>
          )}
        </section>

        <section className="console-col wide">
          <h2>고객 정보</h2>
          {focus ? (
            <CustomerPanel call={focus} />
          ) : (
            <Empty>전화가 오면 발신번호로 고객을 찾아 여기에 보여줍니다.</Empty>
          )}
        </section>

        <section className="console-col wide">
          <h2>상담 기록</h2>
          {focus ? (
            <ConsultationForm call={focus} types={types} sip={sip} audio={audio}
                              onSaved={cc.refresh} />
          ) : (
            <Empty>통화가 시작되면 여기에 상담 내용을 적습니다.</Empty>
          )}
        </section>
      </div>

      {testOpen && (
        <TestCallModal onClose={() => setTestOpen(false)} onDone={() => {
          setTestOpen(false);
          cc.refresh();
        }} />
      )}
    </>
  );
}

/** 상단 바 — 내 상태, 통화 시간, 마이크. */
function CounselorBar({ cc, user, mic, sip, audio }) {
  const elapsed = useElapsed(cc.inCall?.answered_at || null);
  const [busy, setBusy] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);

  const change = async (status) => {
    setBusy(true);
    try {
      await cc.setStatus(status);
      if (status === "AVAILABLE" && !mic.ready) await mic.start();
      if (status === "OFFLINE") mic.stop();
    } finally {
      setBusy(false);
    }
  };

  const status = cc.me?.availability_status || "OFFLINE";

  return (
    <div className="callbar">
      <div className="callbar-who">
        <strong>{user?.name}</strong>
        <span className={`live ${cc.connected ? "on" : "off"}`}>
          <span className="dot" />
          {cc.connected ? "실시간 연결됨" : "연결 끊김 — 다시 붙는 중"}
        </span>
      </div>

      <div className="btn-row">
        {["AVAILABLE", "AWAY", "OFFLINE"].map((s) => (
          <button
            key={s}
            className={`btn sm ${status === s ? "primary" : ""}`}
            disabled={busy || status === "BUSY"}
            onClick={() => change(s)}
          >
            {STATUS_LABEL[s]}
          </button>
        ))}
        {status === "BUSY" && <span className="badge stop">통화 중</span>}
      </div>

      <span className="spacer" />

      <div className="mic">
        {audio?.state && audio.state !== "idle" && (
          <span className={`badge ${audio.inCall ? "done" : audio.state === "failed" ? "stop" : "hold"}`}
                title="브라우저 통화 상태">
            {audio.inCall ? "음성 연결됨"
              : audio.state === "failed" ? "음성 연결 실패" : "음성 연결 중"}
          </span>
        )}
        {sip?.state && sip.state !== "idle" && (
          <span className={`badge ${sip.ready ? "done" : sip.state === "failed" ? "stop" : "hold"}`}
                title="브라우저 전화기 상태">
            {sip.ready ? "전화기 준비됨"
              : sip.state === "failed" ? "전화기 연결 실패"
              : "전화기 연결 중"}
          </span>
        )}
        {mic.ready ? (
          <>
            <button
              className={`btn sm ${mic.muted ? "danger" : ""}`}
              onClick={() => {
                mic.toggleMute();
                // 통화 중이면 실제 음성도 함께 끊는다. 화면만 음소거로
                // 바뀌고 목소리는 계속 가면 사고가 된다.
                sip?.setMuted(!mic.muted);
                audio?.setMuted(!mic.muted);
              }}
            >
              {mic.muted ? "음소거 해제" : "음소거"}
            </button>
            <span className="meter" title="마이크 입력 크기">
              <span style={{ width: `${mic.muted ? 0 : mic.level}%` }} />
            </span>
          </>
        ) : (
          <button className="btn sm" onClick={mic.start}>마이크 켜기</button>
        )}
      </div>

      {cc.inCall && (
        <div className="timer">
          <span className="tiny muted">통화 시간</span>
          <strong>{fmtDuration(elapsed)}</strong>
          <button className="btn sm" onClick={() => setTransferOpen(true)}>
            돌리기
          </button>
          <button className="btn sm danger" onClick={() => {
            sip?.hangup();
            audio?.stop();
            cc.hangup(cc.inCall.id);
          }}>
            통화 종료
          </button>
        </div>
      )}

      {mic.error && <span className="tiny" style={{ color: "var(--danger)" }}>{mic.error}</span>}
      {sip?.error && <span className="tiny" style={{ color: "var(--danger)" }}>{sip.error}</span>}
      {audio?.error && <span className="tiny" style={{ color: "var(--danger)" }}>{audio.error}</span>}

      {transferOpen && cc.inCall && (
        <TransferModal
          call={cc.inCall}
          onClose={() => setTransferOpen(false)}
          onDone={() => {
            setTransferOpen(false);
            cc.refresh();
            cc.refreshMe();
          }}
        />
      )}
    </div>
  );
}

/** 벨이 울리는 동안 가장 크게 보여야 할 것. */
function IncomingCall({ call, onAnswer, onReject }) {
  const [customer, setCustomer] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let alive = true;
    api.lookupCustomer(call.phone_number)
      .then((r) => alive && setCustomer(r.found ? r.customer : null))
      .catch(() => {})
      .finally(() => alive && setChecked(true));
    return () => {
      alive = false;
    };
  }, [call.phone_number]);

  return (
    <div className="incoming">
      <div className="incoming-mark">☎ 전화가 왔습니다</div>
      <div className="incoming-no">{call.phone_number}</div>
      <div className="incoming-who">
        {!checked ? (
          <span className="muted">고객을 찾는 중…</span>
        ) : customer ? (
          <>
            <strong>{customer.name || "이름 미등록"}</strong>
            {customer.school_name && <span> · {customer.school_name}</span>}
            <span> · {CUSTOMER_TYPE_LABEL[customer.customer_type] || "기타"}</span>
          </>
        ) : (
          <span className="badge wait">신규 고객입니다</span>
        )}
      </div>
      <div className="incoming-act">
        <button className="btn go big" onClick={onAnswer}>받기</button>
        <button className="btn big" onClick={onReject}>거절</button>
      </div>
    </div>
  );
}

/** 내가 건 전화. 받는 전화와 생김새를 달리해야 헷갈리지 않는다. */
function OutgoingCall({ call, isMock, onHangup, onMockAnswered }) {
  const elapsed = useElapsed(call.started_at);

  return (
    <div className="outgoing">
      <div className="outgoing-mark">↗ 전화를 거는 중</div>
      <div className="incoming-no">{call.phone_number}</div>
      <div className="incoming-who">
        {call.customer_name ? <strong>{call.customer_name}</strong> : <span className="muted">고객 미등록</span>}
        <span className="tiny muted"> · 발신 {fmtDuration(elapsed)}</span>
      </div>
      <div className="incoming-act">
        {isMock && (
          <button className="btn" onClick={onMockAnswered} title="Mock Provider 에서만 보입니다">
            상대가 받음(테스트)
          </button>
        )}
        <button className="btn danger big" onClick={onHangup}>발신 취소</button>
      </div>
      {isMock && (
        <p className="tiny muted" style={{ margin: "8px 0 0" }}>
          Mock 에는 받을 상대가 없습니다. [상대가 받음]을 눌러야 통화 시간이 돌고
          상담 기록을 남기는 흐름을 확인할 수 있습니다.
        </p>
      )}
    </div>
  );
}

/** 통화를 다른 상담원에게 넘긴다.
 *
 *  지금 [상담 가능] 인 사람만 고를 수 있게 한다. 자리 비운 사람에게 넘기면
 *  고객은 20초를 더 기다린 뒤 다시 대기열로 돌아간다. */
function TransferModal({ call, onClose, onDone }) {
  const cc = useCallCenter();
  const [list, setList] = useState([]);
  const [target, setTarget] = useState("");
  const [external, setExternal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canExternal = !!cc.settings?.provider_capabilities?.transfer;

  useEffect(() => {
    api.counselors()
      .then((r) => setList((r.items || []).filter(
        (c) => c.id !== cc.me?.id && c.availability_status === "AVAILABLE"
      )))
      .catch(() => {});
  }, [cc.me?.id]);

  const go = async () => {
    if (!target && !external.trim()) {
      setError("넘길 상담원이나 번호를 고르세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.transferCall(call.id, target
        ? { counselor_id: Number(target) }
        : { phone_number: external.trim() });
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="통화 돌리기"
      sub={`${call.phone_number} · 넘기면 내 상태는 바로 상담 가능으로 돌아갑니다`}
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>취소</button>
          <button className="btn go" onClick={go} disabled={busy}>
            {busy ? "돌리는 중…" : "돌리기"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>

      <div className="field">
        <label htmlFor="tr-target">상담원에게</label>
        <select id="tr-target" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">선택 안 함</option>
          {list.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}{c.department ? ` · ${c.department}` : ""}
            </option>
          ))}
        </select>
        {list.length === 0 && (
          <p className="tiny muted" style={{ margin: "4px 0 0" }}>
            지금 [상담 가능] 인 다른 상담원이 없습니다.
          </p>
        )}
      </div>

      {canExternal && (
        <div className="field">
          <label htmlFor="tr-ext">또는 외부 번호로</label>
          <input id="tr-ext" value={external} onChange={(e) => setExternal(e.target.value)}
                 placeholder="02-1234-5678" disabled={!!target} />
          <p className="tiny muted" style={{ margin: "4px 0 0" }}>
            외부로 넘기면 우리 쪽 통화는 거기서 끝난 것으로 기록됩니다.
          </p>
        </div>
      )}
    </Modal>
  );
}

/** 왼쪽 — 대기열과 다른 상담원의 통화. */
function QueuePanel({ cc }) {
  if (!cc.calls.length) return <Empty>대기 중인 전화가 없습니다.</Empty>;
  return (
    <ul className="calllist">
      {cc.calls.map((c) => (
        <li key={c.id} className={c.session_state === "QUEUED" ? "queued" : ""}>
          <div className="no">{c.phone_number}</div>
          <div className="tiny muted">
            {/* 발신은 '몇 번째로 호출 중'이라는 말이 성립하지 않는다.
                같은 문구를 쓰면 내가 건 전화가 남이 안 받은 전화로 보인다.
                단, 발신을 다른 상담원에게 돌린 뒤에는 진짜로 그 사람에게
                벨이 울리고 있는 것이므로(담당자가 비워진다) 호출로 적는다. */}
            {c.direction === "OUTBOUND" && c.counselor_id
              ? c.session_state === "ANSWERED"
                ? `통화 중(발신) · ${c.counselor_name || "—"}`
                : `발신 중 · ${c.counselor_name || "—"}`
              : c.session_state === "QUEUED"
              ? `대기열 · ${fmtDateTime(c.queued_at)}`
              : c.session_state === "ANSWERED"
              ? `통화 중 · ${c.counselor_name || "—"}`
              : `호출 중 · ${c.counselor_name || "—"} (${c.ring_step}번째)`}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** 가운데 — 고객 정보. 없으면 그 자리에서 등록한다. */
function CustomerPanel({ call }) {
  const [state, setState] = useState({ loading: true, found: false, customer: null, stats: null });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", customer_type: "STUDENT", school_name: "", email: "" });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await api.lookupCustomer(call.phone_number);
      setState({
        loading: false,
        found: r.found,
        customer: r.customer,
        stats: r.found
          ? {
              consultation_count: r.consultation_count,
              open_consultation_count: r.open_consultation_count,
              last_consulted_at: r.last_consulted_at,
              call_count: r.call_count,
            }
          : null,
      });
    } catch (e) {
      setError(e.message);
      setState({ loading: false, found: false, customer: null, stats: null });
    }
  }, [call.phone_number]);

  useEffect(() => {
    load();
  }, [load]);

  const register = async () => {
    setSaving(true);
    setError("");
    try {
      const created = await api.createCustomer({
        ...form,
        phone_number: call.phone_number,
        school_id: null,
        memo: "",
      });
      // 이 통화가 어느 고객의 것이었는지 남긴다. 안 이으면 통화 이력이 뜬다.
      await api.linkCallCustomer(call.id, created.id).catch(() => {});
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (state.loading) return <Empty>불러오는 중…</Empty>;

  if (!state.found) {
    return (
      <>
        <Note kind="warn">신규 고객입니다. 지금 등록하면 다음 전화부터 바로 뜹니다.</Note>
        <Note kind="bad">{error}</Note>
        <div className="field">
          <label>전화번호</label>
          <div className="masked">{call.phone_number}</div>
        </div>
        <div className="field">
          <label htmlFor="nc-name">이름</label>
          <input id="nc-name" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="grid2">
          <div className="field">
            <label htmlFor="nc-type">고객 유형</label>
            <select id="nc-type" value={form.customer_type}
                    onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
              {Object.entries(CUSTOMER_TYPE_LABEL).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="nc-school">학교</label>
            <input id="nc-school" value={form.school_name}
                   onChange={(e) => setForm({ ...form, school_name: e.target.value })} />
          </div>
        </div>
        <button className="btn primary" onClick={register} disabled={saving}>
          {saving ? "등록 중…" : "고객 등록"}
        </button>
      </>
    );
  }

  const c = state.customer;
  return (
    <>
      <div className="cust-head">
        <strong>{c.name || "이름 미등록"}</strong>
        <span className="badge flat">{CUSTOMER_TYPE_LABEL[c.customer_type] || "기타"}</span>
      </div>
      <dl className="kv">
        <dt>전화</dt><dd>{c.phone_number}</dd>
        <dt>학교</dt><dd>{c.school_name || "—"}</dd>
        <dt>이메일</dt><dd>{c.email || "—"}</dd>
        <dt>상담 횟수</dt><dd>{state.stats?.consultation_count ?? 0}회</dd>
        <dt>미처리</dt>
        <dd>
          {state.stats?.open_consultation_count
            ? <span className="badge wait">{state.stats.open_consultation_count}건</span>
            : "없음"}
        </dd>
        <dt>최근 상담</dt><dd>{fmtDateTime(state.stats?.last_consulted_at)}</dd>
      </dl>
      {c.memo && <div className="note info" style={{ marginTop: 10 }}>{c.memo}</div>}
      <RecentConsultations customerId={c.id} />
    </>
  );
}

function RecentConsultations({ customerId }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.customerConsultations(customerId, { limit: 5, offset: 0 })
      .then((r) => setItems(r.items || []))
      .catch(() => {});
  }, [customerId]);

  if (!items.length) return null;
  return (
    <>
      <h3 className="sub-head">최근 상담</h3>
      <ul className="minilist">
        {items.map((x) => (
          <li key={x.id}>
            <span className="tiny muted">{fmtDateTime(x.created_at)}</span>
            <span>{x.subject || "제목 없음"}</span>
            <span className="tiny muted">{x.inquiry_type_name || "미분류"}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** 오른쪽 — 상담 내용. 통화 중에 적고 저장한다. */
function ConsultationForm({ call, types, sip, audio, onSaved }) {
  // 상태·우선순위의 이름과 목록은 관리자가 정한다(전화 설정 화면).
  const cc = useCallCenter();
  const statuses = activeOptions(cc.options?.statuses);
  const priorities = activeOptions(cc.options?.priorities);
  const [form, setForm] = useState({
    subject: "", content: "", result: "",
    inquiry_type_id: "", status: "RECEIVED", priority: "NORMAL",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  // 다른 전화로 넘어가면 앞 통화의 메모가 남아 있으면 안 된다.
  useEffect(() => {
    setForm({ subject: "", content: "", result: "",
              inquiry_type_id: "", status: "RECEIVED", priority: "NORMAL" });
    setSaved("");
    setError("");
  }, [call.id]);

  const save = async (finish) => {
    if (!form.content.trim()) {
      setError("상담 내용을 적어주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createConsultation({
        customer_id: call.customer_id || null,
        call_log_id: call.id,
        channel: "PHONE",
        inquiry_type_id: form.inquiry_type_id ? Number(form.inquiry_type_id) : null,
        subject: form.subject.trim(),
        content: form.content.trim(),
        result: form.result.trim(),
        status: finish ? "COMPLETED" : form.status,
        priority: form.priority,
      });
      setSaved("상담이 저장되었습니다.");
      if (finish) {
        sip?.hangup();
        audio?.stop();
        await api.hangupCall(call.id).catch(() => {});
      }
      onSaved?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Note kind="bad">{error}</Note>
      <Note kind="good">{saved}</Note>

      <div className="field">
        <label htmlFor="cf-subject">제목</label>
        <input id="cf-subject" value={form.subject}
               onChange={(e) => setForm({ ...form, subject: e.target.value })}
               placeholder="예: 로그인 문의" />
      </div>

      <div className="grid2">
        <div className="field">
          <label htmlFor="cf-type">문의 유형</label>
          <select id="cf-type" value={form.inquiry_type_id}
                  onChange={(e) => setForm({ ...form, inquiry_type_id: e.target.value })}>
            <option value="">선택 안 함</option>
            {types.filter((t) => t.is_active).map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="cf-pri">우선순위</label>
          <select id="cf-pri" value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: e.target.value })}>
            {priorities.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div className="field">
        <label htmlFor="cf-content">상담 내용</label>
        <textarea id="cf-content" value={form.content}
                  onChange={(e) => setForm({ ...form, content: e.target.value })}
                  placeholder="고객이 말한 내용을 그대로 적습니다." />
      </div>

      <div className="field">
        <label htmlFor="cf-result">처리 결과</label>
        <textarea id="cf-result" value={form.result}
                  onChange={(e) => setForm({ ...form, result: e.target.value })}
                  placeholder="어떻게 안내했는지 적습니다." />
      </div>

      <div className="field">
        <label htmlFor="cf-status">상담 상태</label>
        <select id="cf-status" value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}>
          {statuses.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
        </select>
      </div>

      <div className="btn-row">
        <button className="btn primary" onClick={() => save(false)} disabled={busy}>저장</button>
        <button className="btn go" onClick={() => save(true)} disabled={busy}>
          저장하고 통화 종료
        </button>
      </div>
    </>
  );
}

/** 실제 전화 없이 순차분배를 확인하는 문. Mock Provider 일 때만 열린다. */
function TestCallModal({ onClose, onDone }) {
  const [phone, setPhone] = useState("010-1234-5678");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const go = async () => {
    setBusy(true);
    setError("");
    try {
      await api.mockIncoming(phone);
      onDone();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="테스트 전화 걸기"
      sub="실제 전화망을 쓰지 않고, 순차분배부터 기록까지 똑같이 돌려봅니다."
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>닫기</button>
          <button className="btn go" onClick={go} disabled={busy}>
            {busy ? "거는 중…" : "전화 수신"}
          </button>
        </>
      }
    >
      <Note kind="bad">{error}</Note>
      <div className="field">
        <label htmlFor="tc-phone">발신번호</label>
        <input id="tc-phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <p className="tiny muted" style={{ margin: "4px 0 0" }}>
          이미 등록된 고객 번호를 넣으면 고객 정보가 뜨고, 새 번호를 넣으면
          신규 고객 등록 화면이 뜹니다.
        </p>
      </div>
    </Modal>
  );
}
