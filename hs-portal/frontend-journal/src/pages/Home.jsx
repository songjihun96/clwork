import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

const STAGE_LABEL = {
  interest: "관심 탐색", topic: "주제 선정", question: "연구 질문", plan: "연구 계획",
  literature: "문헌 조사", method: "연구 설계", execution: "실행", data: "데이터 수집",
  analysis: "분석", discussion: "논의", final: "최종 산출물",
};

const KIND_LABEL = { lesson: "수업 일지", diary: "학교생활 일기" };

// "YYYY-MM-DD" — toISOString은 UTC라 자정 근처에 날짜가 하루 밀릴 수 있어
// 브라우저 로컬 시각 그대로 문자열을 만든다.
function localDateKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 연속으로 기록을 남긴 날 수. 오늘 아직 안 썼어도 어제까지 이어졌다면
// 스트릭이 끊긴 것으로 보지 않는다(오늘 하루는 아직 안 끝났으니까) —
// 대신 이틀 이상 비면 그날부터 스트릭은 0이다.
function computeStreak(journals) {
  const dates = new Set((journals || []).map((j) => j.entry_date));
  const cursor = new Date();
  if (!dates.has(localDateKey(cursor))) cursor.setDate(cursor.getDate() - 1);
  let streak = 0;
  while (dates.has(localDateKey(cursor))) {
    streak++;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

export default function Home() {
  const { user } = useAuth();
  const [journals, setJournals] = useState(null);
  const [notif, setNotif] = useState(null);

  useEffect(() => {
    api.journals().then(setJournals).catch(() => setJournals([]));
    api.notificationsSummary().then(setNotif).catch(() => setNotif(null));
  }, []);

  const recentJournals = (journals || []).slice(0, 3);
  const streak = journals ? computeStreak(journals) : 0;

  return (
    <div className="wrap page">
      <span className="label">홈</span>
      <h1 style={{ marginTop: 4 }}>{user?.name ? `${user.name}님, 안녕하세요` : "안녕하세요"}</h1>
      <p style={{ color: "var(--steel)", lineHeight: 1.8, marginTop: 0 }}>
        오늘의 기록을 한눈에 볼 수 있어요.
      </p>

      {(streak > 0 || notif?.unread_journal_feedback > 0) && (
        <div className="row" style={{ gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          {streak > 0 && (
            <span className="badge badge-done" style={{ fontSize: 13, padding: "5px 10px" }}>
              🔥 {streak}일 연속 기록 중
            </span>
          )}
          {notif?.unread_journal_feedback > 0 && (
            <Link to="/journals" className="badge badge-new" style={{ fontSize: 13, padding: "5px 10px" }}>
              선생님 한마디 {notif.unread_journal_feedback}건 도착
            </Link>
          )}
        </div>
      )}

      <SectionLabel>최근 기록</SectionLabel>
      {journals === null ? (
        <p className="meta">불러오는 중…</p>
      ) : recentJournals.length === 0 ? (
        <div className="empty">
          <h3>아직 기록이 없습니다</h3>
          <p>오늘 있었던 일부터 한 줄 남겨보세요.</p>
          <Link to="/journals/new" className="btn btn-primary" style={{ marginTop: 12 }}>첫 기록 쓰기</Link>
        </div>
      ) : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 8 }}>
            {recentJournals.map((it) => (
              <Link key={it.id} to={`/journals/${it.id}`} className="entry">
                <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                  <span className="badge">{KIND_LABEL[it.kind] || it.kind}</span>
                  {it.feedback_unread && <span className="badge badge-new">선생님 한마디 도착</span>}
                </div>
                <h4>{it.title || it.subject || it.entry_date}</h4>
                <div className="meta">{it.entry_date}{it.subject && it.title ? ` · ${it.subject}` : ""}</div>
              </Link>
            ))}
          </div>
          <Link to="/journals" className="meta" style={{ fontSize: 12.5, display: "inline-block", marginTop: 8 }}>
            내 기록 전체보기 →
          </Link>
        </>
      )}
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div className="label" style={{ marginTop: 26, marginBottom: 10 }}>{children}</div>
  );
}
