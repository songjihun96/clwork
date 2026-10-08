import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import SavedDialog from "../components/SavedDialog";
import { api } from "../api";
import { useAuth } from "../auth";

/** 학생 홈(로그인 후). 첫 화면 시안(기록해 첫 화면.pdf)과 같은 모양으로, 내용은
 *  **내 실제 기록**으로 채운다 — 최근 일지 카드, 그 일지가 연결된 자기소개서 문항,
 *  문항별로 모인 내 기록 수. 예전 홈의 기능(저장 완료 창, 연속 기록, 선생님 한마디,
 *  최근 기록과 종류 필터)은 그대로 둔다. */

const KIND_LABEL = { lesson: "수업일지", diary: "학교생활일지" };
// 홈의 기록 필터. 주소(?type=)에 남겨 새로고침해도 유지한다.
const TYPE_TABS = [["all", "전체보기"], ["class", "수업일지"], ["school", "학교생활일지"]];
const TYPE_KEYS = TYPE_TABS.map(([k]) => k);
const RECENT_COUNT = 6;

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

const fmtDay = (d) => {
  if (!d) return "";
  const [, m, day] = String(d).split("-");
  return `${Number(m)}월 ${Number(day)}일`;
};
const kindTag = (k) => (k === "lesson" ? "lp-tag lesson" : "lp-tag diary");

export default function Home() {
  const { user } = useAuth();
  const [journals, setJournals] = useState(null);   // 전체(연속 기록·문항별 집계용)
  const [shown, setShown] = useState(null);         // 고른 종류의 기록
  const [notif, setNotif] = useState(null);
  const [topics, setTopics] = useState([]);         // 자기소개서 문항 [{key,label}]
  const [search, setSearch] = useSearchParams();
  const type = TYPE_KEYS.includes(search.get("type")) ? search.get("type") : "all";
  const location = useLocation();
  const navigate = useNavigate();
  // 일지 화면에서 [저장]하고 넘어온 경우 완료 창을 띄운다. 한 번 띄우면 기록을 지워
  // 새로고침했을 때 다시 뜨지 않게 한다.
  const [saved, setSaved] = useState(null);
  useEffect(() => {
    if (location.state?.saved) {
      setSaved(location.state.saved);
      navigate(location.pathname + location.search, { replace: true, state: null });
    }
  }, [location.key]);

  useEffect(() => {
    api.journals().then(setJournals).catch(() => setJournals([]));
    api.notificationsSummary().then(setNotif).catch(() => setNotif(null));
    api.journalMeta().then((m) => setTopics(m.resume_categories || [])).catch(() => setTopics([]));
  }, []);

  // 종류를 고르면 서버에서 그 종류만 받아 온다.
  useEffect(() => {
    setShown(null);
    api.journals(type).then(setShown).catch(() => setShown([]));
  }, [type]);

  const recentJournals = (shown || []).slice(0, RECENT_COUNT);
  const streak = journals ? computeStreak(journals) : 0;

  // 문항별로 연결된 내 일지
  const byTopic = useMemo(() => {
    const m = {};
    for (const j of journals || []) for (const k of j.resume_tags || []) (m[k] ||= []).push(j);
    return m;
  }, [journals]);
  const linkedCount = topics.filter((t) => (byTopic[t.key] || []).length > 0).length;
  const latest = (journals || [])[0] || null;

  return (
    <div className="lp home-lp">
      {saved && (
        <SavedDialog kind={saved.kind} count={saved.count || 0} id={saved.id} onClose={() => setSaved(null)} />
      )}

      <section className="lp-hero home-hero" aria-labelledby="home-title">
        <div className="wrap lp-hero-inner">
          <div>
            <span className="lp-pill">{user?.name ? `${user.name}님, 안녕하세요` : "안녕하세요"}</span>
            <h1 id="home-title" className="lp-h1">
              오늘의 수업이<br />내일의 <em>자기소개서</em>가 됩니다
            </h1>
            <p className="lp-lead">오늘의 기록이 자기소개서 작성과 면접에 큰 도움이 될 수 있습니다.</p>
            <div className="lp-cta-row">
              <Link className="btn btn-primary lp-btn" to="/journals/new?kind=lesson">수업일지 쓰기</Link>
              <Link className="btn lp-btn" to="/journals/new?kind=diary">학교생활일지 쓰기</Link>
            </div>
            <div className="home-stats">
              <span><b>{journals ? journals.length : "-"}</b>개의 기록</span>
              <span><b>{linkedCount}</b>/{topics.length || 11} 문항에 연결</span>
              {streak > 0 && <span className="home-streak">🔥 <b>{streak}</b>일 연속 기록 중</span>}
              {notif?.unread_journal_feedback > 0 && (
                <Link to="/journals" className="home-feedback">선생님 한마디 {notif.unread_journal_feedback}건 도착 →</Link>
              )}
            </div>
          </div>

          <LatestVisual latest={latest} topics={topics} byTopic={byTopic} loading={journals === null} />
        </div>
      </section>

      <MaterialsSection topics={topics} byTopic={byTopic} loading={journals === null} />

      <section className="lp-section lp-white" aria-labelledby="home-recent">
        <div className="wrap">
          <span className="lp-eyebrow">최근 기록</span>
          <h2 id="home-recent" className="lp-h2">내가 쌓아 온 기록</h2>
          <div className="row" role="group" aria-label="기록 종류" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
            {TYPE_TABS.map(([k, label]) => (
              <button key={k} type="button" aria-pressed={type === k}
                className={`btn btn-sm ${type === k ? "" : "btn-ghost"}`}
                onClick={() => setSearch(k === "all" ? {} : { type: k }, { replace: true })}>
                {label}
              </button>
            ))}
          </div>
          {shown === null ? (
            <p className="meta">불러오는 중…</p>
          ) : recentJournals.length === 0 ? (
            <div className="empty">
              <h3>{type === "class" ? "아직 수업일지가 없습니다"
                : type === "school" ? "아직 학교생활일지가 없습니다" : "아직 기록이 없습니다"}</h3>
              <p>오늘 있었던 일부터 한 줄 남겨보세요.</p>
              <Link to="/journals/new" className="btn btn-primary" style={{ marginTop: 12 }}>첫 기록 쓰기</Link>
            </div>
          ) : (
            <>
              <div className="home-recent-grid">
                {recentJournals.map((it) => (
                  <Link key={it.id} to={`/journals/${it.id}`} className="entry">
                    <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                      <span className={kindTag(it.kind)}>{KIND_LABEL[it.kind] || it.kind}</span>
                      {it.feedback_unread && <span className="badge badge-new">선생님 한마디 도착</span>}
                    </div>
                    <h4>{it.title || it.subject || it.entry_date}</h4>
                    {it.preview && <p className="entry-preview">{it.preview}</p>}
                    <div className="meta">
                      {it.entry_date}{it.subject && it.title ? ` · ${it.subject}` : ""}
                      {(it.resume_tags || []).length > 0 && ` · 문항 ${it.resume_tags.length}개에 연결`}
                    </div>
                  </Link>
                ))}
              </div>
              <Link to={type === "all" ? "/journals" : `/journals?type=${type}`} className="meta"
                style={{ fontSize: 12.5, display: "inline-block", marginTop: 8 }}>
                {type === "all" ? "내 기록 전체보기 →" : `${TYPE_TABS.find(([k]) => k === type)[1]} 모두 보기 →`}
              </Link>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/** 오른쪽 그림: 가장 최근 일지와, 그 일지가 연결된 자기소개서 문항. 기록이 없으면 쓰는 법 안내. */
function LatestVisual({ latest, topics, byTopic, loading }) {
  if (loading) return <div className="lp-hero-visual" aria-busy="true" />;
  if (!latest) {
    return (
      <div className="lp-hero-visual">
        <div className="lp-card lp-record">
          <div className="lp-card-head"><span className="lp-tag lesson">첫 기록</span></div>
          <b className="lp-card-title">오늘 배운 것 하나만 적어 보세요</b>
          <ul className="lp-kv">
            <li><b>어려웠던 점</b> · 수업에서 막혔던 부분</li>
            <li><b>해결 방법</b> · 어떻게 풀었는지</li>
            <li><b>느낀 점</b> · 그 과정에서 배운 것</li>
          </ul>
        </div>
        <div className="lp-link-line" aria-hidden="true">↓ <span>저장할 때 자기소개서 문항을 고르면 연결됩니다</span></div>
      </div>
    );
  }
  const tagIdx = (latest.resume_tags || []).map((k) => topics.findIndex((t) => t.key === k)).filter((i) => i >= 0);
  const first = tagIdx.length ? topics[tagIdx[0]] : null;
  const linked = first ? byTopic[first.key] || [] : [];
  const lessonN = linked.filter((j) => j.kind === "lesson").length;
  const diaryN = linked.length - lessonN;
  return (
    <div className="lp-hero-visual">
      <Link to={`/journals/${latest.id}`} className="lp-card lp-record home-card-link">
        <div className="lp-card-head">
          <span className={kindTag(latest.kind)}>{KIND_LABEL[latest.kind] || latest.kind}</span>
          <span className="lp-muted">{fmtDay(latest.entry_date)}{latest.subject ? ` · ${latest.subject}` : ""}</span>
        </div>
        <b className="lp-card-title">{latest.title || latest.subject || "제목 없는 기록"}</b>
        {latest.preview && <p className="lp-muted" style={{ margin: 0 }}>{latest.preview}</p>}
      </Link>
      {first ? (
        <>
          <div className="lp-link-line" aria-hidden="true">↓ <span>자기소개서 {tagIdx.map((i) => i + 1).join(", ")}번 문항에 연결됨</span></div>
          <Link to="/cover-letters" className="lp-card lp-resume home-card-link">
            <span className="lp-muted-inv">자기소개서 · 문항 {tagIdx[0] + 1}</span>
            <b>{first.label}</b>
            <div className="lp-chips">
              {lessonN > 0 && <span>수업일지 {lessonN}건</span>}
              {diaryN > 0 && <span>학교생활일지 {diaryN}건</span>}
            </div>
          </Link>
        </>
      ) : (
        <div className="lp-link-line home-unlinked">
          아직 자기소개서 문항에 연결하지 않았어요.{" "}
          <Link to={`/journals/${latest.id}`}>이 기록에 문항 연결하기 →</Link>
        </div>
      )}
    </div>
  );
}

/** 문항별로 모인 내 기록(실제 데이터). 문항을 누르면 그 문항에 연결한 일지가 옆에 나온다. */
function MaterialsSection({ topics, byTopic, loading }) {
  const firstWith = topics.findIndex((t) => (byTopic[t.key] || []).length > 0);
  const [active, setActive] = useState(null);
  const idx = active ?? (firstWith >= 0 ? firstWith : 0);
  const cur = topics[idx];
  const records = cur ? byTopic[cur.key] || [] : [];
  if (!topics.length) return null;
  return (
    <section className="lp-section" aria-labelledby="home-materials">
      <div className="wrap">
        <span className="lp-eyebrow">자기소개서 재료</span>
        <h2 id="home-materials" className="lp-h2">문항을 고르면, 쓸 재료가 먼저 와 있습니다</h2>
        <p className="lp-muted">일지를 저장할 때 고른 문항별로 내 기록을 모았습니다. 문항을 눌러 보세요.</p>
        <div className="lp-resume" id="resume-home">
          <ol className="lp-topics" aria-label="자기소개서 문항">
            {topics.map((t, i) => {
              const n = (byTopic[t.key] || []).length;
              return (
                <li key={t.key}>
                  <button type="button" className={`lp-topic${idx === i ? " on" : ""}`}
                    aria-pressed={idx === i} onClick={() => setActive(i)}>
                    <span className="lp-topic-no">{i + 1}</span>
                    <span className="lp-topic-text">{t.label}</span>
                    {n > 0 && <span className="lp-topic-cnt">기록 {n}건</span>}
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="lp-picked" aria-live="polite">
            <b>이 문항에 쓸 만한 내 기록</b>
            <p className="lp-muted">{idx + 1}번 · {cur?.label}</p>
            {loading ? <p className="lp-empty">불러오는 중…</p> : records.length === 0 ? (
              <p className="lp-empty">
                아직 이 문항에 연결한 기록이 없어요. 일지를 저장할 때 이 문항을 체크하면 여기에 모입니다.
              </p>
            ) : (
              <>
                {records.slice(0, 4).map((r) => (
                  <Link key={r.id} to={`/journals/${r.id}`} className="lp-picked-item home-card-link">
                    <div className="lp-card-head">
                      <span className={kindTag(r.kind)}>{KIND_LABEL[r.kind] || r.kind}</span>
                      <span className="lp-muted">{fmtDay(r.entry_date)}{r.subject ? ` · ${r.subject}` : ""}</span>
                    </div>
                    <b>{r.title || r.subject || "제목 없는 기록"}</b>
                    {r.preview && <p>{r.preview}</p>}
                  </Link>
                ))}
                {records.length > 4 && <p className="lp-muted" style={{ marginTop: 8 }}>외 {records.length - 4}건</p>}
                <Link to="/cover-letters" className="btn btn-primary" style={{ marginTop: 12 }}>
                  이 기록으로 자기소개서 쓰기
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
