import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";

/** 교사 관찰 기록.
 *
 *  NEIS 누가기록이나 학교생활기록부를 대신하는 기능이 아니다 — 수업과
 *  학교생활에서 학생을 관찰하며 필요한 내용을 날짜별로 기록하고, 교사
 *  본인이 필요할 때 다시 찾아볼 수 있게 하는 이 서비스만의 독립된 개인
 *  기록이다. 학생 포트폴리오에는 자동으로 반영되지 않는다.
 *
 *  /observations       — 담당 학생 전체 보기(기록 수·최근 날짜)
 *  /observations/:id   — 학생 한 명의 기록을 날짜순으로 누적해서 본다 */
export default function TeacherObservations() {
  const { studentId } = useParams();
  return studentId ? <StudentObservations studentId={parseInt(studentId, 10)} /> : <ClassOverview />;
}

function ClassOverview() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    api.observationsSummary().then(setRows).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="wrap page"><div className="notice notice-error">{error}</div></div>;
  if (!rows) return <div className="wrap page"><p className="meta">불러오는 중…</p></div>;

  const shown = rows.filter((r) => !q.trim() || r.name.includes(q.trim()));

  return (
    <div className="wrap page">
      <span className="label">교사 관찰 기록</span>
      <h1>학생별 관찰 기록</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        수업과 학교생활에서 학생을 관찰하며 필요한 내용을 날짜별로 기록하고 관리합니다.
        여기 적는 내용은 선생님 본인에게만 보이고, 학생 포트폴리오에는 자동으로 들어가지 않습니다.
      </p>

      <input className="input" value={q} placeholder="이름으로 찾기" style={{ maxWidth: 220, marginBottom: 14 }}
        onChange={(e) => setQ(e.target.value)} />

      {shown.length === 0 ? (
        <div className="empty"><h3>담당 학생이 없습니다</h3></div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr><th>학생</th><th>학급</th><th>기록 수</th><th>최근 날짜</th><th></th></tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.student_id}>
                  <td>{r.name}</td>
                  <td>{r.class_name || "—"}</td>
                  <td>{r.count > 0 ? `${r.count}건` : "기록 없음"}</td>
                  <td>{r.last_observed_at || "-"}</td>
                  <td>
                    <Link className="btn btn-sm btn-ghost" to={`/observations/${r.student_id}`}>보기</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const QUICK_PHRASES = [
  "문제 해결", "질문", "협업", "역할 수행", "성장", "집중", "개선", "주도적 시도",
];

function StudentObservations({ studentId }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [order, setOrder] = useState("desc");
  const [q, setQ] = useState("");
  const [subjects, setSubjects] = useState([]);
  const [subjectId, setSubjectId] = useState(
    params.get("subject") ? parseInt(params.get("subject"), 10) : "");
  const [writing, setWriting] = useState(!!params.get("journal") || !!params.get("date"));
  const [studentName, setStudentName] = useState("");

  const load = () => api.teacherObservations(studentId, { order, q, subjectId: subjectId || undefined })
    .then(setRows).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [studentId, order, subjectId]);

  useEffect(() => { api.mySubjects().then(setSubjects).catch(() => {}); }, []);

  // 학생 이름 정도는 요약 목록에서 가져와 제목에 쓴다(별도 학생 조회 API를
  // 새로 만들 필요 없이, 이미 있는 목록 데이터를 재사용한다).
  useEffect(() => {
    api.observationsSummary().then((list) => {
      const found = list.find((s) => s.student_id === studentId);
      if (found) setStudentName(found.name);
    }).catch(() => {});
  }, [studentId]);

  const search = (e) => { e.preventDefault(); load(); };

  return (
    <div className="wrap page" style={{ maxWidth: 720 }}>
      <button className="btn btn-sm btn-ghost" onClick={() => navigate("/observations")}>← 학생별 관찰 기록</button>
      <h1 style={{ marginTop: 12 }}>{studentName ? `${studentName}의 관찰 기록` : "관찰 기록"}</h1>

      {subjects.length > 0 && (
        <div className="row" style={{ gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          <button className={`btn btn-sm ${subjectId === "" ? "" : "btn-ghost"}`}
            onClick={() => setSubjectId("")}>전체 과목</button>
          {subjects.map((s) => (
            <button key={s.subject_id}
              className={`btn btn-sm ${subjectId === s.subject_id ? "" : "btn-ghost"}`}
              onClick={() => setSubjectId(s.subject_id)}>
              {s.subject_name}
            </button>
          ))}
        </div>
      )}

      {!writing && (
        <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={() => setWriting(true)}>
          + 관찰 기록 작성
        </button>
      )}

      {writing && (
        <ObservationForm studentId={studentId}
          initialJournalId={params.get("journal") ? parseInt(params.get("journal"), 10) : null}
          initialSubjectId={params.get("subject") ? parseInt(params.get("subject"), 10)
            : (subjectId || null)}
          initialDate={params.get("date") || ""}
          onDone={() => { setWriting(false); load(); }}
          onCancel={() => setWriting(false)} />
      )}

      {subjectId !== "" && (
        <AiNotePanel studentId={studentId} subjectId={subjectId}
          subjectName={subjects.find((s) => s.subject_id === subjectId)?.subject_name || ""} />
      )}

      <form onSubmit={search} className="row" style={{ gap: 8, margin: "18px 0 6px", flexWrap: "wrap" }}>
        <input className="input" value={q} placeholder="날짜·과목·내용 검색" style={{ maxWidth: 220 }}
          onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-sm" type="submit">검색</button>
        <div className="spacer" />
        <button className={`btn btn-sm ${order === "desc" ? "" : "btn-ghost"}`}
          onClick={() => setOrder("desc")} type="button">최신순</button>
        <button className={`btn btn-sm ${order === "asc" ? "" : "btn-ghost"}`}
          onClick={() => setOrder("asc")} type="button">오래된순</button>
      </form>

      {error && <div className="notice notice-error">{error}</div>}
      {!error && !rows && <p className="meta">불러오는 중…</p>}
      {!error && rows && rows.length === 0 && <p className="meta">아직 남긴 기록이 없습니다.</p>}
      {rows && rows.length > 0 && (
        <div className="panel">
          {rows.map((r) => <ObservationCard key={r.id} row={r} onChanged={load} />)}
        </div>
      )}
    </div>
  );
}

/** 이 과목으로 쌓은 관찰 기록만 모아 AI 세특 초안을 만든다. 학생이 쓴
 *  수업일지가 아니라 교사 본인이 쓴 관찰 기록만 재료로 쓴다. */
function AiNotePanel({ studentId, subjectId, subjectName }) {
  const [drafts, setDrafts] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.aiRecords(studentId, "subject_special_note")
    .then((all) => setDrafts(all.filter((d) => d.subject_id === subjectId)))
    .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [studentId, subjectId]);

  const generate = async () => {
    setBusy(true); setError("");
    try {
      const job = await api.requestObservationNote(studentId, subjectId);
      await api.waitAiJob(job.job_id);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <b>{subjectName} 세특 AI 결과물</b>
        <button className="btn btn-sm btn-primary" disabled={busy} onClick={generate}>
          {busy ? "만드는 중…" : "AI로 만들기"}
        </button>
      </div>
      <p className="meta" style={{ marginTop: 6 }}>
        위에서 이 과목으로 남긴 관찰 기록만 근거로 씁니다. 만들어진 초안은 자유롭게 고치고 확정할 수 있습니다.
      </p>
      {error && <div className="notice notice-error" style={{ marginTop: 8 }}>{error}</div>}
      {drafts && drafts.length === 0 && <p className="meta">아직 만든 결과물이 없습니다.</p>}
      {drafts && drafts.map((d) => <AiDraftCard key={d.id} draft={d} onChanged={load} />)}
    </div>
  );
}

function AiDraftCard({ draft, onChanged }) {
  const [content, setContent] = useState(draft.content);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const confirmed = draft.status === "confirmed";

  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.updateAiRecord(draft.id, content);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true); setError("");
    try {
      await api.confirmAiRecord(draft.id);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 10 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className={`badge ${confirmed ? "badge-done" : ""}`}>
          {confirmed ? "확정됨" : draft.status === "reviewed" ? "수정됨" : "AI 초안"}
        </span>
        <span className="meta">{draft.created_at?.slice(0, 10)}</span>
      </div>
      <textarea className="input" rows={4} value={content} disabled={confirmed}
        onChange={(e) => setContent(e.target.value)}
        style={{ width: "100%", fontFamily: "inherit", marginTop: 8 }} />
      {error && <div className="notice notice-error" style={{ marginTop: 8 }}>{error}</div>}
      {!confirmed && (
        <div className="row" style={{ gap: 8, marginTop: 8 }}>
          <button className="btn btn-sm btn-ghost" disabled={busy || content === draft.content}
            onClick={save}>수정 저장</button>
          <button className="btn btn-sm btn-primary" disabled={busy} onClick={confirm}>확정</button>
        </div>
      )}
    </div>
  );
}

function ObservationCard({ row, onChanged }) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <ObservationForm studentId={row.student_id} editRow={row}
        onDone={() => { setEditing(false); onChanged(); }}
        onCancel={() => setEditing(false)} />
    );
  }

  const del = async () => {
    if (!window.confirm("이 관찰 기록을 삭제할까요?")) return;
    await api.deleteObservation(row.id);
    onChanged();
  };

  return (
    <div className="timeline-item">
      <div className="timeline-head">
        <span className="timeline-date">{row.observed_at}</span>
        {row.subject_name && <span className="badge">{row.subject_name}</span>}
        {row.title && <span className="meta">{row.title}</span>}
      </div>
      <p className="timeline-body">{row.content}</p>
      <div className="row" style={{ gap: 4, marginTop: 8 }}>
        <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>수정</button>
        <button className="btn btn-sm btn-ghost" onClick={del}>삭제</button>
        {row.journal_id && (
          <Link className="btn btn-sm btn-ghost" to={`/students/${row.student_id}`}>관련 학생 기록 보기</Link>
        )}
      </div>
    </div>
  );
}

/** 작성/수정 폼. 일지에서 넘어오면 학생·날짜·과목이 미리 채워진다. */
function ObservationForm({ studentId, editRow, initialJournalId, initialSubjectId, initialDate,
                          onDone, onCancel }) {
  const [observedAt, setObservedAt] = useState(
    editRow?.observed_at || initialDate || new Date().toISOString().slice(0, 10));
  const [title, setTitle] = useState(editRow?.title || "");
  const [content, setContent] = useState(editRow?.content || "");
  const [subjectId, setSubjectId] = useState(
    editRow?.subject_id ?? initialSubjectId ?? "");
  const [journalId] = useState(editRow?.journal_id ?? initialJournalId ?? null);
  const [subjects, setSubjects] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.mySubjects().then((list) => {
      setSubjects(list);
      // 담당 과목이 하나뿐이면 굳이 고르게 하지 않고 바로 채워 둔다.
      // 여럿이면 첫 번째를 기본값으로 보여주되 바꿀 수 있게 둔다 —
      // 과목 선택 자체를 생략할 수는 없다(반드시 하나를 골라야 한다).
      if (!editRow && !subjectId && list.length > 0) setSubjectId(list[0].subject_id);
    }).catch(() => {});
    api.observationTemplates().then(setTemplates).catch(() => {});
  }, []);

  const insertPhrase = (phrase) => {
    setContent((cur) => (cur ? `${cur} ${phrase}` : phrase));
  };

  const proofread = async () => {
    if (!content.trim()) return;
    setBusy(true); setError("");
    try {
      const job = await api.requestProofread(content, "TEXT_EDIT");
      const result = await api.waitAiJob(job.job_id);
      setContent(result.result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!content.trim()) { setError("관찰 내용을 적어주세요."); return; }
    if (subjects.length > 0 && !subjectId) { setError("과목을 선택해주세요."); return; }
    setBusy(true); setError("");
    const body = {
      observed_at: observedAt, title, content,
      subject_id: subjectId || null, journal_id: journalId || null,
    };
    try {
      if (editRow) await api.updateObservation(editRow.id, body);
      else await api.createObservation({ student_id: studentId, ...body });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveTemplate = async () => {
    const label = window.prompt("이 문구를 부를 짧은 이름 (예: 문제 해결)");
    if (!label || !content.trim()) return;
    try {
      const t = await api.createObservationTemplate(label, content.trim());
      setTemplates((cur) => [...cur, t]);
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <div className="field" style={{ maxWidth: 160 }}>
          <span className="label">관찰 날짜</span>
          <input className="input" type="date" value={observedAt}
            onChange={(e) => setObservedAt(e.target.value)} />
        </div>
        {subjects.length > 0 && (
          <div className="field" style={{ maxWidth: 220 }}>
            <span className="label">과목</span>
            <select className="select" value={subjectId}
              onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : "")}>
              {subjects.map((s) => (
                <option key={s.subject_id} value={s.subject_id}>{s.subject_name}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {journalId && (
        <p className="meta" style={{ marginTop: 8 }}>
          <Link to={`/students/${studentId}`}>연결된 학생 기록 보기</Link>
        </p>
      )}

      <div className="field" style={{ marginTop: 10 }}>
        <span className="label">제목(선택)</span>
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>

      <div className="field" style={{ marginTop: 10 }}>
        <span className="label">관찰 내용</span>
        <textarea className="input" rows={4} value={content}
          onChange={(e) => setContent(e.target.value)}
          style={{ width: "100%", fontFamily: "inherit" }} />
      </div>

      <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        {QUICK_PHRASES.map((p) => (
          <button key={p} type="button" className="btn btn-sm btn-ghost" onClick={() => insertPhrase(p)}>
            {p}
          </button>
        ))}
      </div>

      {templates.length > 0 && (
        <div className="row" style={{ gap: 6, marginTop: 6, flexWrap: "wrap" }}>
          {templates.map((t) => (
            <button key={t.id} type="button" className="btn btn-sm btn-ghost"
              onClick={() => insertPhrase(t.content)} title={t.content}>
              {t.title}
            </button>
          ))}
        </div>
      )}

      <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button className="btn btn-sm btn-ghost" disabled={busy || !content.trim()} onClick={proofread}>
          AI로 다듬기
        </button>
        <button className="btn btn-sm btn-ghost" disabled={!content.trim()} onClick={saveTemplate}>
          내 문구로 저장
        </button>
      </div>

      {error && <div className="notice notice-error" style={{ marginTop: 8 }}>{error}</div>}

      <div className="row" style={{ gap: 8, marginTop: 12 }}>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "저장 중…" : "저장"}
        </button>
        <button className="btn btn-ghost" onClick={onCancel}>취소</button>
      </div>
    </div>
  );
}
