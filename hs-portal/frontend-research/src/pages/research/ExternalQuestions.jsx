import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

// AI 호출은 다 만들어질 때까지 기다렸다가 한 번에 받으므로, 다른 연구
// 화면과 같은 방식으로 체감 진행률만 보여준다.
function estimateAiProgress(seconds, expectedSeconds) {
  const pct = 90 * (1 - Math.exp(-seconds / expectedSeconds));
  return Math.min(90, Math.round(pct));
}

function AiGauge({ percent }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, maxWidth: 220 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--color-border)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", background: "var(--color-primary)",
          transition: "width .3s ease" }} />
      </div>
      <span style={{ fontSize: 11.5, color: "var(--color-text-muted)", minWidth: 32, textAlign: "right" }}>
        {percent}%
      </span>
    </div>
  );
}

const STAGE_LABEL = { literature: "문헌·배경지식", method: "연구 방법",
  analysis: "데이터 분석", discussion: "해석·논의" };

export default function ExternalQuestions() {
  const { id } = useParams();
  const [research, setResearch] = useState(null);
  const [questions, setQuestions] = useState(null);
  const [notes, setNotes] = useState([]);
  const [error, setError] = useState("");

  const load = () => {
    api.getResearch(id).then(setResearch).catch((e) => setError(e.message));
    api.listExternalQuestions(id).then((r) => setQuestions(r.items)).catch(() => setQuestions([]));
    api.listAnswerNotes(id).then((r) => setNotes(r.items)).catch(() => {});
  };
  useEffect(load, [id]);
  // 답변을 보러 들어온 시점을 "확인함"으로 남긴다 — 홈 화면의 "새 답변" 배지가
  // 이 시각 이후에 온 답변만 새것으로 센다.
  useEffect(() => { api.markExternalAnswersSeen(id).catch(() => {}); }, [id]);

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!research || questions === null) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page" style={{ maxWidth: 760 }}>
      <Link to={`/research/${id}`} className="label">← {research.title || research.interest_keyword}</Link>
      <h1 style={{ marginTop: 8 }}>외부 선생님께 질문하기</h1>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
        다른 학교 선생님께 궁금한 점을 물어볼 수 있어요. 어떤 선생님이 답했는지는 서로 알 수 없고,
        분야는 AI가 알아서 추천해서 맞는 선생님께 전달돼요.
      </p>

      <AskPanel researchId={id} researchTitle={research.title || research.interest_keyword}
        onCreated={load} />

      {notes.length > 0 && <NotesPanel notes={notes} onChanged={load} />}

      <QuestionList researchId={id} questions={questions} onChanged={load} />
    </div>
  );
}

function AskPanel({ researchId, onCreated }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    if (!body.trim()) return setMsg("질문 내용을 입력해주세요.");
    setBusy(true); setMsg("");
    try {
      await api.createExternalQuestion(researchId, title, body);
      setTitle(""); setBody(""); setMsg("질문을 올렸어요. 맞는 선생님이 보시면 답변이 달려요.");
      onCreated();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <h3 style={{ margin: "0 0 8px" }}>새 질문</h3>
      <div style={{ display: "grid", gap: 8 }}>
        <input className="input" placeholder="제목 (선택)" value={title}
          onChange={(e) => setTitle(e.target.value)} />
        <textarea className="textarea" rows={3} placeholder="무엇이 궁금한가요?"
          value={body} onChange={(e) => setBody(e.target.value)} />
      </div>
      {msg && <p className="meta" style={{ marginTop: 6 }}>{msg}</p>}
      <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={submit} disabled={busy}>
        {busy ? "올리는 중…" : "질문 올리기"}
      </button>
    </div>
  );
}

function NotesPanel({ notes, onChanged }) {
  const [busyId, setBusyId] = useState(null);

  const approve = async (id) => {
    setBusyId(id);
    try { await api.approveAnswerNote(id); onChanged(); }
    catch (e) { alert(e.message); }
    finally { setBusyId(null); }
  };
  const discard = async (id) => {
    setBusyId(id);
    try { await api.discardAnswerNote(id); onChanged(); }
    catch (e) { alert(e.message); }
    finally { setBusyId(null); }
  };

  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <h3 style={{ margin: "0 0 8px" }}>연구에 반영할 내용</h3>
      <p className="meta">AI가 정리한 내용이에요. 승인해야만 논문에 참고자료로 들어가요.</p>
      <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
        {notes.map((n) => (
          <div key={n.id} className="entry" style={{ cursor: "default" }}>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              {n.suggested_stage && <span className="badge">{STAGE_LABEL[n.suggested_stage]}</span>}
              <span className="badge" style={{ marginLeft: "auto" }}>
                {n.approved ? "승인됨" : "승인 대기"}
              </span>
            </div>
            <p style={{ margin: "6px 0", fontSize: 13.5 }}>{n.note}</p>
            {!n.approved && (
              <div className="row" style={{ gap: 6 }}>
                <button className="btn btn-sm" disabled={busyId === n.id}
                  onClick={() => approve(n.id)}>승인</button>
                <button className="btn btn-sm btn-ghost" disabled={busyId === n.id}
                  onClick={() => discard(n.id)}>지우기</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function QuestionList({ researchId, questions, onChanged }) {
  return (
    <div style={{ marginTop: 14 }}>
      <h3>내 질문 ({questions.length})</h3>
      {questions.length === 0 ? (
        <p className="meta">아직 올린 질문이 없어요.</p>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {questions.map((q) => (
            <QuestionCard key={q.id} researchId={researchId} question={q} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}

function QuestionCard({ researchId, question, onChanged }) {
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState(null);

  const toggleOpen = () => {
    if (!open && answers === null) {
      api.listExternalAnswers(question.id).then((r) => setAnswers(r.items)).catch(() => setAnswers([]));
    }
    setOpen((v) => !v);
  };

  return (
    <div className="panel">
      <div className="row" style={{ gap: 8, alignItems: "center", cursor: "pointer" }} onClick={toggleOpen}>
        <b>{question.title || "(제목 없음)"}</b>
        <div className="spacer" />
        {question.field_tags.map((t) => <span key={t} className="badge">{t}</span>)}
        <span className="badge">{question.answer_count > 0 ? `답변 ${question.answer_count}개` : "답변 대기"}</span>
      </div>
      <p style={{ margin: "6px 0", fontSize: 13.5, color: "var(--color-text-secondary)" }}>{question.body}</p>
      {open && (
        <div style={{ marginTop: 8, borderTop: "1px solid var(--color-border)", paddingTop: 8 }}>
          {answers === null ? (
            <p className="meta">불러오는 중…</p>
          ) : answers.length === 0 ? (
            <p className="meta">아직 답변이 없어요.</p>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {answers.map((a) => <AnswerRow key={a.id} answer={a} onChanged={onChanged} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnswerRow({ answer, onChanged }) {
  const [helpful, setHelpful] = useState(answer.helpful);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [reflected, setReflected] = useState(answer.reflected);

  const toggleHelpful = async () => {
    try {
      const r = await api.toggleAnswerHelpful(answer.id);
      setHelpful(r.helpful);
    } catch (e) { alert(e.message); }
  };

  const reflect = async () => {
    setBusy(true); setProgress(0);
    try {
      const { job_id } = await api.reflectAnswer(answer.id);
      await api.waitAiJob(job_id, { onTick: (s) => setProgress(estimateAiProgress(s, 5)) });
      setProgress(100);
      setReflected(true);
      onChanged();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="row" style={{ gap: 6, alignItems: "center" }}>
        <span className="meta">교사 답변</span>
        <span className="meta">{answer.created_at?.slice(0, 10)}</span>
      </div>
      <p style={{ margin: "4px 0", fontSize: 13.5, whiteSpace: "pre-wrap" }}>{answer.body}</p>
      <div className="row" style={{ gap: 6 }}>
        <button className={`btn btn-sm ${helpful ? "" : "btn-ghost"}`} onClick={toggleHelpful}>
          {helpful ? "도움됐어요 ✓" : "도움됐어요"}
        </button>
        <button className="btn btn-sm btn-ghost" onClick={reflect} disabled={busy || reflected}>
          {reflected ? "반영 요청됨" : busy ? "정리하는 중…" : "연구에 반영하기"}
        </button>
      </div>
      {busy && <AiGauge percent={progress} />}
    </div>
  );
}
