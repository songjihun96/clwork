import { useEffect, useState } from "react";
import { api } from "../api";
import { useCallCenter } from "../callcenter";
import { toUlaw8k } from "../ulaw";
import { Empty, Note } from "../components/ui";

/** 관리자 — 전화 설정.
 *
 *  순서를 바꾸는 화면이 가장 중요하다. 상담원 수는 늘 3명이 아니고,
 *  누가 먼저 받을지는 사람이 바뀔 때마다 달라진다. 그래서 순서를 코드가
 *  아니라 여기서 정한다.
 */

const STATUS_LABEL = {
  AVAILABLE: "상담 가능",
  BUSY: "통화 중",
  AWAY: "자리 비움",
  OFFLINE: "오프라인",
};

const STATUS_BADGE = { AVAILABLE: "done", BUSY: "stop", AWAY: "hold", OFFLINE: "flat" };

export default function PhoneSettings() {
  const [settings, setSettings] = useState(null);
  const [counselors, setCounselors] = useState([]);
  const [types, setTypes] = useState([]);
  const [opts, setOpts] = useState({ statuses: [], priorities: [] });
  const [snd, setSnd] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const cc = useCallCenter();

  const load = () => {
    api.phoneSettings().then(setSettings).catch((e) => setError(e.message));
    api.counselors().then((r) => setCounselors(r.items || [])).catch(() => {});
    api.inquiryTypes().then((r) => setTypes(r.items || [])).catch(() => {});
    api.consultationOptions().then(setOpts).catch(() => {});
    api.phoneSounds().then(setSnd).catch(() => {});
  };

  useEffect(load, []);

  const flash = (msg) => {
    setSaved(msg);
    setTimeout(() => setSaved(""), 2500);
  };

  if (!settings) return <Empty>불러오는 중…</Empty>;

  return (
    <>
      <div className="page-head">
        <h1>전화 설정</h1>
        <p>순차분배 순서와 응답 대기 시간을 정합니다.</p>
      </div>

      <Note kind="bad">{error}</Note>
      <Note kind="good">{saved}</Note>

      <ProviderCard settings={settings} />
      <RingCard settings={settings} onSaved={(s) => { setSettings(s); flash("저장했습니다."); }}
                onError={setError} />
      <OrderCard counselors={counselors} onChanged={(items) => { setCounselors(items); flash("순서를 바꿨습니다."); }}
                 onError={setError} />
      <TypesCard types={types} onChanged={() => { load(); flash("문의 유형을 저장했습니다."); }}
                 onError={setError} />
      <SoundsCard
        sounds={snd}
        onChanged={() => {
          api.phoneSounds().then(setSnd).catch(() => {});
          flash("소리를 저장했습니다.");
        }}
        onError={setError}
      />
      <ConsultationOptionsCard
        opts={opts}
        onSaved={(next) => {
          setOpts(next);
          // 다른 화면이 들고 있는 이름표도 함께 갈아 끼운다.
          cc?.reloadOptions?.();
          flash("상담 상태·우선순위를 저장했습니다.");
        }}
        onError={setError}
      />
    </>
  );
}

function ProviderCard({ settings }) {
  const caps = settings.provider_capabilities || {};
  const rows = [
    ["전화 수신", caps.inbound],
    ["전화 발신", caps.outbound],
    ["통화 전환", caps.transfer],
    ["통화 녹취", caps.recording],
    ["브라우저 음성(WebRTC)", caps.webrtc_audio],
  ];
  return (
    <div className="card">
      <h2>전화 사업자</h2>

      {settings.provider_error && (
        <Note kind="bad">
          <b>전화 기능이 멈춰 있습니다.</b> 서버가 뜰 때 전화 사업자 설정을 읽지
          못했습니다. 본 사이트는 정상 동작합니다.
          <div style={{ marginTop: 6, fontFamily: "monospace", fontSize: 12 }}>
            {settings.provider_error}
          </div>
          <div style={{ marginTop: 6 }}>
            서버의 <code>backend/.env</code> 를 고친 뒤{" "}
            <code>systemctl restart udt-backend</code> 를 실행하세요.
          </div>
        </Note>
      )}

      <dl className="kv">
        <dt>Provider</dt>
        <dd>
          <span className="badge flat">{settings.provider}</span>
          {settings.provider === "mock" && (
            <span className="tiny muted"> · 실제 전화망에 연결되어 있지 않습니다</span>
          )}
        </dd>
        <dt>녹취</dt><dd>{settings.recorder === "none" ? "사용 안 함" : settings.recorder}</dd>
      </dl>

      <table style={{ marginTop: 10 }}>
        <thead><tr><th>기능</th><th>지원</th></tr></thead>
        <tbody>
          {rows.map(([label, ok]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>
                <span className={`badge ${ok ? "done" : "flat"}`}>
                  {ok ? "가능" : "불가"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!caps.webrtc_audio && (
        <Note kind="warn">
          지금 사업자는 브라우저로 목소리를 전달하지 못합니다. 순차분배·상담기록·통계는
          그대로 쓸 수 있지만, 실제 통화는 전화 사업자를 연결한 뒤에 가능합니다.
          사업자는 코드가 아니라 서버의 <code>PHONE_PROVIDER</code> 환경변수로 바꿉니다.
        </Note>
      )}
    </div>
  );
}

function RingCard({ settings, onSaved, onError }) {
  const [form, setForm] = useState({
    ring_timeout_seconds: settings.ring_timeout_seconds,
    sequential_enabled: settings.sequential_enabled,
    queue_enabled: settings.queue_enabled,
    agent_dial_mode: settings.agent_dial_mode || "number",
  });
  const caps = settings.provider_capabilities || {};
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      onSaved(await api.savePhoneSettings({
        ...form,
        ring_timeout_seconds: Number(form.ring_timeout_seconds),
      }));
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>분배 규칙</h2>
      <div className="field" style={{ maxWidth: 260 }}>
        <label htmlFor="rt">응답 대기 시간(Ring Timeout)</label>
        <input id="rt" type="number" min={3} max={120}
               value={form.ring_timeout_seconds}
               onChange={(e) => setForm({ ...form, ring_timeout_seconds: e.target.value })} />
        <p className="tiny muted" style={{ margin: "4px 0 0" }}>
          이 시간 안에 받지 않으면 다음 상담원에게 넘어갑니다. 기본 20초.
        </p>
      </div>

      <label className="check">
        <input type="checkbox" checked={form.sequential_enabled}
               onChange={(e) => setForm({ ...form, sequential_enabled: e.target.checked })} />
        <span>
          순차분배 사용
          <span className="tiny muted"> — 끄면 가장 오래 쉰 상담원에게 먼저 갑니다</span>
        </span>
      </label>

      <label className="check">
        <input type="checkbox" checked={form.queue_enabled}
               onChange={(e) => setForm({ ...form, queue_enabled: e.target.checked })} />
        <span>
          대기열 사용
          <span className="tiny muted"> — 끄면 아무도 못 받을 때 바로 부재중 처리됩니다</span>
        </span>
      </label>

      <div className="field" style={{ maxWidth: 420, marginTop: 6 }}>
        <label htmlFor="dm">상담원을 무엇으로 부를까</label>
        <select id="dm" value={form.agent_dial_mode}
                onChange={(e) => setForm({ ...form, agent_dial_mode: e.target.value })}>
          <option value="number">상담원 휴대폰으로 건다</option>
          <option value="stream">상담원 PC로 받는다 (음성 중계 · 부가서비스 불필요)</option>
          <option value="sip">상담원 PC로 받는다 (SIP·WebRTC · 부가서비스 필요)</option>
        </select>
        <p className="tiny muted" style={{ margin: "6px 0 0" }}>
          {form.agent_dial_mode === "stream" ? (
            <>
              통화 음성을 우리 서버가 받아 상담원 PC 로 중계합니다. 전화 사업자
              부가서비스가 필요 없습니다. 대신 <b>음성 중계 서비스(udt-audio)가
              떠 있어야</b> 하고, 음질은 전화 수준(8kHz)입니다.
              상담원은 <code>/calls</code> 화면에서 전화를 받으면 됩니다.
            </>
          ) : form.agent_dial_mode === "number" ? (
            <>
              걸려온 전화를 아래 표의 <b>휴대폰 번호</b>로 돌립니다. 사업자 부가서비스
              없이 지금 바로 됩니다. 통화는 휴대폰으로 하고, 고객 정보와 상담 기록은
              이 화면에서 봅니다.
            </>
          ) : (
            <>
              상담원 PC 로 직접 연결합니다. 아래 표의 <b>내선(SIP 주소)</b> 을 씁니다.
              전화 사업자가 SIP 연결을 지원해야 하며, 지금 사업자는{" "}
              <b>{caps.webrtc_audio ? "지원합니다" : "아직 지원하지 않습니다"}</b>.
            </>
          )}
        </p>
      </div>

      <button className="btn go" onClick={save} disabled={busy} style={{ marginTop: 10 }}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

function OrderCard({ counselors, onChanged, onError }) {
  const [busy, setBusy] = useState(false);

  const move = async (index, delta) => {
    const next = [...counselors];
    const to = index + delta;
    if (to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    setBusy(true);
    try {
      const r = await api.setCounselorOrder(next.map((c) => c.id));
      onChanged(r.items || next);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggleCalls = async (c) => {
    setBusy(true);
    try {
      await api.updateCounselor(c.id, { accepts_calls: !c.accepts_calls });
      const r = await api.counselors();
      onChanged(r.items || []);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>상담원 순서</h2>
      <p className="tiny muted" style={{ marginTop: -4 }}>
        위에 있는 사람부터 전화를 받습니다. 상담원 수는 몇 명이든 됩니다.
        <br />
        <b>휴대폰 번호가 비어 있으면 그 사람은 건너뜁니다.</b> 전화가 실제로
        울리려면 위 &lsquo;분배 규칙&rsquo;에서 고른 방식에 맞는 칸이 채워져 있어야 합니다.
      </p>
      {counselors.length === 0 ? (
        <Empty>상담원이 없습니다.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: 40 }}>순서</th>
              <th>이름</th>
              <th>부서·직위</th>
              <th style={{ width: 150 }}>휴대폰</th>
              <th style={{ width: 130 }}>내선·SIP</th>
              <th>상태</th>
              <th>전화 받기</th>
              <th style={{ width: 96 }} />
            </tr>
          </thead>
          <tbody>
            {counselors.map((c, i) => (
              <tr key={c.id}>
                <td className="tiny muted">{i + 1}</td>
                <td>
                  {c.name}
                  {c.role === "admin" && (
                    <>
                      {" "}
                      <span className="badge flat">관리자</span>
                    </>
                  )}
                </td>
                <td className="tiny muted">
                  {[c.department, c.position].filter(Boolean).join(" · ") || "—"}
                </td>
                <td><ContactInput row={c} field="phone_number" placeholder="010-0000-0000"
                                  disabled={busy} onSaved={onChanged} onError={onError} /></td>
                <td><ContactInput row={c} field="extension" placeholder="101"
                                  disabled={busy} onSaved={onChanged} onError={onError} /></td>
                <td>
                  <span className={`badge ${STATUS_BADGE[c.availability_status]}`}>
                    {STATUS_LABEL[c.availability_status]}
                  </span>
                </td>
                <td>
                  <button className={`btn sm ${c.accepts_calls ? "primary" : ""}`}
                          disabled={busy} onClick={() => toggleCalls(c)}>
                    {c.accepts_calls ? "받음" : "제외"}
                  </button>
                </td>
                <td>
                  <div className="btn-row">
                    <button className="btn sm" disabled={busy || i === 0}
                            onClick={() => move(i, -1)} aria-label="위로">↑</button>
                    <button className="btn sm" disabled={busy || i === counselors.length - 1}
                            onClick={() => move(i, 1)} aria-label="아래로">↓</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** 표 안에서 바로 고치는 연락처 칸.
 *
 *  전화번호를 고치려고 다른 화면으로 보내지 않는다. 관리자가 세 명의 번호를
 *  한 번에 채워 넣는 일이 가장 흔하기 때문이다. 칸을 벗어날 때 저장한다. */
function ContactInput({ row, field, placeholder, disabled, onSaved, onError }) {
  const [value, setValue] = useState(row[field] || "");
  const [busy, setBusy] = useState(false);

  // 다른 관리자가 바꿨거나 순서를 옮겨 행이 바뀌면 화면 값도 따라간다.
  useEffect(() => {
    setValue(row[field] || "");
  }, [row.id, row[field], field]);

  const commit = async () => {
    const next = value.trim();
    if (next === (row[field] || "")) return;
    setBusy(true);
    try {
      await api.updateCounselor(row.id, { [field]: next });
      const r = await api.counselors();
      onSaved(r.items || []);
    } catch (e) {
      setValue(row[field] || "");
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <input
      value={value}
      placeholder={placeholder}
      disabled={disabled || busy}
      aria-label={`${row.name} ${field === "phone_number" ? "휴대폰" : "내선"}`}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      style={{
        width: "100%", padding: "4px 7px", fontSize: 12.5,
        border: "1px solid var(--line)", borderRadius: 6,
      }}
    />
  );
}

function TypesCard({ types, onChanged, onError }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const add = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.createInquiryType({ name: name.trim(), sort_order: (types.length + 1) * 10, is_active: true });
      setName("");
      onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (t) => {
    setBusy(true);
    try {
      await api.updateInquiryType(t.id, { ...t, is_active: !t.is_active });
      onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>문의 유형</h2>
      <p className="tiny muted" style={{ marginTop: -4 }}>
        지우지 않고 감춥니다. 지우면 지난 상담의 유형이 사라져 예전 통계를 다시 그릴 수 없습니다.
      </p>
      <div className="toolbar" style={{ marginTop: 10 }}>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="새 문의 유형" aria-label="새 문의 유형" />
        <button className="btn go" onClick={add} disabled={busy || !name.trim()}>추가</button>
      </div>
      {types.length === 0 ? (
        <Empty>문의 유형이 없습니다.</Empty>
      ) : (
        <table>
          <thead><tr><th>이름</th><th>표시</th><th /></tr></thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>
                  <span className={`badge ${t.is_active ? "done" : "flat"}`}>
                    {t.is_active ? "사용" : "숨김"}
                  </span>
                </td>
                <td>
                  <button className="btn sm" disabled={busy} onClick={() => toggle(t)}>
                    {t.is_active ? "숨기기" : "다시 쓰기"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** 상담 상태·우선순위.
 *
 *  코드값(NEW, COMPLETED …)은 못 바꾼다. 엔진과 통계가 그 값을 보고 판단하기
 *  때문이다. 바꿀 수 있는 것은 화면에 보이는 이름, 드롭다운 노출 여부,
 *  그리고 그 상태를 '미처리'로 셀지 여부다.
 */
function ConsultationOptionsCard({ opts, onSaved, onError }) {
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);

  const statuses = draft?.statuses || opts.statuses || [];
  const priorities = draft?.priorities || opts.priorities || [];

  const patch = (kind, code, key, value) => {
    const base = { statuses: [...statuses], priorities: [...priorities] };
    base[kind] = base[kind].map((o) => (o.code === code ? { ...o, [key]: value } : o));
    setDraft(base);
  };

  const save = async () => {
    setBusy(true);
    try {
      const next = await api.saveConsultationOptions({
        statuses: statuses.map((o) => ({
          code: o.code, label: o.label, is_active: o.is_active, is_open: o.is_open,
        })),
        priorities: priorities.map((o) => ({
          code: o.code, label: o.label, is_active: o.is_active,
        })),
      });
      setDraft(null);
      onSaved(next);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!statuses.length) return null;

  return (
    <div className="card">
      <h2>상담 상태 · 우선순위</h2>
      <p className="tiny muted" style={{ marginTop: -4 }}>
        이름과 사용 여부를 바꿉니다. 상태 자체를 새로 만들 수는 없습니다 —
        통계와 분배가 이 값을 보고 판단하기 때문입니다.
      </p>

      <h3 className="sub-head">상담 상태</h3>
      <table>
        <thead>
          <tr>
            <th style={{ width: 130 }}>코드</th>
            <th>화면에 보일 이름</th>
            <th style={{ width: 90 }}>사용</th>
            <th style={{ width: 110 }}>미처리로 셈</th>
          </tr>
        </thead>
        <tbody>
          {statuses.map((o) => (
            <tr key={o.code}>
              <td className="tiny muted">{o.code}</td>
              <td>
                <input
                  value={o.label}
                  aria-label={`${o.code} 이름`}
                  onChange={(e) => patch("statuses", o.code, "label", e.target.value)}
                  style={{ width: "100%", padding: "5px 8px", border: "1px solid var(--line)",
                           borderRadius: 6 }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={o.is_active}
                  disabled={o.locked}
                  aria-label={`${o.code} 사용`}
                  onChange={(e) => patch("statuses", o.code, "is_active", e.target.checked)}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={o.is_open}
                  disabled={o.code === "COMPLETED"}
                  aria-label={`${o.code} 미처리`}
                  onChange={(e) => patch("statuses", o.code, "is_open", e.target.checked)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tiny muted" style={{ marginTop: 6 }}>
        완료는 언제나 처리된 것으로 봅니다. 끝난 상담이 미처리 목록에 영원히
        남으면 아무도 그 숫자를 보지 않게 됩니다.
      </p>

      <h3 className="sub-head">우선순위</h3>
      <table>
        <thead>
          <tr>
            <th style={{ width: 130 }}>코드</th>
            <th>화면에 보일 이름</th>
            <th style={{ width: 90 }}>사용</th>
          </tr>
        </thead>
        <tbody>
          {priorities.map((o) => (
            <tr key={o.code}>
              <td className="tiny muted">{o.code}</td>
              <td>
                <input
                  value={o.label}
                  aria-label={`${o.code} 이름`}
                  onChange={(e) => patch("priorities", o.code, "label", e.target.value)}
                  style={{ width: "100%", padding: "5px 8px", border: "1px solid var(--line)",
                           borderRadius: 6 }}
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={o.is_active}
                  disabled={o.locked}
                  aria-label={`${o.code} 사용`}
                  onChange={(e) => patch("priorities", o.code, "is_active", e.target.checked)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button className="btn go" onClick={save} disabled={busy || !draft}
              style={{ marginTop: 12 }}>
        {busy ? "저장 중…" : "저장"}
      </button>
    </div>
  );
}

/** 전화 소리.
 *
 *  누가 듣는 소리인지로 갈라 놓았다. 이걸 헷갈리면 고객에게 상담원 벨소리가
 *  나가는 사고가 난다.
 */
const SOUND_ROWS = [
  {
    kind: "ring",
    title: "수신 벨소리",
    who: "상담원이 듣습니다",
    desc: "전화가 걸려오면 상담원 PC 에서 납니다. 올리지 않으면 기본 벨소리가 납니다.",
  },
  {
    kind: "dial",
    title: "발신음",
    who: "상담원이 듣습니다",
    desc: "전화를 걸고 상대가 받기 전까지 상담원 PC 에서 납니다. 올리지 않으면 기본 발신음이 납니다.",
  },
  {
    kind: "hold",
    title: "대기음",
    who: "고객이 듣습니다",
    desc: "고객이 상담원 연결을 기다리는 동안 들립니다. 음성 중계 모드에서만 쓰입니다. "
        + "전화망에 맞춰 8kHz 로 바꿔 올라가므로 음질은 통화 수준입니다.",
  },
];

function SoundsCard({ sounds, onChanged, onError }) {
  const [busy, setBusy] = useState("");

  if (!sounds) return null;

  const pick = async (kind, file) => {
    if (!file) return;
    setBusy(kind);
    try {
      if (kind === "hold") {
        // 전화망으로 나갈 소리라 8kHz μ-law 여야 한다. 브라우저가 바꾼다.
        // 서버 파이썬 버전에 기대지 않기 위해서다.
        const { blob, seconds } = await toUlaw8k(file, 90);
        if (seconds < 0.5) throw new Error("소리가 너무 짧습니다.");
        await api.uploadPhoneSound(kind, blob, "hold.ulaw");
      } else {
        await api.uploadPhoneSound(kind, file, file.name);
      }
      onChanged();
    } catch (e) {
      onError(e.message || "소리를 올리지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  const remove = async (kind) => {
    setBusy(kind);
    try {
      await api.deletePhoneSound(kind);
      onChanged();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="card">
      <h2>전화 소리</h2>
      <p className="tiny muted" style={{ marginTop: -4 }}>
        mp3·m4a·wav 를 올릴 수 있습니다. 올리지 않으면 기본 소리가 납니다 —
        <b> 소리가 아예 안 나는 상태는 없습니다.</b> 전화를 놓치면 안 되니까요.
      </p>

      <table>
        <thead>
          <tr>
            <th style={{ width: 150 }}>소리</th>
            <th>설명</th>
            <th style={{ width: 130 }}>지금</th>
            <th style={{ width: 190 }} />
          </tr>
        </thead>
        <tbody>
          {SOUND_ROWS.map((row) => {
            const cur = sounds[row.kind] || {};
            return (
              <tr key={row.kind}>
                <td>
                  <div style={{ fontWeight: 600 }}>{row.title}</div>
                  <div className="tiny" style={{ color: "var(--signal-deep)" }}>{row.who}</div>
                </td>
                <td className="tiny muted">{row.desc}</td>
                <td>
                  {cur.exists ? (
                    <span className="badge done">
                      {row.kind === "hold" ? `${cur.seconds}초` : "올림"}
                    </span>
                  ) : (
                    <span className="badge flat">기본 소리</span>
                  )}
                </td>
                <td>
                  <div className="btn-row">
                    <label className="btn sm" style={{ cursor: "pointer", margin: 0 }}>
                      {busy === row.kind ? "처리 중…" : "파일 선택"}
                      <input
                        type="file"
                        accept="audio/*"
                        style={{ display: "none" }}
                        disabled={!!busy}
                        onChange={(e) => {
                          pick(row.kind, e.target.files?.[0]);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    {cur.exists && (
                      <button className="btn sm danger" disabled={!!busy}
                              onClick={() => remove(row.kind)}>
                        기본으로
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
