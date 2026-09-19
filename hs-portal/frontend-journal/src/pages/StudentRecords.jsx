import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import Help from "../components/Help";

/** 학생을 카드로 골라 수업일지·학교생활일지·내 관찰 기록을 다루는 화면.
 *  /students 는 목록, /students/:id 는 그 학생의 상세다 — 주소로 바로
 *  들어올 수 있어야 다른 곳에서도 카드를 눌러 바로 이 상세로 이어줄 수 있다.
 *  담당 과목이 없으면 수업일지가, 담임이 아니면 학교생활일지·관찰 기록이
 *  제한된다 — 실제 차단은 서버가 한다(여긴 안내일 뿐이다).
 *
 *  예전에는 여기서 AI가 세특·행동특성 초안을 만들어 확정하는 기능이
 *  있었는데, 서비스 방향이 학생 포트폴리오 쪽으로 바뀌면서 그 화면은
 *  뺐다(기존에 만든 초안 데이터는 지우지 않았다). 대신 선생님이 학생을
 *  보며 남기는 개인 관찰 기록(본인만 보임)을 여기서 다룬다.
 *
 *  예전에는 이 화면과 거의 같은 화면이 '학생 기록'이라는 이름으로 하나 더
 *  있었다(제출 현황 확인용). 메뉴 두 개가 결국 같은 학생 상세로 이어지다
 *  보니 어디가 어디인지 헷갈린다는 의견이 있어 하나로 합쳤다 — 제출 현황
 *  요약과 담당 범위 전환(내 학급/우리 학교 전체)도 이제 여기서 함께 본다. */
export default function StudentRecords() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [students, setStudents] = useState(null);
  const [mySubjects, setMySubjects] = useState([]);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [grade, setGrade] = useState("");
  const [classNo, setClassNo] = useState("");
  const [dept, setDept] = useState("");
  const [scope, setScope] = useState("mine");   // 선생님만 고를 수 있다
  const [schoolId, setSchoolId] = useState(""); // 관리자만 쓴다

  const isTeacher = user?.role === "teacher";
  const isAdmin = user?.role === "admin";
  const effectiveScope = isTeacher ? scope : "all";

  useEffect(() => {
    setStudents(null);
    setError("");
    if (isAdmin && !schoolId) {
      setStudents([]);
      return;
    }
    api.teacherStudents({ scope: effectiveScope, school_id: isAdmin ? schoolId : undefined })
      .then(setStudents)
      .catch((e) => { setError(e.message); setStudents([]); });
    if (isTeacher) api.mySubjects().then(setMySubjects).catch(() => {});
  }, [effectiveScope, schoolId, isTeacher, isAdmin]);

  const grades = useMemo(
    () => [...new Set((students || []).map((s) => s.grade).filter(Boolean))].sort(),
    [students]);
  const classes = useMemo(
    () => [...new Set((students || []).map((s) => s.class_no).filter(Boolean))].sort(),
    [students]);
  const depts = useMemo(
    () => [...new Set((students || []).map((s) => s.department).filter(Boolean))].sort(),
    [students]);

  const shown = (students || []).filter((s) => {
    if (grade && String(s.grade) !== grade) return false;
    if (classNo && s.class_no !== classNo) return false;
    if (dept && s.department !== dept) return false;
    if (q.trim()) {
      const term = q.trim();
      const hay = `${s.name} ${s.student_no || ""}`;
      if (!hay.includes(term)) return false;
    }
    return true;
  });
  const never = (students || []).filter((s) => s.submitted === 0);
  const waiting = (students || []).reduce((a, s) => a + (s.awaiting_feedback || 0), 0);

  if (id) {
    const studentId = parseInt(id, 10);
    const selected = (students || []).find((s) => s.id === studentId);
    if (students && !selected) {
      return (
        <div className="wrap page">
          <button className="btn btn-sm btn-ghost" onClick={() => navigate("/students")}>← 학생 목록</button>
          <div className="empty" style={{ marginTop: 16 }}>
            <h3>볼 수 없는 학생입니다</h3>
            <p>담당 학급·과목 학생만 볼 수 있습니다.</p>
          </div>
        </div>
      );
    }
    if (!selected) return <div className="wrap page"><p className="meta">불러오는 중…</p></div>;
    return (
      <StudentDetail
        student={selected}
        mySubjects={mySubjects}
        isTeacher={isTeacher}
        onBack={() => navigate("/students")}
      />
    );
  }

  return (
    <div className="wrap page">
      <span className="label">학생 기록</span>
      <h1>학생 기록</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        학생을 골라 제출한 수업일지·학교생활일지를 확인하고, 개인 관찰 기록을 남길 수 있습니다.
      </p>

      {!isTeacher && !isAdmin && (
        <div className="notice" style={{ marginBottom: 14, fontSize: 13.5 }}>
          학생의 기록은 민감한 개인정보입니다. 담당 교사가 아닌 계정의 열람은
          누가 무엇을 보았는지 기록으로 남습니다.
        </div>
      )}

      {error && <div className="notice notice-error">{error}</div>}

      {isTeacher && (
        <div className="panel" style={{ marginBottom: 16, lineHeight: 1.7, fontSize: 13.5 }}>
          <b>내 담당 과목</b>
          <Help text="담당 학급(담임)과 별개로, 학교 계정이 배정한 과목입니다. 담임이 아니어도 여기 있는 과목의 수업일지는 보고 세특 초안을 만들 수 있습니다." />
          {" "}
          {mySubjects.length === 0
            ? <span className="meta">아직 담당 과목이 없습니다. 학교 계정에 문의해주세요.</span>
            : mySubjects.map((s) => (
                <span key={s.id} className="badge" style={{ marginRight: 6 }}>
                  {[s.department, s.grade ? `${s.grade}학년` : "", s.subject_name]
                    .filter(Boolean).join(" · ")}
                </span>
              ))}
        </div>
      )}

      {isTeacher && (
        <div className="row" style={{ gap: 6, marginBottom: 16 }}>
          {[["mine", "내 학급"], ["all", "우리 학교 전체"]].map(([k, label]) => (
            <button key={k} className={`btn btn-sm ${scope === k ? "" : "btn-ghost"}`}
              onClick={() => setScope(k)}>{label}</button>
          ))}
        </div>
      )}

      {isAdmin && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <label className="field" style={{ marginBottom: 0 }}>
            <span className="label">학교 번호(ID)</span>
            <input className="input" value={schoolId} inputMode="numeric"
              placeholder="관리자는 볼 학교를 지정해야 합니다"
              onChange={(e) => setSchoolId(e.target.value.replace(/\D/g, ""))} />
          </label>
        </div>
      )}

      <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input className="input" value={q} placeholder="이름·번호로 찾기" style={{ maxWidth: 200 }}
          onChange={(e) => setQ(e.target.value)} />
        <select className="select" value={grade} style={{ maxWidth: 120 }}
          onChange={(e) => setGrade(e.target.value)}>
          <option value="">학년 전체</option>
          {grades.map((g) => <option key={g} value={g}>{g}학년</option>)}
        </select>
        <select className="select" value={classNo} style={{ maxWidth: 120 }}
          onChange={(e) => setClassNo(e.target.value)}>
          <option value="">반 전체</option>
          {classes.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="select" value={dept} style={{ maxWidth: 160 }}
          onChange={(e) => setDept(e.target.value)}>
          <option value="">학과 전체</option>
          {depts.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {students && students.length > 0 && (
        <div className="row" style={{ gap: 8, alignItems: "baseline", marginBottom: 14, flexWrap: "wrap" }}>
          <span className="meta">
            학생 {students.length}명
            {never.length > 0 && ` · 아직 안 낸 학생 ${never.length}명`}
            {waiting > 0 && ` · 답을 기다리는 일지 ${waiting}건`}
          </span>
        </div>
      )}

      {!students ? (
        <p className="meta">불러오는 중…</p>
      ) : shown.length === 0 ? (
        <div className="empty">
          <h3>{students.length === 0 ? "아직 담당 학생이 없습니다" : "조건에 맞는 학생이 없습니다"}</h3>
        </div>
      ) : (
        <div style={{
          display: "grid", gap: 12,
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        }}>
          {shown.map((s) => <StudentCard key={s.id} s={s} onOpen={() => navigate(`/students/${s.id}`)} />)}
        </div>
      )}
    </div>
  );
}

/** 학생 한 명당 카드 하나. 학년·반·번호·학과·이름과 제출 건수를 보여준다.
 *  다른 화면(제출된 일지 등)에서도 같은 모양으로 쓸 수 있게 내보낸다. */
export function StudentCard({ s, onOpen }) {
  const where = [s.grade ? `${s.grade}학년` : "", s.class_no, s.student_no ? `${s.student_no}번` : ""]
    .filter(Boolean).join(" ");
  return (
    <button className="panel" onClick={onOpen}
      style={{ textAlign: "left", cursor: "pointer", display: "grid", gap: 4 }}>
      <span className="meta">{where || "소속 미배정"}</span>
      <span className="meta">{s.department || "학과 없음"}</span>
      <b style={{ fontSize: 16 }}>{s.name}</b>
      <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        <span className="badge">수업일지 {s.lesson_count}건</span>
        <span className="badge">학교생활 {s.diary_count}건</span>
      </div>
      {s.awaiting_feedback > 0 && (
        <span className="meta" style={{ marginTop: 2 }}>답변 {s.awaiting_feedback}건 대기</span>
      )}
    </button>
  );
}

function StudentDetail({ student, mySubjects, isTeacher, onBack }) {
  const [tab, setTab] = useState("lesson");
  const where = [student.grade ? `${student.grade}학년` : "", student.class_no,
    student.student_no ? `${student.student_no}번` : ""].filter(Boolean).join(" ");

  return (
    <div className="wrap page">
      <button className="btn btn-sm btn-ghost" onClick={onBack}>← 학생 목록</button>
      <div className="row" style={{ marginTop: 12, alignItems: "flex-start" }}>
        <div>
          <span className="label" style={{ display: "block" }}>{where || "소속 미배정"}</span>
          <h1>{student.name}</h1>
          <p className="meta" style={{ marginTop: -6 }}>{student.department || "학과 없음"}</p>
        </div>
        <div className="spacer" />
        {/* 관찰 기록은 별개 화면이다 — 교사 본인만 쓰고 볼 수 있는 개인
            기록이라, 학생 기록 탭 사이에 섞어 두지 않고 따로 뺐다. */}
        {isTeacher && (
          <Link to={`/observations/${student.id}`} className="btn btn-sm">관찰 기록 보기</Link>
        )}
      </div>

      <div className="row" style={{ gap: 6, margin: "16px 0" }}>
        {[["lesson", "수업일지"], ["diary", "학교생활일지"]].map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? "" : "btn-ghost"}`}
            onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === "lesson" && (
        <LessonTab student={student} mySubjects={mySubjects} isTeacher={isTeacher} />
      )}
      {tab === "diary" && <DiaryTab student={student} />}
    </div>
  );
}

/** 과목별 수업일지. 담당 과목이 아니면 목록 자체가 서버에서 걸러지지
 *  않지만(담임은 반 전체를 볼 수 있음), 열람만 되고 따로 표시는 안 한다. */
function LessonTab({ student, mySubjects, isTeacher }) {
  const [subjectId, setSubjectId] = useState(mySubjects[0]?.subject_id ? String(mySubjects[0].subject_id) : "");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setItems(null);
    setError("");
    api.teacherJournals({ student_id: student.id, kind: "lesson",
      subject_id: subjectId || undefined, limit: 200 })
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e) => setError(e.message));
  }, [student.id, subjectId]);

  return (
    <>
      {isTeacher && mySubjects.length > 0 && (
        <select className="select" value={subjectId} style={{ maxWidth: 260, marginBottom: 12 }}
          onChange={(e) => setSubjectId(e.target.value)}>
          <option value="">과목 전체 (열람만)</option>
          {mySubjects.map((s) => (
            <option key={s.subject_id} value={s.subject_id}>
              {[s.department, s.grade ? `${s.grade}학년` : "", s.subject_name].filter(Boolean).join(" · ")}
            </option>
          ))}
        </select>
      )}

      {error && <div className="notice notice-error">{error}</div>}
      {!error && !items && <p className="meta">불러오는 중…</p>}
      {!error && items && items.length === 0 && (
        <p className="meta">{subjectId ? "이 과목으로 제출된 수업일지가 없습니다." : "제출된 수업일지가 없습니다."}</p>
      )}
      {items && items.map((it) => (
        <JournalEntryCard key={it.id} item={it} studentId={student.id} isTeacher={isTeacher}
          badge={it.subject || "과목 미지정"} />
      ))}
    </>
  );
}

/** 담임 학급 학교생활일지. */
function DiaryTab({ student }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.teacherJournals({ student_id: student.id, kind: "diary", limit: 200 })
      .then((d) => setItems(Array.isArray(d) ? d : []))
      .catch((e) => setError(e.message));
  }, [student.id]);

  return (
    <>
      {error && <div className="notice notice-error">{error}</div>}
      {!error && !items && <p className="meta">불러오는 중…</p>}
      {!error && items && items.length === 0 && <p className="meta">제출된 학교생활일지가 없습니다.</p>}
      {items && items.map((it) => (
        <JournalEntryCard key={it.id} item={it} studentId={student.id} isTeacher />
      ))}
    </>
  );
}

/** 일지 한 건. 누르면 펼쳐져 AI 요약과 '학생에게 한마디' 칸이 나온다. */
function JournalEntryCard({ item, badge, studentId, isTeacher }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (detail) return;
    setBusy(true);
    try {
      setDetail(await api.teacherJournal(item.id));
    } catch (e) {
      setDetail({ error: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="entry" style={{ cursor: "pointer" }} onClick={toggle}>
      {badge && (
        <div className="row" style={{ gap: 6, marginBottom: 4 }}>
          <span className="badge">{badge}</span>
        </div>
      )}
      <h4>{item.title || item.entry_date}</h4>
      <div className="meta">
        {item.title ? item.entry_date : ""}
        {item.submitted_at ? ` · 제출 ${String(item.submitted_at).slice(0, 10)}` : ""}
      </div>

      {open && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}
          onClick={(e) => e.stopPropagation()}>
          {busy && <p style={{ fontSize: 14 }}>불러오는 중…</p>}
          {detail?.error && <div className="notice notice-error">{detail.error}</div>}
          {detail && !detail.error && (
            <>
              {(detail.items || []).map((sec, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <div className="label">{sec.label || sec.title}</div>
                  <div style={{ fontSize: 14, whiteSpace: "pre-wrap", lineHeight: 1.75 }}>
                    {sec.text || sec.value || "—"}
                  </div>
                </div>
              ))}
              {detail.record_draft && (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px dashed var(--line)" }}>
                  <div className="label">생활기록부 초안 (참고용)</div>
                  <div style={{ fontSize: 14, whiteSpace: "pre-wrap", lineHeight: 1.75 }}>
                    {detail.record_draft}
                  </div>
                  <button className="btn btn-sm" style={{ marginTop: 10 }}
                    onClick={() => navigator.clipboard?.writeText(detail.record_draft)}>
                    초안 복사
                  </button>
                </div>
              )}
              <FeedbackBox journalId={item.id} detail={detail}
                onSaved={(r) => setDetail((d) => ({
                  ...d, feedback: r.feedback, feedback_by_name: r.feedback_by_name || "",
                  feedback_at: r.feedback_at || null, feedback_read_at: null,
                }))} />
              {isTeacher && studentId && (
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px dashed var(--line)" }}>
                  <Link className="btn btn-sm btn-ghost"
                    to={`/observations/${studentId}?journal=${item.id}` +
                        `&subject=${item.subject_id || ""}&date=${item.entry_date || ""}`}>
                    관찰 기록 남기기
                  </Link>
                  <p className="meta" style={{ marginTop: 6 }}>
                    이 일지를 근거로 개인 관찰 기록을 남깁니다 — 학생에게는 보이지 않습니다.
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** 선생님이 남기는 한마디.
 *  일지를 읽고 아무 말이 없으면 학생에게는 제출이 형식으로만 남는다. */
function FeedbackBox({ journalId, detail, onSaved }) {
  const [text, setText] = useState(detail.feedback || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => {
    setText(detail.feedback || "");
    setSaved("");
    setError("");
  }, [journalId]);

  const save = async () => {
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const r = await api.writeFeedback(journalId, text);
      setSaved(r.feedback ? "남겼습니다." : "지웠습니다.");
      onSaved?.(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const dirty = (text || "").trim() !== (detail.feedback || "").trim();

  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px dashed var(--line)" }}>
      <div className="label">학생에게 한마디</div>

      {detail.feedback_at && !dirty && (
        <div className="meta" style={{ marginBottom: 6 }}>
          {detail.feedback_by_name && `${detail.feedback_by_name} · `}
          {String(detail.feedback_at).slice(0, 10)} 남김
          {detail.feedback_read_at ? " · 학생이 읽음" : " · 아직 안 읽음"}
        </div>
      )}

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        maxLength={1000}
        placeholder="잘한 점 하나와 다음에 해볼 것 하나를 적어주면 학생에게 가장 도움이 됩니다."
        style={{ width: "100%", fontSize: 14, lineHeight: 1.7 }}
      />

      {error && <div className="notice notice-error" style={{ marginTop: 8 }}>{error}</div>}
      {saved && !dirty && <div className="meta" style={{ marginTop: 6 }}>{saved}</div>}

      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button className="btn btn-sm btn-primary" onClick={save} disabled={busy || !dirty}>
          {busy ? "저장 중…" : detail.feedback ? "고쳐 남기기" : "남기기"}
        </button>
        {detail.feedback && (
          <span className="meta">
            내용을 지우고 저장하면 한마디가 삭제됩니다.
          </span>
        )}
      </div>
    </div>
  );
}
