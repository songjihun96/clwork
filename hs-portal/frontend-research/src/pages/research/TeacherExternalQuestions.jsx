import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import "../../research-theme.css";

/** 다른 학교 학생의 질문에 답하는 화면. 담임 학급과 무관한 완전히 별도
 *  경로다 — 분야 태그를 등록해야만(옵트인) 질문이 보인다. 학생 신원·학교는
 *  절대 안 보여준다(양방향 익명). */
export default function TeacherExternalQuestions() {
  const [tags, setTags] = useState(null);
  const [newTag, setNewTag] = useState("");
  const [questions, setQuestions] = useState(null);
  const [error, setError] = useState("");

  const load = () => {
    api.myFieldTags().then((r) => setTags(r.items)).catch((e) => setError(e.message));
    api.matchedExternalQuestions().then((r) => setQuestions(r.items)).catch(() => setQuestions([]));
  };
  useEffect(load, []);

  const addTag = async () => {
    const tag = newTag.trim();
    if (!tag) return;
    try {
      await api.addFieldTag(tag);
      setNewTag("");
      load();
    } catch (e) { setError(e.message); }
  };

  const removeTag = async (id) => {
    try { await api.removeFieldTag(id); load(); }
    catch (e) { setError(e.message); }
  };

  if (error) {
    return <div className="research-theme wrap page"><div className="notice notice-error">{error}</div></div>;
  }
  if (!tags || questions === null) {
    return <div className="research-theme wrap page"><p>불러오는 중…</p></div>;
  }

  return (
    <div className="research-theme wrap page" style={{ maxWidth: 760 }}>
      <Link to="/research/teacher" className="label">← 연구 현황</Link>
      <h1 style={{ marginTop: 8 }}>외부 학생 질문</h1>
      <p style={{ fontSize: 13.5, color: "var(--color-text-secondary)" }}>
        다른 학교 학생이 남긴 질문 중, 아래 등록한 분야와 겹치는 것만 보여드려요.
        어느 학생인지는 서로 알 수 없어요.
      </p>

      <div className="panel" style={{ marginTop: 14 }}>
        <h3 style={{ margin: "0 0 8px" }}>내 분야</h3>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          {tags.length === 0 && <span className="meta">등록한 분야가 없어요. 하나 이상 등록해야 질문이 보여요.</span>}
          {tags.map((t) => (
            <span key={t.id} className="badge" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {t.tag}
              <button onClick={() => removeTag(t.id)}
                style={{ border: "none", background: "none", cursor: "pointer", padding: 0,
                  color: "var(--color-text-muted)" }}>×</button>
            </span>
          ))}
        </div>
        <div className="row" style={{ gap: 6, marginTop: 10 }}>
          <input className="input" style={{ maxWidth: 200 }} placeholder="예: 생물, 컴퓨터공학"
            value={newTag} onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTag()} />
          <button className="btn btn-sm" onClick={addTag}>추가</button>
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        <h3>매칭된 질문 ({questions.length})</h3>
        {questions.length === 0 ? (
          <p className="meta">지금은 맞는 질문이 없어요.</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {questions.map((q) => (
              <QuestionCard key={q.id} question={q} onAnswered={load} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function QuestionCard({ question, onAnswered }) {
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    if (!answer.trim()) return setMsg("답변 내용을 입력해주세요.");
    setBusy(true); setMsg("");
    try {
      await api.answerExternalQuestion(question.id, answer);
      setMsg("답변을 보냈어요.");
      setAnswer("");
      onAnswered();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <b>{question.title || "(제목 없음)"}</b>
        <div className="spacer" />
        {question.field_tags.map((t) => <span key={t} className="badge">{t}</span>)}
        {question.answered_by_me && <span className="badge badge-done">이미 답변함</span>}
      </div>
      <p className="meta" style={{ marginTop: 2 }}>{question.research_title}</p>
      <p style={{ margin: "6px 0", fontSize: 13.5 }}>{question.body}</p>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        <textarea className="textarea" rows={3} placeholder="답변을 입력하세요"
          value={answer} onChange={(e) => setAnswer(e.target.value)} />
        {msg && <p className="meta">{msg}</p>}
        <div>
          <button className="btn btn-sm" onClick={submit} disabled={busy}>
            {busy ? "보내는 중…" : "답변 보내기"}
          </button>
        </div>
      </div>
    </div>
  );
}
