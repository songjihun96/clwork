import { useEffect, useState } from "react";
import { api } from "../api";
import Help from "../components/Help";

/** 선생님 계정 관리, 학생 명단 확인, 선생님 담당 과목 배정.
 *  예전에는 '이용권' 화면의 탭 중 하나였는데, 결제·좌석과는 무관한 기능이라
 *  '이용권'이라는 이름만 보고는 여기 들어갈 생각을 못 한다는 의견이 있어
 *  따로 뺐다. 선생님 계정 탭은 원래 UDJ 자체 화면에 있던 것을 옮겨 왔다 —
 *  계정 원본은 여전히 UDJ 뿐이라 이 화면도 매 요청을 그대로 전달만 한다. */
export default function SchoolClasses() {
  const [tab, setTab] = useState("accounts");
  const tabs = [["accounts", "선생님 계정"], ["roster", "학생 명단"], ["subjects", "담당 과목"]];

  return (
    <div className="wrap page" style={{ maxWidth: 860 }}>
      <span className="label">학교 관리</span>
      <h1>학급·과목 관리</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        선생님 계정을 관리하고, 학생 명단을 확인하고, 세특을 만들 수 있는 담당 과목을 정합니다.
      </p>

      <div className="row" style={{ gap: 6, margin: "16px 0" }}>
        {tabs.map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? "" : "btn-ghost"}`}
            onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "accounts" && <AccountsTab />}
      {tab === "roster" && <RosterTab />}
      {tab === "subjects" && <SubjectsTab />}
    </div>
  );
}

function AccountsTab() {
  const [teachers, setTeachers] = useState(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState(null);   // { mode: "grant"|"edit", user }
  const [className, setClassName] = useState("");

  const load = () => api.teacherAccounts().then(setTeachers).catch((e) => setMsg({ type: "error", text: e.message }));
  useEffect(() => { load(); }, []);

  const search = async () => {
    if (q.trim().length < 2) return setMsg({ type: "error", text: "2글자 이상 입력해주세요." });
    setBusy(true); setMsg(null);
    try { setResults(await api.searchTeacherAccounts(q.trim())); }
    catch (e) { setMsg({ type: "error", text: e.message }); }
    finally { setBusy(false); }
  };

  const openGrant = (u) => { setClassName(""); setTarget({ mode: "grant", user: u }); };
  const openEdit = (t) => { setClassName(t.class_name || ""); setTarget({ mode: "edit", user: t }); };

  const confirmTarget = async () => {
    setMsg(null);
    try {
      if (target.mode === "grant") {
        await api.grantTeacherAccount(target.user.id, className);
        setMsg({ type: "ok", text: `${target.user.name} 님에게 선생님 권한을 부여했습니다.` });
        setResults(null); setQ("");
      } else {
        await api.updateTeacherAccount(target.user.id, { class_name: className });
        setMsg({ type: "ok", text: "담당 학급을 변경했습니다." });
      }
      setTarget(null); load();
    } catch (e) { setMsg({ type: "error", text: e.message }); }
  };

  const toggle = async (t) => {
    try { await api.updateTeacherAccount(t.id, { is_active: !t.is_active }); load(); }
    catch (e) { setMsg({ type: "error", text: e.message }); }
  };

  const revoke = async (t) => {
    if (!window.confirm(`${t.name} 선생님의 권한을 해제할까요?\n계정은 삭제되지 않고 일반 사용자로 돌아갑니다.`)) return;
    try { await api.revokeTeacherAccount(t.id); load(); }
    catch (e) { setMsg({ type: "error", text: e.message }); }
  };

  if (!teachers) return <p className="meta">불러오는 중…</p>;

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="panel">
        <b>선생님 권한 부여</b>
        <p className="meta" style={{ marginTop: 4, lineHeight: 1.6 }}>
          선생님이 먼저 우리동네 직업계고에 일반 회원가입을 한 뒤, 그 계정을 아래에서
          찾아 선생님 권한을 부여하세요. 비밀번호는 선생님 본인이 정한 것을 그대로
          쓰므로 학교가 따로 관리할 필요가 없습니다.
        </p>
        <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <input className="input" style={{ flex: 1, minWidth: 220 }} value={q}
            placeholder="이메일 / 이름 / 연락처"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="btn btn-sm" onClick={search} disabled={busy}>
            {busy ? "검색 중…" : "검색"}
          </button>
        </div>

        {results && (
          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {results.length === 0 ? (
              <p className="meta">검색 결과가 없습니다. 선생님이 회원가입을 했는지 확인해 주세요.</p>
            ) : results.map((u) => (
              <div key={u.id} className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{u.name}</div>
                  <div className="meta">{u.email}{u.phone ? ` · ${u.phone}` : ""}</div>
                </div>
                {u.is_our_teacher ? (
                  <span className="badge badge-done">이미 우리 학교 선생님</span>
                ) : u.other_school ? (
                  <span className="badge">다른 학교 선생님</span>
                ) : (
                  <button className="btn btn-sm" onClick={() => openGrant(u)}>선생님 권한 부여</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {target && (
        <div className="panel" style={{ borderColor: "var(--accent, var(--signal))" }}>
          <b>{target.mode === "grant" ? `${target.user.name} 님에게 권한 부여` : `${target.user.name} 선생님 학급 변경`}</b>
          <div className="field" style={{ marginTop: 10, maxWidth: 260 }}>
            <label className="label">담당 학급 (예: 2학년 3반)</label>
            <input className="input" value={className} onChange={(e) => setClassName(e.target.value)} />
          </div>
          <div className="row" style={{ gap: 8, marginTop: 12 }}>
            <button className="btn btn-sm" onClick={confirmTarget}>
              {target.mode === "grant" ? "권한 부여" : "학급 저장"}
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => setTarget(null)}>취소</button>
          </div>
        </div>
      )}

      {msg && <div className={`notice notice-${msg.type}`}>{msg.text}</div>}

      <div className="panel">
        <b>우리 학교 선생님 ({teachers.length})</b>
        {teachers.length === 0 ? (
          <p className="meta" style={{ marginTop: 10 }}>아직 등록된 선생님이 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
            {teachers.map((t) => (
              <div key={t.id} className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    {t.name} <span className="meta">{t.class_name}</span>
                    {!t.is_active && <span className="badge" style={{ marginLeft: 6 }}>정지됨</span>}
                  </div>
                  <div className="meta">{t.email}</div>
                </div>
                <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => openEdit(t)}>학급 변경</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => toggle(t)}>{t.is_active ? "정지" : "활성화"}</button>
                  <button className="btn btn-sm btn-ghost" onClick={() => revoke(t)}>권한 해제</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RosterTab() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [offset, setOffset] = useState(0);
  const LIMIT = 20;

  useEffect(() => {
    api.schoolStudents({ q, limit: LIMIT, offset })
      .then(setData).catch(() => setData({ total: 0, items: [] }));
  }, [q, offset]);

  useEffect(() => { setOffset(0); }, [q]);

  if (!data) return <p className="meta">불러오는 중…</p>;

  const page = Math.floor(offset / LIMIT) + 1;
  const last = Math.max(1, Math.ceil(data.total / LIMIT));

  return (
    <div className="panel">
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b>학생 {data.total}명</b>
        <input className="input" value={term} style={{ maxWidth: 220 }}
          placeholder="이름·반으로 찾기"
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setQ(term)} />
        <button className="btn btn-sm" onClick={() => setQ(term)}>찾기</button>
      </div>

      {data.items.length === 0 ? (
        <p className="meta" style={{ marginTop: 12 }}>
          {q ? "찾는 학생이 없습니다." : "등록된 학생이 없습니다."}
        </p>
      ) : (
        <>
          <table style={{ width: "100%", fontSize: 13.5, marginTop: 12 }}>
            <thead>
              <tr style={{ color: "var(--steel-light)", textAlign: "left" }}>
                <th>이름</th><th>학년·반</th>
                <th>재학생 인증<Help text="선생님이 우리동네 직업계고에서 승인하는 절차입니다. 인증돼야 학생이 일지를 선생님께 제출할 수 있습니다." /></th>
                <th>이용권</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((s) => (
                <tr key={s.user_id}>
                  <td style={{ padding: "6px 0" }}>{s.name}</td>
                  <td>{s.class_name || (s.grade ? `${s.grade}학년` : "—")}</td>
                  <td>{s.verified
                    ? <span className="badge badge-done">인증됨</span>
                    : <span className="meta">미인증</span>}</td>
                  <td>{s.has_seat
                    ? <span className="badge badge-done">이용 중</span>
                    : <span className="meta">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="row" style={{ gap: 10, marginTop: 14, alignItems: "center" }}>
            <button className="btn btn-sm" disabled={offset === 0}
              onClick={() => setOffset(offset - LIMIT)}>이전</button>
            <span className="meta">{page} / {last} 쪽</span>
            <button className="btn btn-sm" disabled={offset + LIMIT >= data.total}
              onClick={() => setOffset(offset + LIMIT)}>다음</button>
          </div>
        </>
      )}

      <p className="meta" style={{ marginTop: 12, lineHeight: 1.7 }}>
        재학생 인증은 <b>우리동네 직업계고</b>에서 담당 선생님이 승인합니다.
        인증되지 않은 학생도 이용권은 받을 수 있지만, 일지를 선생님께 제출하려면
        인증이 필요합니다.
      </p>
    </div>
  );
}

function SubjectsTab() {
  const [teachers, setTeachers] = useState(null);
  const [picked, setPicked] = useState(null);       // 선택한 선생님
  const [subjectList, setSubjectList] = useState([]); // 그 선생님의 담당 과목
  const [options, setOptions] = useState([]);         // 학교 전체 과목 목록
  const [addId, setAddId] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadTeachers = () =>
    api.schoolTeachers().then(setTeachers).catch((e) => setMsg({ type: "error", text: e.message }));

  useEffect(() => {
    loadTeachers();
    api.journalSubjects().then((s) => setOptions(s?.subject_options || [])).catch(() => {});
  }, []);

  const openTeacher = (t) => {
    setPicked(t);
    setMsg(null);
    api.teacherSubjects(t.id).then(setSubjectList).catch((e) => setMsg({ type: "error", text: e.message }));
  };

  const add = async () => {
    if (!picked || !addId) return;
    setBusy(true); setMsg(null);
    try {
      await api.addTeacherSubject(picked.id, parseInt(addId, 10));
      setAddId("");
      openTeacher(picked);
      loadTeachers();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (assignmentId) => {
    setBusy(true); setMsg(null);
    try {
      await api.removeTeacherSubject(picked.id, assignmentId);
      openTeacher(picked);
      loadTeachers();
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  if (!teachers) return <p className="meta">불러오는 중…</p>;

  return (
    <div className="row" style={{ gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
      <div className="panel" style={{ flex: "1 1 260px", minWidth: 240 }}>
        <b>선생님 {teachers.length}명</b>
        <p className="meta" style={{ marginTop: 4, lineHeight: 1.6 }}>
          담당 학급은 위 <b>선생님 계정</b> 탭에서 정합니다. 여기서는
          과목 세특을 만들 수 있는 <b>담당 과목</b>
          <Help text="담임 학급(1명당 1개)과 별개 개념입니다. 담당 과목으로 정해두면 담임이 아니어도 그 과목 수업일지를 보고 세특 초안을 만들 수 있습니다. 한 선생님이 여러 과목을 맡을 수 있습니다." />
          만 정합니다.
        </p>
        {teachers.length === 0 ? (
          <p className="meta" style={{ marginTop: 10 }}>등록된 선생님이 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
            {teachers.map((t) => (
              <button key={t.id}
                className={`btn btn-sm ${picked?.id === t.id ? "" : "btn-ghost"}`}
                style={{ justifyContent: "space-between", display: "flex" }}
                onClick={() => openTeacher(t)}>
                <span>{t.name}{t.class_name ? ` · ${t.class_name} 담임` : ""}</span>
                <span className="meta">담당 과목 {t.subject_count}개</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="panel" style={{ flex: "1 1 300px", minWidth: 260 }}>
        {!picked ? (
          <p className="meta">왼쪽에서 선생님을 골라주세요.</p>
        ) : (
          <>
            <b>{picked.name} 선생님 담당 과목</b>
            <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <select className="select" value={addId} style={{ maxWidth: 220 }}
                onChange={(e) => setAddId(e.target.value)}>
                <option value="">과목 선택</option>
                {options
                  .filter((o) => !subjectList.some((s) => s.subject_id === o.id))
                  .map((o) => (
                    <option key={o.id} value={o.id}>
                      {[o.department, o.grade ? `${o.grade}학년` : "", o.name]
                        .filter(Boolean).join(" · ")}
                    </option>
                  ))}
              </select>
              <button className="btn btn-sm btn-primary" onClick={add} disabled={busy || !addId}>
                추가
              </button>
            </div>

            {subjectList.length === 0 ? (
              <p className="meta" style={{ marginTop: 12 }}>아직 담당 과목이 없습니다.</p>
            ) : (
              <div style={{ display: "grid", gap: 6, marginTop: 12 }}>
                {subjectList.map((s) => (
                  <div key={s.id} className="row"
                    style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <span>
                      {[s.department, s.grade ? `${s.grade}학년` : "", s.subject_name]
                        .filter(Boolean).join(" · ")}
                    </span>
                    <button className="btn btn-sm btn-ghost" onClick={() => remove(s.id)}
                      disabled={busy}>제거</button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}
      </div>
    </div>
  );
}
