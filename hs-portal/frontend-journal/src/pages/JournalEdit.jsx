import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";

const today = () => new Date().toISOString().slice(0, 10);
const DAYS = ["일", "월", "화", "수", "목", "금", "토"];

function formatDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return { text: iso, day: "" };
  return {
    text: `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`,
    day: `${DAYS[d.getDay()]}요일`,
  };
}

// 날씨 칸. 일기장 맨 위에 늘 있던 그 칸이다.
const WEATHERS = [
  { key: "sun", label: "맑음",
    path: <><circle cx="12" cy="12" r="4.4" /><path d="M12 2v2.4M12 19.6V22M2 12h2.4M19.6 12H22M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M19.1 4.9l-1.7 1.7M6.6 17.4l-1.7 1.7" /></> },
  { key: "cloud", label: "흐림",
    path: <path d="M7.5 18h9a3.8 3.8 0 0 0 .3-7.6A5.4 5.4 0 0 0 6.7 11 3.5 3.5 0 0 0 7.5 18z" /> },
  { key: "rain", label: "비",
    path: <><path d="M7.5 14h9a3.6 3.6 0 0 0 .3-7.2A5.2 5.2 0 0 0 6.8 7.4 3.4 3.4 0 0 0 7.5 14z" /><path d="M9 17.5l-1 3M13 17.5l-1 3M17 17.5l-1 3" /></> },
  { key: "snow", label: "눈",
    path: <><path d="M7.5 13h9a3.6 3.6 0 0 0 .3-7.2A5.2 5.2 0 0 0 6.8 6.4 3.4 3.4 0 0 0 7.5 13z" /><path d="M9 17v3M15 17v3M12 18.5v3M7.8 18.5h2.4M13.8 18.5h2.4" /></> },
];

function WeatherIcon({ item }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {item.path}
    </svg>
  );
}

// 내용에 맞춰 높이를 늘린다.
function useAutoGrow(value) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 96)}px`;
  }, [value]);
  return ref;
}

function Field({ label, value, onChange }) {
  const ref = useAutoGrow(value);
  return (
    <div className="journal-section field">
      <span className="label">{label}</span>
      <textarea ref={ref} className="textarea" value={value}
        placeholder="여기에 적어보세요" onChange={onChange} />
    </div>
  );
}

export default function JournalEdit() {
  const { id } = useParams();
  // 무엇을 쓸지는 '새로 쓰기'에서 이미 골랐다(내 기록 화면). 여기서 다시
  // 바꾸게 하면 다 쓴 글의 항목이 통째로 갈리는 사고가 난다.
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const isNew = !id;

  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState({
    kind: search.get("kind") === "lesson" ? "lesson" : "diary",
    entry_date: today(), title: "", subject: "", teacher_name: "", content: {},
  });
  const [sentAt, setSentAt] = useState(null);
  const [feedback, setFeedback] = useState(null);   // 선생님이 남긴 한마디
  const [shareToken, setShareToken] = useState(""); // 공유 링크 토큰
  const [shareBusy, setShareBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [subjects, setSubjects] = useState(null);   // 학교에서 열리는 과목
  const [spell, setSpell] = useState(null);         // 맞춤법 지적
  const [checking, setChecking] = useState(false);
  const [manualSubject, setManualSubject] = useState(false);  // 목록에 없는 과목 직접 입력

  useEffect(() => {
    api.journalMeta().then(setMeta).catch(() => {});
    api.journalSubjects().then(setSubjects).catch(() => setSubjects(null));
  }, []);

  // 저장된 교과가 목록에 없으면(직접 입력해 둔 것) 입력칸으로 연다.
  useEffect(() => {
    if (!subjects || !form.subject) return;
    if (!subjects.subjects.includes(form.subject)) setManualSubject(true);
  }, [subjects, form.subject]);

  useEffect(() => {
    if (isNew) return;
    api.journal(id)
      .then((d) => {
        setForm({
          kind: d.kind, entry_date: d.entry_date, title: d.title || "",
          subject: d.subject || "", teacher_name: d.teacher_name || "",
          content: d.content || {},
        });
        setSentAt(d.sent_at || null);
        setShareToken(d.share_token || "");
        setFeedback(
          d.feedback
            ? { text: d.feedback, by: d.feedback_by_name || "", at: d.feedback_at || null }
            : null
        );
      })
      .catch((e) => setMsg({ type: "error", text: e.message }));
  }, [id, isNew]);

  const shareUrl = shareToken ? `${window.location.origin}/journal-share/${shareToken}` : "";

  const toggleShare = async () => {
    setShareBusy(true);
    setMsg(null);
    try {
      if (shareToken) {
        if (!confirm("공유를 끊을까요? 이미 보낸 링크도 열리지 않게 됩니다.")) return;
        await api.revokeShare(id);
        setShareToken("");
        setMsg({ type: "ok", text: "공유를 끊었습니다." });
      } else {
        const r = await api.createShare(id);
        setShareToken(r.share_token);
        setMsg({ type: "ok", text: "링크를 만들었습니다. 아래 주소를 복사해 보내세요." });
      }
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setShareBusy(false);
    }
  };

  const fields = useMemo(() => {
    if (!meta) return [];
    const found = meta.kinds.find((k) => k.kind === form.kind);
    return found ? found.fields : [];
  }, [meta, form.kind]);

  const setContent = (key) => (e) =>
    setForm((f) => ({ ...f, content: { ...f.content, [key]: e.target.value } }));

  const setWeather = (key) =>
    setForm((f) => ({
      ...f,
      content: { ...f.content, weather: f.content.weather === key ? "" : key },
    }));

  const runSpellcheck = async () => {
    setChecking(true);
    setSpell(null);
    try {
      const labels = Object.fromEntries(fields.map((f) => [f.key, f.label]));
      const target = {};
      for (const f of fields) {
        const t = (form.content[f.key] || "").trim();
        if (t) target[f.key] = t;
      }
      if (Object.keys(target).length === 0) {
        setSpell({ empty: true });
        return;
      }
      const r = await api.spellcheck(target);
      const flat = [];
      for (const [key, items] of Object.entries(r.results || {})) {
        for (const it of items) flat.push({ ...it, fieldLabel: labels[key] || key });
      }
      setSpell({ items: flat });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setChecking(false);
    }
  };

  const save = async () => {
    if (!form.title.trim()) {
      setMsg({ type: "error", text: "제목을 적어주세요." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const body = { ...form, resume_tags: [] };
      if (isNew) {
        const r = await api.createJournal(body);
        navigate(`/journals/${r.id}`, { replace: true });
      } else {
        await api.updateJournal(id, body);
      }
      setMsg({ type: "ok", text: "저장했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const submitToTeacher = async () => {
    if (!confirm("선생님께 제출할까요? 제출한 뒤에도 내용은 고칠 수 있습니다.")) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.submitJournal(id);
      if (r?.share_token) setShareToken(r.share_token);
      setSentAt(new Date().toISOString());
      setMsg({ type: "ok", text: "선생님께 제출했습니다." });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm("이 기록을 지울까요? 되돌릴 수 없습니다.")) return;
    try {
      await api.deleteJournal(id);
      navigate("/journals", { replace: true });
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    }
  };

  if (!meta) return <div className="wrap page"><p>펼치는 중…</p></div>;

  const { text: dateText, day } = formatDate(form.entry_date);
  const isLesson = form.kind === "lesson";
  const kindLabel = (meta.kinds.find((k) => k.kind === form.kind) || {}).label || "일지";

  return (
    <div className="wrap page" style={{ maxWidth: 720 }}>
      <div className="row">
        <h1 style={{ margin: 0, fontSize: 20 }}>{kindLabel}</h1>
        <div className="spacer" />
        {sentAt && <span className="badge badge-done">제출함</span>}
      </div>
      <p className="meta" style={{ margin: "6px 0 0", lineHeight: 1.6 }}>
        {isLesson
          ? "제출하면 이 과목 선생님이 읽어 봅니다."
          : "제출하면 담임 선생님이 읽어 봅니다."}
      </p>

      {msg && <div className={`notice notice-${msg.type}`} style={{ marginTop: 12 }}>{msg.text}</div>}

      {/* 선생님 한마디. 학생이 가장 먼저 보고 싶어 하는 것이라 본문 위에 둔다. */}
      {feedback && (
        <div className="feedback-card">
          <div className="label">선생님 한마디</div>
          <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.75, margin: "6px 0 0" }}>
            {feedback.text}
          </p>
          <div className="meta" style={{ marginTop: 8 }}>
            {feedback.by ? `${feedback.by} 선생님` : "선생님"}
            {feedback.at ? ` · ${String(feedback.at).slice(0, 10)}` : ""}
          </div>
        </div>
      )}

      <article className="journal-card">
        <header className="journal-head">
          <div className="journal-date">
            <input type="date" value={form.entry_date} max={today()} aria-label="날짜"
              onChange={(e) => setForm({ ...form, entry_date: e.target.value })} />
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text-muted)", marginTop: 2 }}>
              {dateText}<span className="journal-day">{day}</span>
            </div>
          </div>

          {isLesson ? (
            <div className="journal-meta subject-pick">
              {subjects && subjects.subjects.length > 0 && !manualSubject ? (
                <select
                  value={subjects.subjects.includes(form.subject) ? form.subject : (form.subject ? "__keep" : "")}
                  aria-label="교과명"
                  onChange={(e) => {
                    if (e.target.value === "__other") {
                      setManualSubject(true);
                      setForm({ ...form, subject: "" });
                      return;
                    }
                    if (e.target.value === "__keep") return;
                    setForm({ ...form, subject: e.target.value });
                  }}
                >
                  <option value="">교과 선택</option>
                  {subjects.subjects.map((n) => <option key={n} value={n}>{n}</option>)}
                  {form.subject && !subjects.subjects.includes(form.subject) && (
                    <option value="__keep">{form.subject}</option>
                  )}
                  <option value="__other">직접 입력…</option>
                </select>
              ) : (
                <>
                  <input value={form.subject} placeholder="교과명" aria-label="교과명"
                    autoFocus={manualSubject}
                    onChange={(e) => setForm({ ...form, subject: e.target.value })} />
                  {/* 직접 입력으로 넘어오면 목록으로 돌아갈 길이 있어야 한다 */}
                  {subjects && subjects.subjects.length > 0 && (
                    <button type="button" className="btn btn-sm btn-ghost"
                      onClick={() => { setManualSubject(false); setForm({ ...form, subject: "" }); }}>
                      목록에서 고르기
                    </button>
                  )}
                </>
              )}
              <input value={form.teacher_name} placeholder="선생님" aria-label="선생님 성함"
                onChange={(e) => setForm({ ...form, teacher_name: e.target.value })} />
            </div>
          ) : (
            <div className="journal-weather" role="group" aria-label="오늘의 날씨">
              {WEATHERS.map((w) => (
                <button key={w.key} type="button" title={w.label} aria-label={w.label}
                  aria-pressed={form.content.weather === w.key}
                  onClick={() => setWeather(w.key)}>
                  <WeatherIcon item={w} />
                </button>
              ))}
            </div>
          )}
        </header>

        <div className="journal-section field">
          <span className="label">제목</span>
          <input className="journal-title" value={form.title}
            placeholder="오늘의 제목을 적어보세요" maxLength={120} aria-label="제목"
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>

        {fields.map((f) => (
          <Field key={f.key} label={f.label}
            value={form.content[f.key] || ""} onChange={setContent(f.key)} />
        ))}
      </article>

      <div className="journal-actions">
        <button className="btn" onClick={runSpellcheck} disabled={checking}>
          {checking ? "살펴보는 중…" : "맞춤법 살펴보기"}
        </button>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "적는 중…" : "저장"}
        </button>
        {!isNew && (
          <>
            <button className="btn" onClick={submitToTeacher} disabled={busy}>
              {sentAt ? "다시 제출" : "선생님께 제출"}
            </button>
            <button className="btn" onClick={toggleShare} disabled={shareBusy}>
              {shareToken ? "공유 끊기" : "링크로 공유"}
            </button>
            <div className="spacer" />
            <button className="btn btn-ghost" onClick={remove}>지우기</button>
          </>
        )}
      </div>

      {/* 공유 링크. 로그인 없이 열리므로 어디까지 보이는지 분명히 알려준다. */}
      {shareUrl && (
        <div className="share-box">
          <div className="label">공유 링크</div>
          <p className="meta" style={{ margin: "4px 0 8px" }}>
            이 주소를 아는 사람은 누구나 <b>로그인 없이</b> 이 일지를 읽을 수 있습니다.
            학교·학년·연락처는 보이지 않고, 내용과 이름만 보입니다.
          </p>
          <div className="row" style={{ gap: 8 }}>
            <input className="input" readOnly value={shareUrl} onFocus={(e) => e.target.select()}
              style={{ flex: 1, fontSize: 13 }} />
            <button className="btn btn-sm"
              onClick={() => {
                navigator.clipboard?.writeText(shareUrl);
                setMsg({ type: "ok", text: "주소를 복사했습니다." });
              }}>
              복사
            </button>
          </div>
        </div>
      )}

      {spell && (
        <div className="spell">
          {spell.empty && <p style={{ margin: 0, fontSize: 14 }}>먼저 내용을 적어주세요.</p>}
          {spell.items && spell.items.length === 0 && (
            <p style={{ margin: 0, fontSize: 14 }}>
              고칠 만한 표현을 찾지 못했습니다. 다만 모든 오타를 잡아내지는 못합니다.
            </p>
          )}
          {spell.items && spell.items.length > 0 && (
            <>
              <h4>고쳐 볼 만한 곳 {spell.items.length}군데</h4>
              {spell.items.map((it, i) => (
                <div className="spell-item" key={i}>
                  <span className={`spell-tag ${it.level === "maybe" ? "maybe" : ""}`}>
                    {it.level === "maybe" ? "확인" : "고침"}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span className="spell-fix">{it.found} → {it.suggest}</span>
                    <span className="spell-why"> · {it.reason}</span>
                    <span className="spell-why" style={{ display: "block", fontSize: 12 }}>
                      {it.fieldLabel}
                    </span>
                  </span>
                </div>
              ))}
              <p style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--steel-light)", lineHeight: 1.7 }}>
                자주 틀리는 표현만 찾습니다. 고칠지는 직접 정하세요.
                &lsquo;확인&rsquo;은 문맥에 따라 맞을 수도 있는 표현입니다.
              </p>
            </>
          )}
        </div>
      )}

      {!isNew && (
        <p style={{ fontSize: 13, color: "var(--steel)", marginTop: 16, lineHeight: 1.8 }}>
          선생님께 제출하는 기능은 무료입니다.
          모아둔 기록을 자기소개서로 옮기려면 <a href="/cover-letters">자기소개서</a>로 가세요.
        </p>
      )}
    </div>
  );
}
