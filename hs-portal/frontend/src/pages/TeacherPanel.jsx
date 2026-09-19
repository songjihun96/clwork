import { useEffect, useState } from "react";
import ClassPicker, { formatClass, parseClass } from "../components/ClassPicker";
import CategoryBrowser from "../components/CategoryBrowser";
import { api } from "../api";
import { useAuth } from "../auth";
import { errMsg, okMsg } from "../toast";

/** 선생님 전용 화면. 학교가 발급한 계정으로 로그인해 사용한다. */
export default function TeacherPanel() {
  const { user } = useAuth();
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("students");
  const [students, setStudents] = useState([]);
  const [pending, setPending] = useState([]);

  const load = () => {
    api.teacherMe().then(setMe).catch(() => {});
    api.teacherStudents().then(setStudents).catch(() => {});
    api.teacherVerifications().then((v) => setPending(v.filter((x) => x.status === "pending"))).catch(() => {});
  };

  useEffect(() => {
    if (user?.role === "teacher") load();
  }, [user]);

  if (!user) {
    return <div className="wrap" style={{ padding: "40px 0" }}><div className="empty"><p>로그인이 필요합니다.</p></div></div>;
  }
  if (user.role !== "teacher") {
    return <div className="wrap" style={{ padding: "40px 0" }}><div className="empty"><p>선생님 계정에서만 사용할 수 있습니다.</p></div></div>;
  }
  if (!me) {
    return <div className="wrap" style={{ padding: "40px 0" }}><div className="empty"><p>불러오는 중…</p></div></div>;
  }

  return (
    <div className="wrap" style={{ padding: "34px 0 60px" }}>
      <span className="label">{me.school_name}</span>
      <h1 style={{ fontSize: 26, margin: "8px 0 4px" }}>
        {me.name} 선생님 {me.class_name && <span style={{ fontSize: 16, color: "var(--steel)" }}>· {me.class_name}</span>}
      </h1>

      <div className="tabs" style={{ margin: "18px 0" }}>
        <button className={`tab ${tab === "students" ? "active" : ""}`} onClick={() => setTab("students")}>학급 학생 ({students.length})</button>
        <button className={`tab ${tab === "verify" ? "active" : ""}`} onClick={() => setTab("verify")}>
          재학생 인증{pending.length > 0 ? ` (${pending.length})` : ""}
        </button>
        <button className={`tab ${tab === "account" ? "active" : ""}`} onClick={() => setTab("account")}>내 계정</button>
      </div>

      {tab === "students" && <StudentsTab me={me} students={students} reload={load} />}
      {tab === "verify" && <VerifyTab me={me} reload={load} />}
      {tab === "account" && <AccountTab me={me} onChanged={load} />}
    </div>
  );
}

/* ---------------- 학급 학생 관리 ---------------- */
function StudentsTab({ me, students, reload }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [target, setTarget] = useState(null);
  const [cls, setCls] = useState(parseClass(me.class_name));
  const [scope, setScope] = useState("mine");
  const [rows, setRows] = useState(students);
  // 학급 이관용. 고른 학생과 옮겨갈 학급.
  const [picked, setPicked] = useState([]);
  const [options, setOptions] = useState(null);
  const [moveTo, setMoveTo] = useState("");
  const [moving, setMoving] = useState(false);

  useEffect(() => {
    api.teacherStudents(scope).then(setRows).catch(() => setRows([]));
    setPicked([]);   // 목록이 바뀌면 고른 것을 비운다
  }, [scope, students]);

  useEffect(() => {
    api.classOptions().then(setOptions).catch(() => {});
  }, []);

  const toggle = (id) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  // 옮길 수 있는 학생만 고를 수 있게 한다. 선생님은 자기 학생만이다.
  const movable = rows.filter((s) => me.role === "school" || s.is_mine);
  const allPicked = movable.length > 0 && picked.length === movable.length;

  const move = async () => {
    if (!moveTo || picked.length === 0) return;
    const opt = options.options.find((o) => o.class_name === moveTo);
    if (!window.confirm(
      `${picked.length}명을 ${moveTo}(${opt?.teacher_name} 선생님)으로 옮깁니다.\n` +
      `담당 선생님도 함께 바뀝니다. 진행할까요?`
    )) return;
    setMoving(true); setMsg(null);
    try {
      const r = await api.moveStudents(picked, moveTo);
      setMsg(okMsg(r.message));
      setPicked([]); setMoveTo("");
      reload();
      api.teacherStudents(scope).then(setRows).catch(() => {});
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally {
      setMoving(false);
    }
  };

  const search = async () => {
    if (q.trim().length < 2) return setMsg(errMsg("2글자 이상 입력해주세요."));
    setBusy(true); setMsg(null);
    try { setResults(await api.teacherSearchStudents(q.trim())); }
    catch (e) { setMsg(errMsg(e.message)); }
    finally { setBusy(false); }
  };

  const openRegister = (u) => { setCls(parseClass(me.class_name)); setTarget(u); };

  const confirmRegister = async () => {
    try {
      await api.teacherRegisterStudent(target.id, formatClass(cls.grade, cls.ban));
      setMsg(okMsg(`${target.name} 학생을 등록했습니다.`));
      setTarget(null); setResults(null); setQ(""); reload();
    } catch (e) { setMsg(errMsg(e.message)); }
  };

  const revoke = async (s) => {
    if (!window.confirm(`${s.name} 학생의 재학생 인증을 해제할까요?\n해제하면 내 학급 명단에서 빠집니다.`)) return;
    await api.teacherUnregisterStudent(s.user_id);
    reload();
    api.teacherStudents(scope).then(setRows).catch(() => {});
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="notice notice-info">
        학생 계정을 <b>아이디(이메일)·이름·연락처</b>로 찾아 학급 인원으로 등록하세요.
        등록(인증)된 학생이 내 학급 명단이 되며, 언제든 <b>인증 해제</b>할 수 있습니다.
      </div>

      <div className="panel">
        <h3>학생 검색</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ flex: 1, minWidth: 220 }} value={q}
            placeholder="이메일 / 이름 / 연락처"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="btn btn-primary btn-sm" onClick={search} disabled={busy}>
            {busy ? "검색 중…" : "검색"}
          </button>
        </div>
        {msg && <div className={`notice notice-${msg.type === "error" ? "error" : "ok"}`} style={{ marginTop: 10 }}>{msg.text}</div>}

        {results && (
          <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
            {results.length === 0 ? (
              <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>검색 결과가 없습니다.</p>
            ) : results.map((s) => (
              <div key={s.id} className="event-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{s.name}</div>
                  <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                    {s.email}{s.phone ? ` · ${s.phone}` : ""}
                  </div>
                </div>
                {s.registered
                  ? <span className="badge badge-dorm">인증됨{s.class_name ? ` · ${s.class_name}` : ""}</span>
                  : <button className="btn btn-primary btn-sm" onClick={() => openRegister(s)}>학급에 등록</button>}
              </div>
            ))}
          </div>
        )}
      </div>

      {target && (
        <div className="panel" style={{ borderColor: "var(--signal)" }}>
          <h3>{target.name} 학생 학급 지정</h3>
          <ClassPicker grade={cls.grade} ban={cls.ban} onChange={setCls} label="배정할 학급" />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn btn-primary btn-sm" onClick={confirmRegister}>등록</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>취소</button>
          </div>
        </div>
      )}

      <div className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>인증된 학생 ({rows.length})</h3>
          <div style={{ display: "flex", gap: 6 }}>
            {[["mine", "내 학급"], ["all", "학교 전체"]].map(([v, label]) => (
              <button key={v} className={`btn btn-sm ${scope === v ? "btn-primary" : "btn-ghost"}`} onClick={() => setScope(v)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        {rows.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "10px 0 0" }}>인증된 학생이 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
            {movable.length > 0 && (
              <label style={{ display: "flex", alignItems: "center", gap: 8,
                              fontSize: 13.5, color: "var(--steel)" }}>
                <input type="checkbox" checked={allPicked}
                  onChange={(e) => setPicked(e.target.checked ? movable.map((x) => x.user_id) : [])} />
                전체 선택 ({movable.length}명)
              </label>
            )}

            {rows.map((s) => (
              <div key={s.user_id} className="event-row">
                {(me.role === "school" || s.is_mine) && (
                  <input type="checkbox" style={{ marginRight: 10 }}
                    checked={picked.includes(s.user_id)}
                    onChange={() => toggle(s.user_id)} />
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    {s.name} <span style={{ fontWeight: 400, fontSize: 12.5, color: "var(--steel)" }}>{s.class_name}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--steel)" }}>
                    {s.email}{s.phone ? ` · ${s.phone}` : ""}
                    {!s.is_mine && s.teacher_name ? ` · 담당 ${s.teacher_name} 선생님` : ""}
                  </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => revoke(s)}>인증 해제</button>
              </div>
            ))}
          </div>
        )}

        {/* 고른 학생을 다른 학급으로 넘긴다. 담당 선생님은 학급으로 자동 판별한다. */}
        {picked.length > 0 && (
          <div style={{ marginTop: 14, padding: 12, borderRadius: 10,
                        background: "var(--paper-warm, #fff8f2)",
                        border: "1px solid var(--signal)" }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              {picked.length}명을 다른 학급으로 옮기기
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select className="input" style={{ minWidth: 220 }} value={moveTo}
                onChange={(e) => setMoveTo(e.target.value)}>
                <option value="">옮겨갈 학급을 고르세요</option>
                {(options?.options || []).map((o) => (
                  <option key={o.class_name} value={o.class_name}>
                    {o.class_name} · {o.teacher_name} 선생님
                  </option>
                ))}
              </select>
              <button className="btn btn-primary btn-sm" onClick={move}
                disabled={moving || !moveTo}>
                {moving ? "옮기는 중…" : "옮기기"}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setPicked([])}>
                선택 해제
              </button>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--steel)", margin: "8px 0 0", lineHeight: 1.7 }}>
              학급을 고르면 <b>그 반을 맡은 선생님에게 담당이 함께 넘어갑니다.</b>
              {" "}기록해의 일지도 그 선생님이 보게 됩니다.
            </p>
            {options?.teachers_without_class?.length > 0 && (
              <p style={{ fontSize: 12.5, color: "#9a6700", margin: "6px 0 0", lineHeight: 1.7 }}>
                담당 학급이 비어 있는 선생님({options.teachers_without_class.map((t) => t.name).join(", ")})은
                {" "}목록에 나오지 않습니다. 학교 계정에서 담당 학급을 적어주세요.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- 재학생 인증 신청 처리 ---------------- */
function VerifyTab({ me, reload }) {
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(0);
  const [target, setTarget] = useState(null);
  const [cls, setCls] = useState(parseClass(me.class_name));

  const load = () => api.teacherVerifications().then(setList).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const openApprove = (v) => { setCls(parseClass(v.class_name || me.class_name)); setTarget(v); };

  const approve = async () => {
    setBusy(target.id);
    try {
      await api.approveVerification(target.id, formatClass(cls.grade, cls.ban));
      setTarget(null); load(); reload();
    } finally { setBusy(0); }
  };

  const reject = async (id) => {
    setBusy(id);
    try { await api.rejectVerification(id); load(); reload(); } finally { setBusy(0); }
  };

  const pending = list.filter((v) => v.status === "pending");
  const decided = list.filter((v) => v.status !== "pending");
  const LABEL = { approved: "승인됨", rejected: "거절됨" };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="notice notice-info">
        학생이 직접 낸 <b>재학생 인증 신청</b>입니다. 승인하면 그 학생이 우리 학교 재학생으로 등록됩니다.
      </div>

      {target && (
        <div className="panel" style={{ borderColor: "var(--signal)" }}>
          <h3>{target.user_name} 학생 승인</h3>
          {target.note && <p style={{ fontSize: 13.5, color: "var(--steel)", margin: "0 0 8px" }}>학생 메모: {target.note}</p>}
          <ClassPicker grade={cls.grade} ban={cls.ban} onChange={setCls} label="배정할 학급" />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn btn-primary btn-sm" onClick={approve} disabled={busy === target.id}>승인</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setTarget(null)}>취소</button>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>승인 대기 ({pending.length})</h3>
        {pending.length === 0 ? (
          <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>대기 중인 신청이 없습니다.</p>
        ) : pending.map((v) => (
          <div className="event-row" key={v.id} style={{ alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>
                {v.user_name} <span style={{ fontWeight: 400, color: "var(--steel)", fontSize: 12.5 }}>{v.user_email}</span>
              </div>
              {v.note && <div style={{ fontSize: 12.5, color: "var(--steel)", marginTop: 2 }}>{v.note}</div>}
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="btn btn-primary btn-sm" disabled={busy === v.id} onClick={() => openApprove(v)}>승인</button>
              <button className="btn btn-ghost btn-sm" disabled={busy === v.id} onClick={() => reject(v.id)}>거절</button>
            </div>
          </div>
        ))}
      </div>

      {decided.length > 0 && (
        <div className="panel">
          <h3>처리 내역 ({decided.length})</h3>
          {decided.map((v) => (
            <div className="event-row" key={v.id}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {v.user_name} <span style={{ fontWeight: 400, color: "var(--steel)", fontSize: 12.5 }}>{v.class_name}</span>
                </div>
                <div style={{ fontSize: 12.5, color: "var(--steel)" }}>{v.user_email}</div>
              </div>
              <span className={`badge ${v.status === "approved" ? "badge-dorm" : ""}`}>{LABEL[v.status]}</span>
              {v.status === "rejected" && (
                <button className="btn btn-ghost btn-sm" disabled={busy === v.id} onClick={() => openApprove(v)}>승인으로 변경</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 일지 목록 섹션. 컴포넌트 밖에 두어 매 렌더마다 다시 만들어지지 않게 한다. */
function JournalSection({ title, items, onOpen }) {
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <h3>{title} ({items.length})</h3>
      {items.length === 0 ? (
        <p style={{ fontSize: 13.5, color: "var(--steel)", margin: 0 }}>제출된 항목이 없습니다.</p>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((j) => (
            <button key={j.id} onClick={() => onOpen(j.id)}
              style={{ display: "flex", alignItems: "center", gap: 12, textAlign: "left", width: "100%", background: "var(--paper)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "12px 14px", cursor: "pointer" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {j.entry_date}{j.subject ? ` · ${j.subject}` : ""}
                </div>
              </div>
              <span style={{ color: "var(--steel-light)", fontSize: 18 }}>›</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- 제출된 일지 + AI 요약 ---------------- */
/* ---------------- 내 계정 ---------------- */
function AccountTab({ me, onChanged }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const change = async () => {
    if (next.length < 8) return setMsg(errMsg("새 비밀번호는 8자 이상이어야 합니다."));
    setBusy(true); setMsg(null);
    try {
      await api.teacherChangePassword({ current_password: cur, new_password: next });
      setMsg(okMsg("비밀번호를 변경했습니다."));
      setCur(""); setNext(""); onChanged();
    } catch (e) {
      setMsg(errMsg(e.message));
    } finally { setBusy(false); }
  };

  return (
    <div className="panel">
      <h3>비밀번호 변경</h3>
      <p style={{ fontSize: 13, color: "var(--steel)", marginTop: -4 }}>
        회원가입 때 정한 비밀번호를 변경할 수 있습니다.
      </p>
      {msg && <div className={`notice notice-${msg.type === "error" ? "error" : "ok"}`} style={{ marginBottom: 10 }}>{msg.text}</div>}
      <div style={{ display: "grid", gap: 10, maxWidth: 380 }}>
        <div className="field">
          <label className="label">현재 비밀번호</label>
          <input className="input" type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
        </div>
        <div className="field">
          <label className="label">새 비밀번호 (8자 이상)</label>
          <input className="input" type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div>
          <button className="btn btn-primary btn-sm" onClick={change} disabled={busy}>
            {busy ? "변경 중…" : "비밀번호 변경"}
          </button>
        </div>
      </div>

      <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
        <span className="label">계정 정보</span>
        <p style={{ fontSize: 14, margin: "4px 0 0" }}>
          {me.name} · {me.email}<br />
          {me.school_name}{me.class_name ? ` · ${me.class_name}` : ""}
        </p>
      </div>
    </div>
  );
}
